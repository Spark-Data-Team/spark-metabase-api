#!/usr/bin/env python3
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import migrate_dashboard_full as mdf


def test_connect_retries_transient_connection_errors(monkeypatch):
    attempts = []
    sleeps = []

    def fake_api(**kwargs):
        attempts.append(kwargs)
        if len(attempts) < 3:
            raise requests.exceptions.ConnectionError("dns")
        return "connected"

    monkeypatch.setattr(mdf, "_load_env", lambda: {
        "METABASE_DOMAIN": "https://example.invalid",
        "METABASE_EMAIL": "user@example.invalid",
        "METABASE_PASSWORD": "secret",
    })
    monkeypatch.setattr(mdf, "Metabase_API", fake_api)
    monkeypatch.setattr(mdf.time, "sleep", sleeps.append)

    assert mdf.connect(retries=4, retry_delay=2) == "connected"
    assert len(attempts) == 3
    assert sleeps == [2, 4]


def test_values_match_is_fail_closed_on_empty_or_different_results():
    assert mdf.values_match_fail_closed([0.0], [0.0]) is True
    assert mdf.values_match_fail_closed([], []) is False
    assert mdf.values_match_fail_closed([1.0], [2.0]) is False
