#!/usr/bin/env python3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_conversion_manifest as manifest


def by_original(result, original_id):
    return next(row for row in result["dashboards"] if row["original_id"] == original_id)


def test_reconciles_and_deduplicates_by_original_id_with_structured_causes():
    worklist = {"Client A": [1, 2, 3]}
    tracker = [
        {"client": "Client A", "dashboard": "One", "original_id": 1, "copy_id": 10, "tagged": True},
        {"client": "Client A", "dashboard": "Two", "original_id": 2, "copy_id": 20, "tagged": True},
        {"client": "Client A", "dashboard": "Two v2", "original_id": 2, "copy_id": 21, "tagged": True},
        {"client": "Client Z", "dashboard": "Outside", "original_id": 9, "copy_id": 90, "tagged": True},
    ]
    iron = {
        "source": "unit-cache",
        "copies": [
            {"copy_id": 10, "status": "complete"},
            {
                "copy_id": 20,
                "status": "residual",
                "causes": [{"code": "unmapped_slot", "category": "consultant", "slot": 2}],
            },
            {"copy_id": 21, "on_old": False},
            {"copy_id": 90, "visible_100": True},
        ],
    }

    result = manifest.build_manifest(worklist, tracker, iron)

    assert [row["original_id"] for row in result["dashboards"]].count(2) == 1
    assert by_original(result, 1)["roadmap_status"] == "complete"
    assert by_original(result, 2)["copy_ids"] == [20, 21]
    assert by_original(result, 2)["roadmap_status"] == "multiple_copies"
    assert by_original(result, 2)["iron_law_status"] == "residual"
    assert by_original(result, 3)["roadmap_status"] == "never_copied"
    assert by_original(result, 9)["roadmap_status"] == "out_of_scope"

    original_two_codes = {cause["code"] for cause in by_original(result, 2)["causes"]}
    assert {"multiple_copies", "iron_law_residual"} <= original_two_codes
    residual_cause = by_original(result, 2)["copies"][0]["iron_law"]["causes"][0]
    assert residual_cause == {
        "code": "unmapped_slot",
        "category": "consultant",
        "source": "unit-cache",
        "details": {"slot": 2},
    }

    summary = result["summary"]
    assert summary["originals"] == {"total": 4, "in_scope": 3, "out_of_scope": 1}
    assert summary["copy_topology_in_scope"] == {
        "never_copied": 1,
        "single_copy": 1,
        "multiple_copies": 1,
        "excess_copies": 1,
    }
    assert summary["copies"] == {"total": 4, "in_scope": 3, "out_of_scope": 1}


def test_duplicate_tracker_row_is_not_a_second_copy():
    worklist = {"A": [1]}
    tracker = [
        {"client": "A", "original_id": 1, "copy_id": 10},
        {"client": "A", "original_id": "1", "copy_id": "10"},
    ]

    result = manifest.build_manifest(worklist, tracker, {"by_copy": {"10": "complete"}})
    row = by_original(result, 1)

    assert row["copy_status"] == "single_copy"
    assert row["copy_ids"] == [10]
    assert row["copies"][0]["tracker_entry_count"] == 2
    assert row["copies"][0]["tracker_duplicate_rows"] is True


def test_explicit_copy_decision_resolves_multiple_topology_without_losing_history():
    result = manifest.build_manifest(
        {"A": [1]},
        [
            {"client": "A", "original_id": 1, "copy_id": 10},
            {"client": "A", "original_id": 1, "copy_id": 11},
        ],
        {"by_copy": {"10": "residual", "11": "complete"}},
        copy_decisions={
            "source": "unit-reconciliation",
            "decisions": [{
                "original_id": 1,
                "canonical_copy_id": 11,
                "superseded_copy_ids": [10],
                "reason": "clean copy wins",
            }],
        },
    )
    row = by_original(result, 1)

    assert row["copy_status"] == "multiple_copies"
    assert row["copy_reconciliation_status"] == "resolved"
    assert row["canonical_copy_id"] == 11
    assert row["superseded_copy_ids"] == [10]
    assert row["roadmap_status"] == "complete"
    assert row["iron_law_status"] == "complete"
    assert {copy["copy_id"]: copy["selection"] for copy in row["copies"]} == {
        10: "superseded",
        11: "canonical",
    }
    codes = {cause["code"] for cause in row["causes"]}
    assert "multiple_copies_reconciled" in codes
    assert "iron_law_residual" not in codes
    assert result["summary"]["roadmap_in_scope"] == {
        "complete": 1,
        "residual": 0,
        "unknown": 0,
        "never_copied": 0,
        "multiple_copies": 0,
    }
    assert result["summary"]["copy_reconciliation_in_scope"] == {
        "resolved": 1,
        "unresolved": 0,
        "not_applicable": 0,
        "superseded_copies": 1,
    }


def test_copy_decision_must_exhaustively_match_tracker_topology():
    try:
        manifest.build_manifest(
            {"A": [1]},
            [
                {"client": "A", "original_id": 1, "copy_id": 10},
                {"client": "A", "original_id": 1, "copy_id": 11},
            ],
            {"by_copy": {"10": "complete", "11": "complete"}},
            copy_decisions={
                "decisions": [{
                    "original_id": 1,
                    "canonical_copy_id": 11,
                    "superseded_copy_ids": [],
                }],
            },
        )
    except ValueError as exc:
        assert "copies declarees" in str(exc)
    else:
        raise AssertionError("une decision partielle doit etre refusee")


def test_missing_iron_state_is_unknown_and_never_inferred_from_tracker_status():
    result = manifest.build_manifest(
        {"A": [1]},
        [{"client": "A", "original_id": 1, "copy_id": 10, "status": "valide"}],
        None,
    )
    row = by_original(result, 1)

    assert row["iron_law_status"] == "unknown"
    assert row["roadmap_status"] == "unknown"
    assert row["copies"][0]["iron_law"]["causes"][0]["code"] == "iron_law_state_missing"


def test_conflicting_iron_rows_fail_closed_to_unknown():
    iron = [
        {"copy_id": 10, "status": "complete"},
        {"copy_id": 10, "status": "residual", "causes": ["old column"]},
    ]
    result = manifest.build_manifest(
        {"A": [1]},
        [{"client": "A", "original_id": 1, "copy_id": 10}],
        iron,
    )
    state = by_original(result, 1)["copies"][0]["iron_law"]

    assert state["status"] == "unknown"
    assert state["source_rows"] == 2
    assert "iron_state_conflict" in {cause["code"] for cause in state["causes"]}
    assert result["diagnostics"]["iron_state"]["conflicting_copy_ids"] == [10]


def test_orphan_iron_copy_and_reused_copy_are_reported():
    tracker = [
        {"client": "A", "original_id": 1, "copy_id": 10},
        {"client": "A", "original_id": 2, "copy_id": 10},
    ]
    result = manifest.build_manifest(
        {"A": [1, 2]},
        tracker,
        {"by_copy": {"10": True, "999": False}},
    )

    assert result["diagnostics"]["copy_ids_reused_across_originals"] == {"10": [1, 2]}
    assert result["diagnostics"]["iron_state"]["orphan_copy_ids"] == [999]
    assert "copy_reused_across_originals" in {
        cause["code"] for cause in by_original(result, 1)["causes"]
    }


def test_rejects_aggregate_accounting_without_copy_grain():
    aggregate = {"dashboards": 370, "visible_100": 123, "residu": 247}
    try:
        manifest.build_manifest({"A": [1]}, [], aggregate)
    except ValueError as exc:
        assert "trop agrege" in str(exc)
    else:
        raise AssertionError("un accounting agrege ne doit pas etre interprete par copie")


def test_client_attribution_keeps_worklist_owner_and_flags_default_mismatch():
    attribution = {
        "source": "live-default-audit",
        "by_original": {
            "18438": {
                "owner_client": "Canopea",
                "dashboard_default_clients": ["Figaret"],
                "scope_flags": [{"code": "parent_owner_verified", "category": "scope"}],
                "evidence": {"parameter": "Client"},
            },
        },
    }
    result = manifest.build_manifest(
        {"Canopea": [18438]},
        [],
        None,
        client_attribution=attribution,
    )
    row = by_original(result, 18438)

    assert row["owner_client"] == "Canopea"
    assert row["client_attribution"]["dashboard_default_clients"] == ["Figaret"]
    assert row["client_attribution"]["status"] == "mismatch"
    assert {cause["code"] for cause in row["scope_flags"]} == {
        "parent_owner_verified",
        "dashboard_default_client_mismatch",
    }
    assert row["client_attribution"]["evidence"] == [{"parameter": "Client"}]


def test_explicit_client_alias_is_accepted_without_reassigning_owner():
    result = manifest.build_manifest(
        {"Mavala France": [25368]},
        [],
        None,
        client_attribution={
            "by_original": {
                "25368": {
                    "dashboard_default_clients": ["Mavala", "Mavala France"],
                    "accepted_owner_aliases": ["Mavala"],
                },
            },
        },
    )
    row = by_original(result, 25368)

    assert row["owner_client"] == "Mavala France"
    assert row["client_attribution"]["status"] == "match"
    assert "dashboard_default_client_mismatch" not in {
        cause["code"] for cause in row["scope_flags"]
    }
    assert "multiple_dashboard_default_clients" in {
        cause["code"] for cause in row["scope_flags"]
    }


def test_never_copied_dashboard_uses_live_attribution_name():
    result = manifest.build_manifest(
        {"Absolut Cashmere": [18406]},
        [],
        None,
        client_attribution={
            "source": "metabase-dashboard-get",
            "dashboards": [{
                "original_id": 18406,
                "dashboard_default_clients": ["Figaret"],
                "evidence": {
                    "dashboard_name": "Global | Absolut Cashmere",
                    "endpoint": "/api/dashboard/18406",
                },
            }],
        },
    )

    row = by_original(result, 18406)
    assert row["copy_status"] == "never_copied"
    assert row["dashboard"] == "Global | Absolut Cashmere"
    assert row["client_attribution"]["dashboard_names"] == ["Global | Absolut Cashmere"]


def test_cli_writes_a_local_manifest(tmp_path):
    worklist_path = tmp_path / "worklist.json"
    tracker_path = tmp_path / "tracker.json"
    iron_path = tmp_path / "iron.json"
    output_path = tmp_path / "manifest.json"
    worklist_path.write_text(json.dumps({"A": [1]}))
    tracker_path.write_text(json.dumps([{"client": "A", "original_id": 1, "copy_id": 10}]))
    iron_path.write_text(json.dumps({"by_copy": {"10": {"status": "complete"}}}))

    result = manifest.main([
        "--worklist", str(worklist_path),
        "--tracker", str(tracker_path),
        "--iron-state", str(iron_path),
        "--output", str(output_path),
    ])

    assert result == 0
    written = json.loads(output_path.read_text())
    assert written["dashboards"][0]["roadmap_status"] == "complete"
