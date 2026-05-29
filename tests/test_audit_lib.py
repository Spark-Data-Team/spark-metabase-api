#!/usr/bin/env python3
"""Tests unitaires d'audit_lib — script autonome (convention du repo).

Usage : python3 tests/test_audit_lib.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import audit_lib


# --- Registre ----------------------------------------------------------------

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


# --- Empreinte v2 (régression faux-positifs GSC) -----------------------------

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


def test_output_fingerprint_handles_none_in_metrics():
    # Donnée réelle sale rencontrée en prod : graph.metrics/dimensions peut contenir None.
    card = {"id": 1, "display": "line", "legacy_query": _GSC_SQL,
            "visualization_settings": {"graph.metrics": ["CLICKS", None], "graph.dimensions": [None]}}
    fp = audit_lib.output_fingerprint(card)  # ne doit pas lever
    assert isinstance(fp, str)


def test_output_fingerprint_distinct_for_parameter_default_variants():
    # "Conversions by device/age/country" : même SQL, même display 'pie', sans
    # graph.metrics — diffèrent seulement par le défaut du paramètre `breakdown`
    # (2e classe de faux positifs constatée en prod).
    sql = json.dumps({"type": "native", "database": 2,
                      "native": {"query": "SELECT breakdown_value AS dimension FROM t"}})

    def card(cid, val):
        return {"id": cid, "name": f"Conversions by {val}", "display": "pie", "legacy_query": sql,
                "visualization_settings": {}, "parameters": [{"slug": "breakdown", "default": [val]}]}

    a, b, c = card(1, "device"), card(2, "age"), card(3, "country")
    assert len({audit_lib.output_fingerprint(x) for x in (a, b, c)}) == 3
    res = audit_lib.classify_query_groups([a, b, c])
    assert res["pure_dups"] == []
    assert any({x["id"] for x in g} == {1, 2, 3} for g in res["variant_families"])


# --- Classification ----------------------------------------------------------

def test_classify_separates_dups_variants_and_viz():
    # Groupe A : même requête + même display 'line', sélections ≠ -> variantes (#9),
    # avec un doublon pur dedans (#1 == #2). variant_families ⟂ diff_viz pour un
    # même groupe de requête, donc le cas viz≠ a besoin de sa propre requête.
    a1 = _gsc_card(1, "Clicks", "CLICKS")
    a2 = _gsc_card(2, "Clicks copie", "CLICKS")          # doublon de #1 (output identique)
    a3 = _gsc_card(3, "CTR", "CTR")                       # variante
    a4 = _gsc_card(4, "Position", "WEIGHTED_POSITION")    # variante
    # Groupe B : autre requête, mêmes données mais displays ≠ -> diff_viz.
    sql_b = json.dumps({"type": "native", "database": 2, "native": {"query": "SELECT a, b FROM t"}})
    b1 = {"id": 5, "name": "B line", "display": "line", "legacy_query": sql_b,
          "visualization_settings": {"graph.metrics": ["A"]}}
    b2 = {"id": 6, "name": "B bar", "display": "bar", "legacy_query": sql_b,
          "visualization_settings": {"graph.metrics": ["A"]}}
    res = audit_lib.classify_query_groups([a1, a2, a3, a4, b1, b2])
    assert any(sorted(c["id"] for c in g) == [1, 2] for g in res["pure_dups"])          # #6
    assert any({c["id"] for c in g} == {1, 2, 3, 4} for g in res["variant_families"])   # #9
    assert any({c["id"] for c in g} == {5, 6} for g in res["diff_viz"])


# --- Graphe de sources / inutilisées -----------------------------------------

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


# --- Détecteurs de collections -----------------------------------------------

def test_find_empty_collections_respects_descendants_and_personal():
    collections = [
        {"id": 1, "name": "Parent", "location": "/"},
        {"id": 2, "name": "Enfant occupé", "location": "/1/"},
        {"id": 3, "name": "Vraiment vide", "location": "/"},
        {"id": 4, "name": "Perso vide", "location": "/", "personal_owner_id": 9},
        {"id": "root", "name": "Our analytics", "location": "/"},  # racine Metabase, à exclure
        {"id": 6, "name": "Metrics", "location": "/", "type": "library-metrics"},  # système, non archivable
    ]
    cards = [{"id": 50, "collection_id": 2, "archived": False}]
    dashboards = []
    empty = audit_lib.find_empty_collections(collections, cards, dashboards)
    ids = {e["id"] for e in empty}
    assert ids == {3}        # 1 descendant occupé ; 2 occupée ; 4 perso ; root + 6 (système) exclues


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


# --- Sprawl perso / nommage --------------------------------------------------

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


# --- Dérive template ---------------------------------------------------------

def test_find_template_drift_by_name_and_query():
    def card(cid, name, sql):
        return {"id": cid, "name": name, "collection_id": 1,
                "legacy_query": json.dumps({"type": "native", "database": 2, "native": {"query": sql}})}
    template = [card(10, "Daily revenue", "SELECT day, sum(amount) FROM sales GROUP BY 1")]
    others = [
        card(20, "Daily revenue", "SELECT day, sum(amount) FROM sales GROUP BY 1"),           # conforme
        card(21, "Daily revenue", "SELECT day, sum(amount) FROM sales WHERE x GROUP BY 1"),   # dérivée
        card(22, "Autre carte", "SELECT 1"),  # pas d'équivalent template
    ]
    drift = audit_lib.find_template_drift(template, others)
    assert [d["id"] for d in drift] == [21]
    assert drift[0]["template_id"] == 10


# --- Scoring -----------------------------------------------------------------

def test_summarize_findings_sorts_by_wave_then_count():
    findings = {
        "template_drift": {"count": 5, "items": []},        # wave 3
        "empty_collections": {"count": 200, "items": []},   # wave 0
        "naming_issues": {"count": 9, "items": []},         # wave 1
    }
    rows = audit_lib.summarize_findings(findings)
    assert [r["key"] for r in rows][:3] == ["empty_collections", "naming_issues", "template_drift"]
    assert rows[0]["wave"] == 0 and rows[0]["impact"] == "H"


TESTS = [
    test_patterns_registry_complete,
    test_query_fingerprint_identical_for_gsc_trio,
    test_output_fingerprint_distinct_for_gsc_trio,
    test_output_fingerprint_identical_for_true_duplicate,
    test_output_fingerprint_handles_none_in_metrics,
    test_output_fingerprint_distinct_for_parameter_default_variants,
    test_classify_separates_dups_variants_and_viz,
    test_build_source_ids_finds_card_references,
    test_find_unused_cards_excludes_sources_and_used,
    test_find_empty_collections_respects_descendants_and_personal,
    test_find_junk_collections_matches_names,
    test_find_duplicate_collection_names,
    test_find_personal_sprawl_groups_by_client,
    test_find_naming_issues_flags_non_normalized_outside_template,
    test_find_template_drift_by_name_and_query,
    test_summarize_findings_sorts_by_wave_then_count,
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
