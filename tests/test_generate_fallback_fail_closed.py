#!/usr/bin/env python3
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import generate_fallback as fallback


class _Response:
    text = "{}"

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def test_run_card_includes_dashboard_required_defaults():
    calls = []

    class MB:
        def post(self, endpoint, mode, json, timeout):
            calls.append(json)
            return _Response({
                "status": "completed",
                "data": {"cols": [{"name": "value"}], "rows": [[1]]},
            })

    card = {
        "dataset_query": {
            "type": "native",
            "native": {"query": "select 1", "template-tags": {}},
        }
    }
    extra = [{
        "type": "string/=",
        "value": ["age"],
        "target": ["dimension", ["template-tag", "breakdown"]],
    }]

    assert fallback._run_card(MB(), card, "Client", extra_params=extra) == (
        ["value"],
        [[1]],
    )
    assert calls[0]["parameters"] == extra


class _RunningForeverMetabase:
    def __init__(self):
        self.posts = 0

    def get(self, _endpoint):
        return {
            "dataset_query": {
                "type": "native",
                "native": {"query": "select 1", "template-tags": {}},
            }
        }

    def post(self, *_args, **_kwargs):
        self.posts += 1
        return _Response({"status": "running"})


def test_render_check_blocks_non_terminal_execution():
    mb = _RunningForeverMetabase()

    ok, blank = fallback.render_check(mb, 123, "Acme")
    assert ok is False and blank is False  # statut non terminal -> fail-closed, jamais « ok »
    assert mb.posts == 2


def test_value_review_distinguishes_unverifiable_from_equal(monkeypatch):
    results = iter([(None, None), (["PURCHASES"], [[1]])])
    monkeypatch.setattr(fallback, "_run_card", lambda *_args, **_kwargs: next(results))

    class _Metabase:
        def get(self, _endpoint):
            return {"dataset_query": {}}

    assert fallback.value_review(
        _Metabase(), {"dataset_query": {}}, 456, "Acme", {"CONVERSIONS": "PURCHASES"}
    ) is None


def test_value_review_returns_empty_list_only_after_two_completed_runs(monkeypatch):
    results = iter([
        (["CONVERSIONS"], [[3], [4]]),
        (["PURCHASES"], [[7]]),
    ])
    monkeypatch.setattr(fallback, "_run_card", lambda *_args, **_kwargs: next(results))

    class _Metabase:
        def get(self, _endpoint):
            return {"dataset_query": {}}

    assert fallback.value_review(
        _Metabase(), {"dataset_query": {}}, 456, "Acme", {"CONVERSIONS": "PURCHASES"}
    ) == []


def _card(query):
    return {
        "dataset_query": {
            "type": "native",
            "native": {"query": query, "template-tags": {}},
        }
    }


def _dashboard(primary=10, series=11, viz="old"):
    return {
        "id": 42,
        "name": "Dashboard complet",
        "description": "présente seulement dans le snapshot complet",
        "tabs": [{"id": 5, "name": "Vue"}],
        "dashcards": [{
            "id": 7,
            "card_id": primary,
            "row": 0,
            "col": 0,
            "size_x": 12,
            "size_y": 6,
            "dashboard_tab_id": 5,
            "series": [] if series is None else [{"id": series}],
            "parameter_mappings": [{"card_id": primary}],
            "visualization_settings": {"graph.metrics": [viz]},
        }],
    }


def test_final_audit_detects_positional_series_even_when_primary_is_named():
    dashboard = _dashboard()

    class MB:
        def get(self, path):
            card_id = int(path.rsplit("/", 1)[1])
            return _card("select CONVERSIONS_2 from x" if card_id == 11 else "select PURCHASES from x")

    assert fallback.conversion_reference_issues(MB(), dashboard) == [{
        "dashcard_id": 7,
        "location": "series[0]",
        "card_id": 11,
        "status": "POSITIONAL",
        "old_columns": ["CONVERSIONS_2"],
    }]


def test_final_audit_treats_missing_or_unreadable_series_as_inaccessible():
    dashboard = _dashboard()
    dashboard["dashcards"][0]["series"] = [{"name": "sans id"}, {"id": 12}]

    class MB:
        def get(self, path):
            card_id = int(path.rsplit("/", 1)[1])
            if card_id == 12:
                raise PermissionError("forbidden")
            return _card("select PURCHASES from x")

    issues = fallback.conversion_reference_issues(MB(), dashboard)

    assert [issue["status"] for issue in issues] == ["INACCESSIBLE", "INACCESSIBLE"]
    assert issues[0]["reason"] == "SERIES_CARD_ID_MISSING"
    assert issues[1]["reason"].startswith("CARD_READ_FAILED:")


def test_verified_dashboard_put_snapshots_full_object_and_rereads(tmp_path):
    before = _dashboard(primary=10, series=11, viz="old")
    wanted_dashboard = _dashboard(primary=20, series=11, viz="new")
    wanted = wanted_dashboard["dashcards"]

    class MB:
        def __init__(self):
            self.puts = []

        def put(self, path, mode, json):
            self.puts.append((path, mode, json))
            return SimpleNamespace(status_code=200, text="")

        def get(self, path):
            return wanted_dashboard

    mb = MB()
    snapshot = fallback.put_dashboard_verified(
        mb, 42, before, wanted, {7}, tmp_path
    )

    assert len(mb.puts) == 1
    assert mb.puts[0][2]["tabs"] == before["tabs"]
    assert json.loads(snapshot.read_text()) == before
    assert json.loads(snapshot.read_text())["description"].startswith("présente")


def test_non_200_put_triggers_verified_rollback_and_failure(tmp_path):
    before = _dashboard(primary=10, series=11, viz="old")
    wanted = _dashboard(primary=20, series=11, viz="new")["dashcards"]

    class MB:
        def __init__(self):
            self.puts = []

        def put(self, path, mode, json):
            self.puts.append(json)
            if len(self.puts) == 1:
                return SimpleNamespace(status_code=500, text="boom")
            return SimpleNamespace(status_code=200, text="")

        def get(self, path):
            return before

    mb = MB()
    with pytest.raises(RuntimeError, match="PUT HTTP 500") as exc:
        fallback.put_dashboard_verified(mb, 42, before, wanted, {7}, tmp_path)

    assert "rollback vérifié" in str(exc.value)
    assert len(mb.puts) == 2
    assert mb.puts[1] == fallback.dashboard_payload(before)


def test_divergent_series_reread_triggers_verified_rollback(tmp_path):
    before = _dashboard(primary=10, series=11, viz="old")
    wanted_dashboard = _dashboard(primary=20, series=11, viz="new")
    wanted = wanted_dashboard["dashcards"]
    divergent = _dashboard(primary=20, series=99, viz="new")

    class MB:
        def __init__(self):
            self.puts = []
            self.reads = 0

        def put(self, path, mode, json):
            self.puts.append(json)
            return SimpleNamespace(status_code=200, text="")

        def get(self, path):
            self.reads += 1
            return divergent if self.reads == 1 else before

    mb = MB()
    with pytest.raises(RuntimeError, match="relecture post-PUT divergente") as exc:
        fallback.put_dashboard_verified(mb, 42, before, wanted, {7}, tmp_path)

    assert "séries attendues" in str(exc.value)
    assert "rollback vérifié" in str(exc.value)
    assert len(mb.puts) == 2


def test_main_returns_nonzero_when_verified_put_fails(monkeypatch):
    dashboard = _dashboard(primary=10, series=None, viz="old")

    class MB:
        def get(self, path):
            return dashboard if path.startswith("/api/dashboard/") else _card("select CONVERSIONS from x")

    monkeypatch.setattr(sys, "argv", [
        "generate_fallback.py", "--copy", "42", "--client", "Acme", "--yes",
    ])
    monkeypatch.setattr(fallback, "connect", MB)
    monkeypatch.setattr(fallback, "load_inputs", lambda: ({"Acme": {"0": "Purchases"}}, {}))
    monkeypatch.setattr(fallback, "load_reg", lambda: {})
    monkeypatch.setattr(fallback, "load_special_ids", lambda: set())
    monkeypatch.setattr(fallback, "generate_card", lambda *_args, **_kwargs: 20)
    monkeypatch.setattr(fallback, "render_check", lambda *_args, **_kwargs: (True, False))
    monkeypatch.setattr(fallback, "value_review", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        fallback,
        "put_dashboard_verified",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("PUT divergent")),
    )

    assert fallback.main() == 1


def test_main_applied_mode_returns_nonzero_for_positional_series(monkeypatch):
    dashboard = _dashboard(primary=10, series=11, viz="old")

    class MB:
        def get(self, path):
            if path.startswith("/api/dashboard/"):
                return dashboard
            card_id = int(path.rsplit("/", 1)[1])
            return _card("select CONVERSIONS_1 from x" if card_id == 11 else "select PURCHASES from x")

    monkeypatch.setattr(sys, "argv", [
        "generate_fallback.py", "--copy", "42", "--client", "Acme", "--yes",
    ])
    monkeypatch.setattr(fallback, "connect", MB)
    monkeypatch.setattr(fallback, "load_inputs", lambda: ({"Acme": {}}, {}))
    monkeypatch.setattr(fallback, "load_reg", lambda: {})
    monkeypatch.setattr(fallback, "load_special_ids", lambda: set())

    assert fallback.main() == 1
