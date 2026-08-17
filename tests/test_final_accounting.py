#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import final_accounting as fa


def test_dashboard_card_refs_includes_primary_and_series():
    dc = {
        "card_id": 10,
        "series": [{"id": 11}, {"card_id": 12}, {}],
    }
    assert list(fa.dashboard_card_refs(dc)) == [
        ("card", 10),
        ("series", 11),
        ("series", 12),
    ]


def test_embedded_cards_reuses_complete_primary_and_series_only():
    dashboard = {
        "dashcards": [{
            "card": {"id": 10, "dataset_query": {"type": "native"}},
            "series": [
                {"id": 11, "dataset_query": {"type": "native"}},
                {"id": 12, "card": {"id": 12, "dataset_query": {"type": "native"}}},
                {"id": 13},
            ],
        }]
    }

    assert [card["id"] for card in fa.embedded_cards(dashboard)] == [10, 11, 12]


def test_fetch_dict_uses_authenticated_http_session_without_session_probe():
    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"id": 10}

    class Http:
        def __init__(self):
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return Response()

    class MB:
        domain = "https://metabase.example"
        header = {"X-Metabase-Session": "redacted"}

        def __init__(self):
            self._http = Http()

        def get(self, *_args, **_kwargs):
            raise AssertionError("le wrapper ne doit pas sonder /api/user/current")

    mb = MB()
    assert fa.fetch_dict(mb, "/api/card/10") == {"id": 10}
    assert mb._http.calls[0][0] == "https://metabase.example/api/card/10"


def test_fetch_dict_retries_and_never_turns_error_into_empty(monkeypatch):
    class MB:
        def __init__(self):
            self.responses = [False, RuntimeError("network"), {"id": 10}]

        def get(self, endpoint, timeout):
            value = self.responses.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

    sleeps = []
    monkeypatch.setattr(fa.time, "sleep", sleeps.append)
    assert fa.fetch_dict(MB(), "/api/card/10") == {"id": 10}
    assert sleeps == [1, 2]


def test_fetch_dict_fails_closed_after_retries(monkeypatch):
    class MB:
        def get(self, endpoint, timeout):
            return False

    monkeypatch.setattr(fa.time, "sleep", lambda _delay: None)
    try:
        fa.fetch_dict(MB(), "/api/card/10", retries=2)
    except RuntimeError as exc:
        assert "lecture Metabase impossible" in str(exc)
    else:
        raise AssertionError("une carte inaccessible ne doit jamais être considérée clean")


def test_classify_copy_reports_primary_series_and_both_cause_families():
    cards = {
        10: ({"CONVERSIONS", "CONVERSIONS_1"}, "mixed"),
        11: ({"CONVERSIONS_2"}, "series"),
        99: ({"CONVERSIONS_3"}, "special"),
    }
    dashboard = {
        "dashcards": [{
            "id": 100,
            "card_id": 10,
            "series": [{"id": 11}, {"id": 99}],
        }]
    }
    result = fa.classify_copy(
        dashboard,
        {0: "Purchases", 1: fa.conv_lib.CONFLICT, 2: "Leads"},
        cards.__getitem__,
        {99},
    )
    assert result["iron_law"] == "residual"
    assert result["consultant_slots"] == [1]
    assert [(x["card_id"], x["slots"]) for x in result["coverage"]] == [
        (10, [0]),
        (11, [2]),
    ]
    assert [x["card_id"] for x in result["residual_cards"]] == [10, 11]
    assert result["unknown_cards"] == []


def test_classify_copy_is_clean_when_only_real_special_replacements_remain():
    dashboard = {"dashcards": [{"id": 1, "card_id": 49788}]}
    result = fa.classify_copy(
        dashboard,
        {},
        lambda _cid: ({"CONVERSIONS"}, "special"),
        {49788},
    )
    assert result == {
        "iron_law": "clean",
        "consultant_slots": [],
        "coverage": [],
        "residual_cards": [],
        "unknown_cards": [],
    }


def test_classify_copy_keeps_opaque_card_unknown_instead_of_false_clean():
    dashboard = {"dashcards": [{"id": 1, "card_id": 50}]}

    result = fa.classify_copy(
        dashboard,
        {},
        lambda _cid: (set(), "opaque source", True),
    )

    assert result["iron_law"] == "unknown"
    assert result["residual_cards"] == []
    assert result["unknown_cards"] == [{
        "dashcard_id": 1,
        "card_id": 50,
        "location": "card",
        "name": "opaque source",
        "reason": "opaque_snippet_or_source_card",
    }]
