# Conversion Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate every old-system conversion tile on the ~110 client custom dashboards (under Metabase collection 317) to its new named-conversion equivalent, preserving layout and filter wiring, mapping-driven and per-client, with snapshot rollback and per-tile validation.

**Architecture:** A pure logic library (`conv_lib.py`, unit-tested) + a per-dashboard CLI migrator (`migrate_conversions_on_dashboard.py`, reusing `swap_lib.rewrite_dashcards`) + input builders (Airtable mapping export, new-tree index, target discovery) + a wave orchestrator with a living tracker. The old→new mapping comes from Airtable (`type` slot → `new_type` named, per client); card shape is matched structurally against the generated new tree (collection 11673).

**Tech stack:** Python 3 (`.venv`), the in-repo `spark_metabase_api` wrapper (Metabase REST), standalone-script pytest-style tests (run via `python3 tests/test_x.py`), Airtable via MCP (export to JSON), Snowflake via Metabase `/api/dataset`.

**Validated facts (spike, 2026-06-03):** `266 "Conversions 1" → 42635 "Custom Conversion 1"` swap on a copy of dashboard 14118 preserved layout+filters; value reconciled exactly vs Snowflake. New cards lack `legacy_query` (tags live in `dataset_query.stages[].template-tags`). Pro Nutrition mapping: `Main→Purchases`, `1st→Custom 1`, `3rd→Custom 2` (slot ≠ Custom number). Spec: `docs/superpowers/specs/2026-06-03-conversion-migration-design.md`. Sandbox to clean up: collection 13851, dashboard 25302.

**Conventions:** pure logic in `scripts/conv_lib.py` (no network I/O), tested in `tests/test_conv_lib.py`. CLIs default to dry-run; mutations require `--yes`; every mutation writes a JSON snapshot under `migration/`. Commit after each task.

---

## Phase 0 — Library scaffolding: columns + format-tolerant extractor

### Task 1: Column inventory + native/tag extractor

**Files:**
- Create: `scripts/conv_lib.py`
- Test: `tests/test_conv_lib.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_conv_lib.py
#!/usr/bin/env python3
"""Tests de conv_lib — script autonome. Usage : python3 tests/test_conv_lib.py"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import conv_lib

def _native(sql, tags=()):  # old legacy-native card
    return {"dataset_query": {"type": "native", "native": {"query": sql, "template-tags": {t: {} for t in tags}}}}

def _staged(sql, tags=()):  # new pMBQL stages-native card (no legacy_query)
    return {"dataset_query": {"lib/type": "mbql/query",
            "stages": [{"lib/type": "mbql.stage/native", "native": sql,
                        "template-tags": {t: {} for t in tags}}]}}

def test_native_and_tags_legacy_format():
    sql, tags = conv_lib.native_and_tags(_native("SELECT SUM(conversions_1)", ["clients", "date"]))
    assert "conversions_1" in sql and tags.keys() == {"clients", "date"}

def test_native_and_tags_stages_format():
    sql, tags = conv_lib.native_and_tags(_staged("SELECT SUM(custom_conversions_1)", ["clients", "date"]))
    assert "custom_conversions_1" in sql and set(tags) == {"clients", "date"}

def test_native_and_tags_legacy_query_fallback():
    card = {"legacy_query": json.dumps({"type": "native", "native": {"query": "SELECT 1", "template-tags": {"date": {}}}})}
    sql, tags = conv_lib.native_and_tags(card)
    assert sql == "SELECT 1" and set(tags) == {"date"}

def test_old_columns_detects_positional_not_custom():
    sql = "SELECT SUM(global.campaign_daily_metrics.conversions_1), SUM(custom_conversions_1) "
    assert conv_lib.old_conversion_columns(sql) == {"CONVERSIONS_1"}

def test_old_columns_base_not_matched_inside_positional():
    assert conv_lib.old_conversion_columns("SELECT SUM(conversions_12)") == {"CONVERSIONS_12"}

def test_old_columns_ignores_conversion_type_filter():
    assert conv_lib.old_conversion_columns("WHERE conversion_type = 'x'") == set()

def test_new_columns_named_and_custom():
    sql = "SELECT SUM(purchases), SUM(custom_conversions_2_value)"
    assert conv_lib.new_conversion_columns(sql) == {"PURCHASES", "CUSTOM_CONVERSIONS_2_VALUE"}

TESTS = [test_native_and_tags_legacy_format, test_native_and_tags_stages_format,
         test_native_and_tags_legacy_query_fallback, test_old_columns_detects_positional_not_custom,
         test_old_columns_base_not_matched_inside_positional, test_old_columns_ignores_conversion_type_filter,
         test_new_columns_named_and_custom]

def run():
    failures = 0
    for t in TESTS:
        try: t(); print(f"PASS  {t.__name__}")
        except Exception as e: failures += 1; print(f"FAIL  {t.__name__}: {e!r}")
    print(f"\n{len(TESTS) - failures}/{len(TESTS)} tests passés"); sys.exit(1 if failures else 0)

if __name__ == "__main__":
    run()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python tests/test_conv_lib.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'conv_lib'`.

- [ ] **Step 3: Implement `conv_lib.py` (this part)**

```python
# scripts/conv_lib.py
#!/usr/bin/env python3
"""Logique pure de la migration de conversions (ancien positionnel -> nouveau nommé).
Aucune I/O réseau. Voir docs/superpowers/specs/2026-06-03-conversion-migration-design.md."""
from __future__ import annotations
import json, re
from collections import defaultdict

# --- Column inventory (authoritative, Snowflake information_schema 2026-06-03) ---
OLD_COUNT = ["CONVERSIONS"] + [f"CONVERSIONS_{n}" for n in range(1, 20)]
OLD_VALUE = ["CONVERSION_VALUE"] + [f"CONVERSION_{n}_VALUE" for n in range(1, 20)]
OLD_COLS = set(OLD_COUNT) | set(OLD_VALUE)

CUSTOM_COUNT = {n: f"CUSTOM_CONVERSIONS_{n}" for n in range(1, 16)}
CUSTOM_VALUE = {n: f"CUSTOM_CONVERSIONS_{n}_VALUE" for n in range(1, 16)}
NAMED_COL = {  # new_type label -> (count_col, value_col | None)
    "Purchases": ("PURCHASES", "PURCHASES_VALUE"),
    "Add to cart": ("ADD_TO_CARTS_NEW", "ADD_TO_CARTS_VALUE_NEW"),
    "Initiate checkouts": ("INITIATE_CHECKOUTS", "INITIATE_CHECKOUTS_VALUE"),
    "Content views OR View Item": ("CONTENT_VIEWS", None),
    "Sign ups": ("SIGN_UPS", None),
    "Leads": ("LEADS", "LEADS_VALUE"),
    "Marketing Qualified Leads": ("MARKETING_QUALIFIED_LEADS", "MARKETING_QUALIFIED_LEADS_VALUE"),
    "Sales Qualified Leads": ("SALES_QUALIFIED_LEADS", "SALES_QUALIFIED_LEADS_VALUE"),
    "Offline sales": ("OFFLINE_SALES", "OFFLINE_SALES_VALUE"),
    "App installs": ("APP_INSTALLS_NEW", "APP_INSTALL_VALUE"),
    "Search visits (combo organic + sea custom conv meta)": ("SEARCH_VISITS_COMBO", None),
    "Organic search visits (custom conv meta)": ("ORGANIC_SEARCH_VISITS", None),
    "Paid search visits (custom conv meta)": ("PAID_SEARCH_VISITS", None),
}
NEW_COLS = set()
for n in range(1, 16):
    NEW_COLS |= {CUSTOM_COUNT[n], CUSTOM_VALUE[n]}
for _c, _v in NAMED_COL.values():
    NEW_COLS.add(_c)
    if _v:
        NEW_COLS.add(_v)

def _rx(cols):
    return re.compile(r"(?<![A-Z0-9_])(" + "|".join(sorted(cols, key=len, reverse=True)) + r")(?![A-Z0-9_])")
_OLD_RX, _NEW_RX = _rx(OLD_COLS), _rx(NEW_COLS)

def native_and_tags(card):
    """(sql, template-tags dict) — tolère natif legacy, stages pMBQL, et legacy_query."""
    dq = card.get("dataset_query") or {}
    if dq.get("type") == "native":
        n = dq.get("native") or {}
        return n.get("query") or "", (n.get("template-tags") or {})
    for st in dq.get("stages") or []:
        if st.get("lib/type") == "mbql.stage/native":
            return st.get("native") or "", (st.get("template-tags") or {})
    lq = card.get("legacy_query")
    if isinstance(lq, str):
        try:
            lq = json.loads(lq)
        except Exception:
            lq = {}
        if isinstance(lq, dict) and lq.get("type") == "native":
            n = lq.get("native") or {}
            return n.get("query") or "", (n.get("template-tags") or {})
    return "", {}

def old_conversion_columns(sql):
    return set(_OLD_RX.findall((sql or "").upper()))

def new_conversion_columns(sql):
    return set(_NEW_RX.findall((sql or "").upper()))
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python tests/test_conv_lib.py`
Expected: `7/7 tests passés`.

- [ ] **Step 5: Commit**

```bash
git add scripts/conv_lib.py tests/test_conv_lib.py
git commit -m "conv/lib: column inventory + format-tolerant native/tag extractor (TDD)"
```

---

## Phase 1 — Type-axis: slot↔column maps + Airtable mapping ingestion

### Task 2: Slot/new_type column maps + `build_client_mappings`

**Files:**
- Modify: `scripts/conv_lib.py` (append)
- Modify: `tests/test_conv_lib.py` (add tests + extend `TESTS`)

- [ ] **Step 1: Add failing tests**

```python
# append to tests/test_conv_lib.py before TESTS list
def test_slot_old_columns():
    assert conv_lib.slot_old_columns(0) == ("CONVERSIONS", "CONVERSION_VALUE")
    assert conv_lib.slot_old_columns(3) == ("CONVERSIONS_3", "CONVERSION_3_VALUE")

def test_type_to_slot():
    assert conv_lib.TYPE_TO_SLOT["Main conversion"] == 0
    assert conv_lib.TYPE_TO_SLOT["1st conversion"] == 1
    assert conv_lib.TYPE_TO_SLOT["3rd conversion"] == 3
    assert conv_lib.TYPE_TO_SLOT["19th conversion"] == 19

def test_new_type_columns_custom_and_named():
    assert conv_lib.new_type_columns("Custom 1") == ("CUSTOM_CONVERSIONS_1", "CUSTOM_CONVERSIONS_1_VALUE")
    assert conv_lib.new_type_columns("Custom 2") == ("CUSTOM_CONVERSIONS_2", "CUSTOM_CONVERSIONS_2_VALUE")
    assert conv_lib.new_type_columns("Purchases") == ("PURCHASES", "PURCHASES_VALUE")
    assert conv_lib.new_type_columns("Sign ups") == ("SIGN_UPS", None)

def test_build_client_mappings_resolves_consistent_and_flags_unmapped_conflict():
    records = [
        {"client": "Pro Nutrition", "type": "Main conversion", "new_type": "Purchases"},
        {"client": "Pro Nutrition", "type": "Main conversion", "new_type": "Purchases"},   # consistent dup
        {"client": "Pro Nutrition", "type": "1st conversion", "new_type": "Custom 1"},
        {"client": "Pro Nutrition", "type": "3rd conversion", "new_type": "Custom 2"},      # slot != custom#
        {"client": "Pro Nutrition", "type": "1st conversion", "new_type": None},            # empty ignored
        {"client": "Acme", "type": "Main conversion", "new_type": None},                    # only empty -> UNMAPPED
        {"client": "Acme", "type": "2nd conversion", "new_type": "Leads"},
        {"client": "Acme", "type": "2nd conversion", "new_type": "Purchases"},              # conflict
    ]
    m = conv_lib.build_client_mappings(records)
    assert m["Pro Nutrition"][0] == "Purchases"
    assert m["Pro Nutrition"][1] == "Custom 1"
    assert m["Pro Nutrition"][3] == "Custom 2"
    assert m["Acme"][0] == conv_lib.UNMAPPED
    assert m["Acme"][2] == conv_lib.CONFLICT
```

```python
# extend TESTS list with:
    test_slot_old_columns, test_type_to_slot, test_new_type_columns_custom_and_named,
    test_build_client_mappings_resolves_consistent_and_flags_unmapped_conflict,
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python tests/test_conv_lib.py`
Expected: FAIL — `AttributeError: module 'conv_lib' has no attribute 'slot_old_columns'`.

- [ ] **Step 3: Implement (append to `conv_lib.py`)**

```python
# --- Type-axis (Airtable slot -> new named) ---
TYPE_TO_SLOT = {"Main conversion": 0}
_ORD = ["1st", "2nd", "3rd"] + [f"{n}th" for n in range(4, 20)]
for _i, _o in enumerate(_ORD, start=1):
    TYPE_TO_SLOT[f"{_o} conversion"] = _i

UNMAPPED = "__UNMAPPED__"
CONFLICT = "__CONFLICT__"

def slot_old_columns(slot):
    if slot == 0:
        return ("CONVERSIONS", "CONVERSION_VALUE")
    return (f"CONVERSIONS_{slot}", f"CONVERSION_{slot}_VALUE")

def new_type_columns(new_type):
    m = re.match(r"Custom (\d+)$", new_type or "")
    if m:
        n = int(m.group(1))
        return (CUSTOM_COUNT.get(n), CUSTOM_VALUE.get(n))
    return NAMED_COL.get(new_type, (None, None))

def build_client_mappings(records):
    """records: [{client, type, new_type}] (flattened Airtable rows) ->
    {client: {slot: new_type | UNMAPPED | CONFLICT}}. Slots seen with only empty
    new_type -> UNMAPPED; multiple distinct new_type for one slot -> CONFLICT."""
    seen = defaultdict(lambda: defaultdict(set))
    for r in records:
        client, typ = r.get("client"), r.get("type")
        if not client or typ not in TYPE_TO_SLOT:
            continue
        slot = TYPE_TO_SLOT[typ]
        nt = r.get("new_type")
        seen[client][slot]  # ensure slot recorded even if empty
        if nt:
            seen[client][slot].add(nt)
    out = {}
    for client, slots in seen.items():
        out[client] = {}
        for slot, nts in slots.items():
            out[client][slot] = (next(iter(nts)) if len(nts) == 1
                                 else CONFLICT if len(nts) > 1 else UNMAPPED)
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python tests/test_conv_lib.py`
Expected: `11/11 tests passés`.

- [ ] **Step 5: Commit**

```bash
git add scripts/conv_lib.py tests/test_conv_lib.py
git commit -m "conv/lib: slot/new_type column maps + per-client mapping ingestion (TDD)"
```

### Task 3: Export the Airtable mapping to JSON (input artifact)

> The Python tool has no Airtable token; the mapping is exported once (and re-exported when it changes) via the Airtable MCP in the orchestrating Claude session, then transformed by `build_client_mappings`.

**Files:**
- Create: `scripts/export_conv_mapping.py`
- Output: `migration/conv-airtable-rows-<ts>.json` (raw flattened rows) and `migration/conv-client-mapping.json` (resolved)

- [ ] **Step 1: Produce raw rows via MCP (orchestrator session)**

In the Claude session, page through Airtable base `apptzpE1FqCMGH0dw` table `tbliHOIPYGJCvLvas` with `list_records_for_table`, filter `type` isNotEmpty (field `fldKwKgjtULTSjX6g`), fields `[brand_name, type, new_type]`, paginating on `cursor`. Flatten each record to `{"client": <brand_name>, "type": <type name>, "new_type": <new_type name or null>}` and write the list to `migration/conv-airtable-rows-<ts>.json`. (`brand_name`/`type`/`new_type` come back as objects/arrays — take `.name` / first element name.)

- [ ] **Step 2: Implement the transform CLI**

```python
# scripts/export_conv_mapping.py
#!/usr/bin/env python3
"""Transforme les lignes Airtable exportées en mapping client résolu.
Usage: python3 scripts/export_conv_mapping.py migration/conv-airtable-rows-<ts>.json"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import conv_lib

def main():
    rows = json.loads(Path(sys.argv[1]).read_text())
    mapping = conv_lib.build_client_mappings(rows)
    n_un = sum(1 for c in mapping.values() for v in c.values() if v == conv_lib.UNMAPPED)
    n_cf = sum(1 for c in mapping.values() for v in c.values() if v == conv_lib.CONFLICT)
    out = Path("migration/conv-client-mapping.json")
    out.write_text(json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"{len(mapping)} clients -> {out}  (UNMAPPED slots: {n_un}, CONFLICT slots: {n_cf})")

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run + sanity-check Pro Nutrition**

Run: `.venv/bin/python scripts/export_conv_mapping.py migration/conv-airtable-rows-<ts>.json`
Then: `.venv/bin/python -c "import json; m=json.load(open('migration/conv-client-mapping.json')); print(m['Pro Nutrition'])"`
Expected: `{'0': 'Purchases', '1': 'Custom 1', '3': 'Custom 2'}` (JSON keys are strings).

- [ ] **Step 4: Commit**

```bash
git add scripts/export_conv_mapping.py migration/conv-client-mapping.json
git commit -m "conv/mapping: export Airtable type->new_type to per-client JSON"
```

---

## Phase 2 — Shape axis: new-tree index + card matcher

### Task 4: Card shape signature + matcher (`conv_lib`)

**Files:**
- Modify: `scripts/conv_lib.py` (append)
- Modify: `tests/test_conv_lib.py`

- [ ] **Step 1: Add failing tests**

```python
def _card(name, display, dims=(), sql="SELECT 1"):
    return {"name": name, "display": display,
            "visualization_settings": {"graph.dimensions": list(dims)},
            "dataset_query": {"type": "native", "native": {"query": sql}}}

def test_metric_kind():
    assert conv_lib.metric_kind("Conversions 1") == "COUNT"
    assert conv_lib.metric_kind("CR (conversions 1)") == "RATE"
    assert conv_lib.metric_kind("CAC (Custom Conversion 1)") == "CAC"
    assert conv_lib.metric_kind("ROAS (Custom Conversion 1)") == "ROAS"
    assert conv_lib.metric_kind("Custom Conversion 1 value") == "VALUE"

def test_card_shape():
    s = conv_lib.card_shape(_card("Conversions 1 by date, campaign channel", "bar", ["date"]))
    assert s == ("bar", "COUNT", ("channel", "date"))

def test_resolve_new_card_picks_single_shape_match():
    old = _card("Conversions 1", "smartscalar", sql="SELECT SUM(conversions_1)")
    new_index = {("CUSTOM_CONVERSIONS_1", ("smartscalar", "COUNT", ())): [42635],
                 ("PURCHASES", ("smartscalar", "COUNT", ())): [99999]}
    mapping = {0: "Purchases", 1: "Custom 1"}
    res = conv_lib.resolve_new_card(old, mapping, new_index)
    assert res["status"] == "ok" and res["new_card_id"] == 42635 and res["new_type"] == "Custom 1"

def test_resolve_new_card_unmapped_slot():
    old = _card("Conversions 2", "smartscalar", sql="SELECT SUM(conversions_2)")
    res = conv_lib.resolve_new_card(old, {2: conv_lib.UNMAPPED}, {})
    assert res["status"] == "unmapped"

def test_resolve_new_card_no_shape_match_goes_to_review():
    old = _card("Conversions 1 by URL", "table", ["url"], sql="SELECT SUM(conversions_1)")
    mapping = {1: "Custom 1"}
    res = conv_lib.resolve_new_card(old, mapping, {})  # empty index -> no candidate
    assert res["status"] == "review" and res["reason"]
```

```python
# extend TESTS with: test_metric_kind, test_card_shape,
# test_resolve_new_card_picks_single_shape_match, test_resolve_new_card_unmapped_slot,
# test_resolve_new_card_no_shape_match_goes_to_review
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python tests/test_conv_lib.py`
Expected: FAIL — `AttributeError: ... 'metric_kind'`.

- [ ] **Step 3: Implement (append to `conv_lib.py`)**

```python
# --- Shape axis (display x metric x breakdown) ---
_BREAKDOWN = [("date", "date"), ("channel", "channel"), ("network", "network"),
              ("categor", "category"), ("countr", "country"), ("location", "location"),
              ("device", "device"), ("product", "product"), ("url", "url"), ("type", "type"),
              ("adset", "adset"), ("adgroup", "adgroup"), ("placement", "placement"),
              ("segment", "segment"), ("medium", "medium"), ("page", "page")]

def metric_kind(name):
    n = (name or "").upper()
    for k in ("ROAS", "CAC", "COS", "CPA", "CPI", "CTR"):
        if re.search(rf"\b{k}\b", n):
            return k
    if re.search(r"\bCR\b", n) or "RATE" in n:
        return "RATE"
    if "VALUE" in n:
        return "VALUE"
    if "AVG" in n or "AVERAGE" in n:
        return "AVG"
    return "COUNT"

def _breakdown(name, viz):
    found = set()
    src = (name or "").lower()
    m = re.search(r"\bby\b(.+)$", src)
    seg = m.group(1) if m else ""
    for needle, label in _BREAKDOWN:
        if needle in seg:
            found.add(label)
    for d in (viz or {}).get("graph.dimensions") or []:
        if isinstance(d, str):
            dl = d.lower()
            for needle, label in _BREAKDOWN:
                if needle in dl:
                    found.add(label)
    return tuple(sorted(found))

def card_shape(card):
    return (card.get("display") or "?", metric_kind(card.get("name")),
            _breakdown(card.get("name"), card.get("visualization_settings")))

def _old_slot_and_value(card):
    """(slot, is_value) inferred from the old columns the card sums, or (None, None)."""
    sql, _ = native_and_tags(card)
    cols = old_conversion_columns(sql)
    if not cols:
        return None, None
    is_value = any(c.endswith("_VALUE") or c == "CONVERSION_VALUE" for c in cols)
    slots = set()
    for c in cols:
        if c in ("CONVERSIONS", "CONVERSION_VALUE"):
            slots.add(0)
        else:
            mm = re.search(r"(\d+)", c)
            if mm:
                slots.add(int(mm.group(1)))
    return (min(slots) if slots else None, is_value)

def resolve_new_card(old_card, client_mapping, new_index):
    """Return {status: ok|unmapped|conflict|multi|review|skip, ...}.
    client_mapping: {slot:int -> new_type|UNMAPPED|CONFLICT}. new_index:
    {(NEW_COL, shape) -> [card_id]}."""
    slot, is_value = _old_slot_and_value(old_card)
    if slot is None:
        return {"status": "skip", "reason": "no old conversion column"}
    nt = client_mapping.get(slot)
    if nt is None:
        return {"status": "review", "reason": f"slot {slot} absent from client mapping"}
    if nt in (UNMAPPED, CONFLICT):
        return {"status": nt.strip("_").lower(), "slot": slot}
    count_col, value_col = new_type_columns(nt)
    new_col = value_col if is_value else count_col
    if not new_col:
        return {"status": "review", "reason": f"new_type {nt!r} has no {'value' if is_value else 'count'} column"}
    cands = new_index.get((new_col, card_shape(old_card))) or []
    if len(cands) == 1:
        return {"status": "ok", "new_card_id": cands[0], "new_type": nt, "new_col": new_col, "slot": slot}
    if len(cands) > 1:
        return {"status": "multi", "candidates": cands, "new_type": nt, "new_col": new_col}
    return {"status": "review", "reason": f"no new card for {new_col} shape {card_shape(old_card)}",
            "new_type": nt, "new_col": new_col}
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python tests/test_conv_lib.py`
Expected: `16/16 tests passés`.

- [ ] **Step 5: Commit**

```bash
git add scripts/conv_lib.py tests/test_conv_lib.py
git commit -m "conv/lib: card shape signature + new-card resolver (TDD)"
```

### Task 5: Build the new-tree index from the live instance

**Files:**
- Create: `scripts/build_new_conv_index.py`
- Output: `migration/conv-new-index.json`

- [ ] **Step 1: Implement the index builder**

```python
# scripts/build_new_conv_index.py
#!/usr/bin/env python3
"""Indexe l'arbre des nouvelles conversions (collection 11673) :
{(NEW_COL, [display, metric_kind, breakdown]) -> [card_id]}.
Usage: python3 scripts/build_new_conv_index.py [--root 11673]"""
import argparse, json, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env
import conv_lib

def connect():
    e = _load_env()
    return Metabase_API(domain=e["METABASE_DOMAIN"], email=e["METABASE_EMAIL"], password=e["METABASE_PASSWORD"])

def walk_cards(mb, cid, acc):
    r = mb.get(f"/api/collection/{cid}/items?models=card&models=collection")
    data = r.get("data") if isinstance(r, dict) else r
    for it in data or []:
        if it.get("model") == "collection":
            walk_cards(mb, it["id"], acc)
        elif it.get("model") == "card":
            acc.append(it["id"])

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--root", type=int, default=11673)
    args = ap.parse_args()
    mb = connect()
    ids = []
    walk_cards(mb, args.root, ids)
    index = defaultdict(list)
    for cid in ids:
        c = mb.get(f"/api/card/{cid}")
        if not isinstance(c, dict) or c.get("archived"):
            continue
        sql, _ = conv_lib.native_and_tags(c)
        for col in conv_lib.new_conversion_columns(sql):
            key = json.dumps([col, list(conv_lib.card_shape(c))])
            index[key].append(cid)
    out = Path("migration") / "conv-new-index.json"
    out.write_text(json.dumps(index, ensure_ascii=False, indent=2))
    multi = sum(1 for v in index.values() if len(v) > 1)
    print(f"{len(ids)} cards walked -> {len(index)} (col,shape) keys ({multi} ambiguous) -> {out}")

if __name__ == "__main__":
    main()
```

> Note: keys are JSON strings `[col, [display, kind, [breakdowns]]]`; the migrator rebuilds the tuple form when looking up. Ambiguous (>1) keys feed the review queue.

- [ ] **Step 2: Run + sanity-check the Custom 1 smartscalar entry**

Run: `.venv/bin/python scripts/build_new_conv_index.py`
Then verify `["CUSTOM_CONVERSIONS_1", ["smartscalar", "COUNT", []]]` maps to `[42635]`:
`.venv/bin/python -c "import json; i=json.load(open('migration/conv-new-index.json')); print(i.get('[\"CUSTOM_CONVERSIONS_1\", [\"smartscalar\", \"COUNT\", []]]'))"`
Expected: `[42635]`.

- [ ] **Step 3: Commit**

```bash
git add scripts/build_new_conv_index.py migration/conv-new-index.json
git commit -m "conv/index: build (col,shape)->card index of the new conversions tree"
```

---

## Phase 3 — Per-dashboard migrator + validation

### Task 6: The migrator CLI (`migrate_conversions_on_dashboard.py`)

**Files:**
- Create: `scripts/migrate_conversions_on_dashboard.py`
- Reuse: `scripts/swap_lib.py` (`rewrite_dashcards`, `referenced_template_tags`), `scripts/conv_lib.py`

- [ ] **Step 1: Implement the CLI**

```python
# scripts/migrate_conversions_on_dashboard.py
#!/usr/bin/env python3
"""Migre les tuiles de conversion d'UN dashboard vers le nouveau système.
Par tuile : détecte la carte ancienne, résout new_type (mapping client) + carte cible
(index de forme), garde-fous relâchés, snapshot, repointe (swap_lib), recâble les
column_settings, valide (structurel + lecture de valeur + réconciliation Snowflake).
NE archive JAMAIS la carte partagée. Réversible (snapshot).

Usage:
  python3 scripts/migrate_conversions_on_dashboard.py --dashboard 25302 --client "Pro Nutrition"          # dry-run
  python3 scripts/migrate_conversions_on_dashboard.py --dashboard 25302 --client "Pro Nutrition" --copy   # migre une COPIE
  python3 scripts/migrate_conversions_on_dashboard.py --dashboard 14118 --client "Pro Nutrition" --yes     # applique in-place + snapshot
"""
import argparse, json, sys
from datetime import datetime
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env
import swap_lib, conv_lib

MIG = REPO / "migration"

def connect():
    e = _load_env()
    return Metabase_API(domain=e["METABASE_DOMAIN"], email=e["METABASE_EMAIL"], password=e["METABASE_PASSWORD"])

def _dashcards(d):
    return d.get("dashcards") or d.get("ordered_cards") or []

def load_inputs():
    mapping = json.loads((MIG / "conv-client-mapping.json").read_text())
    raw = json.loads((MIG / "conv-new-index.json").read_text())
    index = {}
    for k, v in raw.items():
        col, shape = json.loads(k)
        index[(col, tuple([shape[0], shape[1], tuple(shape[2])]))] = v
    return mapping, index

def remap_column_settings(viz, old_col, new_col):
    """Re-key dashcard column_settings ["name","OLD_COL"] -> NEW_COL so number formatting applies."""
    cs = (viz or {}).get("column_settings")
    if not cs:
        return viz
    out = dict(viz)
    new_cs = {}
    for k, val in cs.items():
        nk = k.replace(f'"{old_col}"', f'"{new_col}"').replace(f'"{old_col.lower()}"', f'"{new_col.lower()}"')
        new_cs[nk] = val
    out["column_settings"] = new_cs
    return out

def reconcile(mb, client, old_col, new_col, start, end):
    """Independent SUM of old/new columns over the same join chain (Snowflake via /api/dataset)."""
    sql = f"""
WITH base AS (
  SELECT global.campaign_daily_metrics.{old_col} AS old_c,
         global.campaign_daily_metrics.{new_col} AS new_c
  FROM utils.clients
    JOIN utils.client_ad_platforms ON client_id = utils.clients.id
    JOIN reports.campaign_details ON reports.campaign_details.account_id = utils.client_ad_platforms.account_id
    JOIN global.campaign_daily_metrics ON global.campaign_daily_metrics.campaign_id = reports.campaign_details.campaign_id
  WHERE utils.clients.name = '{client}'
    AND global.campaign_daily_metrics.date BETWEEN '{start}' AND '{end}')
SELECT COALESCE(SUM(old_c),0), COALESCE(SUM(new_c),0) FROM base""".strip()
    ds = mb.post("/api/dataset", json={"database": 144, "type": "native", "native": {"query": sql}}, timeout=180)
    rows = ds.get("data", {}).get("rows") if isinstance(ds, dict) else None
    return (rows[0][0], rows[0][1]) if rows else (None, None)

def tile_value(mb, dash_id, dc_id, card_id, client, date_range):
    d = mb.get(f"/api/dashboard/{dash_id}")
    dc = next((x for x in _dashcards(d) if x.get("id") == dc_id), {})
    params = []
    for pm in dc.get("parameter_mappings") or []:
        p = next((q for q in d.get("parameters") or [] if q.get("id") == pm.get("parameter_id")), {})
        val = [client] if p.get("slug") == "client" else (date_range if p.get("slug") == "date" else None)
        if val is not None:
            params.append({"id": p["id"], "type": p.get("type"), "value": val, "target": pm.get("target")})
    r = mb.post(f"/api/dashboard/{dash_id}/dashcard/{dc_id}/card/{card_id}/query", json={"parameters": params}, timeout=120)
    try:
        return r["data"]["rows"][-1][-1]
    except Exception:
        return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard", type=int, required=True)
    ap.add_argument("--client", required=True)
    ap.add_argument("--copy", action="store_true", help="migrer une copie (test) au lieu de l'original")
    ap.add_argument("--yes", action="store_true", help="appliquer (sinon dry-run)")
    ap.add_argument("--window", default="2026-05-01~2026-05-31", help="fenêtre de validation date/all-options")
    args = ap.parse_args()
    mb = connect()
    mapping_all, index = load_inputs()
    cmap = {int(k): v for k, v in mapping_all.get(args.client, {}).items()}
    if not cmap:
        sys.exit(f"Aucun mapping pour client {args.client!r} (conv-client-mapping.json).")

    src = args.dashboard
    if args.copy and args.yes:
        cp = mb.post(f"/api/dashboard/{src}/copy", json={"collection_id": None, "name": f"MIGRATION TEST {src}", "is_deep_copy": False})
        src = cp["id"]
        print(f"copie -> dashboard {src}")
    dash = mb.get(f"/api/dashboard/{src}")
    dcs = _dashcards(dash)

    plan, report = [], {"dashboard": src, "client": args.client, "tiles": []}
    for dc in dcs:
        cid = dc.get("card_id")
        if not cid:
            continue
        card = mb.get(f"/api/card/{cid}")
        sql, _ = conv_lib.native_and_tags(card)
        if not conv_lib.old_conversion_columns(sql):
            continue
        res = conv_lib.resolve_new_card(card, cmap, index)
        entry = {"dashcard_id": dc["id"], "old_card": cid, "old_name": card.get("name"), **res}
        if res["status"] == "ok":
            new = mb.get(f"/api/card/{res['new_card_id']}")
            ref = swap_lib.referenced_template_tags(dcs, cid)
            _, ntags = conv_lib.native_and_tags(new)
            problems = []
            if new.get("archived"): problems.append("new archived")
            if card.get("database_id") != new.get("database_id"): problems.append("different DB")
            miss = ref - set(ntags)
            if miss: problems.append(f"new misses tags {sorted(miss)}")
            entry["safety"] = problems
            if problems:
                entry["status"] = "blocked"
            else:
                oc = res["old_col"]  # resolver supplies old+new cols for reconciliation
                entry["old_col"] = oc
                plan.append((dc, card, new, res, oc))
        report["tiles"].append(entry)

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if not args.yes or not plan:
        print("\n(DRY-RUN ou rien à faire — aucune modification.)")
        return

    MIG.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    snap = MIG / f"conv-migrate-snapshot-{src}-{ts}.json"
    snap.write_text(json.dumps({"dashboard": src, "dashcards": dcs}, ensure_ascii=False, indent=2))
    print(f"snapshot: {snap}")

    new_dcs = dcs
    for dc, card, new, res, oc in plan:
        new_dcs, _ = swap_lib.rewrite_dashcards(new_dcs, card["id"], res["new_card_id"])
        for ndc in new_dcs:
            if ndc.get("id") == dc["id"]:
                ndc["visualization_settings"] = remap_column_settings(ndc.get("visualization_settings") or {}, oc, res["new_col"])
    rc = mb.put(f"/api/dashboard/{src}", json={"dashcards": new_dcs})
    print(f"PUT dashboard {src}: {rc}")

    start, end = args.window.split("~")
    for dc, card, new, res, oc in plan:
        nv = tile_value(mb, src, dc["id"], res["new_card_id"], args.client, args.window)
        o_sum, n_sum = reconcile(mb, args.client, oc, res["new_col"], start, end)
        ok = (nv is not None and n_sum is not None and abs(float(nv) - float(n_sum)) < 1e-6)
        print(f"  tile {dc['id']} {card['name']!r} -> #{res['new_card_id']}: tile={nv} snowflake_new={n_sum} reconciled={ok} (old_sum={o_sum})")
    print(f"\nRollback: restaurer dashcards depuis {snap}.")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry-run against the existing sandbox copy (25302)**

Run: `.venv/bin/python scripts/migrate_conversions_on_dashboard.py --dashboard 25302 --client "Pro Nutrition"`
Expected: report lists the conversion tile resolving `status: ok` to `new_card_id: 42635`, `new_type: Custom 1`, empty `safety`. No mutation.

- [ ] **Step 3: Apply on a FRESH copy (Custom 1 case, value unchanged)**

Run: `.venv/bin/python scripts/migrate_conversions_on_dashboard.py --dashboard 14118 --client "Pro Nutrition" --copy --yes`
Expected: PUT 200; tile reconciled `True` (`tile == snowflake_new`), matching the spike's `646.225741`.

- [ ] **Step 4: Validate the value-CHANGING case (Main conversion → Purchases)**

Find a Pro Nutrition dashboard tile backed by base `conversions` (slot 0). Dry-run the migrator on a copy and confirm it resolves to a `PURCHASES` card; apply on the copy; confirm `reconciled True` with `tile == snowflake_new` and `old_sum != new_sum` (the number genuinely changes). Record both values in the report.

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_conversions_on_dashboard.py
git commit -m "conv/migrate: per-dashboard migrator (mapping+shape resolve, relaxed safety, snapshot, Snowflake reconcile)"
```

---

## Phase 4 — Target discovery

### Task 7: Discover custom dashboards + conversion tiles under 317

**Files:**
- Create: `scripts/discover_conversion_targets.py`
- Output: `migration/conv-targets-<ts>.json`

- [ ] **Step 1: Implement the crawler**

```python
# scripts/discover_conversion_targets.py
#!/usr/bin/env python3
"""Liste les dashboards custom sous 317 et leurs tuiles de conversion (ancien système).
Sortie: migration/conv-targets-<ts>.json = [{client, collection_id, dashboard_id, dashboard_name,
is_template_like, tiles:[{dashcard_id, card_id, card_name, old_cols}]}].
Usage: python3 scripts/discover_conversion_targets.py [--root 317]"""
import argparse, json, re, sys
from datetime import datetime
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env
import conv_lib

TEMPLATE_RX = re.compile(r"template|\bspec\b|master", re.I)

def connect():
    e = _load_env()
    return Metabase_API(domain=e["METABASE_DOMAIN"], email=e["METABASE_EMAIL"], password=e["METABASE_PASSWORD"])

def items(mb, cid):
    r = mb.get(f"/api/collection/{cid}/items")
    return (r.get("data") if isinstance(r, dict) else r) or []

def dashboards_under(mb, cid, acc):
    for it in items(mb, cid):
        if it.get("model") == "collection":
            dashboards_under(mb, it["id"], acc)
        elif it.get("model") == "dashboard":
            acc.append((cid, it["id"], it.get("name")))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--root", type=int, default=317)
    args = ap.parse_args()
    mb = connect()
    clients = [(c["id"], c["name"]) for c in items(mb, args.root) if c.get("model") == "collection"]
    card_cache, out = {}, []
    for coll_id, client in clients:
        dl = []
        dashboards_under(mb, coll_id, dl)
        for _src, did, dname in dl:
            full = mb.get(f"/api/dashboard/{did}")
            tiles = []
            for dc in (full.get("dashcards") or full.get("ordered_cards") or []):
                cid = dc.get("card_id")
                if not cid:
                    continue
                if cid not in card_cache:
                    card_cache[cid] = mb.get(f"/api/card/{cid}")
                sql, _ = conv_lib.native_and_tags(card_cache[cid] or {})
                oc = conv_lib.old_conversion_columns(sql)
                if oc:
                    tiles.append({"dashcard_id": dc["id"], "card_id": cid,
                                  "card_name": (card_cache[cid] or {}).get("name"), "old_cols": sorted(oc)})
            if tiles:
                out.append({"client": client, "collection_id": coll_id, "dashboard_id": did,
                            "dashboard_name": dname, "is_template_like": bool(TEMPLATE_RX.search(dname or "")),
                            "tiles": tiles})
    p = REPO / "migration" / f"conv-targets-{datetime.now():%Y%m%d-%H%M%S}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"{len(clients)} clients | {len(out)} dashboards w/ conversion tiles | "
          f"{sum(len(d['tiles']) for d in out)} tiles | template-like: {sum(d['is_template_like'] for d in out)} -> {p}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run + sanity-check Pro Nutrition appears**

Run: `.venv/bin/python scripts/discover_conversion_targets.py`
Expected: prints totals; the output JSON contains a Pro Nutrition entry with dashboard 14118 listing the `Conversions 1` tile (`old_cols: ["CONVERSIONS_1"]`).

- [ ] **Step 3: Commit**

```bash
git add scripts/discover_conversion_targets.py
git commit -m "conv/discover: crawl custom dashboards under 317 for old-conversion tiles"
```

---

## Phase 5 — Wave orchestration, tracker, agent rollout

### Task 8: Pre-flight resolver report (what auto-applies vs review)

**Files:**
- Create: `scripts/conv_preflight.py`
- Output: `migration/conv-preflight-<ts>.{json,csv}`

- [ ] **Step 1: Implement preflight (resolve every target tile, no mutation)**

```python
# scripts/conv_preflight.py
#!/usr/bin/env python3
"""Pour chaque tuile cible, résout new_type+carte sans rien modifier; classe en
ok / unmapped / conflict / multi / review. Produit la file de revue.
Usage: python3 scripts/conv_preflight.py migration/conv-targets-<ts>.json"""
import csv, json, sys
from collections import Counter
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env
import conv_lib

def connect():
    e = _load_env()
    return Metabase_API(domain=e["METABASE_DOMAIN"], email=e["METABASE_EMAIL"], password=e["METABASE_PASSWORD"])

def main():
    mb = connect()
    targets = json.loads(Path(sys.argv[1]).read_text())
    mapping_all = json.loads((REPO / "migration" / "conv-client-mapping.json").read_text())
    raw = json.loads((REPO / "migration" / "conv-new-index.json").read_text())
    index = {}
    for k, v in raw.items():
        col, shape = json.loads(k)
        index[(col, tuple([shape[0], shape[1], tuple(shape[2])]))] = v
    rows, counts = [], Counter()
    for d in targets:
        cmap = {int(k): v for k, v in mapping_all.get(d["client"], {}).items()}
        for t in d["tiles"]:
            card = mb.get(f"/api/card/{t['card_id']}")
            res = conv_lib.resolve_new_card(card, cmap, index) if cmap else {"status": "review", "reason": "client not in mapping"}
            counts[res["status"]] += 1
            rows.append({"client": d["client"], "dashboard_id": d["dashboard_id"], "dashcard_id": t["dashcard_id"],
                         "old_card": t["card_id"], "old_name": t["card_name"], "status": res["status"],
                         "new_card": res.get("new_card_id"), "new_type": res.get("new_type"), "reason": res.get("reason")})
    base = REPO / "migration"
    (base / "conv-preflight.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    with open(base / "conv-preflight.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print("status counts:", dict(counts))
    print("-> migration/conv-preflight.json / .csv")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run and read the status distribution**

Run: `.venv/bin/python scripts/conv_preflight.py migration/conv-targets-<ts>.json`
Expected: a `status counts` dict; `ok` should dominate (~the 77% measured), the rest split across `review/multi/unmapped/conflict`. The CSV is the human review queue.

- [ ] **Step 3: Commit**

```bash
git add scripts/conv_preflight.py migration/conv-preflight.json migration/conv-preflight.csv
git commit -m "conv/preflight: resolve every target tile, emit auto vs review queue"
```

### Task 9: Wave runner + living tracker

**Files:**
- Create: `scripts/migrate_conversions_wave.py`
- Create: `docs/conversion-migration-roadmap.md` (tracker, mirrors `cleaning-roadmap.md`)
- Output: `migration/conv-wave-report-<ts>.json`

- [ ] **Step 1: Implement the wave runner (one dashboard at a time, copy or in-place)**

```python
# scripts/migrate_conversions_wave.py
#!/usr/bin/env python3
"""Exécute le migrateur sur une liste de dashboards (une vague). Par défaut --copy
(sandbox) ; --in-place --yes pour appliquer pour de vrai. Agrège un rapport + met à
jour le tracker. Réversible (chaque dashboard a son snapshot).
Usage:
  python3 scripts/migrate_conversions_wave.py --targets migration/conv-targets-<ts>.json --clients "Pro Nutrition" --copy --yes
  python3 scripts/migrate_conversions_wave.py --targets ... --clients "Pro Nutrition" --in-place --yes
"""
import argparse, json, subprocess, sys
from datetime import datetime
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", required=True)
    ap.add_argument("--clients", nargs="*", help="restreindre à ces clients (défaut: tous)")
    ap.add_argument("--copy", action="store_true")
    ap.add_argument("--in-place", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    targets = json.loads(Path(args.targets).read_text())
    sel = [d for d in targets if (not args.clients or d["client"] in args.clients) and not d["is_template_like"]]
    report = []
    for d in sel:
        cmd = [str(REPO / ".venv/bin/python"), str(REPO / "scripts/migrate_conversions_on_dashboard.py"),
               "--dashboard", str(d["dashboard_id"]), "--client", d["client"]]
        if args.copy: cmd.append("--copy")
        if args.yes: cmd.append("--yes")
        r = subprocess.run(cmd, capture_output=True, text=True)
        report.append({"client": d["client"], "dashboard_id": d["dashboard_id"],
                       "rc": r.returncode, "stdout_tail": r.stdout[-2000:], "stderr_tail": r.stderr[-500:]})
        print(f"[{ 'OK' if r.returncode==0 else 'ERR' }] {d['client']} / {d['dashboard_id']}")
    p = REPO / "migration" / f"conv-wave-report-{datetime.now():%Y%m%d-%H%M%S}.json"
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"-> {p}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create the tracker doc**

```markdown
# Conversion Migration — Roadmap (tracker vivant)

> Migration ancien positionnel -> nouveau nommé sur les dashboards custom (collection 317).
> Design: docs/superpowers/specs/2026-06-03-conversion-migration-design.md. Réversible (snapshots).
> Légende : ✅ fait · 🚧 en cours · ⬜ à faire

## Outillage (testé)
- `conv_lib.py` (+ `tests/test_conv_lib.py`) — colonnes, extracteur tolérant, mapping client, résolveur.
- `export_conv_mapping.py` · `build_new_conv_index.py` · `discover_conversion_targets.py` · `conv_preflight.py`.
- `migrate_conversions_on_dashboard.py` (snapshot, garde-fous, recâblage, réconciliation Snowflake).
- `migrate_conversions_wave.py` — runner par vague.

## Inputs (régénérables)
- `migration/conv-client-mapping.json` — mapping Airtable (date d'export : __).
- `migration/conv-new-index.json` — index arbre 11673 (date : __).
- `migration/conv-targets-<ts>.json` — dashboards cibles.
- `migration/conv-preflight.csv` — file de revue (statuts non-`ok`).

## Vagues
| # | Périmètre | Statut | Auto | Revue | Note |
|---|-----------|--------|------|-------|------|
| 0 | Pro Nutrition (pilote, copies) | ⬜ | | | valider ok + Main→Purchases |
| 1 | Pro Nutrition (in-place) | ⬜ | | | après revue vague 0 |
| 2 | 5 clients échantillon | ⬜ | | | |
| 3 | Reste (~104 clients) | ⬜ | | | par lots |

## Garde-fous
Snapshot → réconciliation Snowflake par tuile → échantillon → batch. Jamais d'archivage de
template partagé. Tuiles non-`ok` (review/conflict/unmapped/multi) : NON appliquées, file de revue.
```

- [ ] **Step 3: Pilot wave 0 on Pro Nutrition copies**

Run: `.venv/bin/python scripts/migrate_conversions_wave.py --targets migration/conv-targets-<ts>.json --clients "Pro Nutrition" --copy --yes`
Expected: each Pro Nutrition dashboard migrated on a copy, `rc 0`, reconciliations `True`. Inspect copies in Metabase, fill the tracker's wave-0 row.

- [ ] **Step 4: Commit**

```bash
git add scripts/migrate_conversions_wave.py docs/conversion-migration-roadmap.md
git commit -m "conv/wave: wave runner + living migration tracker; pilot wave 0 (Pro Nutrition copies)"
```

### Task 10: Agent-parallel rollout (optional scale-out)

> For >100 dashboards, parallelize wave execution. Each unit is independent (distinct dashboard, own snapshot), so it fans out cleanly. Use the Workflow tool: one agent per dashboard runs `migrate_conversions_on_dashboard.py --in-place --yes`, returns its reconciliation verdict; a final stage aggregates failures into the review queue and updates the tracker. Gate each wave on the prior wave's reconciliations being green. Apply in-place only after the copy-based pilot for that client passed.

- [ ] **Step 1:** After wave-0 (copies) is signed off, run wave-1 in-place for Pro Nutrition; verify each tile reconciles and the live dashboards render; update tracker.
- [ ] **Step 2:** Run a 5-client sample wave (copies → review → in-place). Triage the preflight review queue; map exotic shapes by hand into `migration/conv-new-index.json` overrides or skip.
- [ ] **Step 3:** Batch the remaining clients in waves of ~10, each gated on green reconciliation; keep the tracker current; never archive shared templates.
- [ ] **Step 4: Cleanup** — delete the spike sandbox (collection 13851, dashboard 25302) and any `MIGRATION TEST` copies once their client is migrated in-place.

---

## Self-review notes

- **Spec coverage:** tool design (§5)→Tasks 1–6; validation incl. Snowflake reconcile (§6)→Task 6 steps 2–4; sizing/coverage (§7)→Tasks 7–8; type-axis ingestion (§2,§9)→Tasks 2–3; scaling/agents/tracker (§8)→Tasks 9–10; custom-dashboard discovery (§9 open)→Task 7.
- **Format-tolerant extractor** (mandatory per spike) is Task 1 and used everywhere downstream.
- **Never-archive / per-dashcard / snapshot** invariants encoded in Task 6.
- **Review queue** (unmapped/conflict/multi/review) never auto-applies (Tasks 6, 8, 10).
