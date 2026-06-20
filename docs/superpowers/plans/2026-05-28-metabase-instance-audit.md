# Audit instance-wide Metabase — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire `scripts/audit.py` (scan → deep → report) qui scanne toute l'instance Metabase (868 collections, ~5654 cartes), détecte 11 patterns d'optimisation et produit un rapport markdown court + un JSON exhaustif servant de backlog de campagnes.

**Architecture:** Trois fichiers à responsabilité unique — `audit_lib.py` (analyse pure : empreintes v2, détecteurs, scoring), `audit_report.py` (rendu markdown digest), `audit.py` (orchestration + I/O réseau + cache disque reprenable). Logique pure testée en TDD sur fixtures (aucun réseau) ; commandes CLI vérifiées par run live. Lecture seule.

**Tech Stack:** Python 3 (stdlib uniquement : `hashlib`, `json`, `re`, `argparse`, `collections`), le wrapper `spark_metabase_api`, réutilise `reorg_phase1._load_env` / `rename_lib.normalize_name`. Tests = scripts standalone (convention du repo, pas de pytest).

---

## Spec de référence

`docs/superpowers/specs/2026-05-28-metabase-instance-audit-design.md`

## File Structure

| Fichier | Responsabilité |
|---------|----------------|
| `scripts/audit_lib.py` | Analyse pure : `query_fingerprint`, `output_fingerprint`, `classify_query_groups`, détecteurs (#1-#10), `build_source_ids`, `PATTERNS` (scoring), `summarize_findings`. Aucune I/O. |
| `scripts/audit_report.py` | `render_report(findings)` → markdown **court** (digest). |
| `scripts/audit.py` | CLI `scan`/`deep`/`report` : connexion, fetch, cache disque reprenable, écriture du JSON et du `.md`. |
| `tests/test_audit_lib.py` | Tests standalone des fonctions pures (dont la régression faux-positifs). |
| `tests/test_audit_report.py` | Tests standalone du rendu (digest court). |

Conventions du repo (à respecter) :
- Scripts en tête : `REPO_ROOT = Path(__file__).resolve().parent.parent` puis `sys.path.insert(0, str(REPO_ROOT / "scripts"))`.
- Connexion run long : email/password (`connect_resilient`), comme `prune_unused.py`.
- Tests : liste `TESTS = [...]`, fonction `run()`, `sys.exit(1 if failures else 0)`, lancés par `python3 tests/test_x.py`.

---

## Task 1: Scaffold `audit_lib.py` + registre `PATTERNS`

**Files:**
- Create: `scripts/audit_lib.py`
- Test: `tests/test_audit_lib.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audit_lib.py`:

```python
#!/usr/bin/env python3
"""Tests unitaires d'audit_lib — script autonome (convention du repo).

Usage : python3 tests/test_audit_lib.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import audit_lib


def test_patterns_registry_complete():
    assert len(audit_lib.PATTERNS) == 11
    for key, meta in audit_lib.PATTERNS.items():
        assert set(meta) >= {"num", "family", "impact", "risk", "effort", "wave"}
        assert meta["impact"] in ("H", "M", "L")
        assert meta["risk"] in ("H", "M", "L")
        assert meta["effort"] in ("H", "M", "L")
        assert meta["wave"] in (0, 1, 2, 3)
    nums = sorted(m["num"] for m in audit_lib.PATTERNS.values())
    assert nums == list(range(1, 12))


TESTS = [
    test_patterns_registry_complete,
]


def run():
    failures = 0
    for t in TESTS:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failures += 1
            print(f"FAIL  {t.__name__}: {e!r}")
    print(f"\n{len(TESTS) - failures}/{len(TESTS)} tests passés")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    run()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_audit_lib.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'audit_lib'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/audit_lib.py`:

```python
#!/usr/bin/env python3
"""Logique d'analyse de l'audit instance-wide (pur, testable, aucune I/O réseau).

Empreintes de requête v2, détecteurs de patterns, scoring. Les fonctions opèrent
sur des listes de dicts déjà récupérés par audit.py.

Voir docs/superpowers/specs/2026-05-28-metabase-instance-audit-design.md
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from rename_lib import normalize_name  # noqa: E402  (réutilise la normalisation Phase 1.5)

TEMPLATE_ROOT_ID = 215

# Registre des patterns : scoring Impact/Risque/Effort + vague (cf. spec §6).
PATTERNS = {
    "empty_collections":    {"num": 1,  "family": "structurel", "impact": "H", "risk": "L", "effort": "L", "wave": 0},
    "personal_sprawl":      {"num": 2,  "family": "structurel", "impact": "H", "risk": "H", "effort": "M", "wave": 2},
    "dup_collection_names": {"num": 3,  "family": "structurel", "impact": "M", "risk": "M", "effort": "M", "wave": 2},
    "junk_collections":     {"num": 4,  "family": "structurel", "impact": "M", "risk": "L", "effort": "L", "wave": 0},
    "unused_cards":         {"num": 5,  "family": "gaspillage", "impact": "H", "risk": "L", "effort": "L", "wave": 1},
    "pure_dups":            {"num": 6,  "family": "gaspillage", "impact": "H", "risk": "M", "effort": "M", "wave": 1},
    "archived_backlog":     {"num": 7,  "family": "gaspillage", "impact": "M", "risk": "L", "effort": "L", "wave": 0},
    "template_drift":       {"num": 8,  "family": "dry",        "impact": "H", "risk": "H", "effort": "H", "wave": 3},
    "variant_families":     {"num": 9,  "family": "dry",        "impact": "M", "risk": "M", "effort": "H", "wave": 3},
    "naming_issues":        {"num": 10, "family": "nommage",    "impact": "M", "risk": "L", "effort": "M", "wave": 1},
    "expensive_cards":      {"num": 11, "family": "perf",       "impact": "M", "risk": "L", "effort": "M", "wave": 3},
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_audit_lib.py`
Expected: `PASS  test_patterns_registry_complete` then `1/1 tests passés`

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_lib.py tests/test_audit_lib.py
git commit -m "audit: squelette audit_lib + registre PATTERNS (scoring)"
```

---

## Task 2: Empreinte v2 — `query_fingerprint` + `output_fingerprint` (régression faux-positifs)

C'est le cœur. Les 3 cartes GSC (#28943 clics, #28945 CTR, #28946 position) ont
**même SQL, mêmes paramètres, même display** ; elles ne diffèrent que par
`visualization_settings["graph.metrics"]`. L'empreinte v2 doit séparer
l'**identité de requête** (commune) de l'**identité fonctionnelle** (distincte).

**Files:**
- Modify: `scripts/audit_lib.py` (ajouter fonctions)
- Test: `tests/test_audit_lib.py` (ajouter tests)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_audit_lib.py` (above the `TESTS = [...]` list):

```python
# Fixture reproduisant les vrais faux positifs GSC : même SQL, même display,
# graph.metrics différents (CLICKS / CTR / WEIGHTED_POSITION).
_GSC_SQL = json.dumps({
    "type": "native",
    "database": 2,
    "native": {"query": "WITH get_data AS (SELECT date, clicks, ctr, weighted_position FROM gsc) SELECT * FROM get_data"},
})


def _gsc_card(cid, name, metric):
    return {
        "id": cid, "name": name, "display": "line",
        "legacy_query": _GSC_SQL,
        "visualization_settings": {"graph.metrics": [metric], "graph.dimensions": ["DATE", "URL_GROUP"]},
    }


def test_query_fingerprint_identical_for_gsc_trio():
    a = _gsc_card(28943, "Clicks by date", "CLICKS")
    b = _gsc_card(28945, "CTR by date", "CTR")
    c = _gsc_card(28946, "Weighted position by date", "WEIGHTED_POSITION")
    assert audit_lib.query_fingerprint(a) == audit_lib.query_fingerprint(b) == audit_lib.query_fingerprint(c)


def test_output_fingerprint_distinct_for_gsc_trio():
    a = _gsc_card(28943, "Clicks by date", "CLICKS")
    b = _gsc_card(28945, "CTR by date", "CTR")
    c = _gsc_card(28946, "Weighted position by date", "WEIGHTED_POSITION")
    fps = {audit_lib.output_fingerprint(a), audit_lib.output_fingerprint(b), audit_lib.output_fingerprint(c)}
    assert len(fps) == 3  # PAS des doublons


def test_output_fingerprint_identical_for_true_duplicate():
    a = _gsc_card(1, "Clicks by date", "CLICKS")
    b = _gsc_card(2, "Clicks by date (copie)", "CLICKS")  # rendu identique
    assert audit_lib.output_fingerprint(a) == audit_lib.output_fingerprint(b)
```

Then add the three test names to the `TESTS` list:

```python
TESTS = [
    test_patterns_registry_complete,
    test_query_fingerprint_identical_for_gsc_trio,
    test_output_fingerprint_distinct_for_gsc_trio,
    test_output_fingerprint_identical_for_true_duplicate,
]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_audit_lib.py`
Expected: FAIL with `AttributeError: module 'audit_lib' has no attribute 'query_fingerprint'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/audit_lib.py`:

```python
def _legacy_query(card):
    """Retourne le legacy_query (dict) ou None.

    Via l'API, `dataset_query` (nouveau format) ressort souvent vide ;
    `legacy_query` (string JSON) porte la requête classique fiable.
    """
    lq = card.get("legacy_query")
    if isinstance(lq, str):
        try:
            lq = json.loads(lq)
        except Exception:
            lq = None
    return lq if isinstance(lq, dict) and lq else None


def query_fingerprint(card):
    """Empreinte de la REQUÊTE seule (SQL/MBQL normalisé + base). Identité logique."""
    lq = _legacy_query(card)
    if lq is None:
        dq = card.get("dataset_query", {}) or {}
        return "ds|" + hashlib.md5(json.dumps(dq, sort_keys=True).encode()).hexdigest()
    db = lq.get("database")
    if lq.get("type") == "native":
        sql = (lq.get("native", {}) or {}).get("query", "") or ""
        norm = re.sub(r"\s+", " ", sql.strip().lower())
        payload = f"native|{db}|{norm}"
    else:
        payload = f"mbql|{db}|" + json.dumps(lq.get("query", {}), sort_keys=True)
    return hashlib.md5(payload.encode()).hexdigest()


def _output_selection(card):
    """Ce que la carte AFFICHE réellement — la clé des faux positifs.

    Graphes : graph.metrics + graph.dimensions. Tables/pivots : colonnes activées.
    """
    vs = card.get("visualization_settings", {}) or {}
    metrics = vs.get("graph.metrics")
    dims = vs.get("graph.dimensions")
    if metrics or dims:
        return json.dumps({"m": sorted(metrics or []), "d": sorted(dims or [])}, sort_keys=True)
    cols = vs.get("table.columns")
    if cols:
        enabled = [c.get("name") for c in cols if isinstance(c, dict) and c.get("enabled", True)]
        return json.dumps({"cols": enabled}, sort_keys=True)
    return ""


def output_fingerprint(card):
    """Empreinte FONCTIONNELLE : requête + display + sélection affichée.

    Même output_fingerprint ⇒ rendu identique ⇒ vrai doublon (#6). Même
    query_fingerprint mais output ≠ (ex. GSC clics/CTR/position) ⇒ variante (#9).
    """
    payload = f"{query_fingerprint(card)}|{card.get('display') or ''}|{_output_selection(card)}"
    return hashlib.md5(payload.encode()).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_audit_lib.py`
Expected: 4/4 tests passés (les 3 nouveaux PASS)

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_lib.py tests/test_audit_lib.py
git commit -m "audit: empreinte v2 (query_fp + output_fp) — corrige les faux positifs GSC"
```

---

## Task 3: `classify_query_groups` — doublons (#6) vs variantes (#9) vs viz≠

**Files:**
- Modify: `scripts/audit_lib.py`
- Test: `tests/test_audit_lib.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_audit_lib.py`:

```python
def test_classify_separates_dups_variants_and_viz():
    # variant_families ⟂ diff_viz pour un même groupe de requête (un groupe a soit
    # un seul display soit plusieurs) — donc deux requêtes distinctes pour tester les deux.
    a1 = _gsc_card(1, "Clicks", "CLICKS")
    a2 = _gsc_card(2, "Clicks copie", "CLICKS")          # doublon de #1 (output identique)
    a3 = _gsc_card(3, "CTR", "CTR")                       # variante
    a4 = _gsc_card(4, "Position", "WEIGHTED_POSITION")    # variante
    sql_b = json.dumps({"type": "native", "database": 2, "native": {"query": "SELECT a, b FROM t"}})
    b1 = {"id": 5, "name": "B line", "display": "line", "legacy_query": sql_b,
          "visualization_settings": {"graph.metrics": ["A"]}}
    b2 = {"id": 6, "name": "B bar", "display": "bar", "legacy_query": sql_b,
          "visualization_settings": {"graph.metrics": ["A"]}}
    res = audit_lib.classify_query_groups([a1, a2, a3, a4, b1, b2])
    assert any(sorted(c["id"] for c in g) == [1, 2] for g in res["pure_dups"])          # #6
    assert any({c["id"] for c in g} == {1, 2, 3, 4} for g in res["variant_families"])   # #9
    assert any({c["id"] for c in g} == {5, 6} for g in res["diff_viz"])
```

Add `test_classify_separates_dups_variants_and_viz` to the `TESTS` list.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_audit_lib.py`
Expected: FAIL with `AttributeError: module 'audit_lib' has no attribute 'classify_query_groups'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/audit_lib.py`:

```python
def classify_query_groups(cards):
    """Classe les cartes partageant une même requête. Enrichit chaque carte de
    'query_fp' et 'output_fp'. Retourne {pure_dups, variant_families, diff_viz}.
    """
    for c in cards:
        c["query_fp"] = query_fingerprint(c)
        c["output_fp"] = output_fingerprint(c)

    by_q = defaultdict(list)
    for c in cards:
        by_q[c["query_fp"]].append(c)

    pure_dups, variant_families, diff_viz = [], [], []
    for _q, group in by_q.items():
        if len(group) < 2:
            continue
        by_out = defaultdict(list)
        for c in group:
            by_out[c["output_fp"]].append(c)
        for _out, sub in by_out.items():
            if len(sub) >= 2:
                pure_dups.append(sub)                 # #6 : rendu identique
        displays = {c.get("display") or "" for c in group}
        if len(by_out) >= 2 and len(displays) == 1:
            variant_families.append(group)            # #9 : même viz, sélection ≠
        if len(displays) >= 2:
            diff_viz.append(group)                    # même logique, viz ≠
    pure_dups.sort(key=len, reverse=True)
    variant_families.sort(key=len, reverse=True)
    return {"pure_dups": pure_dups, "variant_families": variant_families, "diff_viz": diff_viz}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_audit_lib.py`
Expected: 5/5 tests passés

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_lib.py tests/test_audit_lib.py
git commit -m "audit: classify_query_groups — doublons #6 / variantes #9 / viz≠"
```

---

## Task 4: Graphe de sources + cartes inutilisées (#5)

**Files:**
- Modify: `scripts/audit_lib.py`
- Test: `tests/test_audit_lib.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_audit_lib.py`:

```python
def test_build_source_ids_finds_card_references():
    details = [
        {"id": 100, "dataset_query": {"query": {"source-table": "card__42"}}},
        {"id": 101, "legacy_query": json.dumps({"query": {"source-table": "card__7"}})},
    ]
    assert audit_lib.build_source_ids(details) == {42, 7}


def test_find_unused_cards_excludes_sources_and_used():
    cards = [
        {"id": 1, "name": "orpheline", "dashboard_count": 0, "archived": False},
        {"id": 2, "name": "utilisée", "dashboard_count": 3, "archived": False},
        {"id": 3, "name": "source", "dashboard_count": 0, "archived": False},
        {"id": 4, "name": "archivée", "dashboard_count": 0, "archived": True},
    ]
    unused = audit_lib.find_unused_cards(cards, source_ids={3})
    assert [c["id"] for c in unused] == [1]
```

Add both names to the `TESTS` list.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_audit_lib.py`
Expected: FAIL with `AttributeError: module 'audit_lib' has no attribute 'build_source_ids'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/audit_lib.py`:

```python
_CARD_SRC_RE = re.compile(r"card__(\d+)")


def build_source_ids(card_details):
    """Ids des cartes référencées comme SOURCE par une autre (`card__<id>`)."""
    source_ids = set()
    for d in card_details:
        lq = d.get("legacy_query")
        lq_blob = lq if isinstance(lq, str) else json.dumps(lq or {})
        blob = json.dumps(d.get("dataset_query", {})) + lq_blob
        for m in _CARD_SRC_RE.findall(blob):
            source_ids.add(int(m))
    return source_ids


def find_unused_cards(cards, source_ids):
    """Cartes 0 dashboard, non archivées, non utilisées comme source (règle 'hors sources')."""
    return [c for c in cards
            if c.get("dashboard_count", 0) == 0
            and not c.get("archived")
            and c["id"] not in source_ids]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_audit_lib.py`
Expected: 7/7 tests passés

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_lib.py tests/test_audit_lib.py
git commit -m "audit: graphe de sources + cartes inutilisées (#5, hors sources)"
```

---

## Task 5: Détecteurs de collections — vides (#1), fourre-tout (#4), noms dupliqués (#3)

**Files:**
- Modify: `scripts/audit_lib.py`
- Test: `tests/test_audit_lib.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_audit_lib.py`:

```python
def test_find_empty_collections_respects_descendants_and_personal():
    collections = [
        {"id": 1, "name": "Parent", "location": "/"},
        {"id": 2, "name": "Enfant occupé", "location": "/1/"},
        {"id": 3, "name": "Vraiment vide", "location": "/"},
        {"id": 4, "name": "Perso vide", "location": "/", "personal_owner_id": 9},
    ]
    cards = [{"id": 50, "collection_id": 2, "archived": False}]
    dashboards = []
    empty = audit_lib.find_empty_collections(collections, cards, dashboards)
    ids = {e["id"] for e in empty}
    assert ids == {3}        # 1 a un descendant occupé ; 2 est occupée ; 4 est perso


def test_find_junk_collections_matches_names():
    collections = [
        {"id": 1, "name": "To sort", "location": "/"},
        {"id": 2, "name": "TMP backup", "location": "/"},
        {"id": 3, "name": "05. Google Analytics 4", "location": "/"},
    ]
    junk_ids = {c["id"] for c in audit_lib.find_junk_collections(collections)}
    assert junk_ids == {1, 2}


def test_find_duplicate_collection_names():
    collections = [
        {"id": 1, "name": "Bar", "location": "/a/"},
        {"id": 2, "name": "Bar", "location": "/b/"},
        {"id": 3, "name": "Unique", "location": "/"},
    ]
    dups = audit_lib.find_duplicate_collection_names(collections)
    assert len(dups) == 1 and dups[0]["name"] == "Bar" and dups[0]["count"] == 2
```

Add the three names to the `TESTS` list.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_audit_lib.py`
Expected: FAIL with `AttributeError: module 'audit_lib' has no attribute 'find_empty_collections'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/audit_lib.py`:

```python
def _is_personal(col):
    return bool(col.get("personal_owner_id"))


def find_empty_collections(collections, cards, dashboards):
    """Collections non-perso sans carte/dashboard actif ET sans descendant occupé."""
    occupied = {c.get("collection_id") for c in cards if not c.get("archived")}
    occupied |= {d.get("collection_id") for d in dashboards if not d.get("archived")}
    occupied.discard(None)

    # ids de toutes les collections-ancêtres d'une collection occupée (via location)
    occupied_ancestors = set()
    for col in collections:
        if col.get("id") in occupied:
            for part in (col.get("location") or "/").strip("/").split("/"):
                if part.isdigit():
                    occupied_ancestors.add(int(part))

    empty = []
    for col in collections:
        cid = col.get("id")
        if _is_personal(col) or cid in occupied or cid in occupied_ancestors:
            continue
        empty.append({"id": cid, "name": col.get("name"), "location": col.get("location") or "/"})
    return empty


_JUNK_RE = re.compile(
    r"\b(to ?sort|[àa] trier|test|tmp|temp|old|draft|brouillon|wip|backup|"
    r"sauvegarde|copy|copie|untitled|sans titre|delete|supprimer)\b", re.I)


def find_junk_collections(collections):
    """Collections non-perso dont le nom évoque du fourre-tout / staging."""
    out = []
    for col in collections:
        if _is_personal(col):
            continue
        name = col.get("name") or ""
        if _JUNK_RE.search(name):
            out.append({"id": col.get("id"), "name": name, "location": col.get("location") or "/"})
    return out


def find_duplicate_collection_names(collections):
    """Noms de collections apparaissant plus d'une fois."""
    names = defaultdict(list)
    for col in collections:
        nm = (col.get("name") or "").strip()
        if nm:
            names[nm].append({"id": col.get("id"),
                              "location": col.get("location") or "/",
                              "personal": _is_personal(col)})
    return [{"name": nm, "count": len(entries), "entries": entries}
            for nm, entries in names.items() if len(entries) > 1]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_audit_lib.py`
Expected: 10/10 tests passés

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_lib.py tests/test_audit_lib.py
git commit -m "audit: détecteurs collections — vides #1, fourre-tout #4, noms dupliqués #3"
```

---

## Task 6: Sprawl perso (#2) + incohérences de nommage (#10)

**Files:**
- Modify: `scripts/audit_lib.py`
- Test: `tests/test_audit_lib.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_audit_lib.py`:

```python
def test_find_personal_sprawl_groups_by_client():
    collections = [
        {"id": 1, "name": "Accor | Nanga's Personal Collection", "personal_owner_id": 5},
        {"id": 2, "name": "Accor | Nanga's Personal Collection", "personal_owner_id": 5},
        {"id": 3, "name": "Apple | Nanga's Personal Collection", "personal_owner_id": 5},
        {"id": 4, "name": "Louis Monier's Personal Collection", "personal_owner_id": 7},  # pas de client
        {"id": 5, "name": "06. Industry benchmarks"},  # partagée
    ]
    sprawl = {s["client"]: s["count"] for s in audit_lib.find_personal_sprawl(collections, [])}
    assert sprawl == {"Accor": 2, "Apple": 1}


def test_find_naming_issues_flags_non_normalized_outside_template():
    cards = [
        {"id": 1, "name": "Add_to_cart_rate", "archived": False, "collection_id": 99},
        {"id": 2, "name": "Clean name", "archived": False, "collection_id": 99},
        {"id": 3, "name": "Ignored_in_template", "archived": False, "collection_id": 99},
    ]
    issues = audit_lib.find_naming_issues(cards, template_card_ids={3})
    assert [i["id"] for i in issues] == [1]  # #2 déjà propre, #3 dans le template
```

Add both names to the `TESTS` list.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_audit_lib.py`
Expected: FAIL with `AttributeError: module 'audit_lib' has no attribute 'find_personal_sprawl'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/audit_lib.py`:

```python
_CLIENT_PREFIX_RE = re.compile(r"^\s*(.+?)\s*\|\s*.+personal collection\s*$", re.I)


def find_personal_sprawl(collections, cards):
    """Collections personnelles préfixées d'un nom de client (travail client mal logé).

    Retourne des groupes : [{client, count, collections:[...]}].
    """
    by_client = defaultdict(list)
    for col in collections:
        if not _is_personal(col):
            continue
        m = _CLIENT_PREFIX_RE.match(col.get("name") or "")
        if m:
            by_client[m.group(1).strip()].append({"id": col.get("id"), "name": col.get("name")})
    return [{"client": k, "count": len(v), "collections": v} for k, v in sorted(by_client.items())]


def find_naming_issues(cards, template_card_ids):
    """Cartes hors template dont le nom n'est pas normalisé (cf. Phase 1.5)."""
    out = []
    for c in cards:
        if c.get("archived") or c["id"] in template_card_ids:
            continue
        name = c.get("name") or ""
        norm = normalize_name(name)
        if norm and norm != name:
            out.append({"id": c["id"], "name": name, "normalized": norm})
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_audit_lib.py`
Expected: 12/12 tests passés

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_lib.py tests/test_audit_lib.py
git commit -m "audit: sprawl perso #2 + incohérences de nommage #10"
```

---

## Task 7: Dérive template (#8)

**Files:**
- Modify: `scripts/audit_lib.py`
- Test: `tests/test_audit_lib.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_audit_lib.py`:

```python
def test_find_template_drift_by_name_and_query():
    def card(cid, name, sql):
        return {"id": cid, "name": name, "collection_id": 1,
                "legacy_query": json.dumps({"type": "native", "database": 2, "native": {"query": sql}})}
    template = [card(10, "Daily revenue", "SELECT day, sum(amount) FROM sales GROUP BY 1")]
    others = [
        card(20, "Daily revenue", "SELECT day, sum(amount) FROM sales GROUP BY 1"),   # conforme
        card(21, "Daily revenue", "SELECT day, sum(amount) FROM sales WHERE x GROUP BY 1"),  # dérivée
        card(22, "Autre carte", "SELECT 1"),  # pas d'équivalent template
    ]
    drift = audit_lib.find_template_drift(template, others)
    assert [d["id"] for d in drift] == [21]
    assert drift[0]["template_id"] == 10
```

Add the name to the `TESTS` list.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 tests/test_audit_lib.py`
Expected: FAIL with `AttributeError: module 'audit_lib' has no attribute 'find_template_drift'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/audit_lib.py`:

```python
def find_template_drift(template_cards, other_cards):
    """Copies clientes divergentes : même nom normalisé qu'une carte template,
    mais empreinte de requête différente.

    Limite connue : appariement par NOM (rate les copies renommées) — l'audit
    le signale dans le rapport.
    """
    tpl_by_name = {}
    for c in template_cards:
        tpl_by_name.setdefault(normalize_name(c.get("name") or ""), []).append(c)
    drift = []
    for c in other_cards:
        matches = tpl_by_name.get(normalize_name(c.get("name") or ""))
        if not matches:
            continue
        if query_fingerprint(c) != query_fingerprint(matches[0]):
            drift.append({"id": c["id"], "name": c.get("name"),
                          "collection_id": c.get("collection_id"),
                          "template_id": matches[0]["id"]})
    return drift
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 tests/test_audit_lib.py`
Expected: 13/13 tests passés

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_lib.py tests/test_audit_lib.py
git commit -m "audit: dérive template #8 (appariement nom + empreinte requête)"
```

---

## Task 8: `summarize_findings` + rendu du rapport court (`audit_report.py`)

**Files:**
- Modify: `scripts/audit_lib.py` (ajouter `summarize_findings`)
- Create: `scripts/audit_report.py`
- Test: `tests/test_audit_lib.py` (summarize) + Create `tests/test_audit_report.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_audit_lib.py`:

```python
def test_summarize_findings_sorts_by_wave_then_count():
    findings = {
        "template_drift": {"count": 5, "items": []},      # wave 3
        "empty_collections": {"count": 200, "items": []},  # wave 0
        "naming_issues": {"count": 9, "items": []},        # wave 1
    }
    rows = audit_lib.summarize_findings(findings)
    assert [r["key"] for r in rows][:3] == ["empty_collections", "naming_issues", "template_drift"]
    assert rows[0]["wave"] == 0 and rows[0]["impact"] == "H"
```

Add the name to the `TESTS` list. Then append to `scripts/audit_lib.py`:

```python
def summarize_findings(findings):
    """Joint le scoring (PATTERNS) à chaque finding et trie par vague puis compte décroissant.

    findings : {pattern_key: {count, items}}. Retourne une liste de dicts plats.
    """
    out = []
    for key, data in findings.items():
        meta = PATTERNS.get(key, {})
        out.append({"key": key, **meta, "count": data.get("count", 0), "items": data.get("items", [])})
    out.sort(key=lambda f: (f.get("wave", 9), -f.get("count", 0)))
    return out
```

Create `tests/test_audit_report.py`:

```python
#!/usr/bin/env python3
"""Tests du rendu d'audit — script autonome. Usage : python3 tests/test_audit_report.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import audit_report


def _findings():
    return {
        "empty_collections": {"count": 200, "items": [{"id": i, "name": f"col{i}"} for i in range(200)]},
        "pure_dups": {"count": 2, "items": [[{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]]},
        "template_drift": {"count": 0, "items": []},
    }


def test_report_is_short_and_caps_examples():
    md = audit_report.render_report(_findings(), scanned_cards=5654, scanned_collections=868, date="2026-05-28")
    # exec summary + backlog présents
    assert "## Résumé" in md and "## Backlog" in md
    # exemples plafonnés : au plus MAX_EXAMPLES lignes d'exemple + une ligne "+N"
    assert md.count("  - `") <= audit_report.MAX_EXAMPLES
    assert "+195" in md  # 200 - 5 exemples
    # un pattern à 0 n'apparaît pas dans le backlog
    assert "template_drift" not in md.split("## Backlog")[1]


def test_report_short_overall():
    md = audit_report.render_report(_findings(), scanned_cards=5654, scanned_collections=868, date="2026-05-28")
    assert len(md.splitlines()) < 60  # digest, pas un pavé


TESTS = [test_report_is_short_and_caps_examples, test_report_short_overall]


def run():
    failures = 0
    for t in TESTS:
        try:
            t(); print(f"PASS  {t.__name__}")
        except Exception as e:
            failures += 1; print(f"FAIL  {t.__name__}: {e!r}")
    print(f"\n{len(TESTS) - failures}/{len(TESTS)} tests passés")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    run()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 tests/test_audit_lib.py` → FAIL (`summarize_findings` manquant)
Run: `python3 tests/test_audit_report.py` → FAIL (`ModuleNotFoundError: No module named 'audit_report'`)

- [ ] **Step 3: Write minimal implementation**

(After adding `summarize_findings` to `audit_lib.py` per Step 1.) Create `scripts/audit_report.py`:

```python
#!/usr/bin/env python3
"""Rendu du rapport d'audit en markdown — digest COURT (détail exhaustif dans le JSON)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from audit_lib import summarize_findings  # noqa: E402

MAX_EXAMPLES = 5
WAVE_TITLES = {
    0: "Vague 0 — Quick wins",
    1: "Vague 1 — Automatisable",
    2: "Vague 2 — Structurel",
    3: "Vague 3 — DRY / dérive",
}


def _example_line(key, item):
    if key in ("empty_collections", "junk_collections"):
        return f"`{item.get('id')}` {item.get('name')}"
    if key == "dup_collection_names":
        return f"« {item.get('name')} » ×{item.get('count')}"
    if key == "personal_sprawl":
        return f"{item.get('client')} ×{item.get('count')}"
    if key in ("unused_cards", "naming_issues", "template_drift"):
        return f"#{item.get('id')} {item.get('name')}"
    if key in ("pure_dups", "variant_families"):
        return f"groupe de {len(item)} : " + ", ".join(f"#{c['id']}" for c in item[:4])
    return str(item)[:80]


def render_report(findings, *, scanned_cards=0, scanned_collections=0, date=""):
    rows = summarize_findings(findings)
    lines = [f"# Audit Metabase — {date}", "",
             f"_{scanned_collections} collections · {scanned_cards} cartes scannées._", ""]
    lines += ["## Résumé", "", "| # | Pattern | Compte | I/R/E | Vague |",
              "|---|---------|--------|-------|-------|"]
    for f in rows:
        ire = f"{f.get('impact','?')}/{f.get('risk','?')}/{f.get('effort','?')}"
        lines.append(f"| {f.get('num','?')} | {f['key']} | {f.get('count',0)} | {ire} | {f.get('wave','?')} |")
    lines += ["", "## Backlog (quick-wins d'abord)", ""]
    for wave in (0, 1, 2, 3):
        wf = [f for f in rows if f.get("wave") == wave and f.get("count", 0) > 0]
        if not wf:
            continue
        lines.append(f"### {WAVE_TITLES[wave]}")
        for f in wf:
            lines.append(f"- **{f['key']}** ({f.get('count',0)}) — {f.get('impact')}/{f.get('risk')}/{f.get('effort')}")
            for item in f.get("items", [])[:MAX_EXAMPLES]:
                lines.append(f"  - {_example_line(f['key'], item)}")
            if f.get("count", 0) > MAX_EXAMPLES:
                lines.append(f"  - … +{f['count'] - MAX_EXAMPLES} (détail dans le JSON)")
        lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 tests/test_audit_lib.py` → 14/14 tests passés
Run: `python3 tests/test_audit_report.py` → 2/2 tests passés

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_lib.py scripts/audit_report.py tests/test_audit_lib.py tests/test_audit_report.py
git commit -m "audit: summarize_findings + rendu rapport court (digest)"
```

---

## Task 9: Scaffold `audit.py` — connexion, argparse, helpers cache & template

**Files:**
- Create: `scripts/audit.py`

- [ ] **Step 1: Write the implementation**

Create `scripts/audit.py`:

```python
#!/usr/bin/env python3
"""Audit instance-wide Metabase : scan (large) → deep (profond) → report.

Lecture seule. Voir :
  docs/superpowers/specs/2026-05-28-metabase-instance-audit-design.md
  docs/superpowers/plans/2026-05-28-metabase-instance-audit.md

Usage :
  python3 scripts/audit.py scan
  python3 scripts/audit.py deep [--limit N]
  python3 scripts/audit.py report
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from spark_metabase_api import Metabase_API  # noqa: E402
from reorg_phase1 import _load_env  # noqa: E402
import audit_lib  # noqa: E402
from audit_report import render_report  # noqa: E402

MIGRATION_DIR = REPO_ROOT / "migration"
CACHE_DIR = MIGRATION_DIR / "audit-cache"
DOCS_DIR = REPO_ROOT / "docs" / "audits"


def connect_resilient():
    """Connexion email/password (résiste à l'expiration de session sur run long)."""
    env = _load_env()
    domain, email, password = (env.get("METABASE_DOMAIN"),
                               env.get("METABASE_EMAIL"),
                               env.get("METABASE_PASSWORD"))
    if not (domain and email and password):
        sys.exit("METABASE_DOMAIN / EMAIL / PASSWORD requis dans .env (run long).")
    return Metabase_API(domain=domain, email=email, password=password)


def _safe_get(mb, endpoint):
    """GET tolérant : retourne [] sur erreur réseau/HTTP au lieu de tuer le run.

    L'endpoint des archivées est volumineux et l'instance renvoie parfois un
    ConnectionError transitoire (constaté lors de la conception).
    """
    try:
        r = mb.get(endpoint)
    except Exception as e:  # ConnectionError, Timeout, ...
        print(f"  ⚠️  {endpoint} a échoué ({type(e).__name__}) — ignoré.")
        return []
    return r or []


def _latest(prefix):
    files = sorted(MIGRATION_DIR.glob(f"{prefix}-*.json"))
    return files[-1] if files else None


def _template_card_ids(collections, cards):
    """Ids des cartes sous l'arbre du template (215), via location."""
    root = audit_lib.TEMPLATE_ROOT_ID
    tpl_cols = {c.get("id") for c in collections
                if c.get("id") == root or f"/{root}/" in (c.get("location") or "")}
    tpl_cols.add(root)
    return {c["id"] for c in cards if c.get("collection_id") in tpl_cols}


def cmd_scan(args):
    raise NotImplementedError  # Task 10


def cmd_deep(args):
    raise NotImplementedError  # Task 11


def cmd_report(args):
    raise NotImplementedError  # Task 12


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    d = sub.add_parser("deep")
    d.add_argument("--limit", type=int, default=0, help="ne traiter que les N premières cartes (test)")
    sub.add_parser("report")
    args = p.parse_args()
    {"scan": cmd_scan, "deep": cmd_deep, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it parses (smoke)**

Run: `python3 scripts/audit.py --help`
Expected: l'aide liste les sous-commandes `{scan,deep,report}` sans erreur.

Run: `python3 scripts/audit.py report` (sans findings)
Expected: `NotImplementedError` (les commandes sont câblées ; corps en Tasks 10-12).

- [ ] **Step 3: Commit**

```bash
git add scripts/audit.py
git commit -m "audit: squelette CLI audit.py (scan/deep/report) + helpers cache/template"
```

---

## Task 10: `cmd_scan` — passe large (métadonnées + archivées)

**Files:**
- Modify: `scripts/audit.py:cmd_scan`

- [ ] **Step 1: Write the implementation**

Replace the `cmd_scan` stub in `scripts/audit.py`:

```python
def cmd_scan(args):
    mb = connect_resilient()
    print("Passe large : collections, cartes, dashboards (+ archivés)...")
    collections = _safe_get(mb, "/api/collection/")
    arch_cols = _safe_get(mb, "/api/collection/?archived=true")
    cards = _safe_get(mb, "/api/card/")
    arch_cards = _safe_get(mb, "/api/card/?f=archived")
    dashboards = _safe_get(mb, "/api/dashboard/")

    template_ids = _template_card_ids(collections, cards)

    findings = {}
    empty = audit_lib.find_empty_collections(collections, cards, dashboards)
    findings["empty_collections"] = {"count": len(empty), "items": empty}
    junk = audit_lib.find_junk_collections(collections)
    findings["junk_collections"] = {"count": len(junk), "items": junk}
    dn = audit_lib.find_duplicate_collection_names(collections)
    findings["dup_collection_names"] = {"count": len(dn), "items": dn}
    sprawl = audit_lib.find_personal_sprawl(collections, cards)
    findings["personal_sprawl"] = {"count": len(sprawl), "items": sprawl}
    naming = audit_lib.find_naming_issues(cards, template_ids)
    findings["naming_issues"] = {"count": len(naming), "items": naming}
    findings["archived_backlog"] = {
        "count": len(arch_cards) + len(arch_cols),
        "items": [{"archived_cards": len(arch_cards), "archived_collections": len(arch_cols)}],
    }
    # #5 inutilisées : compte provisoire (sans graphe de sources), affiné en `deep`
    prelim = [c for c in cards if c.get("dashboard_count", 0) == 0 and not c.get("archived")]
    findings["unused_cards"] = {"count": len(prelim),
                                "items": [{"id": c["id"], "name": c.get("name")} for c in prelim],
                                "preliminary": True}
    # patterns enrichis par la passe profonde
    for k in ("pure_dups", "variant_families", "template_drift", "expensive_cards"):
        findings.setdefault(k, {"count": 0, "items": []})

    MIGRATION_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = MIGRATION_DIR / f"audit-findings-{ts}.json"
    out.write_text(json.dumps({
        "meta": {"scanned_collections": len(collections), "scanned_cards": len(cards),
                 "archived_cards": len(arch_cards), "archived_collections": len(arch_cols),
                 "template_card_ids": sorted(template_ids), "deep_done": False},
        "findings": findings,
    }, indent=2, ensure_ascii=False))
    print(f"  {len(collections)} collections, {len(cards)} cartes, {len(dashboards)} dashboards")
    print(f"  vides:{len(empty)} fourre-tout:{len(junk)} noms-dupes:{len(dn)} "
          f"sprawl:{len(sprawl)} nommage:{len(naming)} archivées:{len(arch_cards)}")
    print(f"Findings écrits : {out}")
```

- [ ] **Step 2: Run live to verify**

Run: `python3 scripts/audit.py scan`
Expected (ordres de grandeur connus au 2026-05-28) :
- `~868 collections, ~5654 cartes, ~735 dashboards`
- `vides:~241` (collections non-perso vides), `sprawl:` plusieurs dizaines de clients
- archivées : `~1803` collections archivées (gros backlog, pattern #7) ; le compte
  des cartes archivées peut être 0 si `/api/card/?f=archived` a renvoyé un
  `ConnectionError` transitoire (le `⚠️` s'affiche alors) — relancer `scan` pour
  retenter ; le reste du scan reste valide.
- un fichier `migration/audit-findings-<ts>.json` est créé.

- [ ] **Step 3: Sanity-check the JSON**

Run:
```bash
python3 -c "import json,glob; f=sorted(glob.glob('migration/audit-findings-*.json'))[-1]; b=json.load(open(f)); print('keys:', list(b['findings'])); print('empty:', b['findings']['empty_collections']['count']); print('meta:', b['meta']['scanned_cards'], b['meta']['archived_cards'])"
```
Expected: 11 clés de findings ; `empty` ≈ 241 ; `scanned_cards` ≈ 5654.

- [ ] **Step 4: Commit**

```bash
git add scripts/audit.py
git commit -m "audit: cmd_scan — passe large (métadonnées + archivées) -> findings JSON"
```

---

## Task 11: `cmd_deep` — passe profonde (corpus complet, cache reprenable)

**Files:**
- Modify: `scripts/audit.py:cmd_deep` (+ helper `_card_detail`)

- [ ] **Step 1: Write the implementation**

Add the helper above `cmd_deep`, then replace the `cmd_deep` stub in `scripts/audit.py`:

```python
def _card_detail(mb, cid):
    """Fetch /api/card/{id} avec cache disque (reprenable). 3 essais espacés."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = CACHE_DIR / f"card-{cid}.json"
    if f.exists():
        return json.loads(f.read_text())
    for attempt in range(3):
        d = mb.get(f"/api/card/{cid}")
        if d:
            f.write_text(json.dumps(d, ensure_ascii=False))
            return d
        time.sleep(1.5 * (attempt + 1))
    return None


def cmd_deep(args):
    mb = connect_resilient()
    findings_file = _latest("audit-findings")
    if not findings_file:
        sys.exit("Aucun audit-findings : lancer `scan` d'abord.")
    blob = json.loads(findings_file.read_text())

    cards = mb.get("/api/card/") or []
    if args.limit:
        cards = cards[:args.limit]
    print(f"Passe profonde : fetch de {len(cards)} requêtes (cache {CACHE_DIR})...")
    details = []
    for i, c in enumerate(cards, 1):
        d = _card_detail(mb, c["id"])
        if d:
            details.append(d)
        if i % 200 == 0:
            print(f"  {i}/{len(cards)}")

    groups = audit_lib.classify_query_groups(details)
    source_ids = audit_lib.build_source_ids(details)
    unused = audit_lib.find_unused_cards(details, source_ids)

    tpl_ids = set(blob["meta"].get("template_card_ids", []))
    tpl_cards = [d for d in details if d["id"] in tpl_ids]
    other_cards = [d for d in details if d["id"] not in tpl_ids]
    drift = audit_lib.find_template_drift(tpl_cards, other_cards)

    f = blob["findings"]
    f["pure_dups"] = {"count": len(groups["pure_dups"]),
                      "items": [[{"id": c["id"], "name": c.get("name"), "display": c.get("display")}
                                 for c in g] for g in groups["pure_dups"]]}
    f["variant_families"] = {"count": len(groups["variant_families"]),
                             "items": [[{"id": c["id"], "name": c.get("name")} for c in g]
                                       for g in groups["variant_families"]]}
    f["unused_cards"] = {"count": len(unused),
                         "items": [{"id": c["id"], "name": c.get("name")} for c in unused]}
    f["template_drift"] = {"count": len(drift), "items": drift}
    blob["meta"]["deep_done"] = True
    findings_file.write_text(json.dumps(blob, indent=2, ensure_ascii=False))
    print(f"  doublons:{len(groups['pure_dups'])} variantes:{len(groups['variant_families'])} "
          f"inutilisées:{len(unused)} dérive:{len(drift)}")
    print(f"Findings enrichis : {findings_file}")
```

- [ ] **Step 2: Run a small sample first**

Run: `python3 scripts/audit.py deep --limit 50`
Expected: `Passe profonde : fetch de 50 requêtes...`, un résumé `doublons:.. variantes:.. inutilisées:.. dérive:..`, et 50 fichiers `migration/audit-cache/card-*.json`.

- [ ] **Step 3: Verify resumability**

Run the same command again: `python3 scripts/audit.py deep --limit 50`
Expected: termine quasi instantanément (cache touché, aucun re-fetch réseau).

- [ ] **Step 4: Run the full corpus**

Run: `python3 scripts/audit.py deep`
Expected: progresse par paliers de 200 jusqu'à ~5654 ; résumé final avec les comptes réels. Tolérant aux coupures : relancer reprend depuis le cache.

- [ ] **Step 5: Spot-check the GSC false-positives are NOT pure dups**

Run:
```bash
python3 -c "import json,glob; f=sorted(glob.glob('migration/audit-findings-*.json'))[-1]; b=json.load(open(f)); pure=[i for g in b['findings']['pure_dups']['items'] for i in g]; ids={c['id'] for c in pure}; print('28943/28945/28946 dans pure_dups ?', {28943,28945,28946} & ids)"
```
Expected: `set()` — les cartes GSC clics/CTR/position ne sont PAS classées en doublons (elles doivent apparaître en `variant_families`).

- [ ] **Step 6: Commit**

```bash
git add scripts/audit.py
git commit -m "audit: cmd_deep — passe profonde corpus complet (cache reprenable), enrichit findings"
```

---

## Task 12: `cmd_report` + bout-en-bout + .gitignore

**Files:**
- Modify: `scripts/audit.py:cmd_report`
- Modify: `.gitignore`

- [ ] **Step 1: Write the implementation**

Replace the `cmd_report` stub in `scripts/audit.py`:

```python
def cmd_report(args):
    findings_file = _latest("audit-findings")
    if not findings_file:
        sys.exit("Aucun audit-findings : lancer `scan` d'abord.")
    blob = json.loads(findings_file.read_text())
    if not blob["meta"].get("deep_done"):
        print("⚠️  passe profonde non exécutée — doublons/variantes/dérive seront à 0. "
              "Lancer `deep` pour un rapport complet.")
    md = render_report(blob["findings"],
                       scanned_cards=blob["meta"].get("scanned_cards", 0),
                       scanned_collections=blob["meta"].get("scanned_collections", 0),
                       date=datetime.now().strftime("%Y-%m-%d"))
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out = DOCS_DIR / f"audit-{datetime.now().strftime('%Y%m%d')}.md"
    out.write_text(md)
    print(f"Rapport écrit : {out}")
```

- [ ] **Step 2: Add ignore rules**

Add to the end of `.gitignore`:

```
migration/audit-findings-*.json
migration/audit-cache/
# Rapport d'audit : données live (noms de clients) — régénérable, non versionné par défaut
docs/audits/
```

- [ ] **Step 3: Run report + eyeball**

Run: `python3 scripts/audit.py report`
Expected: `Rapport écrit : docs/audits/audit-<date>.md`.

Run: `python3 -c "p=open('docs/audits/audit-$(date +%Y%m%d).md').read(); print(p[:1500]); print('--- lignes:', len(p.splitlines()))"`
Expected: un digest court — `## Résumé` (tableau 11 lignes), `## Backlog` par vague, exemples plafonnés à 5/section. Lignes totales raisonnables (dizaines, pas centaines).

- [ ] **Step 4: Run the whole test suite**

Run: `python3 tests/test_audit_lib.py && python3 tests/test_audit_report.py`
Expected: `14/14 tests passés` puis `2/2 tests passés`.

- [ ] **Step 5: Verify the report is untracked**

Run: `git status --porcelain docs/audits migration/audit-findings-*.json migration/audit-cache`
Expected: aucune sortie (tout ignoré).

- [ ] **Step 6: Commit**

```bash
git add scripts/audit.py .gitignore
git commit -m "audit: cmd_report (digest court) + ignore artefacts d'audit"
```

---

## Self-Review (rempli pendant l'écriture du plan)

**Spec coverage** — chaque pattern de la spec §5 a une tâche :
#1 empty (T5) · #2 sprawl (T6) · #3 dup names (T5) · #4 junk (T5) · #5 unused (T4) · #6 pure_dups (T2/T3) · #7 archived (T10) · #8 drift (T7) · #9 variants (T3) · #10 naming (T6) · #11 perf — *partiellement* : `expensive_cards` est câblé dans le registre/findings à 0 (best-effort, cf. décision « #11 best-effort »). Collecte des stats `query_executions` non implémentée ici ; à ajouter dans une itération si l'API les expose (note ci-dessous).

Scan/deep/report (architecture §4) → T9/T10/T11/T12. Scoring & vagues (§6) → T1 + T8. Format sortie (§7) → T10 (JSON) + T8/T12 (md court). Sûreté (§9) : quirk `dataset_query` (T2), graphe de sources (T4), cache reprenable (T11), archivées (T10).

**Placeholder scan** — pas de TBD ; les stubs `NotImplementedError` (T9) sont remplis en T10-12 (référence explicite). `expensive_cards` reste à 0 par décision produit, pas par oubli.

**Type consistency** — `findings` = `{key: {count, items}}` partout (scan, deep, summarize, render). `query_fingerprint`/`output_fingerprint`/`classify_query_groups`/`build_source_ids`/`find_*`/`summarize_findings`/`render_report` : signatures identiques entre définition (audit_lib) et appels (audit.py, audit_report). `_template_card_ids` produit le set consommé par `find_naming_issues` et par le partitionnement drift en T11.

**Note #11 (perf)** — pour activer plus tard : en `deep`, tenter `GET /api/card/:id` → champ `last_query_start` / endpoint `/api/card/:id/query_metadata`, ou la table d'audit si dispo ; remplir `findings["expensive_cards"]`. Laisser à 0 sinon (le rapport l'affiche simplement à 0).

---

## Execution Handoff

Voir la fin de la conversation pour le choix du mode d'exécution.
