#!/usr/bin/env python3
"""Tests unitaires de rename_lib — script autonome (convention du repo).

Usage : python3 tests/test_rename_lib.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from rename_lib import normalize_name, CardRecord, capture_snapshot


def test_normalize_name_basic():
    # Trim + doubles espaces + snake_case
    assert normalize_name("  Add_to_cart_rate ") == "Add to cart rate"
    assert normalize_name("Cac_7,  conversions_7 by date") == "CAC 7, conversions 7 by date"
    # Acronymes préservés
    assert normalize_name("cac") == "CAC"
    assert normalize_name("Cpc by date") == "CPC by date"
    assert normalize_name("CAC") == "CAC"
    # Sentence case + première lettre capitalisée
    assert normalize_name("average basket - purchase") == "Average basket - purchase"
    # Idempotence
    assert normalize_name(normalize_name("App_installs_rate")) == normalize_name("App_installs_rate")
    # Vide / blanc
    assert normalize_name("   ") == ""


def test_capture_snapshot_excludes_conversions():
    items = {
        "/api/collection/215/items?limit=2000": {"data": [
            {"model": "collection", "id": 214, "name": "Cross-platform"},
            {"model": "collection", "id": 11673, "name": "18. Nouvelles Conversions"},
            {"model": "card", "id": 29, "name": "CAC"},
        ]},
        "/api/collection/214/items?limit=2000": {"data": [
            {"model": "card", "id": 46255, "name": "Loose card"},
        ]},
    }
    cards = {
        29: {"id": 29, "name": "CAC", "collection_id": 215,
             "dashboard_count": 1211, "archived": False, "display": "scalar"},
        46255: {"id": 46255, "name": "Loose card", "collection_id": 214,
                "dashboard_count": 0, "archived": False, "display": "line"},
    }

    def fake_get(endpoint):
        if "/items" in endpoint:
            return items[endpoint]
        card_id = int(endpoint.split("/")[-1])
        return cards[card_id]

    snap = capture_snapshot(fake_get, root_id=215)
    assert set(snap) == {29, 46255}
    assert snap[29] == CardRecord(id=29, name="CAC", collection_id=215,
                                  dashboard_count=1211, archived=False,
                                  display="scalar")


TESTS = [test_normalize_name_basic, test_capture_snapshot_excludes_conversions]


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
