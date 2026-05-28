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
    assert "## Résumé" in md and "## Backlog" in md
    # exemples plafonnés : au plus MAX_EXAMPLES lignes d'exemple type "  - `"
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
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failures += 1
            print(f"FAIL  {t.__name__}: {e!r}")
    print(f"\n{len(TESTS) - failures}/{len(TESTS)} tests passés")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    run()
