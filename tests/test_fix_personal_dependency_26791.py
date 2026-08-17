from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest


REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import fix_personal_dependency_26791 as fix  # noqa: E402


TAGS = tuple(fix.EXPECTED_WIRED_PARAMETER_SPECS)
SOURCE_ONLY_TAGS = ("account_name", "exclude_industry_clients", "industry", "model")
CARD_TAGS = (*TAGS, fix.VALUE_TIME_TAG, *SOURCE_ONLY_TAGS)


class RawResponse:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self):
        return deepcopy(self._body)


def card(card_id=fix.SOURCE_CARD_ID, collection_id=fix.SOURCE_COLLECTION_ID):
    field_ids = {
        "clients": 392829,
        "date": 426427,
        "channel": 396835,
        "campaign_type": 396838,
        "campaign_category": 396842,
        fix.VALUE_TIME_TAG: 392847,
        "account_name": 396648,
        "exclude_industry_clients": 392829,
        "industry": 472655,
        "model": 472654,
    }
    tags = {
        tag: {
            "name": tag,
            "type": "dimension",
            "widget-type": "string/=",
            "dimension": [
                "field",
                {
                    "base-type": "type/Date" if tag == "date" else "type/Text",
                    "effective-type": (
                        "type/Date" if tag == "date" else "type/Text"
                    ),
                },
                field_ids[tag],
            ],
        }
        for tag in CARD_TAGS
    }
    tags[fix.VALUE_TIME_TAG].update({
        "type": "dimension",
        "widget-type": "category",
        "default": ["week"],
    })
    sql = "SELECT date, ctr FROM benchmark WHERE {{clients}}"
    legacy_tags = deepcopy(tags)
    for tag in legacy_tags.values():
        tag["dimension"] = ["field", tag["dimension"][2], None]
    return {
        "id": card_id,
        "name": "Ctr | client vs industry vs global (benchmark)",
        "description": "benchmark CTR",
        "collection_id": collection_id,
        "archived": False,
        "dataset_query": {
            "lib/type": "mbql/query",
            "lib.convert/converted?": True,
            "database": fix.EXPECTED_DATABASE_ID,
            "stages": [{
                "lib/type": "mbql.stage/native",
                "native": sql,
                "template-tags": tags,
            }],
        },
        "legacy_query": json.dumps({
            "type": "native",
            "database": fix.EXPECTED_DATABASE_ID,
            "native": {"query": sql, "template-tags": legacy_tags},
        }),
        "display": "line",
        "database_id": fix.EXPECTED_DATABASE_ID,
        "visualization_settings": {
            "graph.dimensions": ["DATE"],
            "graph.metrics": ["CTR"],
        },
        "result_metadata": [
            {"name": "DATE", "base_type": "type/Date", "display_name": "DATE"},
            {"name": "CTR", "base_type": "type/Float", "display_name": "CTR"},
        ],
        "parameters": [],
        "parameter_mappings": [],
        "cache_ttl": None,
        # Champs serveur qui ne doivent jamais traverser POST /api/card.
        "creator_id": 30,
        "entity_id": "server-only",
        "public_uuid": "do-not-copy",
        "enable_embedding": True,
        "moderation_reviews": [{"id": 7}],
        "updated_at": "volatile",
        "collection": {"id": collection_id},
    }


def dashboard(card_id=fix.SOURCE_CARD_ID):
    defaults = {
        "clients": [fix.EXPECTED_CLIENT],
        "date": "past30days",
        "channel": ["google", "microsoft"],
        "campaign_type": None,
        "campaign_category": None,
    }
    parameters = [
        {
            "id": fix.EXPECTED_WIRED_PARAMETER_SPECS[tag]["parameter_id"],
            "name": tag,
            "slug": fix.EXPECTED_WIRED_PARAMETER_SPECS[tag]["slug"],
            "type": "date/all-options" if tag == "date" else "category",
            "default": defaults[tag],
        }
        for tag in TAGS
    ]
    mappings = [
        {
            "parameter_id": fix.EXPECTED_WIRED_PARAMETER_SPECS[tag]["parameter_id"],
            "card_id": card_id,
            "target": ["dimension", ["template-tag", tag]],
        }
        for tag in TAGS
    ]
    return {
        "id": fix.DASHBOARD_ID,
        "name": "SEA Global Overview (Google & Microsoft) Template - Inoui",
        "description": "copy",
        "collection_id": 14016,
        "archived": False,
        "parameters": parameters,
        "tabs": [{"id": 900, "name": "Overview"}],
        "width": "fixed",
        "auto_apply_filters": True,
        "dashcards": [
            {
                "id": fix.DASHCARD_ID,
                "card_id": card_id,
                "row": 0,
                "col": 0,
                "size_x": 12,
                "size_y": 8,
                "dashboard_tab_id": 900,
                "series": [],
                "parameter_mappings": mappings,
                "visualization_settings": {"card.title": "CTR benchmark"},
                "inline_parameters": [],
                "action_id": None,
                "card": {"id": card_id, "server": "not written"},
                "entity_id": "server-only-dashcard",
            },
            {
                "id": 136041,
                "card_id": 700,
                "row": 8,
                "col": 0,
                "size_x": 12,
                "size_y": 5,
                "dashboard_tab_id": 900,
                "series": [{"id": 701, "name": "server-expanded"}],
                "parameter_mappings": [],
                "visualization_settings": {},
                "inline_parameters": [],
                "action_id": None,
            },
        ],
    }


def query_body(value=0.123):
    return {
        "status": "completed",
        "data": {
            "cols": [
                {
                    "name": "DATE",
                    "display_name": "DATE",
                    "base_type": "type/Date",
                    "effective_type": "type/Date",
                    "semantic_type": None,
                    "source": "native",
                    "field_ref": ["field", "DATE", {"base-type": "type/Date"}],
                },
                {
                    "name": "CTR",
                    "display_name": "CTR",
                    "base_type": "type/Float",
                    "effective_type": "type/Float",
                    "semantic_type": None,
                    "source": "native",
                    "field_ref": ["field", "CTR", {"base-type": "type/Float"}],
                },
            ],
            "rows": [["2026-07-14", value]],
        },
    }


class FakeMetabase:
    def __init__(self):
        self.source = card()
        self.dashboard = dashboard()
        self.original_dashboard = dashboard()
        self.original_dashboard["id"] = fix.ORIGINAL_DASHBOARD_ID
        self.cards = {fix.SOURCE_CARD_ID: self.source}
        self.post_calls = []
        self.put_calls = []
        self.next_card_id = 60001
        self.query_values = {
            fix.SOURCE_CARD_ID: 0.123,
            self.next_card_id: 0.123,
        }
        self.source_query_values = []
        self.diverge_dashboard_reread = False

    def get(self, endpoint, timeout=None):
        if endpoint == f"/api/dashboard/{fix.DASHBOARD_ID}":
            value = deepcopy(self.dashboard)
            if self.diverge_dashboard_reread:
                value["dashcards"][1]["row"] = 99
            return value
        if endpoint == f"/api/dashboard/{fix.ORIGINAL_DASHBOARD_ID}":
            return deepcopy(self.original_dashboard)
        if endpoint == f"/api/collection/{fix.SOURCE_COLLECTION_ID}":
            return {
                "id": fix.SOURCE_COLLECTION_ID,
                "is_personal": True,
                "personal_owner_id": 30,
                "archived": False,
            }
        if endpoint == f"/api/collection/{fix.TARGET_COLLECTION_ID}":
            return {
                "id": fix.TARGET_COLLECTION_ID,
                "is_personal": False,
                "personal_owner_id": None,
                "archived": False,
            }
        if endpoint.startswith(
            f"/api/collection/{fix.TARGET_COLLECTION_ID}/items?models=card"
        ):
            rows = [
                {"id": cid, "name": item.get("name")}
                for cid, item in sorted(self.cards.items())
                if item.get("collection_id") == fix.TARGET_COLLECTION_ID
            ]
            return {"data": rows, "total": len(rows)}
        if endpoint.startswith("/api/card/") and endpoint.endswith("/dashboards"):
            card_id = int(endpoint.split("/")[3])
            uses = []
            for dashcard in self.dashboard["dashcards"]:
                ids = [dashcard.get("card_id")]
                ids.extend(
                    mapping.get("card_id")
                    for mapping in dashcard.get("parameter_mappings") or []
                )
                if card_id in ids:
                    uses.append({"id": fix.DASHBOARD_ID})
                    break
            return uses
        if endpoint.startswith("/api/card/"):
            card_id = int(endpoint.rsplit("/", 1)[1])
            return deepcopy(self.cards.get(card_id))
        raise AssertionError(f"GET inattendu: {endpoint}")

    def post(self, endpoint, mode, json, timeout=None):
        self.post_calls.append((endpoint, mode, deepcopy(json), timeout))
        if endpoint == "/api/card":
            clone = deepcopy(json)
            clone.update({"id": self.next_card_id, "archived": False})
            self.cards[self.next_card_id] = clone
            return RawResponse(200, {"id": self.next_card_id})
        if endpoint.startswith("/api/card/") and endpoint.endswith("/query"):
            card_id = int(endpoint.split("/")[3])
            parameters = json.get("parameters")
            if not isinstance(parameters, list):
                return RawResponse(200, {"status": "failed", "error": "params absent"})
            by_target = {}
            for parameter in parameters:
                try:
                    tag = parameter["target"][1][1]
                except Exception:
                    return RawResponse(200, {"status": "failed", "error": "target invalide"})
                by_target[tag] = parameter
            if (
                by_target.get("clients", {}).get("value") != [fix.EXPECTED_CLIENT]
                or by_target.get("date", {}).get("value") != fix.VALUE_WINDOW
                or by_target.get("channel", {}).get("value")
                != ["google", "microsoft"]
                or by_target.get(fix.VALUE_TIME_TAG, {}).get("value") != ["week"]
                or by_target.get(fix.VALUE_TIME_TAG, {}).get("type") != "category"
            ):
                return RawResponse(200, {"status": "failed", "error": "params incorrects"})
            if card_id == fix.SOURCE_CARD_ID and self.source_query_values:
                value = self.source_query_values.pop(0)
            else:
                value = self.query_values[card_id]
            body = (
                {"status": "completed", "data": {"cols": query_body()["data"]["cols"], "rows": []}}
                if value == "EMPTY"
                else query_body(value)
            )
            return RawResponse(200, body)
        raise AssertionError(f"POST inattendu: {endpoint}")

    def put(self, endpoint, mode, json, timeout=None):
        self.put_calls.append((endpoint, mode, deepcopy(json), timeout))
        if endpoint == f"/api/dashboard/{fix.DASHBOARD_ID}":
            self.dashboard["dashcards"] = deepcopy(json["dashcards"])
            if "tabs" in json:
                self.dashboard["tabs"] = deepcopy(json["tabs"])
            return RawResponse(200, {})
        if endpoint.startswith("/api/card/"):
            card_id = int(endpoint.rsplit("/", 1)[1])
            self.cards[card_id].update(deepcopy(json))
            return RawResponse(200, {})
        raise AssertionError(f"PUT inattendu: {endpoint}")


def test_clone_payload_is_strictly_allowlisted_and_targets_shared_collection():
    source = card()
    payload = fix.build_clone_payload(source)

    assert set(payload) == set(fix.CARD_CREATE_FIELDS) | {"collection_id"}
    assert payload["collection_id"] == fix.TARGET_COLLECTION_ID
    for forbidden in (
        "id",
        "creator_id",
        "entity_id",
        "public_uuid",
        "enable_embedding",
        "moderation_reviews",
        "updated_at",
        "collection",
    ):
        assert forbidden not in payload
    assert payload["dataset_query"] == source["dataset_query"]
    assert payload["result_metadata"] == source["result_metadata"]


def test_preflight_and_prepared_dashboard_have_exactly_six_allowed_leaf_changes():
    mb = FakeMetabase()
    preflight = fix.build_preflight(mb)
    prepared = fix.prepare_dashboard(preflight["dashboard"], 60001)

    assert sorted(
        fix._diff_paths(
            fix.dashboard_rewire_state(preflight["dashboard"]),
            fix.dashboard_rewire_state(prepared),
        )
    ) == sorted(fix.expected_dashboard_diff_paths())
    target = next(
        dc for dc in prepared["dashcards"] if dc["id"] == fix.DASHCARD_ID
    )
    assert target["card_id"] == 60001
    assert [m["card_id"] for m in target["parameter_mappings"]] == [60001] * 5
    assert prepared["dashcards"][1] == preflight["dashboard"]["dashcards"][1]


def test_preflight_refuses_mapping_count_or_reference_outside_exact_topology():
    mb = FakeMetabase()
    mb.dashboard["dashcards"][0]["parameter_mappings"].pop()
    with pytest.raises(fix.RepairError, match="5 mappings attendus"):
        fix.build_preflight(mb)

    mb = FakeMetabase()
    mb.dashboard["dashcards"][1]["series"].append({"id": fix.SOURCE_CARD_ID})
    with pytest.raises(fix.RepairError, match="références.*hors cible"):
        fix.build_preflight(mb)

    mb = FakeMetabase()
    mb.dashboard["dashcards"][1]["series"] = [{"name": "id missing"}]
    with pytest.raises(fix.RepairError, match="id absent ou ambigu"):
        fix.build_preflight(mb)

    mb = FakeMetabase()
    mb.dashboard["dashcards"][0]["parameter_mappings"][0]["parameter_id"] = "wrong"
    with pytest.raises(fix.RepairError, match="ids de paramètres inattendus"):
        fix.build_preflight(mb)

    mb = FakeMetabase()
    mb.dashboard["parameters"][0]["slug"] = "clients"
    with pytest.raises(fix.RepairError, match="slug.*attendu"):
        fix.build_preflight(mb)


def test_dry_run_performs_no_post_put_or_snapshot(tmp_path):
    mb = FakeMetabase()
    report = fix.execute(mb, yes=False, snapshot_dir=tmp_path)

    assert report["mode"] == "DRY_RUN"
    assert report["status"] == "READY"
    assert report["mapping_count"] == 5
    assert mb.post_calls == []
    assert mb.put_calls == []
    assert list(tmp_path.iterdir()) == []


def test_apply_refuses_an_existing_operation_lock_before_any_live_mutation(tmp_path):
    mb = FakeMetabase()
    lock = tmp_path / ".fix-personal-dependency-26791.lock"
    lock.write_text("another run")

    with pytest.raises(fix.RepairError, match="autre réparation"):
        fix.execute(
            mb,
            yes=True,
            snapshot_dir=tmp_path,
            lock_directory=tmp_path,
        )

    assert mb.post_calls == []
    assert mb.put_calls == []
    assert lock.read_text() == "another run"


def test_clone_verification_is_fail_closed_on_metadata_or_sql_divergence():
    source = card()
    clone = card(60001, fix.TARGET_COLLECTION_ID)
    fix.validate_clone(source, clone, 60001)

    clone["result_metadata"][1]["base_type"] = "type/Text"
    with pytest.raises(fix.RepairError, match="structure/métadonnées divergentes"):
        fix.validate_clone(source, clone, 60001)

    clone = card(60001, fix.TARGET_COLLECTION_ID)
    clone["dataset_query"]["stages"][0]["native"] += " -- changed"
    with pytest.raises(fix.RepairError, match="structure/métadonnées divergentes"):
        fix.validate_clone(source, clone, 60001)


def test_clone_pair_accepts_only_observed_metabase_post_reserialization():
    source = card()
    clone = deepcopy(source)
    clone["id"] = 60001
    clone["collection_id"] = fix.TARGET_COLLECTION_ID
    # Forme réellement observée après POST: le champ serveur legacy n'est pas copié,
    # le marqueur converted disparaît et Metabase réhydrate les annotations de dimension.
    clone["legacy_query"] = None
    clone["dataset_query"].pop("lib.convert/converted?")
    clone["dataset_query"]["lib/uuid"] = "clone-query"
    clone_tags = clone["dataset_query"]["stages"][0]["template-tags"]
    for index, tag in enumerate(clone_tags.values()):
        metadata = tag["dimension"][1]
        metadata["lib/uuid"] = f"clone-field-{index}"
        metadata["lib/transformation-added-base-type"] = True
    original = deepcopy(source)
    source_guard = fix.source_guard_state(source)

    fix.validate_clone(source, clone, 60001)
    assert source == original
    assert fix.source_guard_state(source) == source_guard
    assert fix.card_functional_state(source) != fix.card_functional_state(clone)
    source_pair, clone_pair = fix.clone_comparison_functional_states(source, clone)
    assert source_pair == clone_pair

    changed = deepcopy(clone)
    changed["dataset_query"]["stages"][0]["template-tags"]["clients"][
        "dimension"
    ][2] = 7
    with pytest.raises(fix.RepairError, match="structure/métadonnées divergentes"):
        fix.validate_clone(source, changed, 60001)

    changed = deepcopy(clone)
    changed["dataset_query"]["stages"][0]["template-tags"]["clients"][
        "dimension"
    ][1]["lib/transformation-added-base-type"] = False
    with pytest.raises(fix.RepairError, match="structure/métadonnées divergentes"):
        fix.validate_clone(source, changed, 60001)

    changed = deepcopy(clone)
    changed["dataset_query"]["lib.convert/converted?"] = False
    with pytest.raises(fix.RepairError, match="marqueur converted invalide"):
        fix.validate_clone(source, changed, 60001)

    outside_scope = deepcopy(clone)
    outside_scope["collection_id"] = 999
    with pytest.raises(fix.RepairError, match="collection attendue"):
        fix.validate_clone(source, outside_scope, 60001)

    changed_source = deepcopy(source)
    changed_source["dataset_query"].pop("lib.convert/converted?")
    assert fix.source_guard_state(changed_source) != source_guard

    changed_source = deepcopy(source)
    changed_source["dataset_query"]["stages"][0]["template-tags"]["clients"][
        "dimension"
    ][1]["lib/transformation-added-base-type"] = True
    assert fix.source_guard_state(changed_source) != source_guard


def test_value_guard_requires_three_equal_non_empty_results():
    mb = FakeMetabase()
    result = fix.verify_value_equivalence(
        mb, mb.next_card_id, mb.dashboard, mb.source
    )
    assert result["status"] == "IDENTICAL_STABLE_NON_EMPTY"
    assert result["row_count"] == 1
    assert [call[0] for call in mb.post_calls] == [
        f"/api/card/{fix.SOURCE_CARD_ID}/query",
        f"/api/card/{mb.next_card_id}/query",
        f"/api/card/{fix.SOURCE_CARD_ID}/query",
    ]
    sent_parameters = [call[2]["parameters"] for call in mb.post_calls]
    assert sent_parameters[0] == sent_parameters[1] == sent_parameters[2]
    targets = {
        parameter["target"][1][1]: parameter["value"]
        for parameter in sent_parameters[0]
    }
    assert targets["clients"] == [fix.EXPECTED_CLIENT]
    assert targets["date"] == fix.VALUE_WINDOW
    assert targets[fix.VALUE_TIME_TAG] == ["week"]
    time_parameter = next(
        parameter
        for parameter in sent_parameters[0]
        if parameter["target"][1][1] == fix.VALUE_TIME_TAG
    )
    assert time_parameter == {
        "type": "category",
        "value": ["week"],
        "target": ["dimension", ["template-tag", fix.VALUE_TIME_TAG]],
    }

    mb = FakeMetabase()
    mb.query_values[mb.next_card_id] = 0.999
    with pytest.raises(fix.RepairError, match="clone différent"):
        fix.verify_value_equivalence(
            mb, mb.next_card_id, mb.dashboard, mb.source
        )

    mb = FakeMetabase()
    mb.source_query_values = [0.123, 0.124]
    with pytest.raises(fix.RepairError, match="source instable"):
        fix.verify_value_equivalence(
            mb, mb.next_card_id, mb.dashboard, mb.source
        )

    mb = FakeMetabase()
    mb.source_query_values = ["EMPTY"]
    with pytest.raises(fix.RepairError, match="résultat vide"):
        fix.verify_value_equivalence(
            mb, mb.next_card_id, mb.dashboard, mb.source
        )


def test_query_result_accepts_completed_http_202_but_rejects_non_terminal_body():
    assert fix._query_result(
        RawResponse(202, query_body()), "source"
    )["rows"] == [["2026-07-14", 0.123]]

    with pytest.raises(fix.RepairError, match="requête non terminée"):
        fix._query_result(
            RawResponse(202, {"status": "running"}), "source"
        )

    with pytest.raises(fix.RepairError, match="requête HTTP 503"):
        fix._query_result(RawResponse(503, query_body()), "source")


def test_success_snapshots_before_create_then_rewires_and_verifies(tmp_path):
    mb = FakeMetabase()
    events = []
    original_post = mb.post

    def post(endpoint, mode, json, timeout=None):
        if endpoint == "/api/card":
            assert len(list(tmp_path.glob("*.json"))) == 1
            events.append("snapshot-before-create")
        return original_post(endpoint, mode, json, timeout)

    mb.post = post

    def verifier(_mb, dashboard_id, client):
        assert dashboard_id == fix.DASHBOARD_ID
        assert client == fix.EXPECTED_CLIENT
        events.append("verify_pipeline")
        return True, "pipeline terminé; contrôle final sans résidu"

    report = fix.execute(
        mb,
        yes=True,
        snapshot_dir=tmp_path,
        lock_directory=tmp_path,
        verifier=verifier,
    )

    assert report["status"] == "APPLIED"
    assert report["clone_id"] == mb.next_card_id
    assert events == ["snapshot-before-create", "verify_pipeline"]
    target = next(
        dc for dc in mb.dashboard["dashcards"] if dc["id"] == fix.DASHCARD_ID
    )
    assert target["card_id"] == mb.next_card_id
    assert [m["card_id"] for m in target["parameter_mappings"]] == [
        mb.next_card_id
    ] * 5
    assert mb.cards[fix.SOURCE_CARD_ID]["archived"] is False
    assert mb.cards[mb.next_card_id]["archived"] is False
    snapshot = json.loads(Path(report["snapshot"]).read_text())
    assert snapshot["status"] == "COMMITTED"
    assert snapshot["value_guard"]["status"] == "IDENTICAL_STABLE_NON_EMPTY"
    assert snapshot["source_card"]["id"] == fix.SOURCE_CARD_ID
    card_create = next(call for call in mb.post_calls if call[0] == "/api/card")
    assert set(card_create[2]) == set(fix.CARD_CREATE_FIELDS) | {"collection_id"}
    dashboard_put = next(
        call for call in mb.put_calls
        if call[0] == f"/api/dashboard/{fix.DASHBOARD_ID}"
    )
    untouched_series = next(
        dashcard["series"]
        for dashcard in dashboard_put[2]["dashcards"]
        if dashcard["id"] == 136041
    )
    assert untouched_series == [{"id": 701}]
    assert "name" not in untouched_series[0]


def test_value_failure_archives_orphan_without_touching_dashboard(tmp_path):
    mb = FakeMetabase()
    before = deepcopy(mb.dashboard)
    mb.query_values[mb.next_card_id] = 9.9

    with pytest.raises(fix.RepairTransactionError) as exc_info:
        fix.execute(
            mb,
            yes=True,
            snapshot_dir=tmp_path,
            lock_directory=tmp_path,
            verifier=lambda *_: (True, "ok"),
        )

    exc = exc_info.value
    assert exc.cleanup["dashboard"]["status"] == "NOT_ATTEMPTED"
    assert exc.cleanup["clone"]["status"] == "ARCHIVED_ORPHAN"
    assert fix.dashboard_rewire_state(mb.dashboard) == fix.dashboard_rewire_state(before)
    assert mb.cards[mb.next_card_id]["archived"] is True
    snapshot = json.loads(exc.snapshot_path.read_text())
    assert snapshot["status"] == "ROLLED_BACK"
    assert "résultat clone différent" in snapshot["failure"]


def test_verify_pipeline_failure_rolls_back_dashboard_and_archives_clone(tmp_path):
    mb = FakeMetabase()
    before = deepcopy(mb.dashboard)

    with pytest.raises(fix.RepairTransactionError) as exc_info:
        fix.execute(
            mb,
            yes=True,
            snapshot_dir=tmp_path,
            lock_directory=tmp_path,
            verifier=lambda *_: (False, "pipeline ko"),
        )

    exc = exc_info.value
    assert exc.cleanup["dashboard"]["status"] == "ROLLED_BACK_VERIFIED"
    assert exc.cleanup["clone"]["status"] == "ARCHIVED_ORPHAN"
    assert fix.dashboard_rewire_state(mb.dashboard) == fix.dashboard_rewire_state(before)
    assert mb.cards[mb.next_card_id]["archived"] is True
    dashboard_puts = [
        call for call in mb.put_calls
        if call[0] == f"/api/dashboard/{fix.DASHBOARD_ID}"
    ]
    assert len(dashboard_puts) == 2
    snapshot = json.loads(exc.snapshot_path.read_text())
    assert snapshot["status"] == "ROLLED_BACK"
    assert "verify_pipeline en échec" in snapshot["failure"]


def test_failed_rollback_never_archives_a_still_referenced_clone(tmp_path):
    mb = FakeMetabase()
    original_put = mb.put
    dashboard_put_count = 0

    def put(endpoint, mode, json, timeout=None):
        nonlocal dashboard_put_count
        if endpoint == f"/api/dashboard/{fix.DASHBOARD_ID}":
            dashboard_put_count += 1
            if dashboard_put_count == 2:
                return RawResponse(500, {"error": "rollback failed"})
        return original_put(endpoint, mode, json, timeout)

    mb.put = put
    with pytest.raises(fix.RepairTransactionError) as exc_info:
        fix.execute(
            mb,
            yes=True,
            snapshot_dir=tmp_path,
            lock_directory=tmp_path,
            verifier=lambda *_: (False, "pipeline ko"),
        )

    cleanup = exc_info.value.cleanup
    assert cleanup["dashboard"]["status"] == "ROLLBACK_FAILED"
    assert cleanup["clone"]["status"] == "ARCHIVE_SKIPPED_ROLLBACK_UNVERIFIED"
    assert mb.cards[mb.next_card_id]["archived"] is False
    snapshot = json.loads(exc_info.value.snapshot_path.read_text())
    assert snapshot["status"] == "FAILED_CLEANUP_INCOMPLETE"
