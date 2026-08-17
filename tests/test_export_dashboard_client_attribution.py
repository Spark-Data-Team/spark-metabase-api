import importlib.util
import json
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "export_dashboard_client_attribution.py"
spec = importlib.util.spec_from_file_location("export_dashboard_client_attribution", SCRIPT)
attribution = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(attribution)


def _dashboard(dashboard_id, default_marker=...):
    parameter = {"id": "client-filter", "name": "Client", "slug": "client"}
    if default_marker is not ...:
        parameter["default"] = default_marker
    return {
        "id": dashboard_id,
        "name": f"Dashboard {dashboard_id}",
        "parameters": [parameter],
    }


def test_worklist_is_deduplicated_and_owner_is_never_replaced_by_default():
    calls = []

    def fetch(dashboard_id):
        calls.append(dashboard_id)
        return _dashboard(dashboard_id, ["Figaret"])

    result = attribution.build_attribution(
        {"Canopea": [18438, 18438]},
        fetch,
        source="fixture",
    )

    assert calls == [18438]
    assert result["summary"]["unique_originals"] == 1
    row = result["dashboards"][0]
    assert row["owner_client"] == "Canopea"
    assert row["dashboard_default_clients"] == ["Figaret"]
    assert row["mismatch"] is True
    assert row["unknown"] is False


def test_defaults_are_normalised_and_same_owner_is_a_match():
    result = attribution.build_attribution(
        {"Walter": [10]},
        lambda _: _dashboard(10, [" Walter ", "Walter", {"value": "Walter"}]),
        source="fixture",
    )
    row = result["dashboards"][0]

    assert row["dashboard_default_clients"] == ["Walter"]
    assert row["mismatch"] is False
    assert row["unknown"] is False
    assert row["client_default_observed"] is True


def test_missing_parameter_and_fetch_failure_are_unknown_not_mismatches():
    def fetch(dashboard_id):
        if dashboard_id == 1:
            return {"id": 1, "parameters": []}
        raise TimeoutError("fixture failure")

    result = attribution.build_attribution(
        {"A": [1], "B": [2]},
        fetch,
        source="fixture",
    )
    rows = {row["original_id"]: row for row in result["dashboards"]}

    assert rows[1]["unknown"] is True
    assert rows[1]["unknown_reasons"] == ["dashboard_client_parameter_missing"]
    assert rows[1]["mismatch"] is False
    assert rows[2]["unknown"] is True
    assert rows[2]["unknown_reasons"] == ["dashboard_fetch_failed"]
    assert rows[2]["mismatch"] is False
    assert rows[2]["scope_flags"][0]["details"]["error_type"] == "TimeoutError"


def test_owner_conflict_is_explicit_and_default_does_not_break_the_tie():
    result = attribution.build_attribution(
        {"Client A": [7], "Client B": [7]},
        lambda _: _dashboard(7, ["Client B"]),
        source="fixture",
    )
    row = result["dashboards"][0]

    assert row["owner_client"] is None
    assert row["worklist_owner_clients"] == ["Client A", "Client B"]
    assert row["dashboard_default_clients"] == ["Client B"]
    assert row["unknown"] is True
    assert row["mismatch"] is False
    assert "worklist_owner_conflict" in row["unknown_reasons"]


def test_fixture_cli_is_offline_deterministic_and_writes_atomically(tmp_path):
    worklist = tmp_path / "worklist.json"
    fixture = tmp_path / "dashboards.json"
    output = tmp_path / "attribution.json"
    worklist.write_text(json.dumps({"B": [2], "A": [1]}), encoding="utf-8")
    fixture.write_text(json.dumps({
        "dashboards": [
            _dashboard(2, None),
            _dashboard(1, ["A"]),
        ],
    }), encoding="utf-8")

    assert attribution.main([
        "--worklist", str(worklist),
        "--fixture", str(fixture),
        "--output", str(output),
    ]) == 0
    first_bytes = output.read_bytes()
    first = json.loads(first_bytes)
    assert [row["original_id"] for row in first["dashboards"]] == [1, 2]
    assert first["source"] == "metabase-dashboard-fixture"
    assert not list(tmp_path.glob(f".{output.name}.*.tmp"))

    assert attribution.main([
        "--worklist", str(worklist),
        "--fixture", str(fixture),
        "--output", str(output),
    ]) == 0
    assert output.read_bytes() == first_bytes


def test_malformed_default_is_unknown_and_never_stringified():
    result = attribution.build_attribution(
        {"A": [1]},
        lambda _: _dashboard(1, ["A", {"unexpected": "B"}, 42]),
        source="fixture",
    )
    row = result["dashboards"][0]

    assert row["dashboard_default_clients"] == ["A"]
    assert row["mismatch"] is False
    assert row["unknown"] is True
    assert row["unknown_reasons"] == ["dashboard_default_client_invalid"]
