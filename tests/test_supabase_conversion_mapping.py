#!/usr/bin/env python3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import conv_lib
import export_supabase_conversion_mapping as exporter
import migrate_dashboard_full as mdf


def _source():
    companies = [{"id": "company-1", "name": "Acme"}]
    accounts = [{
        "id": "account-row-1",
        "account_id": "external-1",
        "account_name": "Ads",
        "company_id": "company-1",
    }]
    return companies, accounts


def _conversion(row_id, types, new_types):
    return {
        "id": row_id,
        "account_id": "account-row-1",
        "conversion_id": f"external-{row_id}",
        "conversion_name": row_id,
        "type": types,
        "new_type": new_types,
        "updated_at": "2026-07-15T00:00:00+00:00",
    }


def test_build_snapshot_preserves_independent_ordered_arrays():
    companies, accounts = _source()
    snapshot = exporter.build_snapshot(
        companies,
        accounts,
        [
            _conversion("conversion-1", ["Main conversion", "Add to cart"], ["Purchases"]),
            _conversion("conversion-2", ["1st conversion"], ["Custom 1"]),
        ],
        exported_at="2026-07-15T00:00:00+00:00",
    )

    record = snapshot["records"][0]
    assert record["type"] == ["Main conversion", "Add to cart"]
    assert record["new_type"] == ["Purchases"]
    assert record["type_is_null"] is False
    assert record["new_type_is_null"] is False
    assert "pairs" not in record
    assert snapshot["mapping"] == {"Acme": {"0": "Purchases", "1": "Custom 1"}}


def test_snapshot_preserves_raw_null_markers_without_changing_row_sets():
    companies, accounts = _source()
    snapshot = exporter.build_snapshot(
        companies,
        accounts,
        [_conversion("conversion-null", ["Main conversion"], None)],
    )

    record = snapshot["records"][0]
    assert record["type"] == ["Main conversion"]
    assert record["type_is_null"] is False
    assert record["new_type"] == []
    assert record["new_type_is_null"] is True
    assert snapshot["row_sets"]["source"]["Acme"]["0"] == ["conversion-null"]
    assert snapshot["row_sets"]["target"].get("Acme", {}) == {}
    assert snapshot["slot_mapping"]["Acme"]["0"] == conv_lib.UNMAPPED


def test_different_array_cardinalities_are_informative_not_blocking():
    companies, accounts = _source()
    snapshot = exporter.build_snapshot(
        companies,
        accounts,
        [_conversion(
            "conversion-1",
            ["Main conversion", "1st conversion"],
            ["Purchases"],
        )],
    )

    assert snapshot["mapping"]["Acme"] == {
        "0": "Purchases",
        "1": "Purchases",
    }
    assert any(item["kind"] == "independent_array_cardinality" for item in snapshot["ambiguities"])


def test_mapping_uses_row_sets_not_array_positions_even_when_lengths_match():
    companies, accounts = _source()
    snapshot = exporter.build_snapshot(
        companies,
        accounts,
        [
            _conversion(
                "conversion-1",
                ["Main conversion", "1st conversion"],
                ["Purchases", "Custom 1"],
            ),
            _conversion("conversion-2", ["Main conversion"], ["Custom 1"]),
        ],
    )

    # Un zip donnerait Main->Purchases et 1st->Custom 1. Les ensembles exacts
    # prouvent l'inverse avant le garde-fou de collision inter-slots.
    assert snapshot["slot_mapping"]["Acme"] == {
        "0": "Custom 1",
        "1": "Purchases",
    }
    assert snapshot["mapping"]["Acme"] == snapshot["slot_mapping"]["Acme"]


def test_same_client_slot_without_exact_target_row_set_is_unmapped():
    companies, accounts = _source()
    snapshot = exporter.build_snapshot(
        companies,
        accounts,
        [
            _conversion("conversion-1", ["Main conversion"], ["Purchases"]),
            _conversion("conversion-2", ["Main conversion"], ["Leads"]),
        ],
    )

    assert snapshot["slot_mapping"]["Acme"]["0"] == conv_lib.UNMAPPED
    assert any(item["kind"] == "no_row_set_match" for item in snapshot["ambiguities"])


def test_same_target_on_identical_slot_row_sets_is_safe():
    companies, accounts = _source()
    snapshot = exporter.build_snapshot(
        companies,
        accounts,
        [_conversion("same-row", ["Main conversion", "1st conversion"], ["Purchases"])],
    )

    assert snapshot["mapping"]["Acme"] == {"0": "Purchases", "1": "Purchases"}


def test_auto_mapping_requires_identical_source_and_target_row_sets():
    companies, accounts = _source()
    snapshot = exporter.build_snapshot(
        companies,
        accounts,
        [
            _conversion("source-and-target", ["Main conversion"], ["Purchases"]),
            _conversion("target-only", [], ["Purchases"]),
        ],
    )

    assert snapshot["slot_mapping"]["Acme"]["0"] == conv_lib.UNMAPPED
    assert snapshot["mapping"]["Acme"]["0"] == conv_lib.UNMAPPED
    mismatch = next(item for item in snapshot["ambiguities"] if item["kind"] == "no_row_set_match")
    assert mismatch["source_row_count"] == 1


def test_effective_mapping_requires_exact_row_sets_after_consultant_overlay(tmp_path):
    companies = [
        {"id": "company-1", "name": "Gamin Tout Terrain"},
        {"id": "company-2", "name": "Dougs"},
    ]
    accounts = [
        {"id": "account-row-1", "account_id": "gtt", "account_name": "GTT", "company_id": "company-1"},
        {"id": "account-row-2", "account_id": "dougs", "account_name": "Dougs", "company_id": "company-2"},
    ]
    conversions = [
        _conversion("gtt-purchase", ["Main conversion"], ["Purchases"]),
        _conversion("gtt-cart", ["Main conversion"], ["Add to cart"]),
        {**_conversion("dougs-1", ["1st conversion"], ["Custom 2"]), "account_id": "account-row-2"},
        {**_conversion("dougs-2", ["2nd conversion"], ["Custom 2"]), "account_id": "account-row-2"},
    ]
    path = tmp_path / "snapshot.json"
    exporter.write_snapshot(exporter.build_snapshot(companies, accounts, conversions), path)

    mapping, diagnostics = exporter.load_effective_mapping(path, [
        {"client": "Gamin Tout Terrain", "slot": 0, "new_type": "Purchases"},
        {"client": "Dougs", "slot": 1, "new_type": "Custom 2"},
    ])

    assert mapping["Gamin Tout Terrain"]["0"] == "Purchases"
    assert mapping["Dougs"]["1"] == "Custom 2"
    assert mapping["Dougs"]["2"] == conv_lib.UNMAPPED
    assert {(item["client"], item["slot"]) for item in diagnostics} == {
        ("Gamin Tout Terrain", 0),
        ("Dougs", 1),
    }
    assert all(item["kind"] == "decision_row_set_mismatch" for item in diagnostics)


def test_load_inputs_lets_explicit_decision_win_over_auto_collision(tmp_path, monkeypatch):
    # RÈGLE MÉTIER (user 2026-07-17) : une même conversion peut légitimement occuper plusieurs
    # positions positionnelles. Une DÉCISION consultant explicite est donc autoritaire et l'emporte
    # sur le blocage de collision (load_repository_mapping passe decisions_override_collisions=True).
    # Seule une collision AUTO (aucune décision sur le slot) reste en CONFLICT.
    companies, accounts = _source()
    snapshot = exporter.build_snapshot(
        companies,
        accounts,
        [
            _conversion("conversion-1", ["Main conversion"], ["Purchases"]),
            _conversion("conversion-2", ["1st conversion"], ["Custom 1"]),
        ],
    )
    exporter.write_snapshot(snapshot, tmp_path / "conv-supabase-snapshot.json")
    (tmp_path / "consultant-decisions.json").write_text(json.dumps([
        {"client": "Acme", "slot": 1, "new_type": "Purchases"},
    ]))
    (tmp_path / "conv-new-index.json").write_text("{}")
    # Ce fichier legacy ne doit plus être lu.
    (tmp_path / "conv-client-mapping.json").write_text("not json")
    monkeypatch.setattr(mdf, "MIG", tmp_path)

    mapping, index = mdf.load_inputs()

    # slot 1 est DÉCIDÉ Purchases -> il gagne malgré la collision avec le slot 0 (auto Purchases,
    # row-set différent). slot 0 n'a PAS de décision -> reste bloqué CONFLICT.
    assert mapping["Acme"] == {"0": conv_lib.CONFLICT, "1": "Purchases"}
    assert index == {}


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _GetOnlySession:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(self.pages.pop(0))


def test_supabase_reader_is_get_only_and_paginates_without_leaking_key():
    session = _GetOnlySession([[{"id": "1"}, {"id": "2"}], [{"id": "3"}]])
    reader = exporter.SupabaseReader(
        "https://project.supabase.co",
        "top-secret",
        session=session,
        page_size=2,
        retry_delay=0,
    )

    assert reader.fetch_all("pipeline_manager", "conversions", "id") == [
        {"id": "1"}, {"id": "2"}, {"id": "3"},
    ]
    assert [call[1]["params"]["offset"] for call in session.calls] == ["0", "2"]
    assert all(call[1]["headers"]["Accept-Profile"] == "pipeline_manager" for call in session.calls)


def test_credentials_require_explicit_prod_names(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SUPABASE_URL=https://wrong.supabase.co\n"
        "SUPABASE_SERVICE_ROLE_KEY=wrong\n"
    )
    try:
        exporter.load_prod_credentials(env_file, environ={})
    except exporter.SnapshotError as exc:
        assert exporter.PROD_URL_KEY in str(exc)
        assert "wrong" not in str(exc)
    else:
        raise AssertionError("les credentials génériques ne doivent pas être acceptés")
