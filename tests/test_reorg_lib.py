#!/usr/bin/env python3
"""Tests unitaires de reorg_lib — script autonome (convention du repo).

Usage : python3 tests/test_reorg_lib.py
"""
import sys
import tempfile
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from reorg_lib import CollectionNode, CardRef, MetabaseState


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


TESTS = [test_metabase_state_roundtrip]


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
