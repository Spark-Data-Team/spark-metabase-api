from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import bascule_time_filter
import bascule_lib


class _DashboardOnlyMetabase:
    def get(self, endpoint):
        assert endpoint == "/api/dashboard/42"
        return {"id": 42, "parameters": [], "dashcards": []}


def test_missing_time_period_is_a_successful_noop(monkeypatch, capsys):
    monkeypatch.setattr(bascule_time_filter, "connect", lambda: _DashboardOnlyMetabase())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bascule_time_filter.py",
            "--copy",
            "42",
            "--client",
            "Example",
            "--auto-prepare",
            "--yes",
        ],
    )

    assert bascule_time_filter.main() is None
    assert "rien à basculer" in capsys.readouterr().out


def test_dashboard_defaults_supply_required_breakdown_without_overriding_pinned_params():
    dashboard = {
        "parameters": [
            {"id": "client", "type": "string/=", "default": ["Wrong"]},
            {"id": "segment", "type": "category", "default": ["age"]},
            {"id": "time", "type": "string/=", "default": ["day"]},
        ],
        "dashcards": [{
            "id": 10,
            "card_id": 20,
            "parameter_mappings": [
                {"parameter_id": "client", "target": ["dimension", ["template-tag", "clients"]]},
                {"parameter_id": "segment", "target": ["dimension", ["template-tag", "breakdown"]]},
                {"parameter_id": "time", "target": ["dimension", ["template-tag", "time_period"]]},
            ],
        }],
    }

    assert bascule_time_filter.dashboard_defaults_for_card(
        dashboard,
        10,
        20,
        {"breakdown": {"widget-type": "string/="}},
    ) == [{
        "type": "string/=",
        "value": ["age"],
        "target": ["dimension", ["template-tag", "breakdown"]],
    }]


def test_dashboard_defaults_ignore_stale_mapping_missing_from_card_tags():
    dashboard = {
        "parameters": [
            {"id": "segment", "type": "category", "default": ["age"]},
            {"id": "stale", "type": "category", "default": ["campaign-a"]},
        ],
        "dashcards": [{
            "id": 10,
            "card_id": 20,
            "parameter_mappings": [
                {
                    "parameter_id": "segment",
                    "target": ["dimension", ["template-tag", "breakdown"]],
                },
                {
                    "parameter_id": "stale",
                    "target": ["dimension", ["template-tag", "spark_campaigns"]],
                },
            ],
        }],
    }

    assert bascule_time_filter.dashboard_defaults_for_card(
        dashboard,
        10,
        20,
        {"breakdown": {"widget-type": "string/="}},
    ) == [{
        "type": "string/=",
        "value": ["age"],
        "target": ["dimension", ["template-tag", "breakdown"]],
    }]


@pytest.mark.parametrize(
    "target,expected",
    [
        (["dimension", ["template-tag", "time_period"]], True),
        (
            [
                "dimension",
                ["template-tag", "time_period"],
                {"stage-number": 0},
            ],
            True,
        ),
        (
            [
                "dimension",
                ["template-tag", "time_period"],
                {"stage-number": 0, "lib/uuid": "computed"},
            ],
            True,
        ),
        (
            ["dimension", ["template-tag", "other"], {"stage-number": 0}],
            False,
        ),
        (["variable", ["template-tag", "time_period"]], False),
        (
            ["dimension", ["template-tag", "time_period"], {"stage-number": 1}],
            False,
        ),
    ],
)
def test_time_target_accepts_only_canonical_template_tag(target, expected):
    assert bascule_time_filter._is_time_target(target) is expected


def test_duplicate_time_cleanup_removes_only_redundant_legacy_mappings():
    dashboard = {
        "parameters": [
            {"id": "new", "name": "Time period", "slug": "time_period", "type": "temporal-unit"},
            {"id": "old", "name": "Time period ", "slug": "time_period_", "type": "string/="},
        ],
        "dashcards": [{
            "id": 1,
            "card_id": 10,
            "parameter_mappings": [
                {"parameter_id": "new", "card_id": 10, "target": ["dimension", ["template-tag", "time_period"]]},
                {"parameter_id": "old", "card_id": 10, "target": ["dimension", ["template-tag", "time_period"]]},
            ],
        }],
    }
    plan = bascule_time_filter.duplicate_time_cleanup_plan(dashboard)
    assert plan["blockers"] == []
    assert plan["removed_ids"] == ["old"]
    assert [p["id"] for p in plan["parameters"]] == ["new"]
    assert [m["parameter_id"] for m in plan["dashcards"][0]["parameter_mappings"]] == ["new"]


def test_duplicate_time_cleanup_blocks_nonredundant_mapping():
    dashboard = {
        "parameters": [
            {"id": "new", "name": "Time period", "type": "temporal-unit"},
            {"id": "old", "name": "Time period ", "type": "string/="},
        ],
        "dashcards": [{
            "id": 1,
            "card_id": 10,
            "parameter_mappings": [{
                "parameter_id": "old",
                "card_id": 10,
                "target": ["dimension", ["template-tag", "time_period"]],
            }],
        }],
    }
    plan = bascule_time_filter.duplicate_time_cleanup_plan(dashboard)
    assert plan["blockers"] == [
        "dashcard 1: mapping old sans équivalent temporal-unit"
    ]


def _json_copy(value):
    return json.loads(json.dumps(value))


def _normal_dashboard():
    return {
        "id": 42,
        "parameters": [{
            "id": "time",
            "name": "Time period",
            "slug": "time_period",
            "type": "category",
            "default": ["month"],
        }],
        "dashcards": [{
            "id": 7,
            "card_id": 10,
            "parameter_mappings": [{
                "parameter_id": "time",
                "card_id": 10,
                "target": ["dimension", ["template-tag", "time_period"]],
            }],
        }],
        "tabs": [{"id": 3, "name": "Vue"}],
    }


def _time_card(card_id=10, tag_type="temporal-unit"):
    return {
        "id": card_id,
        "dataset_query": {
            "type": "native",
            "native": {
                "query": "select 1",
                "template-tags": {
                    "time_period": {"type": tag_type},
                },
            },
        },
    }


class _NormalApplyMetabase:
    def __init__(
        self,
        dashboard,
        *,
        corrupt_after_apply=False,
        corruption=None,
        apply_failure=None,
        rollback_succeeds=True,
        cards=None,
    ):
        self.dashboard = _json_copy(dashboard)
        self.cards = cards or {10: _time_card()}
        self.corrupt_after_apply = corrupt_after_apply
        self.corruption = corruption
        self.apply_failure = apply_failure
        self.rollback_succeeds = rollback_succeeds
        self.put_calls = []

    def get(self, endpoint):
        if endpoint == "/api/dashboard/42":
            return _json_copy(self.dashboard)
        if endpoint.startswith("/api/card/"):
            card_id = int(endpoint.rsplit("/", 1)[1])
            return _json_copy(self.cards[card_id])
        raise AssertionError(f"GET inattendu: {endpoint}")

    def put(self, endpoint, mode, json):
        assert mode == "raw"
        self.put_calls.append((endpoint, _json_copy(json)))
        is_rollback = len(self.put_calls) > 1
        if is_rollback and not self.rollback_succeeds:
            return SimpleNamespace(status_code=500, text="rollback boom")
        assert endpoint == "/api/dashboard/42"
        if not is_rollback and self.apply_failure == "http":
            return SimpleNamespace(status_code=500, text="apply rejected")
        if not is_rollback and self.apply_failure == "exception":
            raise RuntimeError("connection reset after send")
        self.dashboard["parameters"] = _json_copy(json["parameters"])
        self.dashboard["dashcards"] = _json_copy(json["dashcards"])
        if "tabs" in json:
            self.dashboard["tabs"] = _json_copy(json["tabs"])
        if self.corrupt_after_apply and not is_rollback:
            self.dashboard["parameters"].append({
                "id": "legacy-survivor",
                "name": "Time period",
                "slug": "time_period_",
                "type": "string/=",
                "default": ["week"],
            })
        if self.corruption == "drop_dashcard" and not is_rollback:
            self.dashboard["dashcards"] = []
        if self.corruption == "ignore_swap_and_drop_mapping" and not is_rollback:
            self.dashboard["dashcards"][0]["card_id"] = 10
            self.dashboard["dashcards"][0]["parameter_mappings"] = []
        if self.corruption == "add_stage_metadata" and not is_rollback:
            mapping = self.dashboard["dashcards"][0]["parameter_mappings"][0]
            mapping["target"] = [
                "dimension",
                ["template-tag", "time_period"],
                {"stage-number": 0},
            ]
        return SimpleNamespace(status_code=200, text="")


class _PostApplyReadErrorMetabase(_NormalApplyMetabase):
    def __init__(self, dashboard):
        super().__init__(dashboard)
        self.dashboard_reads = 0

    def get(self, endpoint):
        if endpoint == "/api/dashboard/42":
            self.dashboard_reads += 1
            if self.dashboard_reads == 2:
                raise RuntimeError("temporary read failure")
        return super().get(endpoint)


class _ReorderingMetabase(_NormalApplyMetabase):
    def __init__(
        self,
        dashboard,
        *,
        reorder_after_apply=False,
        reorder_after_rollback=False,
        **kwargs,
    ):
        super().__init__(dashboard, **kwargs)
        self.reorder_after_apply = reorder_after_apply
        self.reorder_after_rollback = reorder_after_rollback

    def put(self, endpoint, mode, json):
        response = super().put(endpoint, mode, json)
        is_rollback = len(self.put_calls) > 1
        should_reorder = (
            self.reorder_after_rollback if is_rollback else self.reorder_after_apply
        )
        if getattr(response, "status_code", None) == 200 and should_reorder:
            self.dashboard["dashcards"].reverse()
            for dashcard in self.dashboard["dashcards"]:
                dashcard["parameter_mappings"] = list(reversed(
                    dashcard.get("parameter_mappings") or []
                ))
        return response


def _normal_plan(dashboard):
    return bascule_lib.bascule_plan(
        dashboard,
        {10: {"time_period": {"type": "temporal-unit"}}},
    )


def _swap_plan(dashboard):
    return bascule_lib.bascule_plan(
        dashboard,
        {
            10: {"time_period": {"type": "dimension"}},
            20: {"time_period": {"type": "temporal-unit"}},
        },
        swaps={10: 20},
    )


def _duplicate_dashboard():
    dashboard = _normal_dashboard()
    dashboard["parameters"] = [
        {
            "id": "new",
            "name": "Time period",
            "slug": "time_period",
            "type": "temporal-unit",
            "default": "month",
            "sectionId": "temporal-unit",
            "temporal_units": ["day", "week", "month", "year"],
        },
        {
            "id": "old",
            "name": "Time period ",
            "slug": "time_period_",
            "type": "string/=",
            "default": ["month"],
        },
    ]
    dashboard["dashcards"][0]["parameter_mappings"] = [
        {
            "parameter_id": "new",
            "card_id": 10,
            "target": ["dimension", ["template-tag", "time_period"]],
        },
        {
            "parameter_id": "old",
            "card_id": 10,
            "target": ["dimension", ["template-tag", "time_period"]],
        },
    ]
    return dashboard


def _reorderable_dashboard():
    dashboard = _normal_dashboard()
    dashboard["dashcards"][0]["parameter_mappings"].append({
        "parameter_id": "other",
        "card_id": 10,
        "target": ["dimension", ["template-tag", "breakdown"]],
    })
    dashboard["dashcards"].append({
        "id": 8,
        "card_id": None,
        "row": 4,
        "col": 0,
        "size_x": 12,
        "size_y": 2,
        "parameter_mappings": [],
        "visualization_settings": {"text": "Info"},
        "series": [],
    })
    return dashboard


def test_normal_apply_rechecks_and_verifies_postconditions(monkeypatch, tmp_path):
    before = _normal_dashboard()
    mb = _NormalApplyMetabase(before)
    monkeypatch.setattr(bascule_time_filter, "REPO", tmp_path)

    outcome = bascule_time_filter.apply_normal_bascule(
        mb, 42, before, _normal_plan(before)
    )

    assert outcome["temporal_ids"] == ["time"]
    assert outcome["residual"] == []
    assert outcome["snapshot"].exists()
    assert len(mb.put_calls) == 1
    assert {endpoint for endpoint, _ in mb.put_calls} == {"/api/dashboard/42"}


def test_normal_apply_accepts_metabase_stage_number_on_time_target(
    monkeypatch, tmp_path
):
    before = _normal_dashboard()
    before["dashcards"][0]["parameter_mappings"][0]["target"].append(
        {"stage-number": 0}
    )
    mb = _NormalApplyMetabase(before, corruption="add_stage_metadata")
    monkeypatch.setattr(bascule_time_filter, "REPO", tmp_path)

    outcome = bascule_time_filter.apply_normal_bascule(
        mb, 42, before, _normal_plan(before)
    )

    assert outcome["residual"] == []
    assert len(mb.put_calls) == 1
    assert mb.put_calls[0][1]["dashcards"][0]["parameter_mappings"][0][
        "target"
    ] == [
        "dimension",
        ["template-tag", "time_period"],
        {"stage-number": 0},
    ]


def test_normal_apply_accepts_get_reordering_but_preserves_put_order(
    monkeypatch, tmp_path
):
    before = _reorderable_dashboard()
    mb = _ReorderingMetabase(before, reorder_after_apply=True)
    monkeypatch.setattr(bascule_time_filter, "REPO", tmp_path)

    outcome = bascule_time_filter.apply_normal_bascule(
        mb, 42, before, _normal_plan(before)
    )

    assert outcome["residual"] == []
    assert [item["id"] for item in mb.dashboard["dashcards"]] == [8, 7]
    sent = mb.put_calls[0][1]
    assert [item["id"] for item in sent["dashcards"]] == [7, 8]
    assert [
        item["parameter_id"]
        for item in sent["dashcards"][0]["parameter_mappings"]
    ] == ["time", "other"]


def test_normal_apply_ignores_server_metadata_but_puts_stable_configuration(
    monkeypatch, tmp_path
):
    before = _normal_dashboard()
    before["dashcards"][0].update({
        "updated_at": "old",
        "card": {"id": 10, "view_count": 1, "last_used_at": "old"},
        "series": [{"id": 801, "name": "expanded", "view_count": 10}],
    })
    before["tabs"][0].update({"updated_at": "old", "entity_id": "server-a"})
    mb = _NormalApplyMetabase(before)
    mb.dashboard["dashcards"][0]["updated_at"] = "new"
    mb.dashboard["dashcards"][0]["card"]["view_count"] = 999
    mb.dashboard["dashcards"][0]["series"][0]["view_count"] = 999
    mb.dashboard["tabs"][0]["updated_at"] = "new"
    monkeypatch.setattr(bascule_time_filter, "REPO", tmp_path)

    bascule_time_filter.apply_normal_bascule(
        mb, 42, before, _normal_plan(before)
    )

    sent_dashcard = mb.put_calls[0][1]["dashcards"][0]
    assert "card" not in sent_dashcard
    assert "updated_at" not in sent_dashcard
    assert sent_dashcard["series"] == [{"id": 801}]
    assert mb.put_calls[0][1]["tabs"] == [{
        "id": 3,
        "name": "Vue",
        "position": None,
    }]


def test_normal_apply_refuses_pre_put_dashboard_drift(monkeypatch, tmp_path):
    before = _normal_dashboard()
    drifted = _normal_dashboard()
    drifted["tabs"][0]["name"] = "Modifié ailleurs"
    mb = _NormalApplyMetabase(drifted)
    monkeypatch.setattr(bascule_time_filter, "REPO", tmp_path)

    with pytest.raises(RuntimeError, match="drift pré-PUT.*aucun PUT"):
        bascule_time_filter.apply_normal_bascule(
            mb, 42, before, _normal_plan(before)
        )

    assert mb.put_calls == []


def test_normal_apply_rolls_back_only_its_dashboard_and_verifies_exact_state(
    monkeypatch, tmp_path
):
    before = _normal_dashboard()
    mb = _NormalApplyMetabase(before, corrupt_after_apply=True)
    monkeypatch.setattr(bascule_time_filter, "REPO", tmp_path)

    with pytest.raises(RuntimeError, match="rollback local vérifié exactement"):
        bascule_time_filter.apply_normal_bascule(
            mb, 42, before, _normal_plan(before)
        )

    assert len(mb.put_calls) == 2
    assert {endpoint for endpoint, _ in mb.put_calls} == {"/api/dashboard/42"}
    assert bascule_time_filter._dashboard_mutable_state(mb.dashboard) == (
        bascule_time_filter._dashboard_mutable_state(before)
    )


def test_normal_rollback_accepts_get_reordering_and_keeps_snapshot_payload_order(
    monkeypatch, tmp_path
):
    before = _reorderable_dashboard()
    mb = _ReorderingMetabase(
        before,
        corrupt_after_apply=True,
        reorder_after_rollback=True,
    )
    monkeypatch.setattr(bascule_time_filter, "REPO", tmp_path)

    with pytest.raises(RuntimeError, match="rollback local vérifié exactement"):
        bascule_time_filter.apply_normal_bascule(
            mb, 42, before, _normal_plan(before)
        )

    assert len(mb.put_calls) == 2
    rollback_payload = mb.put_calls[1][1]
    assert [item["id"] for item in rollback_payload["dashcards"]] == [7, 8]
    assert [
        item["parameter_id"]
        for item in rollback_payload["dashcards"][0]["parameter_mappings"]
    ] == ["time", "other"]
    snapshot = next((tmp_path / "migration").glob("bascule-snapshot-42-*.json"))
    saved_payload = json.loads(snapshot.read_text())["payload"]
    assert saved_payload == rollback_payload
    assert [item["id"] for item in mb.dashboard["dashcards"]] == [8, 7]
    assert bascule_time_filter._dashboard_mutable_state(mb.dashboard) == (
        bascule_time_filter._dashboard_mutable_state(before)
    )


def test_normal_apply_reports_unverified_local_rollback(monkeypatch, tmp_path):
    before = _normal_dashboard()
    mb = _NormalApplyMetabase(
        before,
        corrupt_after_apply=True,
        rollback_succeeds=False,
    )
    monkeypatch.setattr(bascule_time_filter, "REPO", tmp_path)

    with pytest.raises(RuntimeError, match="ROLLBACK LOCAL NON VÉRIFIÉ"):
        bascule_time_filter.apply_normal_bascule(
            mb, 42, before, _normal_plan(before)
        )

    assert len(mb.put_calls) == 2
    assert {endpoint for endpoint, _ in mb.put_calls} == {"/api/dashboard/42"}
    assert bascule_time_filter._dashboard_mutable_state(mb.dashboard) != (
        bascule_time_filter._dashboard_mutable_state(before)
    )


@pytest.mark.parametrize("apply_failure", ["http", "exception"])
def test_normal_apply_skips_rollback_put_when_initial_state_is_already_intact(
    monkeypatch,
    tmp_path,
    apply_failure,
):
    before = _normal_dashboard()
    mb = _NormalApplyMetabase(before, apply_failure=apply_failure)
    monkeypatch.setattr(bascule_time_filter, "REPO", tmp_path)

    with pytest.raises(RuntimeError, match="aucun PUT de rollback"):
        bascule_time_filter.apply_normal_bascule(
            mb, 42, before, _normal_plan(before)
        )

    assert len(mb.put_calls) == 1
    assert bascule_time_filter._dashboard_mutable_state(mb.dashboard) == (
        bascule_time_filter._dashboard_mutable_state(before)
    )


@pytest.mark.parametrize(
    "corruption,cards,plan_factory",
    [
        ("drop_dashcard", None, _normal_plan),
        (
            "ignore_swap_and_drop_mapping",
            {
                10: _time_card(10, "dimension"),
                20: _time_card(20, "temporal-unit"),
            },
            _swap_plan,
        ),
    ],
)
def test_normal_apply_rolls_back_if_put_omits_tile_or_ignores_swap(
    monkeypatch,
    tmp_path,
    corruption,
    cards,
    plan_factory,
):
    before = _normal_dashboard()
    mb = _NormalApplyMetabase(
        before,
        corruption=corruption,
        cards=cards,
    )
    monkeypatch.setattr(bascule_time_filter, "REPO", tmp_path)

    with pytest.raises(
        RuntimeError,
        match="projection configurable divergente.*rollback local vérifié exactement",
    ):
        bascule_time_filter.apply_normal_bascule(
            mb, 42, before, plan_factory(before)
        )

    assert len(mb.put_calls) == 2
    assert bascule_time_filter._dashboard_mutable_state(mb.dashboard) == (
        bascule_time_filter._dashboard_mutable_state(before)
    )


def test_duplicate_cleanup_rechecks_and_verifies_exact_target(monkeypatch, tmp_path):
    before = _duplicate_dashboard()
    plan = bascule_time_filter.duplicate_time_cleanup_plan(before)
    mb = _NormalApplyMetabase(before)
    monkeypatch.setattr(bascule_time_filter, "REPO", tmp_path)

    snapshot = bascule_time_filter.apply_duplicate_time_cleanup(
        mb, 42, before, plan
    )

    assert snapshot.exists()
    assert len(mb.put_calls) == 1
    assert [p["id"] for p in mb.dashboard["parameters"]] == ["new"]
    assert [
        mapping["parameter_id"]
        for mapping in mb.dashboard["dashcards"][0]["parameter_mappings"]
    ] == ["new"]


def test_duplicate_cleanup_refuses_pre_put_drift(monkeypatch, tmp_path):
    before = _duplicate_dashboard()
    drifted = _duplicate_dashboard()
    drifted["dashcards"][0]["col"] = 12
    mb = _NormalApplyMetabase(drifted)
    monkeypatch.setattr(bascule_time_filter, "REPO", tmp_path)

    with pytest.raises(RuntimeError, match="drift pré-PUT.*aucun PUT"):
        bascule_time_filter.apply_duplicate_time_cleanup(
            mb,
            42,
            before,
            bascule_time_filter.duplicate_time_cleanup_plan(before),
        )

    assert mb.put_calls == []


def test_duplicate_cleanup_rolls_back_on_divergent_reread(monkeypatch, tmp_path):
    before = _duplicate_dashboard()
    mb = _NormalApplyMetabase(before, corrupt_after_apply=True)
    monkeypatch.setattr(bascule_time_filter, "REPO", tmp_path)

    with pytest.raises(RuntimeError, match="rollback local vérifié exactement"):
        bascule_time_filter.apply_duplicate_time_cleanup(
            mb,
            42,
            before,
            bascule_time_filter.duplicate_time_cleanup_plan(before),
        )

    assert len(mb.put_calls) == 2
    assert bascule_time_filter._dashboard_mutable_state(mb.dashboard) == (
        bascule_time_filter._dashboard_mutable_state(before)
    )


def test_duplicate_cleanup_rolls_back_if_post_put_get_raises(monkeypatch, tmp_path):
    before = _duplicate_dashboard()
    mb = _PostApplyReadErrorMetabase(before)
    monkeypatch.setattr(bascule_time_filter, "REPO", tmp_path)

    with pytest.raises(
        RuntimeError,
        match="exception après tentative de PUT: RuntimeError.*rollback local vérifié exactement",
    ):
        bascule_time_filter.apply_duplicate_time_cleanup(
            mb,
            42,
            before,
            bascule_time_filter.duplicate_time_cleanup_plan(before),
        )

    assert len(mb.put_calls) == 2
    assert bascule_time_filter._dashboard_mutable_state(mb.dashboard) == (
        bascule_time_filter._dashboard_mutable_state(before)
    )
