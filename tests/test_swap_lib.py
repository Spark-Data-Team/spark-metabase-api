#!/usr/bin/env python3
"""Tests de swap_lib — script autonome. Usage : python3 tests/test_swap_lib.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import swap_lib


def _card(cid, tags, db=2, archived=False, sql="SELECT 1"):
    return {
        "id": cid, "archived": archived, "database_id": db, "display": "line",
        "visualization_settings": {},
        "legacy_query": json.dumps({"type": "native", "database": db,
                                    "native": {"query": sql, "template-tags": {t: {} for t in tags}}}),
    }


def test_referenced_template_tags():
    dashcards = [
        {"card_id": 58, "parameter_mappings": [
            {"parameter_id": "p1", "card_id": 58, "target": ["dimension", ["template-tag", "date"], {"stage-number": 0}]},
            {"parameter_id": "p2", "card_id": 58, "target": ["variable", ["template-tag", "client"]]},
        ]},
        {"card_id": 99, "parameter_mappings": [
            {"parameter_id": "p3", "card_id": 99, "target": ["dimension", ["template-tag", "autre"]]}]},
    ]
    assert swap_lib.referenced_template_tags(dashcards, 58) == {"date", "client"}


def test_rewrite_dashcards_swaps_card_and_mappings_not_target():
    dashcards = [
        {"id": 1, "card_id": 58, "series": [],
         "parameter_mappings": [{"parameter_id": "p1", "card_id": 58,
                                 "target": ["dimension", ["template-tag", "date"]]}]},
        {"id": 2, "card_id": 99, "series": [], "parameter_mappings": []},
    ]
    out, n = swap_lib.rewrite_dashcards(dashcards, 58, 1000)
    assert n == 1
    assert out[0]["card_id"] == 1000
    assert out[0]["parameter_mappings"][0]["card_id"] == 1000
    assert out[0]["parameter_mappings"][0]["target"] == ["dimension", ["template-tag", "date"]]  # inchangé
    assert out[1]["card_id"] == 99  # autre carte intacte
    assert dashcards[0]["card_id"] == 58  # entrée non mutée


def test_rewrite_handles_series():
    dashcards = [{"id": 1, "card_id": 10, "parameter_mappings": [], "series": [{"id": 58, "name": "x"}]}]
    out, n = swap_lib.rewrite_dashcards(dashcards, 58, 1000)
    assert n == 1 and out[0]["series"][0]["id"] == 1000


def test_card_template_tags():
    assert swap_lib.card_template_tags(_card(1, ["date", "client"])) == {"date", "client"}


def test_swap_safety_check_passes_for_identical():
    old = _card(1, ["date", "client"])
    new = _card(2, ["date", "client"])
    assert swap_lib.swap_safety_check(old, new, {"date", "client"}) == []


def test_swap_safety_check_blocks_missing_filter_tag():
    old = _card(1, ["date", "client"])
    new = _card(2, ["date"])  # même SQL/rendu mais ne couvre pas 'client'
    problems = swap_lib.swap_safety_check(old, new, {"date", "client"})
    assert any("client" in p for p in problems)


def test_swap_safety_check_blocks_different_database():
    old = _card(1, ["date"], db=2)
    new = _card(2, ["date"], db=9)
    assert any("base" in p.lower() for p in swap_lib.swap_safety_check(old, new, {"date"}))


def test_swap_safety_check_blocks_different_fingerprint():
    old = _card(1, ["date"], sql="SELECT a")
    new = _card(2, ["date"], sql="SELECT b")  # requête différente -> empreinte différente
    assert any("empreinte" in p.lower() for p in swap_lib.swap_safety_check(old, new, {"date"}))


TESTS = [
    test_referenced_template_tags,
    test_rewrite_dashcards_swaps_card_and_mappings_not_target,
    test_rewrite_handles_series,
    test_card_template_tags,
    test_swap_safety_check_passes_for_identical,
    test_swap_safety_check_blocks_missing_filter_tag,
    test_swap_safety_check_blocks_different_database,
    test_swap_safety_check_blocks_different_fingerprint,
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
