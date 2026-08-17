#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import scan_consultant_rerun as scr


def test_decision_slots_validates_and_groups():
    grouped = scr.decision_slots([
        {"client": "Acme", "slot": 0, "new_type": "Purchases"},
        {"client": "Acme", "slot": 2, "new_type": "Custom 2"},
    ])
    assert grouped == {"Acme": {0, 2}}


def test_matching_cards_only_returns_wanted_old_slots():
    dashboard = {"dashcards": [
        {"id": 10, "card_id": 1},
        {"id": 11, "card_id": 2},
        {"id": 12, "card_id": 3},
    ]}
    cards = {
        1: {"name": "main", "dataset_query": {"type": "native", "native": {"query": "select sum(conversions)"}}},
        2: {"name": "slot 2", "dataset_query": {"type": "native", "native": {"query": "select sum(conversions_2)"}}},
        3: {"name": "named", "dataset_query": {"type": "native", "native": {"query": "select sum(purchases)"}}},
    }
    matches = scr.matching_cards(dashboard, {2}, cards.get)
    assert len(matches) == 1
    assert matches[0]["card_id"] == 2
    assert matches[0]["slots"] == [2]


def test_matching_cards_skips_verified_special_replacements():
    dashboard = {"dashcards": [{"id": 10, "card_id": 49788}]}
    cards = {
        49788: {
            "name": "selector already migrated",
            "dataset_query": {
                "type": "native",
                "native": {"query": "select sum(conversions_1)"},
            },
        },
    }
    assert scr.matching_cards(dashboard, {1}, cards.get, {49788}) == []


def test_matching_cards_includes_positional_series():
    dashboard = {
        "dashcards": [{
            "id": 10,
            "card_id": 1,
            "series": [{"id": 2}],
        }],
    }
    cards = {
        1: {"name": "named", "dataset_query": {"type": "native", "native": {"query": "select purchases"}}},
        2: {"name": "legacy series", "dataset_query": {"type": "native", "native": {"query": "select conversions_2"}}},
    }
    matches = scr.matching_cards(dashboard, {2}, cards.get)
    assert matches == [{
        "dashcard_id": 10,
        "location": "series",
        "card_id": 2,
        "card_name": "legacy series",
        "slots": [2],
        "old_columns": ["CONVERSIONS_2"],
        "series_index": 0,
    }]
