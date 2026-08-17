#!/usr/bin/env python3
import json
from types import SimpleNamespace
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import migrate_client as mc


def test_redact_sensitive_output_removes_session_identifier():
    raw = (
        "Authenticated successfully. Your session ID is: "
        "01234567-89ab-cdef-0123-456789abcdef\nDashboard OK"
    )
    safe = mc.redact_sensitive_output(raw)
    assert "01234567" not in safe
    assert "session masquée" in safe
    assert "Dashboard OK" in safe


def test_run_step_turns_timeout_into_a_redacted_failure(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise mc.subprocess.TimeoutExpired(
            cmd=["step"],
            timeout=1800,
            output=(
                "Authenticated successfully. Your session ID is: "
                "01234567-89ab-cdef-0123-456789abcdef\nwork in progress"
            ),
        )

    monkeypatch.setattr(mc.subprocess, "run", timeout)
    tail, ok = mc.run_step("step.py", 1, "Client", [], yes=True)
    assert ok is False
    assert "timeout" in tail
    assert "01234567" not in tail


def args(
    *,
    yes=True,
    dashboards="10",
    client="Client A",
    preflight_live=False,
    preflight_output=None,
    clear_account_default=False,
):
    return SimpleNamespace(
        yes=yes,
        preflight_live=preflight_live,
        preflight_output=preflight_output,
        dashboards=dashboards,
        client=client,
        test_collection=999,
        name_prefix="[TEST]",
        clear_account_default=clear_account_default,
    )


def local_preflight(monkeypatch, tracker=None, mapping=None):
    mapping = {0: "Purchases"} if mapping is None else mapping
    monkeypatch.setattr(mc, "load_inputs", lambda: ({"Client A": mapping}, {}))
    monkeypatch.setattr(mc.conv_tracker, "load", lambda: list(tracker or []))


def test_dry_run_never_connects_copies_runs_steps_or_writes(monkeypatch):
    local_preflight(monkeypatch)
    monkeypatch.setattr(
        mc, "connect_resilient", lambda: (_ for _ in ()).throw(AssertionError("connexion interdite"))
    )
    monkeypatch.setattr(
        mc, "connect_read_only", lambda: (_ for _ in ()).throw(AssertionError("connexion interdite"))
    )
    monkeypatch.setattr(
        mc, "run_step", lambda *a, **k: (_ for _ in ()).throw(AssertionError("étape interdite"))
    )
    monkeypatch.setattr(
        mc.conv_tracker, "save", lambda *_: (_ for _ in ()).throw(AssertionError("write interdit"))
    )
    monkeypatch.setattr(
        mc.conv_tracker,
        "render_to_file",
        lambda *_: (_ for _ in ()).throw(AssertionError("write interdit")),
    )

    assert mc.execute(args(yes=False)) == 0


def test_existing_original_is_refused_before_connection(monkeypatch):
    local_preflight(monkeypatch, [{"original_id": "10", "copy_id": 99}])
    monkeypatch.setattr(
        mc, "connect_resilient", lambda: (_ for _ in ()).throw(AssertionError("connexion interdite"))
    )

    assert mc.execute(args()) == 1


def test_all_sources_are_preflighted_before_first_copy(monkeypatch):
    local_preflight(monkeypatch)

    class MB:
        posts = []

        def __init__(self):
            self.gets = []

        def get(self, path):
            self.gets.append(path)
            if path == "/api/dashboard/10":
                return {"id": 10, "name": "ok", "dashcards": []}
            return None

        def post(self, path, **kwargs):
            self.posts.append((path, kwargs))
            raise AssertionError("aucune copie si une source du batch manque")

    mb = MB()
    monkeypatch.setattr(mc, "connect_resilient", lambda: mb)

    assert mc.execute(args(dashboards="10,11")) == 1
    assert mb.posts == []
    assert mb.gets == ["/api/dashboard/10", "/api/dashboard/11"]


def test_pipeline_is_fail_fast_and_never_passes_accept_diffs(monkeypatch):
    local_preflight(monkeypatch)
    saved = []
    calls = []

    class MB:
        def get(self, path):
            return {"id": 10, "name": "source", "dashcards": []}

        def post(self, path, **kwargs):
            return {"id": 110}

    monkeypatch.setattr(mc, "connect_resilient", MB)
    monkeypatch.setattr(mc.conv_tracker, "save", lambda tracker: saved.append([dict(x) for x in tracker]))
    monkeypatch.setattr(mc.conv_tracker, "render_to_file", lambda _tracker: None)

    def fail_second(script, copy_id, client, extra, yes):
        calls.append((script, list(extra), yes))
        return ("ok", True) if len(calls) == 1 else ("valeurs divergentes", False)

    monkeypatch.setattr(mc, "run_step", fail_second)

    assert mc.execute(args()) == 1
    assert len(calls) == 2
    assert all("--accept-diffs" not in extra for _script, extra, _yes in calls)
    assert all(yes is True for _script, _extra, yes in calls)
    assert saved[-1][0]["status"] == "échec"
    assert "migrate_dashboard_reuse.py" in saved[-1][0]["notes"]
    assert "valeurs divergentes" in saved[-1][0]["notes"]


def test_success_is_marked_migrated_only_after_residual_check(monkeypatch):
    local_preflight(monkeypatch)
    saved = []

    class MB:
        def get(self, path):
            return {"id": 10, "name": "source", "dashcards": []}

        def post(self, path, **kwargs):
            return {"id": 110}

    monkeypatch.setattr(mc, "connect_resilient", MB)
    monkeypatch.setattr(mc.conv_tracker, "save", lambda tracker: saved.append([dict(x) for x in tracker]))
    monkeypatch.setattr(mc.conv_tracker, "render_to_file", lambda _tracker: None)
    monkeypatch.setattr(mc, "run_step", lambda *a, **k: ("ok", True))

    def verify_before_promotion(
        _mb,
        _copy,
        _client,
        *,
        require_account_default_cleared=False,
    ):
        # Le tracker doit rester non promu jusqu'à la fin du contrôle Iron Law.
        assert saved[-1][0]["status"] == "en cours"
        assert not any(
            entry.get("status") == "migré"
            for snapshot in saved
            for entry in snapshot
        )
        return True, "pipeline terminé; sans résidu"

    monkeypatch.setattr(mc, "verify_pipeline", verify_before_promotion)

    assert mc.execute(args()) == 0
    assert saved[0][0]["status"] == "en cours"
    assert saved[-1][0]["status"] == "migré"
    assert "sans résidu" in saved[-1][0]["notes"]


def test_residual_is_not_masked_as_success(monkeypatch):
    local_preflight(monkeypatch)
    saved = []

    class MB:
        def get(self, path):
            return {"id": 10, "name": "source", "dashcards": []}

        def post(self, path, **kwargs):
            return {"id": 110}

    monkeypatch.setattr(mc, "connect_resilient", MB)
    monkeypatch.setattr(mc.conv_tracker, "save", lambda tracker: saved.append([dict(x) for x in tracker]))
    monkeypatch.setattr(mc.conv_tracker, "render_to_file", lambda _tracker: None)
    monkeypatch.setattr(mc, "run_step", lambda *a, **k: ("ok", True))
    monkeypatch.setattr(
        mc,
        "verify_pipeline",
        lambda _mb, _copy, _client, **_kwargs: (
            False,
            "résidus ancien système: carte #7",
        ),
    )

    assert mc.execute(args()) == 1
    assert saved[-1][0]["status"] == "résiduel"
    assert "carte #7" in saved[-1][0]["notes"]


def test_clear_account_default_is_forwarded_only_to_the_defaults_step(monkeypatch):
    local_preflight(monkeypatch)
    calls = []

    class MB:
        def get(self, path):
            return {"id": 10, "name": "source", "dashcards": []}

        def post(self, path, **kwargs):
            return {"id": 110}

    monkeypatch.setattr(mc, "connect_resilient", MB)
    monkeypatch.setattr(mc.conv_tracker, "save", lambda _tracker: None)
    monkeypatch.setattr(mc.conv_tracker, "render_to_file", lambda _tracker: None)

    def record_step(script, _copy_id, _client, extra, yes):
        assert yes is True
        calls.append((script, list(extra)))
        return "ok", True

    monkeypatch.setattr(mc, "run_step", record_step)
    monkeypatch.setattr(mc, "verify_pipeline", lambda *_args, **_kwargs: (True, "ok"))

    assert mc.execute(args(clear_account_default=True)) == 0
    assert calls[0] == ("ensure_client_default.py", ["--clear-account-default"])
    assert all(
        "--clear-account-default" not in extra
        for script, extra in calls[1:]
    )


def test_final_verification_can_require_account_default_to_be_cleared():
    class MB:
        def get(self, _path):
            return {
                "parameters": [
                    {"name": "Client", "slug": "client", "default": ["Chilowé"]},
                    {"name": "Account", "slug": "account", "default": ["Wttj"]},
                ],
                "dashcards": [],
            }

    ok, note = mc.verify_pipeline(
        MB(),
        110,
        "Chilowé",
        require_account_default_cleared=True,
    )

    assert ok is False
    assert "défaut Account incorrect" in note


def test_find_residuals_checks_primary_cards_and_series():
    dashboard = {
        "dashcards": [{
            "id": 1,
            "card_id": 10,
            "series": [{"card_id": 11}],
        }]
    }

    class MB:
        def get(self, path):
            card_id = int(path.rsplit("/", 1)[1])
            query = "select CONVERSIONS from x" if card_id == 11 else "select PURCHASES from x"
            return {"id": card_id, "dataset_query": {"type": "native", "native": {"query": query}}}

    assert mc.find_residuals(MB(), dashboard) == [
        "série de dashcard 1: carte #11 (CONVERSIONS)"
    ]


def test_time_filter_qa_rejects_dimension_card_wired_to_temporal_unit():
    dashboard = {
        "parameters": [{
            "id": "time-id",
            "name": "Time period",
            "slug": "time_period",
            "type": "temporal-unit",
        }],
        "dashcards": [{
            "id": 1,
            "card_id": 10,
            "parameter_mappings": [{
                "parameter_id": "time-id",
                "card_id": 10,
                "target": ["dimension", ["template-tag", "time_period"]],
            }],
        }],
    }

    class MB:
        def get(self, _path):
            return {
                "dataset_query": {
                    "type": "native",
                    "native": {
                        "query": "select 1",
                        "template-tags": {"time_period": {"type": "dimension"}},
                    },
                }
            }

    assert mc.find_time_filter_issues(MB(), dashboard) == [
        "dashcard 1: carte #10 type 'dimension' câblée au temporal-unit"
    ]


def test_time_filter_qa_accepts_dashboard_without_time_selector():
    assert mc.find_time_filter_issues(None, {"parameters": [], "dashcards": []}) == []


def native_card(query):
    return {
        "dataset_query": {
            "type": "native",
            "native": {"query": query, "template-tags": {}},
        }
    }


def test_card_coverage_distinguishes_usable_unmapped_and_conflict():
    result = mc.analyze_card_coverage(
        70,
        native_card(
            "SELECT CONVERSIONS, CONVERSIONS_1, CONVERSIONS_2, clicks FROM metrics"
        ),
        {
            0: "Purchases",
            1: mc.conv_lib.UNMAPPED,
            2: mc.conv_lib.CONFLICT,
        },
    )

    states = {item["slot"]: item["mapping"] for item in result["slots"]}
    assert states == {0: "USABLE", 1: "UNMAPPED", 2: "CONFLICT"}
    assert result["coverage_status"] == "PARTIAL_PROVEN"
    assert result["path"] == "SUBSTITUTE_AND_SAFE_DROP"
    assert result["post_fallback_residuals"] == []


def test_card_with_only_unmapped_or_conflicted_slots_is_blocked():
    result = mc.analyze_card_coverage(
        70,
        native_card("SELECT CONVERSIONS_1, CONVERSIONS_2 FROM metrics"),
        {1: mc.conv_lib.UNMAPPED, 2: mc.conv_lib.CONFLICT},
    )

    assert result["coverage_status"] == "BLOCKED"
    assert result["path"] == "NO_USABLE_MAPPING"
    assert result["blocking_reasons"] == [
        "NO_USABLE_MAPPING:CONFLICT",
        "NO_USABLE_MAPPING:UNMAPPED",
    ]


def test_partial_mapping_is_blocked_when_safe_drop_cannot_remove_where_reference():
    result = mc.analyze_card_coverage(
        70,
        native_card(
            "SELECT CONVERSIONS FROM metrics WHERE CONVERSIONS_1 > 0"
        ),
        {0: "Purchases", 1: mc.conv_lib.UNMAPPED},
    )

    assert result["coverage_status"] == "BLOCKED"
    assert result["path"] == "UNSAFE_PARTIAL_DROP"
    assert result["post_fallback_residuals"] == ["CONVERSIONS_1"]


def test_count_only_mapping_cannot_silently_drop_value_column():
    result = mc.analyze_card_coverage(
        70,
        native_card(
            "SELECT CONVERSIONS, CONVERSION_2_VALUE FROM metrics"
        ),
        {0: "Purchases", 2: "Sign ups"},
    )

    assert result["coverage_status"] == "BLOCKED"
    assert result["path"] == "COUNT_ONLY_VALUE"
    assert result["blocking_reasons"] == [
        "COUNT_ONLY_VALUE_NO_TARGET:CONVERSION_2_VALUE"
    ]


def test_special_old_card_is_accessible_but_exempt_from_mapping_gate():
    result = mc.analyze_card_coverage(
        87,
        native_card("SELECT CONVERSIONS_9 FROM metrics"),
        {},
    )

    assert result["coverage_status"] == "SPECIAL"
    assert result["path"] == "DEPLOY_SPECIAL_CARD"
    assert result["blocking_reasons"] == []


def test_opaque_native_card_fails_closed_even_without_visible_slot():
    result = mc.analyze_card_coverage(
        70,
        native_card("SELECT * FROM {{snippet: hidden conversion metrics}}"),
        {0: "Purchases"},
    )

    assert result["coverage_status"] == "BLOCKED"
    assert result["path"] == "OPAQUE_REFERENCE"


def test_preflight_checks_primary_and_series_and_blocks_before_copy_or_tracker_write(monkeypatch):
    local_preflight(
        monkeypatch,
        mapping={0: "Purchases", 1: mc.conv_lib.UNMAPPED},
    )
    saved = []

    class MB:
        def __init__(self):
            self.gets = []
            self.posts = []

        def get(self, path):
            self.gets.append(path)
            if path == "/api/dashboard/10":
                return {
                    "id": 10,
                    "name": "source",
                    "dashcards": [{
                        "id": 1,
                        "card_id": 20,
                        "series": [{"card_id": 21}],
                    }],
                }
            if path == "/api/card/20":
                return native_card("SELECT CONVERSIONS FROM metrics")
            if path == "/api/card/21":
                return None
            raise AssertionError(path)

        def post(self, path, **kwargs):
            self.posts.append((path, kwargs))
            raise AssertionError("copie interdite après préflight bloqué")

    mb = MB()
    monkeypatch.setattr(mc, "connect_resilient", lambda: mb)
    monkeypatch.setattr(mc.conv_tracker, "save", lambda tracker: saved.append(tracker))
    monkeypatch.setattr(mc.conv_tracker, "render_to_file", lambda _tracker: None)

    assert mc.execute(args()) == 1
    assert "/api/card/20" in mb.gets
    assert "/api/card/21" in mb.gets
    assert mb.posts == []
    assert saved == []


def test_preflight_allows_special_primary_but_blocks_positional_series_without_driver():
    source = {
        "id": 10,
        "dashcards": [{
            "id": 1,
            "card_id": 87,
            "series": [{"card_id": 21}],
        }],
    }

    class MB:
        def get(self, path):
            if path == "/api/dashboard/10":
                return source
            if path == "/api/card/87":
                return native_card("SELECT CONVERSIONS_9 FROM metrics")
            if path == "/api/card/21":
                return native_card("SELECT CONVERSIONS, CONVERSIONS_1, clicks FROM metrics")
            raise AssertionError(path)

    sources, diagnostics = mc.preflight_sources(
        MB(), [10], {0: "Purchases", 1: mc.conv_lib.UNMAPPED}
    )

    assert sources == {10: source}
    assert [(item["reference"], item["coverage_status"]) for item in diagnostics] == [
        ("primary", "SPECIAL"),
        ("series", "BLOCKED"),
    ]
    assert diagnostics[1]["path"] == "SERIES_NOT_AUTOMIGRATED"


def test_preflight_proves_safe_partial_path_for_primary_card():
    source = {"id": 10, "dashcards": [{"id": 1, "card_id": 20}]}

    class MB:
        def get(self, path):
            if path == "/api/dashboard/10":
                return source
            if path == "/api/card/20":
                return native_card("SELECT CONVERSIONS, CONVERSIONS_1, clicks FROM metrics")
            raise AssertionError(path)

    _sources, diagnostics = mc.preflight_sources(
        MB(), [10], {0: "Purchases", 1: mc.conv_lib.UNMAPPED}
    )

    assert diagnostics[0]["coverage_status"] == "PARTIAL_PROVEN"
    assert diagnostics[0]["path"] == "SUBSTITUTE_AND_SAFE_DROP"


def test_read_only_connector_uses_existing_session_without_credentials(monkeypatch):
    calls = []
    monkeypatch.setattr(mc, "_load_env", lambda: {
        "METABASE_DOMAIN": "https://metabase.example",
        "METABASE_SESSION_ID": "existing-session",
        "METABASE_EMAIL": "must-not-be-used@example.com",
        "METABASE_PASSWORD": "must-not-be-used",
    })
    monkeypatch.setattr(mc, "Metabase_API", lambda **kwargs: calls.append(kwargs) or "mb")

    connection, mode = mc.connect_read_only()
    assert isinstance(connection, mc.GetOnlyMetabase)
    assert connection._client == "mb"
    assert mode == "existing_session"
    assert calls == [{
        "domain": "https://metabase.example",
        "session_id": "existing-session",
    }]


def test_read_only_connector_falls_back_to_standard_auth_and_hides_session_output(
    monkeypatch, capsys
):
    standard_client = SimpleNamespace(get=lambda path: {"path": path})
    fallback_calls = []
    monkeypatch.setattr(mc, "_load_env", lambda: {
        "METABASE_DOMAIN": "https://metabase.example",
        "METABASE_SESSION_ID": "",
    })

    def standard_auth():
        fallback_calls.append(True)
        print("Authenticated successfully. Your session ID is: DO-NOT-EXPOSE")
        return standard_client

    monkeypatch.setattr(mc, "connect_resilient", standard_auth)

    connection, mode = mc.connect_read_only()

    assert mode == "credential_fallback"
    assert fallback_calls == [True]
    assert capsys.readouterr().out == ""
    assert connection.get("/api/dashboard/10") == {"path": "/api/dashboard/10"}
    assert not hasattr(connection, "post")
    assert not hasattr(connection, "put")


def test_read_only_connector_falls_back_when_existing_session_is_expired(monkeypatch):
    attempts = []
    standard_client = SimpleNamespace(get=lambda _path: {})
    monkeypatch.setattr(mc, "_load_env", lambda: {
        "METABASE_DOMAIN": "https://metabase.example",
        "METABASE_SESSION_ID": "expired-session",
    })

    def expired_session(**kwargs):
        attempts.append(kwargs)
        raise RuntimeError("expired")

    monkeypatch.setattr(mc, "Metabase_API", expired_session)
    monkeypatch.setattr(mc, "connect_resilient", lambda: standard_client)

    connection, mode = mc.connect_read_only()

    assert attempts == [{
        "domain": "https://metabase.example",
        "session_id": "expired-session",
    }]
    assert connection._client is standard_client
    assert mode == "credential_fallback"


def test_get_only_facade_uses_authenticated_http_session_without_revalidation():
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

    class Client:
        domain = "https://metabase.example"
        header = {"X-Metabase-Session": "redacted"}

        def __init__(self):
            self._http = Http()

        def get(self, *_args, **_kwargs):
            raise AssertionError("aucune revalidation /api/user/current attendue")

    client = Client()
    facade = mc.GetOnlyMetabase(client)

    assert facade.get("/api/dashboard/10", timeout=60) == {"id": 10}
    assert client._http.calls == [(
        "https://metabase.example/api/dashboard/10",
        {"headers": client.header, "timeout": 60},
    )]


def test_preflight_live_ready_uses_gets_only_and_never_touches_tracker(monkeypatch, capsys):
    local_preflight(monkeypatch)

    class ReadOnlyMB:
        def __init__(self):
            self.gets = []

        def get(self, path):
            self.gets.append(path)
            if path == "/api/dashboard/10":
                return {"id": 10, "dashcards": []}
            raise AssertionError(path)

        def post(self, *_args, **_kwargs):
            raise AssertionError("POST interdit en preflight-live")

        def put(self, *_args, **_kwargs):
            raise AssertionError("PUT interdit en preflight-live")

    mb = ReadOnlyMB()
    monkeypatch.setattr(mc, "connect_read_only", lambda: (mb, "existing_session"))
    monkeypatch.setattr(
        mc, "connect_resilient", lambda: (_ for _ in ()).throw(AssertionError("mauvais connecteur"))
    )
    monkeypatch.setattr(
        mc.conv_tracker, "load", lambda: (_ for _ in ()).throw(AssertionError("tracker interdit"))
    )
    monkeypatch.setattr(
        mc.conv_tracker, "save", lambda *_: (_ for _ in ()).throw(AssertionError("tracker interdit"))
    )

    assert mc.execute(args(yes=False, preflight_live=True)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["result"] == "READY"
    assert report["authentication_mode"] == "existing_session"
    assert report["originals"] == [10]
    assert mb.gets == ["/api/dashboard/10"]


def test_preflight_live_blocked_writes_deterministic_local_report_without_mutation(
    monkeypatch, tmp_path, capsys
):
    local_preflight(monkeypatch)
    output = tmp_path / "nested" / "report.json"

    class ReadOnlyMB:
        def __init__(self):
            self.gets = []

        def get(self, path):
            self.gets.append(path)
            if path == "/api/dashboard/10":
                return {"id": 10, "dashcards": [{"id": 1, "card_id": 20}]}
            if path == "/api/card/20":
                return None
            raise AssertionError(path)

        def post(self, *_args, **_kwargs):
            raise AssertionError("POST interdit")

        def put(self, *_args, **_kwargs):
            raise AssertionError("PUT interdit")

    mb = ReadOnlyMB()
    monkeypatch.setattr(mc, "connect_read_only", lambda: (mb, "credential_fallback"))
    monkeypatch.setattr(
        mc.conv_tracker, "load", lambda: (_ for _ in ()).throw(AssertionError("tracker interdit"))
    )
    monkeypatch.setattr(
        mc.conv_tracker, "save", lambda *_: (_ for _ in ()).throw(AssertionError("tracker interdit"))
    )

    assert mc.execute(args(
        yes=False,
        preflight_live=True,
        preflight_output=str(output),
    )) == 1
    printed = capsys.readouterr()
    report = json.loads(printed.out)
    assert report["result"] == "BLOCKED"
    assert report["authentication_mode"] == "credential_fallback"
    assert report["summary"]["blocked_references"] == 1
    assert output.read_text() == mc.serialize_preflight_report(report)
    assert mb.gets == ["/api/dashboard/10", "/api/card/20"]


def test_preflight_report_order_and_serialization_are_deterministic():
    diagnostics = [
        {"dashboard_id": 2, "dashcard_id": 9, "reference": "series", "card_id": 8,
         "coverage_status": "PROVEN", "slots": [], "old_columns": []},
        {"dashboard_id": 1, "dashcard_id": 7, "reference": "primary", "card_id": 6,
         "coverage_status": "PROVEN", "slots": [], "old_columns": []},
    ]
    first = mc.serialize_preflight_report(
        mc.build_preflight_report("Client A", [2, 1], diagnostics)
    )
    second = mc.serialize_preflight_report(
        mc.build_preflight_report("Client A", [2, 1], list(reversed(diagnostics)))
    )

    assert first == second
    report = json.loads(first)
    assert [item["dashboard_id"] for item in report["diagnostics"]] == [1, 2]


def test_cli_rejects_yes_and_preflight_live_together():
    import pytest

    with pytest.raises(SystemExit) as exc:
        mc.build_parser().parse_args([
            "--client", "Client A",
            "--dashboards", "10",
            "--yes",
            "--preflight-live",
        ])
    assert exc.value.code == 2


def test_cli_uses_current_staging_collection_by_default():
    parsed = mc.build_parser().parse_args([
        "--client", "Client A",
        "--dashboards", "10",
    ])

    assert parsed.test_collection == 14016


def test_preflight_output_without_live_mode_is_rejected_before_any_write(monkeypatch, tmp_path):
    target = tmp_path / "must-not-exist.json"
    monkeypatch.setattr(
        mc, "load_inputs", lambda: (_ for _ in ()).throw(AssertionError("validation doit être immédiate"))
    )

    assert mc.execute(args(
        yes=False,
        preflight_output=str(target),
    )) == 2
    assert not target.exists()
