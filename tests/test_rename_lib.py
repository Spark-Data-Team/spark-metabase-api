#!/usr/bin/env python3
"""Tests unitaires de rename_lib — script autonome (convention du repo).

Usage : python3 tests/test_rename_lib.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from rename_lib import normalize_name, CardRecord, capture_snapshot, propose_renames, ProposalRow, verify_invariant


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


def test_normalize_name_cleanup():
    # Espace après virgule + acronyme
    assert normalize_name("Cr,clicks by date") == "CR, clicks by date"
    # Parenthèses dupliquées réduites + marque préservée
    assert normalize_name("Total installs (Adjust) (Adjust)") == "Total installs (Adjust)"
    # Parenthèse collée à un mot -> espace, et acronyme interne détecté
    assert normalize_name("Cac(conversions 1) - Morning") == "CAC (conversions 1) - morning"
    # Idempotence des règles de nettoyage
    for raw in ("Cr,clicks by date", "Total installs (Adjust) (Adjust)",
                "Cac(conversions 1) - Morning"):
        once = normalize_name(raw)
        assert normalize_name(once) == once


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


def _rec(id, name, display="line", collection_id=214, dashboard_count=0):
    return CardRecord(id=id, name=name, collection_id=collection_id,
                      dashboard_count=dashboard_count, archived=False,
                      display=display)


def test_propose_skips_unchanged_cards():
    snap = {1: _rec(1, "Add to cart rate")}     # déjà propre
    rows = propose_renames(snap)
    assert rows == []


def test_propose_auto_normalize_change():
    snap = {1: _rec(1, "Add_to_cart_rate")}
    rows = propose_renames(snap)
    assert len(rows) == 1
    assert rows[0].card_id == 1
    assert rows[0].proposed_name == "Add to cart rate"
    assert rows[0].status == "auto"
    assert rows[0].rule == "normalize"


def test_propose_viz_collision_adds_suffix():
    snap = {
        1: _rec(1, "Cac by date", display="line"),
        2: _rec(2, "Cac by date", display="bar"),
    }
    rows = sorted(propose_renames(snap), key=lambda r: r.card_id)
    assert [r.proposed_name for r in rows] == ["CAC by date — line", "CAC by date — bar"]
    assert [r.status for r in rows] == ["auto", "auto"]
    assert [r.rule for r in rows] == ["viz_collision", "viz_collision"]


def test_propose_true_duplicate_is_decision():
    snap = {
        1: _rec(1, "Cac_2 by date, channel", display="line"),
        2: _rec(2, "Cac_2 by date, channel", display="line"),
    }
    rows = sorted(propose_renames(snap), key=lambda r: r.card_id)
    assert [r.status for r in rows] == ["décision", "décision"]
    assert [r.rule for r in rows] == ["duplicate", "duplicate"]
    # En statut décision, on laisse proposed = current
    assert rows[0].proposed_name == rows[0].current_name


def test_propose_cryptic_is_decision():
    snap = {1: _rec(1, "Cac3")}
    rows = propose_renames(snap)
    assert len(rows) == 1
    assert rows[0].status == "décision"
    assert rows[0].rule == "cryptic"
    assert rows[0].proposed_name == "Cac3"


def test_propose_idempotent_on_already_suffixed_collision():
    # Cartes déjà à leur forme cible après un premier apply
    snap = {
        1: _rec(1, "CAC by date — line", display="line"),
        2: _rec(2, "CAC by date — bar", display="bar"),
    }
    assert propose_renames(snap) == []


def test_propose_skips_whitespace_only_name():
    snap = {1: _rec(1, "   ")}
    assert propose_renames(snap) == []


def test_verify_clean_when_only_name_changed():
    base = {1: _rec(1, "Cac_2", display="line")}
    current = {1: _rec(1, "CAC 2", display="line")}
    assert verify_invariant(base, current) == []


def test_verify_detects_lost_card():
    base = {1: _rec(1, "X")}
    assert [d.kind for d in verify_invariant(base, {})] == ["lost_card"]


def test_verify_detects_archived_card():
    base = {1: _rec(1, "X")}
    archived = CardRecord(1, "X", 214, 0, True, "line")
    assert [d.kind for d in verify_invariant(base, {1: archived})] == ["archived_card"]


def test_verify_detects_dashboard_count_change():
    base = {1: _rec(1, "X", dashboard_count=10)}
    cur = {1: _rec(1, "X", dashboard_count=9)}
    assert [d.kind for d in verify_invariant(base, cur)] == ["dashboard_count_changed"]


def test_verify_detects_moved_card():
    base = {1: _rec(1, "X", collection_id=214)}
    cur = {1: _rec(1, "X", collection_id=999)}
    assert [d.kind for d in verify_invariant(base, cur)] == ["moved_card"]


TESTS = [
    test_normalize_name_basic,
    test_normalize_name_cleanup,
    test_capture_snapshot_excludes_conversions,
    test_propose_skips_unchanged_cards,
    test_propose_auto_normalize_change,
    test_propose_viz_collision_adds_suffix,
    test_propose_true_duplicate_is_decision,
    test_propose_cryptic_is_decision,
    test_propose_idempotent_on_already_suffixed_collision,
    test_propose_skips_whitespace_only_name,
    test_verify_clean_when_only_name_changed,
    test_verify_detects_lost_card,
    test_verify_detects_archived_card,
    test_verify_detects_dashboard_count_change,
    test_verify_detects_moved_card,
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
