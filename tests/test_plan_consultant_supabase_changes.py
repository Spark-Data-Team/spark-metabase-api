#!/usr/bin/env python3
import json
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import plan_consultant_supabase_changes as planner


def _record(
    row_id,
    client,
    types,
    new_types,
    *,
    company_id="company-1",
    account_id="account-1",
    type_is_null=False,
    new_type_is_null=False,
):
    return {
        "company_id": company_id,
        "client": client,
        "account_row_id": account_id,
        "account_external_id": f"external-{account_id}",
        "account_name": f"Account {account_id}",
        "conversion_row_id": row_id,
        "conversion_id": f"conversion-{row_id}",
        "conversion_name": f"Conversion {row_id}",
        "type": list(types),
        "new_type": list(new_types),
        "type_is_null": type_is_null,
        "new_type_is_null": new_type_is_null,
        "updated_at": "2026-07-15T00:00:00+00:00",
    }


def _snapshot(records, slot_mapping=None):
    return {
        "schema_version": 1,
        "source": {"system": "supabase", "environment": "production"},
        "exported_at": "2026-07-15T10:00:00+00:00",
        "records": records,
        "slot_mapping": slot_mapping or {},
    }


def _group(client, slot, classification, targets):
    return {
        "client": client,
        "slot": slot,
        "class": classification,
        "recommended_action": "Fixture",
        "proposed_targets": targets,
        "requires_live_set_equality": True,
        "notes": "Fixture",
    }


def _normalization(groups):
    return {"schema_version": 1, "groups": groups}


def _by_client(plan):
    return {group["client"]: group for group in plan["groups"]}


def test_add_only_is_automatic_only_for_strict_subset_and_preserves_arrays():
    snapshot = _snapshot([
        _record("alpha-a", "Alpha", ["Main conversion"], ["Leads"]),
        _record(
            "alpha-b",
            "Alpha",
            ["Main conversion", "Add to cart"],
            ["Custom 2", "Purchases"],
        ),
        _record("equal-a", "Equal", ["Main conversion"], ["Leads"]),
    ])
    normalization = _normalization([
        _group("Alpha", 0, "canonicalisable_safe", ["Leads"]),
        _group("Equal", 0, "canonicalisable_safe", ["Leads"]),
    ])

    plan = planner.build_plan(snapshot, normalization)
    groups = _by_client(plan)

    alpha = groups["Alpha"]
    assert alpha["disposition"] == "automatic_add_new_type"
    assert alpha["operation_kinds_needed"] == ["add_new_type"]
    operation = alpha["automatic_operations"][0]
    assert operation["conversion_row_ids"] == ["alpha-b"]
    assert operation["safety_basis"] == (
        "Après l'ajout pur, target_set == source_set du slot demandé et aucune "
        "autre assignation effective de cette cible ne vise un source_set différent."
    )
    change = operation["record_changes"][0]
    assert change["before"] == {
        "type": ["Main conversion", "Add to cart"],
        "new_type": ["Custom 2", "Purchases"],
    }
    assert change["after"] == {
        "type": ["Main conversion", "Add to cart"],
        "new_type": ["Custom 2", "Purchases", "Leads"],
    }
    assert groups["Equal"]["disposition"] == "already_exact"
    assert groups["Equal"]["automatic_operations"] == []
    assert plan["stats"]["automatic_add_new_type_rows"] == 1


def test_add_only_plan_preserves_raw_null_before_and_builds_array_after():
    snapshot = _snapshot([
        _record("already", "Null source", ["Main conversion"], ["Leads"]),
        _record(
            "raw-null",
            "Null source",
            ["Main conversion"],
            [],
            new_type_is_null=True,
        ),
    ])
    normalization = _normalization([
        _group("Null source", 0, "canonicalisable_safe", ["Leads"]),
    ])

    group = planner.build_plan(snapshot, normalization)["groups"][0]
    change = group["automatic_operations"][0]["record_changes"][0]

    assert change["conversion_row_id"] == "raw-null"
    assert change["before"] == {
        "type": ["Main conversion"],
        "new_type": None,
    }
    assert change["after"] == {
        "type": ["Main conversion"],
        "new_type": ["Leads"],
    }


def test_simple_type_cooccurrence_does_not_block_an_add_only_subset():
    snapshot = _snapshot([
        _record("a", "Collision", ["Main conversion"], ["Leads"]),
        _record("b", "Collision", ["Main conversion", "1st conversion"], []),
    ])
    normalization = _normalization([
        _group("Collision", 0, "canonicalisable_safe", ["Leads"]),
    ])

    group = planner.build_plan(snapshot, normalization)["groups"][0]

    assert group["target_comparisons"][0]["relation"] == "target_strict_subset_of_source"
    assert group["disposition"] == "automatic_add_new_type"
    assert group["operation_kinds_needed"] == ["add_new_type"]
    assert group["automatic_operations"][0]["conversion_row_ids"] == ["b"]
    assert not any(
        item["kind"] == "target_would_collide_with_other_slots"
        for item in group["diagnostics"]
    )


def test_same_effective_target_on_different_source_sets_is_blocked():
    snapshot = _snapshot(
        [
            _record("a", "Effective collision", ["Main conversion", "1st conversion"], ["Leads"]),
            _record("b", "Effective collision", ["Main conversion"], []),
        ],
        slot_mapping={"Effective collision": {"0": "__UNMAPPED__", "1": "Leads"}},
    )
    normalization = _normalization([
        _group("Effective collision", 0, "canonicalisable_safe", ["Leads"]),
    ])

    group = planner.build_plan(snapshot, normalization)["groups"][0]

    assert group["disposition"] == "blocked"
    assert group["automatic_operations"] == []
    diagnostic = next(
        item for item in group["diagnostics"]
        if item["kind"] == "target_would_collide_with_other_slots"
    )
    assert diagnostic["colliding_slots"] == [{
        "slot": 1,
        "old_type": "1st conversion",
        "source_row_count": 1,
        "source_conversion_row_ids": ["a"],
    }]


def test_target_only_rows_require_human_choice_without_mutation_payload():
    snapshot = _snapshot([
        _record("source-and-target", "Mixed", ["Main conversion"], ["Purchases"]),
        _record("source-only", "Mixed", ["Main conversion"], ["Custom 1"]),
        _record("target-only", "Mixed", ["1st conversion"], ["Purchases"]),
    ])
    normalization = _normalization([
        _group("Mixed", 0, "canonicalisable_safe", ["Purchases"]),
    ])

    group = planner.build_plan(snapshot, normalization)["groups"][0]

    assert group["disposition"] == "requires_human_data_change"
    assert group["requires_human_data_change"] is True
    assert group["operation_kinds_needed"] == [
        "add_new_type",
        "remove_new_type",
        "add_old_type",
    ]
    assert group["automatic_operations"] == []
    requirements = {
        requirement["operation"]: requirement
        for requirement in group["human_data_change_requirements"]
    }
    assert set(requirements) == {"remove_new_type", "add_old_type"}
    assert requirements["remove_new_type"]["conversion_row_ids"] == ["target-only"]
    assert requirements["add_old_type"]["conversion_row_ids"] == ["target-only"]
    # Une exigence humaine ne contient intentionnellement aucun tableau ``after``.
    assert all("after" not in requirement for requirement in requirements.values())


def test_noncanonical_groups_never_get_a_write_plan_without_exact_selectors():
    classes = ["row_level", "composite", "incomplete_missing", "non_actionable"]
    records = [
        _record(f"row-{index}", f"Client {index}", ["Main conversion"], [])
        for index in range(len(classes))
    ]
    groups = [
        _group(f"Client {index}", 0, classification, ["Leads"] if index < 3 else [])
        for index, classification in enumerate(classes)
    ]

    plan = planner.build_plan(_snapshot(records), _normalization(groups))
    planned = _by_client(plan)

    assert planned["Client 0"]["disposition"] == "ambiguous_or_account_specific"
    assert all(
        not group["automatic_operations"] and not group["human_data_change_requirements"]
        for group in planned.values()
    )
    assert all(
        group["disposition"] in {"ambiguous_or_account_specific", "blocked"}
        for group in planned.values()
    )


def test_build_is_deterministic_and_write_is_atomic_local(tmp_path):
    snapshot = _snapshot([
        _record("b", "Stable", ["Main conversion"], []),
        _record("a", "Stable", ["Main conversion"], ["Leads"]),
    ])
    normalization = _normalization([
        _group("Stable", 0, "canonicalisable_safe", ["Leads"]),
    ])

    first = planner.build_plan(snapshot, normalization)
    second = planner.build_plan(snapshot, normalization)
    assert first == second

    output = tmp_path / "nested" / "plan.json"
    planner.write_plan(first, output)
    assert json.loads(output.read_text(encoding="utf-8")) == first
    assert not output.with_suffix(".json.tmp").exists()


def test_cli_is_dry_run_by_default_and_requires_write_for_local_output(tmp_path, capsys):
    snapshot_path = tmp_path / "snapshot.json"
    normalization_path = tmp_path / "normalization.json"
    output = tmp_path / "plan.json"
    snapshot_path.write_text(json.dumps(_snapshot([
        _record("a", "CLI", ["Main conversion"], []),
    ])))
    normalization_path.write_text(json.dumps(_normalization([
        _group("CLI", 0, "canonicalisable_safe", ["Leads"]),
    ])))
    common = [
        "--snapshot", str(snapshot_path),
        "--normalization", str(normalization_path),
        "--output", str(output),
    ]

    assert planner.main(common) == 0
    assert not output.exists()
    assert "DRY-RUN" in capsys.readouterr().out

    assert planner.main([*common, "--write"]) == 0
    assert output.exists()
    assert json.loads(output.read_text())["read_only"] is True
