#!/usr/bin/env python3
"""Tests de swap_tables (driver) — logique pure. Usage : python3 tests/test_swap_tables.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import swap_tables


class _BoomMB:
    """mb factice : .post explose si appelé — prouve que card_rows court-circuite
    AVANT tout appel réseau quand dim_col is None."""

    def post(self, *a, **k):
        raise AssertionError("card_rows ne doit PAS interroger le réseau quand dim_col is None")


def test_card_rows_none_dim_short_circuits():
    # dashcard sans colonne visible activée -> old_dim None -> non alignable :
    # retourne None (non vérifiable -> non swappé) au lieu de crasher tout le swap.
    assert swap_tables.card_rows(_BoomMB(), 123, [], None) is None


TESTS = [test_card_rows_none_dim_short_circuits]


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
