from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import apply_time_filter_plan as batch


def test_normalise_plan_rejects_duplicate_copy_ids():
    try:
        batch.normalise_plan([
            {"copy_id": 1, "client": "A"},
            {"copy_id": 1, "client": "A"},
        ])
    except ValueError as exc:
        assert "dupliqué" in str(exc)
    else:
        raise AssertionError("un duplicate copy_id doit être refusé")


def test_execute_plan_continues_after_a_blocker(monkeypatch):
    calls = []

    def fake_main(argv, mb):
        calls.append((argv, mb))
        if argv[1] == "1":
            raise SystemExit(1)
        return 0

    monkeypatch.setattr(batch.bascule_time_filter, "main", fake_main)
    report = batch.execute_plan(
        object(),
        [
            {"copy_id": 1, "client": "A"},
            {"copy_id": 2, "client": "B"},
        ],
        yes=True,
    )

    assert [item["status"] for item in report] == ["BLOCKED", "APPLIED"]
    assert len(calls) == 2
