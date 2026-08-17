#!/usr/bin/env python3
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import polish_generated_viz as pgv


def dashboard(viz="old"):
    return {
        "id": 42,
        "name": "Dashboard complet",
        "description": "doit être dans le snapshot",
        "tabs": [{"id": 5, "name": "Tab"}],
        "dashcards": [{
            "id": 7,
            "card_id": 70,
            "visualization_settings": {"graph.metrics": [viz]},
        }],
    }


def response(status=200, text=""):
    return SimpleNamespace(status_code=status, text=text)


def test_dashboard_divergences_is_pure_and_detects_viz_mismatch():
    expected = dashboard("new")["dashcards"]
    actual = dashboard("other")

    assert pgv.dashboard_divergences(expected, actual, {7}) == [
        "dashcard 7: visualization_settings divergents"
    ]
    assert expected[0]["visualization_settings"] == {"graph.metrics": ["new"]}


def test_verified_put_snapshots_full_dashboard_and_rereads(tmp_path):
    before = dashboard("old")
    wanted = dashboard("new")["dashcards"]

    class MB:
        def __init__(self):
            self.puts = []

        def put(self, path, mode, json):
            self.puts.append((path, mode, json))
            return response()

        def get(self, path):
            return dashboard("new")

    mb = MB()
    snapshot = pgv.put_verified(mb, 42, before, wanted, {7}, tmp_path)

    assert len(mb.puts) == 1
    assert mb.puts[0][2]["tabs"] == before["tabs"]
    assert json.loads(snapshot.read_text()) == before
    assert json.loads(snapshot.read_text())["description"] == "doit être dans le snapshot"


def test_divergent_reread_triggers_verified_best_effort_rollback(tmp_path):
    before = dashboard("old")
    wanted = dashboard("new")["dashcards"]

    class MB:
        def __init__(self):
            self.puts = []
            self.reads = 0

        def put(self, path, mode, json):
            self.puts.append(json)
            return response()

        def get(self, path):
            self.reads += 1
            # première relecture: divergence; seconde: rollback restauré
            return dashboard("wrong" if self.reads == 1 else "old")

    mb = MB()
    with pytest.raises(RuntimeError, match="relecture post-PUT divergente") as exc:
        pgv.put_verified(mb, 42, before, wanted, {7}, tmp_path)

    assert "rollback vérifié" in str(exc.value)
    assert len(mb.puts) == 2
    assert mb.puts[1] == pgv.dashboard_payload(before)


def test_http_failure_also_attempts_rollback(tmp_path):
    before = dashboard("old")
    wanted = dashboard("new")["dashcards"]

    class MB:
        def __init__(self):
            self.puts = []

        def put(self, path, mode, json):
            self.puts.append(json)
            return response(500, "boom") if len(self.puts) == 1 else response(200)

        def get(self, path):
            return dashboard("old")

    mb = MB()
    with pytest.raises(RuntimeError, match="PUT HTTP 500") as exc:
        pgv.put_verified(mb, 42, before, wanted, {7}, tmp_path)

    assert "rollback vérifié" in str(exc.value)
    assert len(mb.puts) == 2
