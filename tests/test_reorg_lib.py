#!/usr/bin/env python3
"""Tests unitaires de reorg_lib — script autonome (convention du repo).

Usage : python3 tests/test_reorg_lib.py
"""
import sys
import tempfile
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from reorg_lib import (CollectionNode, CardRef, MetabaseState,
                       load_plan, FamilySpec, CollectionMove,
                       verify_invariant, compute_lots, Phase1Plan,
                       TO_SORT_COLLECTION_ID)


def test_metabase_state_roundtrip():
    state = MetabaseState(
        collections={
            215: CollectionNode(id=215, name="2. Generic Questions", parent_id=None),
            214: CollectionNode(id=214, name="01. Global", parent_id=215),
        },
        cards={
            29: CardRef(id=29, name="CAC", collection_id=214,
                        dashboard_count=1211, archived=False),
        },
    )
    restored = MetabaseState.from_dict(state.to_dict())
    assert restored == state
    assert restored.cards[29].dashboard_count == 1211


def test_load_plan():
    with tempfile.TemporaryDirectory() as d:
        plan_file = Path(d) / "plan.yaml"
        plan_file.write_text(textwrap.dedent("""
            families:
              - key: ad_platforms
                name: "Ad platforms"
                description: "Plateformes publicitaires"
            collection_moves:
              - id: 209
                new_parent: ad_platforms
                new_name: "Google Ads"
            card_filing:
              46255: 217
            delete_empty:
              - 211
        """))
        plan = load_plan(plan_file)
    assert plan.families == [FamilySpec(key="ad_platforms", name="Ad platforms",
                                        description="Plateformes publicitaires")]
    assert plan.collection_moves == [CollectionMove(id=209, new_parent="ad_platforms",
                                                    new_name="Google Ads")]
    assert plan.card_filing == {46255: 217}
    assert plan.delete_empty == [211]


def _state(cards):
    return MetabaseState(collections={}, cards={c.id: c for c in cards})


def test_verify_invariant_clean_when_only_moved():
    base = _state([CardRef(29, "CAC", 214, 1211, False)])
    # même carte, collection différente -> déplacement légitime, pas de divergence
    current = _state([CardRef(29, "CAC", 999, 1211, False)])
    assert verify_invariant(base, current) == []


def test_verify_invariant_detects_lost_card():
    base = _state([CardRef(29, "CAC", 214, 1211, False)])
    current = _state([])
    divs = verify_invariant(base, current)
    assert [d.kind for d in divs] == ["lost_card"]
    assert divs[0].card_id == 29


def test_verify_invariant_detects_archived_card():
    base = _state([CardRef(29, "CAC", 214, 1211, False)])
    current = _state([CardRef(29, "CAC", 214, 1211, True)])
    divs = verify_invariant(base, current)
    assert [d.kind for d in divs] == ["archived_card"]


def test_verify_invariant_detects_dashboard_count_change():
    base = _state([CardRef(29, "CAC", 214, 1211, False)])
    current = _state([CardRef(29, "CAC", 214, 1210, False)])
    divs = verify_invariant(base, current)
    assert [d.kind for d in divs] == ["dashboard_count_changed"]


def test_compute_lots_groups_operations():
    state = MetabaseState(
        collections={
            209: CollectionNode(209, "02. Google", 215),
            211: CollectionNode(211, "04. Microsoft", 215),
        },
        cards={
            46255: CardRef(46255, "Loose card", 214, 0, False),
            777: CardRef(777, "To-sort card", TO_SORT_COLLECTION_ID, 3, False),
        },
    )
    plan = Phase1Plan(
        families=[FamilySpec("ad_platforms", "Ad platforms")],
        collection_moves=[CollectionMove(209, "ad_platforms", "Google Ads")],
        card_filing={46255: 217, 777: 218},
        delete_empty=[211],
    )
    lots = compute_lots(state, plan)
    assert [op.kind for op in lots["lot-1"]] == ["create_collection"]
    assert [op.kind for op in lots["lot-2"]] == ["move_collection"]
    assert lots["lot-2"][0].payload["new_parent_key"] == "ad_platforms"
    assert [op.payload["card_id"] for op in lots["lot-3"]] == [46255]
    assert [op.payload["card_id"] for op in lots["lot-4"]] == [777]
    assert [op.payload["collection_id"] for op in lots["lot-5"]] == [211]


TESTS = [test_metabase_state_roundtrip, test_load_plan,
         test_verify_invariant_clean_when_only_moved,
         test_verify_invariant_detects_lost_card,
         test_verify_invariant_detects_archived_card,
         test_verify_invariant_detects_dashboard_count_change,
         test_compute_lots_groups_operations]


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
