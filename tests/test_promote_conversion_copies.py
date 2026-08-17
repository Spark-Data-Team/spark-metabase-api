#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import promote_conversion_copies as promo


class Response:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300


class FakeMetabase:
    """Double strictement mémoire; tout endpoint non prévu fait échouer le test."""

    def __init__(self, dashboards, collections, cards=None, items=None):
        self.dashboards = deepcopy(dashboards)
        self.collections = deepcopy(collections)
        self.cards = deepcopy(cards or {})
        self.items = deepcopy(items or {})
        self.get_calls = []
        self.get_kwargs = []
        self.put_calls = []
        self.fail_promotion_copy_id = None
        self.fail_post_read_copy_id = None
        self.failed_post_read_copy_ids = set()
        self.fail_final_read_copy_id = None
        self.promoted_get_counts = {}

    def get(self, endpoint, *args, **kwargs):
        self.get_calls.append(endpoint)
        self.get_kwargs.append(deepcopy(kwargs))
        if endpoint.startswith("/api/dashboard/"):
            dashboard_id = int(endpoint.rsplit("/", 1)[1])
            value = deepcopy(self.dashboards.get(dashboard_id, False))
            promoted = (
                isinstance(value, dict)
                and str(value.get("name") or "").endswith(promo.TARGET_TAG)
                and not str(value.get("name") or "").startswith("[TEST]")
            )
            if promoted:
                self.promoted_get_counts[dashboard_id] = (
                    self.promoted_get_counts.get(dashboard_id, 0) + 1
                )
            if (
                dashboard_id == self.fail_post_read_copy_id
                and dashboard_id not in self.failed_post_read_copy_ids
                and promoted
            ):
                self.failed_post_read_copy_ids.add(dashboard_id)
                value["description"] = "dérive simulée au post-read"
            if (
                dashboard_id == self.fail_final_read_copy_id
                and promoted
                and self.promoted_get_counts[dashboard_id] == 2
            ):
                value["description"] = "dérive simulée à l'audit final"
            return value
        if endpoint.startswith("/api/card/"):
            card_id = int(endpoint.rsplit("/", 1)[1])
            return deepcopy(self.cards.get(card_id, False))
        if endpoint.startswith("/api/collection/") and "/items?" in endpoint:
            token = endpoint.split("/api/collection/", 1)[1].split("/", 1)[0]
            collection_id = None if token == "root" else int(token)
            return {"data": deepcopy(self.items.get(collection_id, [])), "total": len(self.items.get(collection_id, []))}
        if endpoint.startswith("/api/collection/"):
            collection_id = int(endpoint.rsplit("/", 1)[1])
            return deepcopy(self.collections.get(collection_id, False))
        raise AssertionError(f"GET imprévu: {endpoint}")

    def put(self, endpoint, mode, json, **kwargs):
        assert mode == "raw"
        assert kwargs == {"timeout": promo.WRITE_TIMEOUT_SECONDS}
        assert endpoint.startswith("/api/dashboard/")
        dashboard_id = int(endpoint.rsplit("/", 1)[1])
        self.put_calls.append((dashboard_id, deepcopy(json)))
        if (
            dashboard_id == self.fail_promotion_copy_id
            and str(json.get("name") or "").endswith(promo.TARGET_TAG)
            and not str(json.get("name") or "").startswith("[TEST]")
        ):
            return Response(500)
        self.dashboards[dashboard_id]["name"] = json["name"]
        self.dashboards[dashboard_id]["collection_id"] = json["collection_id"]
        return Response(200)


def dashboard(dashboard_id, name, collection_id, *, archived=False, cards=None):
    return {
        "id": dashboard_id,
        "name": name,
        "description": None,
        "collection_id": collection_id,
        "archived": archived,
        "archived_directly": archived,
        "can_write": True,
        "parameters": [],
        "tabs": [],
        "dashcards": [
            {
                "id": dashboard_id * 10 + index,
                "card_id": card_id,
                "row": index,
                "col": 0,
                "size_x": 4,
                "size_y": 3,
                "series": [],
                "parameter_mappings": [],
                "visualization_settings": {},
            }
            for index, card_id in enumerate(cards or [])
        ],
    }


def collection(collection_id, location="/", *, personal=False, archived=False):
    return {
        "id": collection_id,
        "name": f"Collection {collection_id}",
        "location": location,
        "is_personal": personal,
        "personal_owner_id": 42 if personal else None,
        "archived": archived,
    }


def card(card_id, collection_id, *, source=None):
    query = {"query": {"source-table": f"card__{source}"}} if source else {"native": {"query": "SELECT 1"}}
    return {
        "id": card_id,
        "name": f"Card {card_id}",
        "collection_id": collection_id,
        "archived": False,
        "dataset_query": query,
        "visualization_settings": {},
        "display": "scalar",
    }


def converted_legacy_card(
    card_id=501,
    collection_id=300,
    *,
    query_uuid="query-a",
    stage_uuid="stage-a",
    field_uuid="field-a",
):
    value = card(card_id, collection_id)
    value["legacy_query"] = {
        "database": 2,
        "query": {
            "source-table": 42,
            "filter": ["=", ["field", 7, None], "Client A"],
        },
    }
    value["dataset_query"] = {
        "lib/type": "mbql/query",
        "lib/uuid": query_uuid,
        "lib.convert/converted?": True,
        "database": 2,
        "stages": [
            {
                "lib/type": "mbql.stage/mbql",
                "lib/uuid": stage_uuid,
                "tag": "client-filter",
                "field": {
                    "lib/type": "metadata/column",
                    "lib/uuid": field_uuid,
                    "id": 7,
                },
            }
        ],
    }
    return value


def manifest_row(
    original_id,
    copy_id,
    client,
    *,
    roadmap="complete",
    in_scope=True,
    copy_status="single_copy",
    reconciliation="not_applicable",
    tagged=True,
    selection="canonical",
    superseded=None,
):
    copies = [
        {
            "copy_id": copy_id,
            "selection": selection,
            "tagged": tagged,
            "iron_law": {"status": "complete" if roadmap == "complete" else "residual"},
        }
    ]
    copies.extend(
        {
            "copy_id": superseded_id,
            "selection": "superseded",
            "tagged": True,
            "iron_law": {"status": "complete"},
        }
        for superseded_id in superseded or []
    )
    return {
        "original_id": original_id,
        "client": client,
        "owner_client": client,
        "dashboard": f"Dashboard {original_id}",
        "scope": {"in_worklist": in_scope, "worklist_clients": [client] if in_scope else []},
        "roadmap_status": roadmap,
        "iron_law_status": "complete" if roadmap == "complete" else "residual",
        "copy_status": copy_status,
        "copy_reconciliation_status": reconciliation,
        "canonical_copy_id": copy_id,
        "superseded_copy_ids": list(superseded or []),
        "copies": copies,
    }


def accounting_row(original_id, copy_id, client, *, clean=True):
    return {
        "original_id": original_id,
        "copy_id": copy_id,
        "client": client,
        "iron_law_status": "clean" if clean else "residual",
        "causes": [],
        "consultant_slots": [],
        "coverage": [],
        "residual_cards": [] if clean else [{"card_id": 1}],
        "unknown_cards": [],
    }


def fixtures_for(rows):
    manifest = {"schema_version": 1, "dashboards": rows}
    accounting = {
        "source": "test",
        "copies": [accounting_row(row["original_id"], row["canonical_copy_id"], row["client"]) for row in rows],
    }
    decisions = {"schema_version": 1, "decisions": []}
    dashboards = {}
    collections = {150: collection(150, "/14016/")}
    items = {}
    for index, row in enumerate(rows):
        destination = 200 + index
        dashboards[row["original_id"]] = dashboard(row["original_id"], f"Live {row['original_id']}", destination)
        dashboards[row["canonical_copy_id"]] = dashboard(
            row["canonical_copy_id"],
            f"[TEST] {row['original_id']} {promo.TARGET_TAG}",
            150,
        )
        collections[destination] = collection(destination)
        items[destination] = []
    return manifest, accounting, decisions, FakeMetabase(dashboards, collections, items=items)


def verified(*_args, **_kwargs):
    return True, "pipeline terminé; contrôle final sans résidu"


def reason_codes(entry):
    return {reason["code"] for reason in entry["reasons"]}


def test_local_selection_excludes_out_of_scope_residual_and_untagged_without_live_reads():
    rows = [
        manifest_row(1, 101, "A"),
        manifest_row(2, 102, "B", in_scope=False),
        manifest_row(3, 103, "C", roadmap="residual"),
        manifest_row(4, 104, "D", tagged=False),
    ]
    manifest, accounting, decisions, mb = fixtures_for(rows)
    plan = promo.build_promotion_plan(manifest, accounting, decisions, mb, verifier=verified)

    assert plan["summary"] == {"total": 4, "ready": 1, "blocked": 3}
    assert plan["entries"][0]["status"] == "READY"
    assert "OUT_OF_SCOPE" in reason_codes(plan["entries"][1])
    assert "ROADMAP_NOT_COMPLETE" in reason_codes(plan["entries"][2])
    assert "CANONICAL_COPY_NOT_TAGGED" in reason_codes(plan["entries"][3])
    assert not any(call == "/api/dashboard/2" for call in mb.get_calls)
    assert not any(call == "/api/dashboard/103" for call in mb.get_calls)
    assert mb.put_calls == []


def test_multiple_copy_requires_matching_canonical_decision():
    row = manifest_row(
        1,
        101,
        "A",
        copy_status="multiple_copies",
        reconciliation="resolved",
        superseded=[99],
    )
    manifest, accounting, decisions, _mb = fixtures_for([row])
    selected = promo.select_local_entries(manifest, accounting, decisions)
    assert selected[0]["local_status"] == "EXCLUDED"
    assert "CANONICAL_DECISION_MISSING" in reason_codes(selected[0])

    decisions["decisions"] = [
        {"original_id": 1, "canonical_copy_id": 101, "superseded_copy_ids": [99]}
    ]
    selected = promo.select_local_entries(manifest, accounting, decisions)
    assert selected[0]["local_status"] == "SELECTED"


def test_archived_trash_original_requires_explicit_target_collection_override(tmp_path):
    row = manifest_row(1, 101, "A")
    manifest, accounting, decisions, mb = fixtures_for([row])
    mb.dashboards[1]["archived"] = True
    mb.dashboards[1]["archived_directly"] = True
    mb.collections[201] = collection(201)
    mb.items[201] = []

    blocked = promo.build_promotion_plan(manifest, accounting, decisions, mb, verifier=verified)
    assert blocked["entries"][0]["status"] == "BLOCKED"
    assert "ORIGINAL_ARCHIVED_OR_TRASH_REQUIRES_OVERRIDE" in reason_codes(blocked["entries"][0])

    allowed = promo.build_promotion_plan(
        manifest,
        accounting,
        decisions,
        mb,
        verifier=verified,
        target_collection_overrides={1: 201},
    )
    assert allowed["entries"][0]["status"] == "READY"
    assert allowed["entries"][0]["overrides"] == ["target_collection:201"]
    assert allowed["entries"][0]["target_collection_override"] == 201
    assert allowed["entries"][0]["target"]["collection_id"] == 201
    assert mb.put_calls == []

    result = promo.apply_plan(
        mb, allowed, tmp_path / "archived-override-snapshot.json", verifier=verified
    )
    assert result["status"] == "APPLIED"
    assert mb.dashboards[101]["collection_id"] == 201
    assert mb.dashboards[1]["collection_id"] == 200


def test_target_collection_override_is_forbidden_for_active_original():
    row = manifest_row(1, 101, "A")
    manifest, accounting, decisions, mb = fixtures_for([row])
    mb.collections[201] = collection(201)
    mb.items[201] = []

    plan = promo.build_promotion_plan(
        manifest,
        accounting,
        decisions,
        mb,
        verifier=verified,
        target_collection_overrides={1: 201},
    )

    assert plan["entries"][0]["status"] == "BLOCKED"
    assert "TARGET_OVERRIDE_FOR_ACTIVE_ORIGINAL_FORBIDDEN" in reason_codes(
        plan["entries"][0]
    )
    assert mb.put_calls == []


def test_target_collection_override_cli_is_strict_and_rejects_duplicates():
    parser = promo.build_parser()
    parsed = parser.parse_args([
        "--target-collection-override",
        "14511:8280",
        "--target-collection-override",
        "15371:8109",
    ])
    assert promo._target_collection_override_map(
        parsed.target_collection_override
    ) == {14511: 8280, 15371: 8109}

    isolated = parser.parse_args([
        "--yes",
        "--continue-on-error",
        "--only-original",
        "18406",
    ])
    assert isolated.yes is True
    assert isolated.continue_on_error is True
    assert isolated.only_original == [18406]

    with pytest.raises(SystemExit):
        parser.parse_args(["--target-collection-override", "14511"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--only-original", "0"])
    with pytest.raises(promo.PromotionError, match="dupliqué"):
        promo._target_collection_override_map([(14511, 8280), (14511, 8109)])


def test_personal_or_inaccessible_card_dependency_blocks_promotion_and_shared_cards_are_never_moved():
    row = manifest_row(1, 101, "A")
    manifest, accounting, decisions, mb = fixtures_for([row])
    mb.dashboards[101] = dashboard(
        101, f"[TEST] {promo.TARGET_TAG}", 150, cards=[501]
    )
    mb.cards[501] = card(501, 999, source=502)
    mb.cards[502] = card(502, promo.SHARED_GENERATED_CARDS_COLLECTION_ID)
    mb.collections[999] = collection(999, personal=True)
    mb.collections[promo.SHARED_GENERATED_CARDS_COLLECTION_ID] = collection(
        promo.SHARED_GENERATED_CARDS_COLLECTION_ID
    )

    plan = promo.build_promotion_plan(manifest, accounting, decisions, mb, verifier=verified)
    entry = plan["entries"][0]
    assert entry["status"] == "BLOCKED"
    assert "DEPENDENCY_IN_PERSONAL_COLLECTION" in reason_codes(entry)
    shared = next(
        dependency
        for dependency in entry["preconditions"]["dependency_cards"]
        if dependency["card_id"] == 502
    )
    assert shared["shared_generated_card"] is True
    assert mb.put_calls == []


def test_converted_legacy_card_fingerprint_ignores_only_recursive_lib_uuids():
    first = converted_legacy_card()
    second = converted_legacy_card(
        query_uuid="query-rehydrated",
        stage_uuid="stage-rehydrated",
        field_uuid="field-rehydrated",
    )
    original = deepcopy(first)

    assert promo.card_fingerprint(first) == promo.card_fingerprint(second)
    assert first == original
    assert promo.card_semantic_state(first)["legacy_query"] == first["legacy_query"]

    changed_type = deepcopy(second)
    changed_type["dataset_query"]["stages"][0]["lib/type"] = "mbql.stage/native"
    assert promo.card_fingerprint(first) != promo.card_fingerprint(changed_type)

    changed_tag = deepcopy(second)
    changed_tag["dataset_query"]["stages"][0]["tag"] = "account-filter"
    assert promo.card_fingerprint(first) != promo.card_fingerprint(changed_tag)

    changed_field = deepcopy(second)
    changed_field["dataset_query"]["stages"][0]["field"]["id"] = 8
    assert promo.card_fingerprint(first) != promo.card_fingerprint(changed_field)

    changed_legacy = deepcopy(second)
    changed_legacy["legacy_query"]["query"]["filter"][2] = "Client B"
    assert promo.card_fingerprint(first) != promo.card_fingerprint(changed_legacy)


def test_non_converted_card_fingerprint_keeps_lib_uuid_significant():
    first = converted_legacy_card()
    second = deepcopy(first)
    first["dataset_query"]["lib.convert/converted?"] = False
    second["dataset_query"]["lib.convert/converted?"] = False
    second["dataset_query"]["stages"][0]["lib/uuid"] = "stage-rehydrated"

    assert promo.card_fingerprint(first) != promo.card_fingerprint(second)

    first["dataset_query"]["lib.convert/converted?"] = True
    second["dataset_query"]["lib.convert/converted?"] = True
    first["legacy_query"] = None
    second["legacy_query"] = None
    assert promo.card_fingerprint(first) != promo.card_fingerprint(second)


def test_converted_legacy_dependency_audit_is_repeatable_and_versioned():
    row = manifest_row(1, 101, "A")
    manifest, accounting, decisions, mb = fixtures_for([row])
    mb.dashboards[101] = dashboard(
        101, f"[TEST] 1 {promo.TARGET_TAG}", 150, cards=[501]
    )
    mb.cards[501] = converted_legacy_card()
    mb.collections[300] = collection(300)

    first = promo.build_promotion_plan(
        manifest, accounting, decisions, mb, verifier=verified
    )
    second = promo.build_promotion_plan(
        manifest, accounting, decisions, mb, verifier=verified
    )

    assert first == second
    assert first["constants"]["card_fingerprint_version"] == 2
    assert (
        first["entries"][0]["preconditions"]["dependency_cards"]
        == second["entries"][0]["preconditions"]["dependency_cards"]
    )
    parts = first["entries"][0]["preconditions"]["dependency_cards"][0][
        "fingerprint_parts"
    ]
    assert set(parts) == set(promo.card_semantic_state(mb.cards[501]))
    assert all(value.startswith("sha256:") for value in parts.values())


def test_apply_precondition_tolerates_rehydrated_uuid_but_blocks_real_card_drift():
    row = manifest_row(1, 101, "A")
    manifest, accounting, decisions, mb = fixtures_for([row])
    mb.dashboards[101] = dashboard(
        101, f"[TEST] 1 {promo.TARGET_TAG}", 150, cards=[501]
    )
    mb.cards[501] = converted_legacy_card()
    mb.collections[300] = collection(300)
    plan = promo.build_promotion_plan(
        manifest, accounting, decisions, mb, verifier=verified
    )
    entry = plan["entries"][0]
    assert entry["status"] == "READY"

    mb.cards[501]["dataset_query"]["lib/uuid"] = "query-rehydrated"
    mb.cards[501]["dataset_query"]["stages"][0]["lib/uuid"] = "stage-rehydrated"
    mb.cards[501]["dataset_query"]["stages"][0]["field"]["lib/uuid"] = (
        "field-rehydrated"
    )
    promo.assert_entry_preconditions(mb, entry, verifier=verified)
    assert mb.put_calls == []

    mb.cards[501]["dataset_query"]["stages"][0]["field"]["id"] = 8
    with pytest.raises(
        promo.PromotionError,
        match=(
            r"dépendances ont changé.*501\[fingerprint,"
            r"fingerprint_parts.dataset_query\]"
        ),
    ):
        promo.assert_entry_preconditions(mb, entry, verifier=verified)
    assert mb.put_calls == []


def test_plan_is_deterministic_and_exact_name_collision_is_blocking():
    row = manifest_row(1, 101, "A")
    manifest, accounting, decisions, mb = fixtures_for([row])
    mb.items[200] = [{"id": 777, "name": f"Live 1 {promo.TARGET_TAG}", "archived": False}]

    first = promo.build_promotion_plan(manifest, accounting, decisions, mb, verifier=verified)
    second = promo.build_promotion_plan(manifest, accounting, decisions, mb, verifier=verified)
    assert first == second
    promo.validate_plan_hash(first)
    assert first["entries"][0]["status"] == "BLOCKED"
    assert "TARGET_NAME_COLLISION" in reason_codes(first["entries"][0])


def test_build_shares_get_cache_with_verifier_and_reports_only_selected_candidates():
    rows = [
        manifest_row(1, 101, "A"),
        manifest_row(2, 102, "B", roadmap="residual"),
    ]
    manifest, accounting, decisions, mb = fixtures_for(rows)
    mb.dashboards[101] = dashboard(
        101, f"[TEST] 1 {promo.TARGET_TAG}", 150, cards=[501]
    )
    mb.cards[501] = card(501, 300)
    mb.collections[300] = collection(300)
    events = []

    def verifier(read_mb, copy_id, _client):
        assert isinstance(read_mb, promo.CachedReadMetabase)
        assert read_mb.get(f"/api/dashboard/{copy_id}")["id"] == copy_id
        assert read_mb.get(f"/api/dashboard/{copy_id}")["id"] == copy_id
        assert read_mb.get("/api/card/501")["id"] == 501
        assert read_mb.get("/api/card/501")["id"] == 501
        return True, "ok"

    plan = promo.build_promotion_plan(
        manifest,
        accounting,
        decisions,
        mb,
        verifier=verifier,
        progress=events.append,
    )

    assert plan["entries"][0]["status"] == "READY"
    assert mb.get_calls.count("/api/dashboard/101") == 1
    assert mb.get_calls.count("/api/card/501") == 1
    assert all(kwargs == {"timeout": promo.READ_TIMEOUT_SECONDS} for kwargs in mb.get_kwargs)
    assert [(event["phase"], event["status"], event["original_id"]) for event in events] == [
        ("plan", "START", 1),
        ("plan", "READY", 1),
    ]


def test_cached_read_uses_direct_session_http_once_with_explicit_timeout():
    class HttpResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"id": 1}

    class Http:
        def __init__(self):
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return HttpResponse()

    class Client:
        domain = "https://metabase.invalid"
        header = {"X-Metabase-Session": "secret"}

        def __init__(self):
            self._http = Http()

        def get(self, *_args, **_kwargs):
            raise AssertionError("le wrapper public ne doit pas valider la session")

    client = Client()
    cached = promo.CachedReadMetabase(client)
    assert cached.get("/api/dashboard/1") == {"id": 1}
    assert cached.get("/api/dashboard/1") == {"id": 1}
    assert client._http.calls == [
        (
            "https://metabase.invalid/api/dashboard/1",
            {
                "headers": {"X-Metabase-Session": "secret"},
                "timeout": promo.READ_TIMEOUT_SECONDS,
            },
        )
    ]


def test_apply_rolls_back_all_attempted_copies_in_reverse_on_first_failure(tmp_path):
    rows = [manifest_row(1, 101, "A"), manifest_row(2, 102, "B")]
    manifest, accounting, decisions, mb = fixtures_for(rows)
    plan = promo.build_promotion_plan(manifest, accounting, decisions, mb, verifier=verified)
    before = {
        copy_id: (mb.dashboards[copy_id]["name"], mb.dashboards[copy_id]["collection_id"])
        for copy_id in (101, 102)
    }
    mb.fail_promotion_copy_id = 102
    snapshot_path = tmp_path / "snapshot.json"
    events = []

    with pytest.raises(promo.PromotionTransactionError) as caught:
        promo.apply_plan(
            mb, plan, snapshot_path, verifier=verified, progress=events.append
        )

    assert caught.value.rollback_ok is True
    assert [copy_id for copy_id, _payload in mb.put_calls] == [101, 102, 102, 101]
    assert all(copy_id not in {1, 2} for copy_id, _payload in mb.put_calls)
    for copy_id, state in before.items():
        assert (mb.dashboards[copy_id]["name"], mb.dashboards[copy_id]["collection_id"]) == state
    snapshot = json.loads(snapshot_path.read_text())
    promo.validate_snapshot_hash(snapshot)
    assert snapshot["status"] == "ROLLED_BACK"
    assert [
        event["copy_id"]
        for event in events
        if event["phase"] == "rollback" and event["status"] == "RESTORED"
    ] == [102, 101]


def test_apply_uses_fresh_read_cache_before_and_after_put_and_reports_progress(tmp_path):
    row = manifest_row(1, 101, "A")
    manifest, accounting, decisions, mb = fixtures_for([row])
    plan = promo.build_promotion_plan(manifest, accounting, decisions, mb, verifier=verified)
    events = []

    result = promo.apply_plan(
        mb,
        plan,
        tmp_path / "snapshot.json",
        verifier=verified,
        progress=events.append,
    )

    assert result["status"] == "APPLIED"
    # build, précondition, post-PUT et audit final sont quatre phases distinctes.
    assert mb.get_calls.count("/api/dashboard/101") == 4
    assert mb.get_calls.count("/api/dashboard/1") == 4
    assert all(kwargs == {"timeout": promo.READ_TIMEOUT_SECONDS} for kwargs in mb.get_kwargs)
    assert [(event["phase"], event["status"]) for event in events] == [
        ("apply", "PRECONDITION"),
        ("apply", "APPLIED"),
        ("final_audit", "VERIFIED"),
    ]


def test_isolated_mode_keeps_successes_and_continues_after_precondition_failure(tmp_path):
    rows = [
        manifest_row(1, 101, "A"),
        manifest_row(2, 102, "B"),
        manifest_row(3, 103, "C"),
    ]
    manifest, accounting, decisions, mb = fixtures_for(rows)
    plan = promo.build_promotion_plan(
        manifest, accounting, decisions, mb, verifier=verified
    )
    # Dérive apparue après le plan : cette ligne doit échouer avant tout PUT.
    mb.dashboards[102]["description"] = "édition externe"
    snapshot_path = tmp_path / "isolated-precondition.json"
    events = []

    result = promo.apply_plan(
        mb,
        plan,
        snapshot_path,
        verifier=verified,
        progress=events.append,
        continue_on_error=True,
    )

    assert result == {
        "status": "PARTIAL",
        "applied": 2,
        "verified": 2,
        "failed": 1,
        "snapshot_path": str(snapshot_path),
    }
    assert [copy_id for copy_id, _payload in mb.put_calls] == [101, 103]
    assert mb.dashboards[101]["collection_id"] == 200
    assert mb.dashboards[102]["collection_id"] == 150
    assert mb.dashboards[103]["collection_id"] == 202
    snapshot = json.loads(snapshot_path.read_text())
    promo.validate_snapshot_hash(snapshot)
    assert snapshot["failure_mode"] == "isolated"
    assert snapshot["status"] == "PARTIAL"
    assert snapshot["applied_order"] == [101, 103]
    assert snapshot["successes"] == [
        {"original_id": 1, "copy_id": 101, "status": "VERIFIED"},
        {"original_id": 3, "copy_id": 103, "status": "VERIFIED"},
    ]
    assert snapshot["failures"][0]["copy_id"] == 102
    assert snapshot["failures"][0]["stage"] == "precondition"
    assert snapshot["failures"][0]["mutation_attempted"] is False
    assert snapshot["failures"][0]["rollback"] == {
        "status": "NOT_REQUIRED",
        "errors": [],
    }
    assert [
        event["copy_id"]
        for event in events
        if event["phase"] == "final_audit"
    ] == [101, 103]


def test_isolated_mode_rolls_back_only_failed_post_read_copy_then_continues(tmp_path):
    rows = [
        manifest_row(1, 101, "A"),
        manifest_row(2, 102, "B"),
        manifest_row(3, 103, "C"),
    ]
    manifest, accounting, decisions, mb = fixtures_for(rows)
    plan = promo.build_promotion_plan(
        manifest, accounting, decisions, mb, verifier=verified
    )
    before_102 = (
        mb.dashboards[102]["name"],
        mb.dashboards[102]["collection_id"],
    )
    mb.fail_post_read_copy_id = 102
    snapshot_path = tmp_path / "isolated-post-read.json"
    events = []

    result = promo.apply_plan(
        mb,
        plan,
        snapshot_path,
        verifier=verified,
        progress=events.append,
        continue_on_error=True,
    )

    assert result["status"] == "PARTIAL"
    assert result["applied"] == 2
    assert result["verified"] == 2
    assert result["failed"] == 1
    # 101 reste promue; 102 seule est restaurée; 103 est ensuite promue.
    assert [copy_id for copy_id, _payload in mb.put_calls] == [101, 102, 102, 103]
    assert mb.dashboards[101]["collection_id"] == 200
    assert (
        mb.dashboards[102]["name"],
        mb.dashboards[102]["collection_id"],
    ) == before_102
    assert mb.dashboards[103]["collection_id"] == 202
    snapshot = json.loads(snapshot_path.read_text())
    promo.validate_snapshot_hash(snapshot)
    failure = snapshot["failures"][0]
    assert failure["copy_id"] == 102
    assert failure["stage"] == "post_read"
    assert failure["mutation_attempted"] is True
    assert failure["rollback"] == {"status": "RESTORED", "errors": []}
    assert snapshot["applied_order"] == [101, 103]
    assert [
        event["copy_id"]
        for event in events
        if event["phase"] == "rollback" and event["status"] == "RESTORED"
    ] == [102]
    assert [
        event["copy_id"]
        for event in events
        if event["phase"] == "final_audit"
    ] == [101, 103]


def test_only_original_applies_exact_ready_selection_and_rejects_unsafe_selection(tmp_path):
    rows = [manifest_row(1, 101, "A"), manifest_row(2, 102, "B")]
    manifest, accounting, decisions, mb = fixtures_for(rows)
    plan = promo.build_promotion_plan(
        manifest, accounting, decisions, mb, verifier=verified
    )
    snapshot_path = tmp_path / "only-original.json"

    result = promo.apply_plan(
        mb,
        plan,
        snapshot_path,
        verifier=verified,
        selected_original_ids=[2],
    )

    assert result["status"] == "APPLIED"
    assert [copy_id for copy_id, _payload in mb.put_calls] == [102]
    snapshot = json.loads(snapshot_path.read_text())
    assert snapshot["selected_original_ids"] == [2]
    assert snapshot["applied_order"] == [102]
    assert mb.dashboards[101]["collection_id"] == 150
    assert mb.dashboards[102]["collection_id"] == 201

    second_snapshot = tmp_path / "must-not-exist.json"
    put_count = len(mb.put_calls)
    with pytest.raises(promo.PromotionError, match="absent ou ambigu"):
        promo.apply_plan(
            mb,
            plan,
            second_snapshot,
            verifier=verified,
            selected_original_ids=[999],
        )
    assert not second_snapshot.exists()
    assert len(mb.put_calls) == put_count

    with pytest.raises(promo.PromotionError, match="dupliquée"):
        promo.apply_plan(
            mb,
            plan,
            second_snapshot,
            verifier=verified,
            selected_original_ids=[1, 1],
        )
    assert not second_snapshot.exists()
    assert len(mb.put_calls) == put_count

    blocked_row = manifest_row(3, 103, "C", roadmap="residual")
    blocked_manifest, blocked_accounting, blocked_decisions, blocked_mb = (
        fixtures_for([blocked_row])
    )
    blocked_plan = promo.build_promotion_plan(
        blocked_manifest,
        blocked_accounting,
        blocked_decisions,
        blocked_mb,
        verifier=verified,
    )
    with pytest.raises(promo.PromotionError, match="original sélectionné #3 non READY"):
        promo.apply_plan(
            blocked_mb,
            blocked_plan,
            second_snapshot,
            verifier=verified,
            selected_original_ids=[3],
        )
    assert not second_snapshot.exists()
    assert blocked_mb.put_calls == []


def test_exclude_original_omits_exact_ready_entry_and_records_selection(tmp_path):
    rows = [
        manifest_row(1, 101, "A"),
        manifest_row(2, 102, "B"),
        manifest_row(3, 103, "C"),
    ]
    manifest, accounting, decisions, mb = fixtures_for(rows)
    plan = promo.build_promotion_plan(
        manifest, accounting, decisions, mb, verifier=verified
    )
    snapshot_path = tmp_path / "exclude-original.json"

    result = promo.apply_plan(
        mb,
        plan,
        snapshot_path,
        verifier=verified,
        continue_on_error=True,
        excluded_original_ids=[2],
    )

    assert result["status"] == "APPLIED"
    assert [copy_id for copy_id, _payload in mb.put_calls] == [101, 103]
    snapshot = json.loads(snapshot_path.read_text())
    assert snapshot["selected_original_ids"] == [1, 3]
    assert snapshot["excluded_original_ids"] == [2]
    assert snapshot["applied_order"] == [101, 103]
    assert mb.dashboards[102]["collection_id"] == 150

    with pytest.raises(promo.PromotionError, match="mutuellement exclusifs"):
        promo.apply_plan(
            mb,
            plan,
            tmp_path / "must-not-exist.json",
            verifier=verified,
            selected_original_ids=[1],
            excluded_original_ids=[2],
        )


def test_isolated_final_audit_failure_is_recorded_without_rollback(tmp_path):
    rows = [manifest_row(1, 101, "A"), manifest_row(2, 102, "B")]
    manifest, accounting, decisions, mb = fixtures_for(rows)
    plan = promo.build_promotion_plan(
        manifest, accounting, decisions, mb, verifier=verified
    )
    mb.fail_final_read_copy_id = 101
    snapshot_path = tmp_path / "isolated-final-audit.json"

    result = promo.apply_plan(
        mb,
        plan,
        snapshot_path,
        verifier=verified,
        continue_on_error=True,
    )

    assert result["status"] == "PARTIAL"
    assert result["applied"] == 2
    assert result["verified"] == 1
    assert result["failed"] == 1
    assert [copy_id for copy_id, _payload in mb.put_calls] == [101, 102]
    snapshot = json.loads(snapshot_path.read_text())
    assert snapshot["applied_order"] == [101, 102]
    assert snapshot["successes"] == [
        {"original_id": 1, "copy_id": 101, "status": "AUDIT_FAILED"},
        {"original_id": 2, "copy_id": 102, "status": "VERIFIED"},
    ]
    assert snapshot["failures"] == [
        {
            "original_id": 1,
            "copy_id": 101,
            "stage": "final_audit",
            "message": "empreinte finale copie #101 divergente",
            "mutation_attempted": True,
            "rollback": {"status": "NOT_ATTEMPTED", "errors": []},
        }
    ]


def test_explicit_rollback_is_dry_run_by_default_then_restores_from_snapshot(tmp_path):
    row = manifest_row(1, 101, "A")
    manifest, accounting, decisions, mb = fixtures_for([row])
    plan = promo.build_promotion_plan(manifest, accounting, decisions, mb, verifier=verified)
    snapshot_path = tmp_path / "snapshot.json"
    result = promo.apply_plan(mb, plan, snapshot_path, verifier=verified)
    assert result["status"] == "APPLIED"
    assert mb.dashboards[101]["name"] == f"Live 1 {promo.TARGET_TAG}"

    snapshot = json.loads(snapshot_path.read_text())
    put_count = len(mb.put_calls)
    dry_run = promo.rollback_snapshot(mb, snapshot, yes=False)
    assert dry_run == {"status": "DRY_RUN", "ready": 1, "already_rolled_back": 0}
    assert len(mb.put_calls) == put_count

    rolled_back = promo.rollback_snapshot(mb, snapshot, yes=True)
    assert rolled_back == {"status": "ROLLED_BACK", "restored": 1, "already_rolled_back": 0}
    assert mb.dashboards[101]["name"] == f"[TEST] 1 {promo.TARGET_TAG}"
    assert mb.dashboards[101]["collection_id"] == 150
    assert all(copy_id != 1 for copy_id, _payload in mb.put_calls)
