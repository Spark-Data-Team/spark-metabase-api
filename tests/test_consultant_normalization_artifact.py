#!/usr/bin/env python3
import json
from collections import Counter
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
REVIEWS = REPO / "migration" / "consultant-answer-reviews.json"
NORMALIZATION = REPO / "migration" / "consultant-normalization.json"

EXPECTED_COUNTS = {
    "canonicalisable_safe": 6,
    "composite": 3,
    "row_level": 21,
    "incomplete_missing": 4,
    "non_actionable": 23,
}


def _key(row):
    return row["client"], int(row["slot"])


def test_consultant_normalization_covers_each_review_group_once():
    reviews = json.loads(REVIEWS.read_text(encoding="utf-8"))
    artifact = json.loads(NORMALIZATION.read_text(encoding="utf-8"))
    groups = artifact["groups"]

    review_keys = [_key(row) for row in reviews]
    normalized_keys = [_key(row) for row in groups]

    assert len(reviews) == 57
    assert len(groups) == 57
    assert len(set(review_keys)) == len(review_keys)
    assert len(set(normalized_keys)) == len(normalized_keys)
    assert set(normalized_keys) == set(review_keys)


def test_consultant_normalization_counts_and_required_fields():
    artifact = json.loads(NORMALIZATION.read_text(encoding="utf-8"))
    groups = artifact["groups"]
    counts = Counter(row["class"] for row in groups)

    assert dict(counts) == EXPECTED_COUNTS
    assert artifact["class_counts"] == EXPECTED_COUNTS

    required = {
        "client",
        "slot",
        "class",
        "recommended_action",
        "proposed_targets",
        "requires_live_set_equality",
        "notes",
    }
    for row in groups:
        assert required <= row.keys()
        assert row["recommended_action"].strip()
        assert isinstance(row["proposed_targets"], list)
        assert isinstance(row["requires_live_set_equality"], bool)
        assert row["notes"].strip()
