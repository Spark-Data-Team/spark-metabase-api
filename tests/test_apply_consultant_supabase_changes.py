#!/usr/bin/env python3
import copy
import json
import sys
from pathlib import Path

import pytest
import requests


REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import apply_consultant_supabase_changes as applier


def _row_id(index: int) -> str:
    return f"00000000-0000-4000-8000-{index:012d}"


def _record(
    index: int,
    *,
    target: str = "Leads",
    before_new_type=None,
    raw_new_type_null: bool = False,
) -> dict:
    normalized_before_new_type = list(before_new_type or [])
    raw_before_new_type = None if raw_new_type_null else normalized_before_new_type
    return {
        "conversion_row_id": _row_id(index),
        "before": {
            "type": ["Main conversion"],
            "new_type": raw_before_new_type,
        },
        "after": {
            "type": ["Main conversion"],
            "new_type": [*normalized_before_new_type, target],
        },
    }


def _plan(records: list[dict], *, target: str = "Leads") -> dict:
    ids = [record["conversion_row_id"] for record in records]
    return {
        "schema_version": 1,
        "read_only": True,
        "source": {"system": "supabase_snapshot", "environment": "production"},
        "stats": {"automatic_add_new_type_rows": len(records)},
        "groups": [
            {
                "client": "Fixture",
                "slot": 0,
                "disposition": "automatic_add_new_type",
                "automatic_operations": [
                    {
                        "operation": "add_new_type",
                        "automatic_safe": True,
                        "new_type": target,
                        "conversion_row_ids": ids,
                        "record_changes": records,
                    }
                ],
            }
        ],
    }


def _changes(count=2):
    return applier.extract_changes(
        _plan([_record(index) for index in range(1, count + 1)]),
        expected_count=count,
    )


class FakeClient:
    def __init__(self, changes, *, snapshot_path=None, fail_after_write_id=None):
        self.changes = {change.row_id: change for change in changes}
        self.snapshot_path = snapshot_path
        self.fail_after_write_id = fail_after_write_id
        self.failed_once = False
        self.calls = []
        self.clock = 0
        self.state = {
            change.row_id: {
                "id": change.row_id,
                "type": None if change.before_type is None else list(change.before_type),
                "new_type": (
                    None
                    if change.before_new_type is None
                    else list(change.before_new_type)
                ),
                "updated_at": f"2026-07-15T10:00:0{index}+00:00",
            }
            for index, change in enumerate(changes)
        }

    def fetch_rows(self, row_ids):
        self.calls.append(("GET", tuple(row_ids)))
        return {row_id: copy.deepcopy(self.state[row_id]) for row_id in row_ids}

    def patch_new_type(self, row_id, expected_updated_at, new_type):
        rendered_new_type = None if new_type is None else list(new_type)
        self.calls.append(("PATCH", row_id, expected_updated_at, rendered_new_type))
        if self.snapshot_path is not None:
            assert self.snapshot_path.exists(), "le snapshot doit précéder le premier PATCH"
        row = self.state[row_id]
        if row["updated_at"] != expected_updated_at:
            raise applier.ApplyError(f"concurrency mismatch for {row_id}")
        row["new_type"] = rendered_new_type
        self.clock += 1
        row["updated_at"] = f"2026-07-15T11:00:{self.clock:02d}+00:00"
        if row_id == self.fail_after_write_id and not self.failed_once:
            self.failed_once = True
            raise applier.ApplyError(f"simulated ambiguous failure for {row_id}")
        return copy.deepcopy(row)


def test_extract_changes_accepts_only_unique_pure_additions():
    records = [
        _record(1, before_new_type=["Custom 1"]),
        _record(2, before_new_type=[]),
    ]

    changes = applier.extract_changes(_plan(records), expected_count=2)

    assert [change.row_id for change in changes] == [_row_id(1), _row_id(2)]
    assert changes[0].before_new_type == ("Custom 1",)
    assert changes[0].after_new_type == ("Custom 1", "Leads")


def test_raw_null_is_preserved_and_never_treated_as_empty_array_in_preflight():
    changes = applier.extract_changes(
        _plan([_record(1, raw_new_type_null=True)]),
        expected_count=1,
    )
    change = changes[0]
    assert change.before_new_type is None
    assert change.after_new_type == ("Leads",)
    client = FakeClient(changes)

    assert applier.preflight(client, changes)[change.row_id]["new_type"] is None
    client.state[change.row_id]["new_type"] = []
    with pytest.raises(applier.ApplyError, match=change.row_id):
        applier.preflight(client, changes)


@pytest.mark.parametrize("unsafe_mutation", ["type", "remove"])
def test_extract_changes_rejects_type_mutation_and_non_append(unsafe_mutation):
    record = _record(1, before_new_type=["Custom 1"])
    if unsafe_mutation == "type":
        record["after"]["type"] = ["1st conversion"]
    else:
        record["after"]["new_type"] = ["Leads"]

    with pytest.raises(applier.ApplyError):
        applier.extract_changes(_plan([record]), expected_count=1)


def test_extract_changes_rejects_duplicate_ids_and_wrong_batch_size():
    duplicated = [_record(1), _record(1)]
    with pytest.raises(applier.ApplyError, match="dupliqué"):
        applier.extract_changes(_plan(duplicated), expected_count=2)
    with pytest.raises(applier.ApplyError, match="lot attendu"):
        applier.extract_changes(_plan([_record(1)]), expected_count=13)


def test_preflight_reads_all_rows_once_and_requires_strict_before_state():
    changes = _changes()
    client = FakeClient(changes)

    live = applier.preflight(client, changes)

    assert set(live) == {change.row_id for change in changes}
    assert client.calls == [("GET", tuple(change.row_id for change in changes))]

    client.state[changes[1].row_id]["new_type"] = ["Unexpected"]
    with pytest.raises(applier.ApplyError, match=changes[1].row_id):
        applier.preflight(client, changes)
    assert all(call[0] == "GET" for call in client.calls)


def test_dry_run_never_patches_or_writes_snapshot(tmp_path):
    changes = _changes()
    snapshot = tmp_path / "before.json"
    client = FakeClient(changes, snapshot_path=snapshot)

    result = applier.execute(
        client,
        changes,
        apply=False,
        snapshot_output=snapshot,
        plan_path=tmp_path / "plan.json",
        plan_sha256="a" * 64,
    )

    assert result["status"] == "dry_run"
    assert not snapshot.exists()
    assert [call[0] for call in client.calls] == ["GET"]


def test_success_snapshots_before_patch_and_strictly_rereads(tmp_path):
    changes = _changes()
    snapshot = tmp_path / "snapshots" / "before.json"
    client = FakeClient(changes, snapshot_path=snapshot)

    result = applier.execute(
        client,
        changes,
        apply=True,
        snapshot_output=snapshot,
        plan_path=tmp_path / "plan.json",
        plan_sha256="b" * 64,
        captured_at="2026-07-15T12:00:00+00:00",
    )

    assert result["status"] == "applied"
    assert [call[0] for call in client.calls] == ["GET", "PATCH", "PATCH", "GET"]
    document = json.loads(snapshot.read_text())
    assert document["source"] == {
        "system": "supabase",
        "environment": "production",
        "schema": "pipeline_manager",
        "table": "conversions",
    }
    assert document["plan"]["sha256"] == "b" * 64
    assert len(document["rows"]) == 2
    assert all(
        client.state[change.row_id]["new_type"] == list(change.after_new_type)
        for change in changes
    )


def test_partial_ambiguous_failure_rolls_back_every_changed_row_and_fails(tmp_path):
    changes = _changes()
    snapshot = tmp_path / "before.json"
    client = FakeClient(
        changes,
        snapshot_path=snapshot,
        fail_after_write_id=changes[1].row_id,
    )

    with pytest.raises(applier.ApplyError, match="rollback complet") as raised:
        applier.execute(
            client,
            changes,
            apply=True,
            snapshot_output=snapshot,
            plan_path=tmp_path / "plan.json",
            plan_sha256="c" * 64,
        )

    assert raised.value.details["rollback"]["complete"] is True
    assert raised.value.details["rollback"]["restored_rows"] == 2
    assert snapshot.exists()
    assert all(
        client.state[change.row_id]["new_type"] == list(change.before_new_type)
        for change in changes
    )
    # Deux PATCH d'application, puis deux PATCH de rollback en ordre inverse.
    assert [call[0] for call in client.calls].count("PATCH") == 4


def test_rollback_restores_raw_null_instead_of_empty_array(tmp_path):
    changes = applier.extract_changes(
        _plan([_record(1, raw_new_type_null=True)]),
        expected_count=1,
    )
    snapshot = tmp_path / "before-null.json"
    client = FakeClient(
        changes,
        snapshot_path=snapshot,
        fail_after_write_id=changes[0].row_id,
    )

    with pytest.raises(applier.ApplyError) as raised:
        applier.execute(
            client,
            changes,
            apply=True,
            snapshot_output=snapshot,
            plan_path=tmp_path / "plan.json",
            plan_sha256="d" * 64,
        )

    assert raised.value.details["rollback"]["complete"] is True
    assert client.state[changes[0].row_id]["new_type"] is None
    assert json.loads(snapshot.read_text())["rows"][0]["before"]["new_type"] is None


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return copy.deepcopy(self.payload)


class RecordingSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def patch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_patch_uses_pipeline_manager_concurrency_and_new_type_only():
    row_id = _row_id(1)
    returned = {
        "id": row_id,
        "type": ["Main conversion"],
        "new_type": ["Leads"],
        "updated_at": "2026-07-15T12:00:00+00:00",
    }
    session = RecordingSession(Response([returned]))
    client = applier.SupabaseConversionsClient(
        "https://project.supabase.co",
        "top-secret",
        session=session,
    )

    assert client.patch_new_type(
        row_id,
        "2026-07-15T10:00:00+00:00",
        ["Leads"],
    ) == returned

    _, kwargs = session.calls[0]
    assert kwargs["json"] == {"new_type": ["Leads"]}
    assert kwargs["params"]["id"] == f"eq.{row_id}"
    assert kwargs["params"]["updated_at"] == "eq.2026-07-15T10:00:00+00:00"
    assert kwargs["headers"]["Accept-Profile"] == "pipeline_manager"
    assert kwargs["headers"]["Content-Profile"] == "pipeline_manager"
    assert kwargs["headers"]["Prefer"] == "return=representation"


def test_atomic_snapshot_refuses_overwrite_and_leaves_no_temp_file(tmp_path):
    output = tmp_path / "nested" / "snapshot.json"
    applier._atomic_write_json({"safe": True}, output)
    assert json.loads(output.read_text()) == {"safe": True}
    assert not list(output.parent.glob("*.tmp"))

    with pytest.raises(applier.ApplyError, match="écraser"):
        applier._atomic_write_json({"safe": False}, output)
    assert json.loads(output.read_text()) == {"safe": True}


class FailingNetworkSession:
    def get(self, *args, **kwargs):
        raise requests.ConnectionError("secret-key at https://secret.supabase.co")


def test_cli_never_logs_credentials_or_supabase_url(monkeypatch, capsys, tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan([_record(index) for index in range(1, 14)])))
    monkeypatch.setattr(
        applier.exporter,
        "load_prod_credentials",
        lambda env_file: ("https://secret.supabase.co", "secret-key"),
    )
    monkeypatch.setattr(applier.requests, "Session", lambda: FailingNetworkSession())

    assert applier.main(["--plan", str(plan_path)]) == 2
    output = capsys.readouterr()
    rendered = output.out + output.err
    assert "secret-key" not in rendered
    assert "secret.supabase.co" not in rendered
    assert "erreur réseau" in rendered
