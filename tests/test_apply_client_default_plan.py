from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import apply_client_default_plan as batch


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


def test_dry_run_plans_client_and_explicit_account_change_without_put(monkeypatch):
    dashboard = {
        "parameters": [
            {"id": "client", "name": "Client", "slug": "client", "default": ["Wrong"]},
            {"id": "account", "name": "Account", "slug": "account", "default": ["Old"]},
        ],
        "dashcards": [],
    }

    class MB:
        def get(self, _path):
            return dashboard

    monkeypatch.setattr(
        batch,
        "put_verified",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("PUT interdit")),
    )
    code, report = batch.execute_plan(
        MB(),
        [{"copy_id": 1, "client": "Right", "clear_account_default": True}],
        yes=False,
    )

    assert code == 0
    assert report[0]["status"] == "PLANNED"
    assert [change["after"] for change in report[0]["changes"]] == [["Right"], None]
