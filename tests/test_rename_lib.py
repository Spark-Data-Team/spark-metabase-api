#!/usr/bin/env python3
"""Tests unitaires de rename_lib — script autonome (convention du repo).

Usage : python3 tests/test_rename_lib.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from rename_lib import normalize_name


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


TESTS = [test_normalize_name_basic]


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
