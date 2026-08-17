from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import ensure_client_default as ensure


def dashboard(default):
    return {
        "parameters": [
            {"id": "client-id", "name": "Client", "slug": "client", "default": default},
            {"id": "account-id", "name": "Account", "slug": "account", "default": ["Old account"]},
            {"id": "date-id", "name": "Date", "slug": "date", "default": None},
        ],
        "dashcards": [{"id": 1, "card_id": 2}],
    }


def test_build_parameters_changes_only_client_default_without_mutating_source():
    before = dashboard(["Wrong client"])
    parameters, changes = ensure.build_parameters(before, "Right client")

    assert parameters[0]["default"] == ["Right client"]
    assert parameters[1]["default"] == ["Old account"]
    assert parameters[2]["default"] is None
    assert before["parameters"][0]["default"] == ["Wrong client"]
    assert changes == [{
        "id": "client-id",
        "name": "Client",
        "before": ["Wrong client"],
        "after": ["Right client"],
    }]


def test_absent_client_parameter_is_a_valid_noop_plan():
    before = {"parameters": [{"name": "Date", "slug": "date"}]}
    parameters, changes = ensure.build_parameters(before, "Right client")
    assert parameters == before["parameters"]
    assert changes == []
    assert ensure.client_defaults(before) == []


def test_account_default_is_cleared_only_when_explicitly_requested():
    before = dashboard(["Wrong client"])
    parameters, changes = ensure.build_parameters(
        before,
        "Right client",
        clear_account_default=True,
    )

    assert parameters[0]["default"] == ["Right client"]
    assert parameters[1]["default"] is None
    assert before["parameters"][1]["default"] == ["Old account"]
    assert changes[-1] == {
        "id": "account-id",
        "name": "Account",
        "before": ["Old account"],
        "after": None,
    }


def test_default_issues_rejects_wrong_client():
    assert ensure.default_issues(dashboard(["Wrong"]), "Right") == [
        "paramètre client-id: défaut attendu ['Right'], relu ['Wrong']"
    ]
    assert ensure.default_issues(dashboard(["Right"]), "Right") == []


def test_default_issues_can_require_a_cleared_account_default():
    assert ensure.default_issues(
        dashboard(["Right"]),
        "Right",
        require_account_default_cleared=True,
    ) == [
        "paramètre account-id: défaut Account attendu None, relu ['Old account']"
    ]


class _Response:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class _Metabase:
    def __init__(self, before, after):
        self.before = before
        self.after = after
        self.puts = []

    def put(self, endpoint, mode, json):
        self.puts.append((endpoint, mode, json))
        return _Response()

    def get(self, endpoint):
        return self.after if len(self.puts) == 1 else self.before


def test_put_verified_rolls_back_when_reread_has_wrong_default(tmp_path, monkeypatch):
    before = dashboard(["Wrong"])
    parameters, _changes = ensure.build_parameters(before, "Right")
    mb = _Metabase(before, dashboard(["Still wrong"]))
    monkeypatch.setattr(ensure, "write_snapshot", lambda *_: tmp_path / "snapshot.json")

    try:
        ensure.put_verified(mb, 42, before, parameters, "Right")
    except RuntimeError as exc:
        assert "défaut attendu" in str(exc)
        assert "rollback vérifié" in str(exc)
    else:
        raise AssertionError("une relecture divergente doit échouer")
    assert len(mb.puts) == 2
