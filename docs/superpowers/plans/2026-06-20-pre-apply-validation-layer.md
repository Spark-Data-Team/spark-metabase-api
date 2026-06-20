# Pre-apply Validation Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable, execution-based validation layer (`spark_metabase_api/validate.py`) that gates Metabase content changes — structure, refs, execution, and before/after differential — consumed by `iac.apply()`, campaign libs, and a `spark-metabase validate` CLI.

**Architecture:** A single module exposes a `CardUnit` normalization, four pure-ish check functions ordered cheap→expensive, a `Report`/`Finding` model that renders like `iac.Plan`, and a `guarded_apply` orchestrator that captures a baseline, runs the pre-apply gate (aborting on error), mutates, then diffs. Execution runs the real query via `POST /api/dataset` (unsaved) or `get_card_data` (saved) — Metabase is the source of truth.

**Tech Stack:** Python 3, the existing `Metabase_API` wrapper (`client.get/post/put`, `get_card_data`), `iac.CollectionSpec`, pytest.

## Global Constraints

- Implements Phase 1 of `docs/superpowers/specs/2026-06-20-metabase-pre-apply-validation-design.md`. Phase 0 (`2026-06-20-repo-menage-leger.md`) lands first.
- **Execution is the source of truth** — no static-only mode is authoritative; `--no-execute` is only a smoke fallback.
- Non-goals: no chatbot wiring, no Enterprise JAR, no metadata cache.
- REST helper contract: `client.post(ep, "raw", json=body)` returns a `requests.Response`; `client.post(ep, json=body)` returns parsed JSON or `False`; `client.get(ep)` returns JSON or `False`. `client.get_card_data(card_id=ID, data_format="json")` returns a list of row dicts.
- Differential metric = auto (row count + column set + per-numeric-column sums), tolerance default 0.0, with optional per-card override.
- Findings are collected into a `Report`, never raised mid-batch.
- Commit messages end with the `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` trailer.

---

### Task 1: Report + Finding data model

**Files:**
- Create: `spark_metabase_api/validate.py`
- Test: `tests/test_validate.py`

**Interfaces:**
- Produces:
  - `Finding(target: str, check: str, level: str, message: str, before=None, after=None)` — `level` ∈ {"error","warn","ok"}.
  - `Report` with `.add(f)`, `.findings: list`, `.errors() -> list`, `.ok() -> bool`, `.summary() -> str`, `.render() -> str`, `.exit_code() -> int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_validate.py
from spark_metabase_api import validate as V

def test_report_collects_and_renders():
    r = V.Report()
    r.add(V.Finding("c/A", "structure", "ok", "well-formed"))
    r.add(V.Finding("c/B", "execution", "error", "query failed: boom"))
    assert [f.level for f in r.findings] == ["ok", "error"]
    assert r.ok() is False
    assert len(r.errors()) == 1
    assert r.exit_code() == 1
    out = r.render()
    assert "c/B" in out and "query failed" in out
    assert "1 error" in r.summary()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_validate.py::test_report_collects_and_renders -v`
Expected: FAIL (`ModuleNotFoundError` / `AttributeError`).

- [ ] **Step 3: Implement the model**

```python
# spark_metabase_api/validate.py
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class Finding:
    target: str
    check: str
    level: str  # "error" | "warn" | "ok"
    message: str
    before: Any = None
    after: Any = None

@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)

    def add(self, f: Finding) -> None:
        self.findings.append(f)

    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.level == "error"]

    def ok(self) -> bool:
        return not self.errors()

    def summary(self) -> str:
        counts: Dict[str, int] = {}
        for f in self.findings:
            counts[f.level] = counts.get(f.level, 0) + 1
        parts = ["{} {}".format(v, k) for k, v in sorted(counts.items())]
        return ", ".join(parts) or "no findings"

    def render(self) -> str:
        glyph = {"error": "✗", "warn": "!", "ok": "✓"}
        lines = ["  {}  {:<12} {}  [{}]".format(
            glyph.get(f.level, "?"), f.check, f.target, f.message)
            for f in self.findings]
        return "\n".join(lines) + ("\n" if lines else "") + "Report: " + self.summary()

    def exit_code(self) -> int:
        return 1 if self.errors() else 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_validate.py::test_report_collects_and_renders -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add spark_metabase_api/validate.py tests/test_validate.py
git commit -m "feat(validate): Report + Finding model with render/exit_code

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: CardUnit + target builders

**Files:**
- Modify: `spark_metabase_api/validate.py`
- Test: `tests/test_validate.py`

**Interfaces:**
- Consumes: `iac.CollectionSpec` / `iac.CardSpec` (have `.name`, `.cards`, `.collections`, `.definition`).
- Produces:
  - `CardUnit(target, dataset_query, display=None, visualization_settings=None, live_card_id=None, expected_columns=None, metric_override=None)`.
  - `units_from_spec(spec) -> List[CardUnit]`
  - `unit_from_payload(target, payload: dict) -> CardUnit`
  - `unit_from_card_id(client, card_id: int) -> CardUnit` (sets `live_card_id`).

- [ ] **Step 1: Write the failing test**

```python
def test_units_from_spec_and_payload():
    from spark_metabase_api import iac
    spec = iac.spec_from_dict({
        "name": "Acme",
        "cards": [{"name": "Rev", "definition": {
            "dataset_query": {"database": 2, "type": "native",
                              "native": {"query": "SELECT 1"}},
            "display": "table"}}],
    })
    units = V.units_from_spec(spec)
    assert len(units) == 1
    assert units[0].target == "Acme/Rev"
    assert units[0].dataset_query["database"] == 2
    assert units[0].live_card_id is None

    u = V.unit_from_payload("c/X", {"dataset_query": {"database": 1, "type": "query",
                                                      "query": {"source-table": 5}}})
    assert u.dataset_query["type"] == "query"

class FakeClient:
    def __init__(self, cards): self._cards = cards
    def get(self, ep, *a, **k):
        cid = int(ep.rstrip("/").split("/")[-1])
        return self._cards.get(cid, False)

def test_unit_from_card_id():
    client = FakeClient({7: {"dataset_query": {"database": 1, "type": "native",
                                               "native": {"query": "SELECT 1"}},
                             "display": "scalar"}})
    u = V.unit_from_card_id(client, 7)
    assert u.live_card_id == 7 and u.dataset_query["database"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_validate.py -k units -v`
Expected: FAIL (`AttributeError: CardUnit`).

- [ ] **Step 3: Implement**

```python
@dataclass
class CardUnit:
    target: str
    dataset_query: Dict[str, Any] = field(default_factory=dict)
    display: Optional[str] = None
    visualization_settings: Optional[Dict[str, Any]] = None
    live_card_id: Optional[int] = None
    expected_columns: Optional[List[str]] = None
    metric_override: Optional[Dict[str, Any]] = None

def units_from_spec(spec) -> List["CardUnit"]:
    units: List[CardUnit] = []
    def walk(coll, path):
        for card in coll.cards:
            defn = card.definition or {}
            units.append(CardUnit(
                target=path + "/" + card.name,
                dataset_query=defn.get("dataset_query") or {},
                display=defn.get("display"),
                visualization_settings=defn.get("visualization_settings"),
            ))
        for sub in coll.collections:
            walk(sub, path + "/" + sub.name)
    walk(spec, spec.name)
    return units

def unit_from_payload(target: str, payload: Dict[str, Any]) -> "CardUnit":
    return CardUnit(
        target=target,
        dataset_query=payload.get("dataset_query") or {},
        display=payload.get("display"),
        visualization_settings=payload.get("visualization_settings"),
    )

def unit_from_card_id(client, card_id: int) -> "CardUnit":
    card = client.get("/api/card/{}".format(card_id))
    if not card:
        raise ValueError("card {} not found".format(card_id))
    return CardUnit(
        target="card#{}".format(card_id),
        dataset_query=card.get("dataset_query") or {},
        display=card.get("display"),
        visualization_settings=card.get("visualization_settings"),
        live_card_id=card_id,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_validate.py -k units -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add spark_metabase_api/validate.py tests/test_validate.py
git commit -m "feat(validate): CardUnit + target builders (spec/payload/live)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: check_structure

**Files:** Modify `spark_metabase_api/validate.py`; Test `tests/test_validate.py`.

**Interfaces:**
- Produces: `check_structure(unit: CardUnit) -> Finding` (level "error" or "ok", check="structure").

- [ ] **Step 1: Write the failing test**

```python
def test_check_structure():
    ok = V.CardUnit("c/A", {"database": 1, "type": "native", "native": {"query": "SELECT 1"}})
    assert V.check_structure(ok).level == "ok"
    no_db = V.CardUnit("c/B", {"type": "native", "native": {"query": "SELECT 1"}})
    assert V.check_structure(no_db).level == "error"
    empty = V.CardUnit("c/C", {"database": 1, "type": "native", "native": {"query": ""}})
    assert V.check_structure(empty).level == "error"
    bad_type = V.CardUnit("c/D", {"database": 1, "type": "weird"})
    assert V.check_structure(bad_type).level == "error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_validate.py -k structure -v` — Expected: FAIL.

- [ ] **Step 3: Implement**

```python
def check_structure(unit: "CardUnit") -> Finding:
    dq = unit.dataset_query
    if not isinstance(dq, dict) or "database" not in dq:
        return Finding(unit.target, "structure", "error", "dataset_query missing 'database'")
    qtype = dq.get("type")
    if qtype == "native":
        if not (dq.get("native") or {}).get("query"):
            return Finding(unit.target, "structure", "error", "native query is empty")
    elif qtype == "query":
        if not dq.get("query"):
            return Finding(unit.target, "structure", "error", "MBQL query is empty")
    else:
        return Finding(unit.target, "structure", "error", "unknown query type {!r}".format(qtype))
    return Finding(unit.target, "structure", "ok", "well-formed")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_validate.py -k structure -v` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add spark_metabase_api/validate.py tests/test_validate.py
git commit -m "feat(validate): check_structure (well-formed payload)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: check_refs

**Files:** Modify `spark_metabase_api/validate.py`; Test `tests/test_validate.py`.

**Interfaces:**
- Produces: `check_refs(client, unit: CardUnit) -> List[Finding]`. Verifies MBQL `source-table: "card__N"` and native field-filter `values_source_config.card_id` resolve to a live, non-archived card via `client.get("/api/card/N")`.

- [ ] **Step 1: Write the failing test**

```python
def test_check_refs():
    client = FakeClient({9: {"archived": False}})  # card 9 exists; 99 does not
    src_ok = V.CardUnit("c/A", {"database": 1, "type": "query",
                                "query": {"source-table": "card__9"}})
    assert all(f.level != "error" for f in V.check_refs(client, src_ok))
    src_bad = V.CardUnit("c/B", {"database": 1, "type": "query",
                                 "query": {"source-table": "card__99"}})
    assert any(f.level == "error" for f in V.check_refs(client, src_bad))
    ff_bad = V.CardUnit("c/C", {"database": 1, "type": "native", "native": {
        "query": "SELECT 1", "template-tags": {
            "x": {"values_source_config": {"card_id": 99}}}}})
    assert any(f.level == "error" for f in V.check_refs(client, ff_bad))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_validate.py -k refs -v` — Expected: FAIL.

- [ ] **Step 3: Implement**

```python
def _card_exists(client, card_id: int) -> bool:
    card = client.get("/api/card/{}".format(card_id))
    return bool(card) and not card.get("archived")

def check_refs(client, unit: "CardUnit") -> List[Finding]:
    findings: List[Finding] = []
    dq = unit.dataset_query
    if dq.get("type") == "query":
        src = (dq.get("query") or {}).get("source-table")
        if isinstance(src, str) and src.startswith("card__"):
            cid = int(src.split("__")[1])
            if not _card_exists(client, cid):
                findings.append(Finding(unit.target, "refs", "error",
                    "source card {} not found / archived".format(cid)))
    for tag in ((dq.get("native") or {}).get("template-tags") or {}).values():
        cid = (tag.get("values_source_config") or {}).get("card_id")
        if cid and not _card_exists(client, cid):
            findings.append(Finding(unit.target, "refs", "error",
                "field-filter source card {} not found / archived".format(cid)))
    if not findings:
        findings.append(Finding(unit.target, "refs", "ok", "refs resolve"))
    return findings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_validate.py -k refs -v` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add spark_metabase_api/validate.py tests/test_validate.py
git commit -m "feat(validate): check_refs (source-card + field-filter cards resolve)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: run_query wrapper + check_execution

**Files:**
- Modify: `spark_metabase_api/main_methods.py` (add `run_query` method).
- Modify: `spark_metabase_api/validate.py` (add `_execute_unit`, `check_execution`).
- Test: `tests/test_validate.py`.

**Interfaces:**
- Produces:
  - `Metabase_API.run_query(self, dataset_query: dict, parameters: list = None) -> dict` — POST `/api/dataset`, returns decoded JSON (`{"data": {"rows", "cols"}, "status", "error"?}`).
  - `_execute_unit(client, unit) -> (rows: List[dict], error: Optional[str])` — uses `get_card_data` for saved cards, `run_query` otherwise.
  - `check_execution(client, unit) -> Finding`.

- [ ] **Step 1: Write the failing test**

```python
class ExecClient:
    def __init__(self, dataset_result=None, card_rows=None):
        self._ds = dataset_result; self._rows = card_rows
    def run_query(self, dq, parameters=None): return self._ds
    def get_card_data(self, card_id=None, data_format="json"): return self._rows

def test_check_execution():
    good = ExecClient(dataset_result={"status": "completed",
        "data": {"cols": [{"name": "n"}], "rows": [[1], [2]]}})
    u = V.CardUnit("c/A", {"database": 1, "type": "native", "native": {"query": "SELECT n"}})
    f = V.check_execution(good, u)
    assert f.level == "ok" and "2 rows" in f.message

    failed = ExecClient(dataset_result={"status": "failed", "error": "SQL compilation error"})
    assert V.check_execution(failed, u).level == "error"

    empty = ExecClient(dataset_result={"status": "completed", "data": {"cols": [], "rows": []}})
    assert V.check_execution(empty, u).level == "warn"

    saved = ExecClient(card_rows=[{"n": 1}])
    su = V.CardUnit("card#5", {"database": 1, "type": "native", "native": {"query": "x"}}, live_card_id=5)
    assert V.check_execution(saved, su).level == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_validate.py -k execution -v` — Expected: FAIL.

- [ ] **Step 3a: Add `run_query` to the wrapper**

In `spark_metabase_api/main_methods.py`, add a method to the `Metabase_API` class (place near `get_card_data`):
```python
    def run_query(self, dataset_query, parameters=None):
        """Run an ad-hoc dataset_query (POST /api/dataset) and return parsed JSON.

        dataset_query is the shape stored in a card's definition:
            {"database": <id>, "type": "native"|"query", "native"|"query": {...}}
        """
        body = dict(dataset_query)
        body["parameters"] = parameters or []
        res = self.post("/api/dataset", "raw", json=body)
        try:
            return res.json()
        except Exception:
            return {"status": "failed", "error": "non-JSON response ({})".format(
                getattr(res, "status_code", "?"))}
```

- [ ] **Step 3b: Add `_execute_unit` + `check_execution` to validate.py**

```python
def _execute_unit(client, unit: "CardUnit"):
    """Run the unit's query. Returns (rows: list[dict], error: str|None)."""
    if unit.live_card_id is not None:
        try:
            rows = client.get_card_data(card_id=unit.live_card_id, data_format="json")
        except Exception as e:
            return [], str(e)
        return rows or [], None
    res = client.run_query(unit.dataset_query)
    if not isinstance(res, dict) or res.get("status") == "failed" or res.get("error"):
        err = res.get("error") if isinstance(res, dict) else "HTTP error"
        return [], err or "query failed"
    data = res.get("data") or {}
    cols = [c.get("name") for c in (data.get("cols") or [])]
    rows = [dict(zip(cols, r)) for r in (data.get("rows") or [])]
    return rows, None

def check_execution(client, unit: "CardUnit") -> Finding:
    rows, error = _execute_unit(client, unit)
    if error:
        return Finding(unit.target, "execution", "error", "query failed: {}".format(error))
    if not rows:
        return Finding(unit.target, "execution", "warn", "query returned 0 rows")
    if unit.expected_columns:
        missing = [c for c in unit.expected_columns if c not in rows[0]]
        if missing:
            return Finding(unit.target, "execution", "warn",
                           "missing expected columns: {}".format(missing))
    return Finding(unit.target, "execution", "ok", "{} rows".format(len(rows)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_validate.py -k execution -v` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add spark_metabase_api/main_methods.py spark_metabase_api/validate.py tests/test_validate.py
git commit -m "feat(validate): run_query wrapper + check_execution (run via /api/dataset)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: check_differential

**Files:** Modify `spark_metabase_api/validate.py`; Test `tests/test_validate.py`.

**Interfaces:**
- Produces:
  - `_signature(rows) -> {"row_count": int, "columns": list, "sums": {col: number}}` (a column is numeric only if all non-null values are int/float and not bool).
  - `check_differential(target, before, after, mode="monitor", tolerance=0.0) -> List[Finding]` — `mode="identical"` ⇒ deltas are errors; `mode="monitor"` ⇒ deltas are warns.

- [ ] **Step 1: Write the failing test**

```python
def test_check_differential():
    before = [{"k": "a", "v": 10}, {"k": "b", "v": 20}]
    same = [{"k": "a", "v": 10}, {"k": "b", "v": 20}]
    assert all(f.level == "ok" for f in V.check_differential("t", before, same, mode="identical"))

    dropped = [{"k": "a", "v": 10}]
    fs = V.check_differential("t", before, dropped, mode="identical")
    assert any(f.level == "error" and "row count" in f.message for f in fs)

    drift = [{"k": "a", "v": 10}, {"k": "b", "v": 25}]
    fs = V.check_differential("t", before, drift, mode="monitor")
    assert any(f.level == "warn" and "sum(v)" in f.message for f in fs)
    fs2 = V.check_differential("t", before, drift, mode="identical")
    assert any(f.level == "error" for f in fs2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_validate.py -k differential -v` — Expected: FAIL.

- [ ] **Step 3: Implement**

```python
def _signature(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    cols = list(rows[0].keys()) if rows else []
    sums: Dict[str, float] = {}
    for c in cols:
        vals = [r.get(c) for r in rows if r.get(c) is not None]
        if vals and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            sums[c] = sum(vals)
    return {"row_count": len(rows), "columns": cols, "sums": sums}

def check_differential(target, before, after, mode="monitor", tolerance=0.0) -> List[Finding]:
    sb, sa = _signature(before), _signature(after)
    level = "error" if mode == "identical" else "warn"
    findings: List[Finding] = []
    if sb["row_count"] != sa["row_count"]:
        findings.append(Finding(target, "differential", level,
            "row count {} -> {}".format(sb["row_count"], sa["row_count"]),
            before=sb["row_count"], after=sa["row_count"]))
    if set(sb["columns"]) != set(sa["columns"]):
        findings.append(Finding(target, "differential", level, "columns changed",
            before=sb["columns"], after=sa["columns"]))
    for c, bsum in sb["sums"].items():
        asum = sa["sums"].get(c)
        if asum is None:
            continue
        denom = abs(bsum) or 1.0
        if abs(asum - bsum) / denom > tolerance:
            findings.append(Finding(target, "differential", level,
                "sum({}) {} -> {}".format(c, bsum, asum), before=bsum, after=asum))
    if not findings:
        findings.append(Finding(target, "differential", "ok", "no significant change"))
    return findings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_validate.py -k differential -v` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add spark_metabase_api/validate.py tests/test_validate.py
git commit -m "feat(validate): check_differential (row/column/numeric-sum, identical|monitor)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: gate + guarded_apply orchestration

**Files:** Modify `spark_metabase_api/validate.py`; Test `tests/test_validate.py`.

**Interfaces:**
- Produces:
  - `gate(client, units, execute=True) -> Report` — per unit: structure → (if ok) refs → (if no ref error and execute) execution. Fail-fast per unit.
  - `guarded_apply(client, units, mutate_fn, differential="monitor", force=False, execute=True) -> Report` — capture baselines (units with `live_card_id`), run `gate`; if errors and not `force`, append an aborted finding and return WITHOUT calling `mutate_fn`; else call `mutate_fn()`, then diff each baselined unit.

- [ ] **Step 1: Write the failing test**

```python
def test_gate_and_guarded_apply():
    # gate: a structurally broken unit short-circuits (no execution attempted)
    broken = V.CardUnit("c/bad", {"type": "native", "native": {"query": "x"}})
    g = V.gate(ExecClient(), [broken], execute=True)
    assert not g.ok() and [f.check for f in g.findings] == ["structure"]

    # guarded_apply: gate errors -> mutate_fn NOT called
    calls = []
    rep = V.guarded_apply(ExecClient(), [broken], lambda: calls.append(1),
                          differential="off", force=False, execute=False)
    assert calls == [] and not rep.ok()

    # force=True runs mutate_fn despite errors
    calls2 = []
    V.guarded_apply(ExecClient(), [broken], lambda: calls2.append(1),
                    differential="off", force=True, execute=False)
    assert calls2 == [1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_validate.py -k guarded -v` — Expected: FAIL.

- [ ] **Step 3: Implement**

```python
def gate(client, units, execute=True) -> Report:
    report = Report()
    for u in units:
        s = check_structure(u)
        report.add(s)
        if s.level == "error":
            continue
        ref_findings = check_refs(client, u)
        for f in ref_findings:
            report.add(f)
        if any(f.level == "error" for f in ref_findings):
            continue
        if execute:
            report.add(check_execution(client, u))
    return report

def guarded_apply(client, units, mutate_fn, differential="monitor",
                  force=False, execute=True) -> Report:
    report = Report()
    baselines: Dict[str, List[Dict[str, Any]]] = {}
    if differential != "off":
        for u in units:
            if u.live_card_id is not None:
                rows, err = _execute_unit(client, u)
                if not err:
                    baselines[u.target] = rows
    g = gate(client, units, execute=execute)
    report.findings.extend(g.findings)
    if g.errors() and not force:
        report.add(Finding("apply", "gate", "error",
                           "aborted: pre-apply errors, nothing mutated"))
        return report
    mutate_fn()
    if differential != "off":
        mode = "identical" if differential == "identical" else "monitor"
        for u in units:
            if u.target in baselines:
                after, err = _execute_unit(client, u)
                if err:
                    report.add(Finding(u.target, "differential", "error",
                        "post-apply query failed: {}".format(err)))
                    continue
                for f in check_differential(u.target, baselines[u.target], after, mode=mode):
                    report.add(f)
    return report
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_validate.py -k guarded -v` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add spark_metabase_api/validate.py tests/test_validate.py
git commit -m "feat(validate): gate + guarded_apply (baseline -> gate -> mutate -> diff)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Integrate the gate into iac.apply

**Files:**
- Modify: `spark_metabase_api/iac.py` (`apply` signature + pre-apply gate).
- Test: `tests/test_validate.py`.

**Interfaces:**
- Consumes: `validate.units_from_spec`, `validate.gate`.
- Produces: `iac.apply(client, spec, parent_id=None, dry_run=False, validate=False, force=False)` — when `validate=True`, build units from the spec, run `gate(client, units, execute=True)`; if it has errors and not `force`, raise `ValidationError` (defined in `validate.py`) before any mutation. Returns the `Plan` as before.

- [ ] **Step 1: Write the failing test**

```python
def test_iac_apply_gate_aborts(monkeypatch):
    from spark_metabase_api import iac, validate as V
    spec = iac.spec_from_dict({"name": "Acme", "cards": [{"name": "Bad",
        "definition": {"dataset_query": {"type": "native", "native": {"query": "x"}}}}]})  # no database -> structure error

    called = {"executed": False}
    monkeypatch.setattr(iac, "_execute_collection",
                        lambda *a, **k: called.__setitem__("executed", True))
    monkeypatch.setattr(iac, "plan", lambda *a, **k: iac.Plan())

    try:
        iac.apply(object(), spec, validate=True)
        assert False, "expected ValidationError"
    except V.ValidationError:
        pass
    assert called["executed"] is False  # gate aborted before mutation
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_validate.py -k iac_apply_gate -v` — Expected: FAIL (`TypeError: unexpected kwarg 'validate'`).

- [ ] **Step 3: Implement**

Add to `validate.py`:
```python
class ValidationError(Exception):
    def __init__(self, report: "Report"):
        self.report = report
        super().__init__("validation failed:\n" + report.render())
```

Modify `iac.apply` in `iac.py`:
```python
def apply(client, spec: CollectionSpec, parent_id: Optional[int] = None,
          dry_run: bool = False, validate: bool = False, force: bool = False) -> Plan:
    p = plan(client, spec, parent_id=parent_id)
    if dry_run:
        return p
    if validate:
        from . import validate as _v
        report = _v.gate(client, _v.units_from_spec(spec), execute=True)
        if not report.ok() and not force:
            raise _v.ValidationError(report)
    by_path = {a.path: a for a in p.actions}
    _execute_collection(client, spec, parent_id, parent_path="", by_path=by_path)
    return p
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_validate.py -k iac_apply_gate -v` — Expected: PASS. Then run the full suite: `python -m pytest -q` — Expected: PASS (no regression in existing iac tests).

- [ ] **Step 5: Commit**

```bash
git add spark_metabase_api/iac.py spark_metabase_api/validate.py tests/test_validate.py
git commit -m "feat(iac): apply(validate=True) runs the pre-apply gate, aborts on error

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: CLI `spark-metabase validate` subcommand

**Files:**
- Modify: `spark_metabase_api/iac.py` (`main` — add `validate` subparser + `resolve_cli_target`).
- Test: `tests/test_validate.py`.

**Interfaces:**
- Consumes: `validate.units_from_spec`, `validate.unit_from_card_id`, `validate.gate`, `iac.load`, `iac.export`.
- Produces:
  - `validate.resolve_cli_target(client, target: str) -> List[CardUnit]` — a `.yaml/.yml/.json` path → `units_from_spec(load(path))`; an all-digit string → `[unit_from_card_id(client, int)]`; else a collection id/name → `units_from_spec(export(client, target))`.
  - CLI: `spark-metabase validate <target> [--no-execute] [--differential identical|monitor|off]` printing `report.render()` and returning `report.exit_code()`.

- [ ] **Step 1: Write the failing test**

```python
def test_resolve_cli_target_spec(tmp_path):
    from spark_metabase_api import iac, validate as V
    spec_file = tmp_path / "s.json"
    iac.dump(iac.spec_from_dict({"name": "Acme", "cards": [{"name": "R",
        "definition": {"dataset_query": {"database": 1, "type": "native",
                                         "native": {"query": "SELECT 1"}}}}]}), str(spec_file))
    units = V.resolve_cli_target(object(), str(spec_file))
    assert len(units) == 1 and units[0].target == "Acme/R"

def test_resolve_cli_target_card_id():
    from spark_metabase_api import validate as V
    client = FakeClient({4: {"dataset_query": {"database": 1, "type": "native",
                                               "native": {"query": "x"}}}})
    units = V.resolve_cli_target(client, "4")
    assert units[0].live_card_id == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_validate.py -k resolve_cli -v` — Expected: FAIL.

- [ ] **Step 3a: Add `resolve_cli_target` to validate.py**

```python
def resolve_cli_target(client, target: str) -> List["CardUnit"]:
    import os
    from . import iac
    if target.lower().endswith((".yaml", ".yml", ".json")) and os.path.exists(target):
        return units_from_spec(iac.load(target))
    if target.isdigit():
        return [unit_from_card_id(client, int(target))]
    return units_from_spec(iac.export(client, target))
```

- [ ] **Step 3b: Add the `validate` subcommand to `iac.main`**

In the subparser block:
```python
    p_val = sub.add_parser("validate", help="Validate a spec / collection / card before applying")
    p_val.add_argument("target", help="spec path | collection id/name | card id")
    p_val.add_argument("--no-execute", action="store_true",
                       help="skip running queries (structure+refs smoke check only)")
```
In the dispatch block (before `return 1`):
```python
    if args.cmd == "validate":
        from . import validate as _v
        units = _v.resolve_cli_target(client, args.target)
        report = _v.gate(client, units, execute=not args.no_execute)
        print(report.render())
        return report.exit_code()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_validate.py -k resolve_cli -v` — Expected: PASS. Then `python -m pytest -q` — Expected: PASS.

- [ ] **Step 5: Verify the CLI wiring end-to-end (smoke)**

Run: `python -m spark_metabase_api.iac validate --help`
Expected: usage text shows the `validate` subcommand and `--no-execute`. (Confirm the `spark-metabase` console entry point maps to `iac.main` in `setup.py`; if a different entry point is used, wire the subcommand there too.)

- [ ] **Step 6: Commit**

```bash
git add spark_metabase_api/iac.py spark_metabase_api/validate.py tests/test_validate.py
git commit -m "feat(cli): spark-metabase validate <spec|collection|card> [--no-execute]

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Opt-in live integration phase

**Files:**
- Modify: `tests/integration_test.py` (add a read-only validation phase against the sandbox).

**Interfaces:**
- Consumes: `validate.unit_from_card_id`, `validate.gate`, `validate.guarded_apply`.

- [ ] **Step 1: Add a read-only validation phase**

In the existing Phase 1 (read-only) section of `tests/integration_test.py`, after a card is known, add:
```python
    # Validation smoke (read-only): the sandbox source card must pass the gate.
    from spark_metabase_api import validate as V
    units = [V.unit_from_card_id(mb, args.source_dashboard_id)] if False else []
    if card_id:  # an existing card id discovered earlier in the phase
        report = V.gate(mb, [V.unit_from_card_id(mb, card_id)], execute=True)
        print(report.render())
        assert report.ok(), "validation gate failed on a known-good card"
```

- [ ] **Step 2: Run the integration test against a live sandbox (manual, opt-in)**

Run:
```bash
python tests/integration_test.py --domain "$MB_URL" --email "$MB_USER" --password "$MB_PASS" --collection "My Reports" --source-dashboard-id 42
```
Expected: the new validation lines print a `Report` and the assertion passes on a known-good card.

- [ ] **Step 3: Commit**

```bash
git add tests/integration_test.py
git commit -m "test(validate): opt-in live validation phase in integration test

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

- **Spec coverage:**
  - §4.1 Target abstraction → Task 2. §4.2 checks: structure → T3, refs → T4, execution → T5, differential → T6. §4.3 Report → T1. §4.4 around-apply orchestration → T7. §4.5 integration: iac.apply → T8, CLI → T9, campaign libs → `guarded_apply` (T7, callable by libs). §4.6 wrapper `run_query` → T5. §6 testing → tests in every task + T10 live phase. ✓
  - §4.5 "campaign libs call guarded_apply" — provided as a public function in T7; wiring each lib is part of using it during a campaign, not a code change here. Noted, not a gap.
- **Placeholder scan:** every code step contains complete, runnable code; no TBD/TODO. ✓
- **Type consistency:** `Finding`/`Report`/`CardUnit` field names, `check_structure`→`Finding`, `check_refs`/`check_execution`/`gate`/`guarded_apply` signatures, and `run_query` return shape are consistent across T1–T9. `_execute_unit` returns `(rows, error)` used identically in T5 and T7. ✓
- **Risk (params for /api/dataset)** from spec §7: surfaced in execution (a failed run becomes an `error` Finding); deriving template-tag defaults is an enhancement, not required for the gate to function. Acceptable for v1.
