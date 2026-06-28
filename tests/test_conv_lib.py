#!/usr/bin/env python3
"""Tests de conv_lib — script autonome. Usage : python3 tests/test_conv_lib.py"""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import conv_lib

def _native(sql, tags=()):
    return {"dataset_query": {"type": "native", "native": {"query": sql, "template-tags": {t: {} for t in tags}}}}

def _staged(sql, tags=()):
    return {"dataset_query": {"lib/type": "mbql/query",
            "stages": [{"lib/type": "mbql.stage/native", "native": sql,
                        "template-tags": {t: {} for t in tags}}]}}

def _card(name, display, dims=(), sql="SELECT 1"):
    return {"name": name, "display": display,
            "visualization_settings": {"graph.dimensions": list(dims)},
            "dataset_query": {"type": "native", "native": {"query": sql}}}

def test_native_and_tags_legacy_format():
    sql, tags = conv_lib.native_and_tags(_native("SELECT SUM(conversions_1)", ["clients", "date"]))
    assert "conversions_1" in sql and tags.keys() == {"clients", "date"}

def test_native_and_tags_stages_format():
    sql, tags = conv_lib.native_and_tags(_staged("SELECT SUM(custom_conversions_1)", ["clients", "date"]))
    assert "custom_conversions_1" in sql and set(tags) == {"clients", "date"}

def test_native_and_tags_legacy_query_fallback():
    card = {"legacy_query": json.dumps({"type": "native", "native": {"query": "SELECT 1", "template-tags": {"date": {}}}})}
    sql, tags = conv_lib.native_and_tags(card)
    assert sql == "SELECT 1" and set(tags) == {"date"}

def test_old_columns_detects_positional_not_custom():
    sql = "SELECT SUM(global.campaign_daily_metrics.conversions_1), SUM(custom_conversions_1) "
    assert conv_lib.old_conversion_columns(sql) == {"CONVERSIONS_1"}

def test_old_columns_base_not_matched_inside_positional():
    assert conv_lib.old_conversion_columns("SELECT SUM(conversions_12)") == {"CONVERSIONS_12"}

def test_old_columns_ignores_conversion_type_filter():
    assert conv_lib.old_conversion_columns("WHERE conversion_type = 'x'") == set()

def test_new_columns_named_and_custom():
    sql = "SELECT SUM(purchases), SUM(custom_conversions_2_value)"
    assert conv_lib.new_conversion_columns(sql) == {"PURCHASES", "CUSTOM_CONVERSIONS_2_VALUE"}

def test_slot_old_columns():
    assert conv_lib.slot_old_columns(0) == ("CONVERSIONS", "CONVERSION_VALUE")
    assert conv_lib.slot_old_columns(3) == ("CONVERSIONS_3", "CONVERSION_3_VALUE")

def test_type_to_slot():
    assert conv_lib.TYPE_TO_SLOT["Main conversion"] == 0
    assert conv_lib.TYPE_TO_SLOT["1st conversion"] == 1
    assert conv_lib.TYPE_TO_SLOT["3rd conversion"] == 3
    assert conv_lib.TYPE_TO_SLOT["19th conversion"] == 19

def test_new_type_columns_custom_and_named():
    assert conv_lib.new_type_columns("Custom 1") == ("CUSTOM_CONVERSIONS_1", "CUSTOM_CONVERSIONS_1_VALUE")
    assert conv_lib.new_type_columns("Custom 2") == ("CUSTOM_CONVERSIONS_2", "CUSTOM_CONVERSIONS_2_VALUE")
    assert conv_lib.new_type_columns("Purchases") == ("PURCHASES", "PURCHASES_VALUE")
    assert conv_lib.new_type_columns("Sign ups") == ("SIGN_UPS", None)

def test_build_client_mappings_resolves_consistent_and_flags_unmapped_conflict():
    records = [
        {"client": "Pro Nutrition", "type": "Main conversion", "new_type": "Purchases"},
        {"client": "Pro Nutrition", "type": "Main conversion", "new_type": "Purchases"},
        {"client": "Pro Nutrition", "type": "1st conversion", "new_type": "Custom 1"},
        {"client": "Pro Nutrition", "type": "3rd conversion", "new_type": "Custom 2"},
        {"client": "Pro Nutrition", "type": "1st conversion", "new_type": None},
        {"client": "Acme", "type": "Main conversion", "new_type": None},
        {"client": "Acme", "type": "2nd conversion", "new_type": "Leads"},
        {"client": "Acme", "type": "2nd conversion", "new_type": "Purchases"},
    ]
    m = conv_lib.build_client_mappings(records)
    assert m["Pro Nutrition"][0] == "Purchases"
    assert m["Pro Nutrition"][1] == "Custom 1"
    assert m["Pro Nutrition"][3] == "Custom 2"
    assert m["Acme"][0] == conv_lib.UNMAPPED
    assert m["Acme"][2] == conv_lib.CONFLICT

def test_metric_kind():
    assert conv_lib.metric_kind("Conversions 1") == "COUNT"
    assert conv_lib.metric_kind("CR (conversions 1)") == "RATE"
    assert conv_lib.metric_kind("CAC (Custom Conversion 1)") == "CAC"
    assert conv_lib.metric_kind("ROAS (Custom Conversion 1)") == "ROAS"
    assert conv_lib.metric_kind("Custom Conversion 1 value") == "VALUE"
    assert conv_lib.metric_kind("Avg. custom 1 value") == "AVG"

def test_card_shape():
    s = conv_lib.card_shape(_card("Conversions 1 by date, campaign channel", "bar", ["date"]))
    assert s == ("bar", "COUNT", ("channel", "date"))

def test_card_shape_ignores_dims_on_scalar_displays():
    # smartscalar cards carry inconsistent leftover graph.dimensions -> must be ignored
    assert conv_lib.card_shape(_card("Custom Conversion 1", "smartscalar", ["date"])) == ("smartscalar", "COUNT", ())
    # non-scalar displays still use dimensions as the breakdown signal
    assert conv_lib.card_shape(_card("Conversions 1", "line", ["date"])) == ("line", "COUNT", ("date",))

CDM = "global.campaign_daily_metrics"

def test_conversion_source():
    assert conv_lib.conversion_source(f"SELECT SUM(conversions_1) FROM {CDM} WHERE x") == CDM
    ga4 = "analytics.google__analytics_per_location"
    assert conv_lib.conversion_source(f"SELECT SUM({ga4}.conversions) FROM {ga4}") == ga4
    assert conv_lib.conversion_source("SELECT 1") is None

def _e(cid, kpis, display="smartscalar", brand=False, source=CDM):
    return {"id": cid, "source": source, "display": display, "kpis": list(kpis), "brand": brand}

def _chart(name, display, metrics, dims=("date",), sql=None):
    return {"name": name, "display": display,
            "visualization_settings": {"graph.metrics": list(metrics), "graph.dimensions": list(dims)},
            "dataset_query": {"type": "native", "native": {"query": sql or f"SELECT SUM(conversions_1) FROM {CDM}"}}}

def test_series_kind_cost_not_cos():
    assert conv_lib.series_kind("COST") == "COST" and conv_lib.series_kind("Spend") == "COST"
    assert conv_lib.series_kind("COS (Custom Conversion 1)") == "COS"
    assert conv_lib.series_kind("CAC_CUSTOM_CONVERSIONS_1") == "CAC"
    assert conv_lib.series_kind("CUSTOM_CONVERSIONS_1") == "CONV"

def test_resolve_picks_by_metric_kind_on_scalar():
    old = _card("Conversions 1", "smartscalar", sql=f"SELECT SUM(conversions_1) FROM {CDM}")
    new_index = {("CUSTOM_CONVERSIONS_1", ()): [_e(42635, ["COUNT"]), _e(42631, ["CAC"])]}
    res = conv_lib.resolve_new_card(old, {1: "Custom 1"}, new_index)
    assert res["status"] == "ok" and res["new_card_id"] == 42635 and res["new_col"] == "CUSTOM_CONVERSIONS_1"

def test_resolve_disambiguates_without_brand_smartscalar():
    # TILE 1: old CAC tile has no hardcoded brand exclusion -> plain card 42631, not 42632
    old = _card("CAC (conversions 1)", "smartscalar", sql=f"SELECT SUM(conversions_1) FROM {CDM}")
    new_index = {("CUSTOM_CONVERSIONS_1", ()): [_e(42631, ["CAC"], brand=False), _e(42632, ["CAC"], brand=True)]}
    res = conv_lib.resolve_new_card(old, {1: "Custom 1"}, new_index)
    assert res["status"] == "ok" and res["new_card_id"] == 42631

def test_resolve_disambiguates_by_kpi_set_chart():
    # TILE 2: old combo shows {CONV, CAC}; pick the candidate with the same KPI set
    old = _chart("CAC 1, conversions 1 by date", "combo", ["CONVERSIONS_1", "CAC_1"])
    new_index = {("CUSTOM_CONVERSIONS_1", ("date",)): [
        _e(42580, ["CAC", "CONV"], display="combo"), _e(42584, ["CAC", "COST"], display="combo")]}
    res = conv_lib.resolve_new_card(old, {1: "Custom 1"}, new_index)
    assert res["status"] == "ok" and res["new_card_id"] == 42580

def test_resolve_is_display_agnostic():
    # TILE 3: old is a BAR; only the KPI-matching COMBO candidate exists -> still matches
    old = _chart("CAC 1, conversions 1, cost by date", "bar", ["CONVERSIONS_1", "CAC_1", "COST"])
    new_index = {("CUSTOM_CONVERSIONS_1", ("date",)): [_e(42582, ["CAC", "CONV", "COST"], display="combo")]}
    res = conv_lib.resolve_new_card(old, {1: "Custom 1"}, new_index)
    assert res["status"] == "ok" and res["new_card_id"] == 42582

def test_resolve_prefers_same_display_then_multi():
    old = _chart("Conversions 1 by date", "line", ["CONVERSIONS_1"])
    new_index = {("CUSTOM_CONVERSIONS_1", ("date",)): [_e(1, ["CONV"], "bar"), _e(2, ["CONV"], "line")]}
    assert conv_lib.resolve_new_card(old, {1: "Custom 1"}, new_index)["new_card_id"] == 2
    idx2 = {("CUSTOM_CONVERSIONS_1", ("date",)): [_e(1, ["CONV"], "bar"), _e(2, ["CONV"], "pie")]}
    r2 = conv_lib.resolve_new_card(old, {1: "Custom 1"}, idx2)
    assert r2["status"] == "multi" and set(r2["candidates"]) == {1, 2}

def test_resolve_new_card_source_mismatch_goes_to_review():
    ga4 = "analytics.google__analytics_per_location"
    old = _card("Main conversions", "smartscalar", sql=f"SELECT SUM({ga4}.conversions) FROM {ga4}")
    new_index = {("PURCHASES", ()): [_e(111, ["COUNT"], source=CDM)]}
    res = conv_lib.resolve_new_card(old, {0: "Purchases"}, new_index)
    assert res["status"] == "review" and res["source"] == ga4 and "source" in res["reason"]

def test_resolve_new_card_multi_slot_combo_goes_to_review():
    old = _card("Conversions + conversions 1 + conversions 3", "bar",
                sql=f"SELECT SUM(conversions)+SUM(conversions_1)+SUM(conversions_3) FROM {CDM}")
    res = conv_lib.resolve_new_card(old, {0: "Purchases", 1: "Custom 1", 3: "Custom 2"}, {})
    assert res["status"] == "review" and res["slots"] == [0, 1, 3]

def test_resolve_new_card_value_card_uses_value_columns():
    old = _card("Conversions 1 value", "smartscalar", sql=f"SELECT SUM(conversion_1_value) FROM {CDM}")
    new_index = {("CUSTOM_CONVERSIONS_1_VALUE", ()): [_e(42636, ["VALUE"])]}
    res = conv_lib.resolve_new_card(old, {1: "Custom 1"}, new_index)
    assert res["status"] == "ok" and res["new_card_id"] == 42636
    assert res["old_col"] == "CONVERSION_1_VALUE" and res["new_col"] == "CUSTOM_CONVERSIONS_1_VALUE"

def test_tag_rename_map_matches_by_field_id():
    old = {"dataset_query": {"type": "native", "native": {"query": "x", "template-tags": {
        "location": {"type": "dimension", "dimension": ["field", {}, 396836]},
        "date": {"type": "dimension", "dimension": ["field", {}, 1]}}}}}
    new = {"dataset_query": {"type": "native", "native": {"query": "x", "template-tags": {
        "campaign_location": {"type": "dimension", "dimension": ["field", {}, 396836]},
        "date": {"type": "dimension", "dimension": ["field", {}, 1]}}}}}
    assert conv_lib.tag_rename_map(old, new) == {"location": "campaign_location"}

def test_resolve_new_card_unmapped_slot():
    old = _card("Conversions 2", "smartscalar", sql="SELECT SUM(conversions_2)")
    res = conv_lib.resolve_new_card(old, {2: conv_lib.UNMAPPED}, {})
    assert res["status"] == "unmapped"

def test_resolve_new_card_no_shape_match_goes_to_review():
    old = _card("Conversions 1 by URL", "table", ["url"], sql="SELECT SUM(conversions_1)")
    res = conv_lib.resolve_new_card(old, {1: "Custom 1"}, {})
    assert res["status"] == "review" and res["reason"]

def test_literals_never_detected_nor_rewritten():
    sql = "SELECT SUM(conversions_1) FROM t WHERE event = 'conversions_1' AND label = 'conversions'"
    assert conv_lib.old_conversion_columns(sql) == {"CONVERSIONS_1"}
    out = conv_lib.apply_substitution(sql, {"CONVERSIONS_1": "CUSTOM_CONVERSIONS_1"})
    assert "SUM(custom_conversions_1)" in out
    assert "event = 'conversions_1'" in out and "label = 'conversions'" in out  # littéraux intacts

def test_metric_kind_french():
    assert conv_lib.metric_kind("Taux de conversion 1") == "RATE"
    assert conv_lib.metric_kind("Coût par conversion") == "CAC"
    assert conv_lib.metric_kind("Panier moyen") == "AVG"
    assert conv_lib.metric_kind("Valeur conversion 1") == "VALUE"
    assert conv_lib.metric_kind("Ajouts au panier") == "COUNT"  # PAS un AVG

def test_series_kind_avg_before_value():
    assert conv_lib.series_kind("AVG_CONVERSION_1_VALUE") == "AVG"  # aligné avec metric_kind

def test_conversion_source_deterministic_with_alias():
    sql = ("SELECT SUM(a.conversions_1) FROM global.social_ad_daily_metrics a "
           "JOIN global.social_adset_daily_metrics b ON a.x=b.x")
    for _ in range(5):
        assert conv_lib.conversion_source(sql) == "global.social_ad_daily_metrics"

def test_has_opaque_refs():
    assert conv_lib.has_opaque_refs("SELECT * FROM x WHERE {{snippet: conv filter}}")
    assert conv_lib.has_opaque_refs("SELECT * FROM {{#1234-perf}} t")
    assert not conv_lib.has_opaque_refs("SELECT SUM(conversions_1) FROM t WHERE {{date}}")

def test_incompatible_wired_tags_temporal_unit():
    old = {"dataset_query": {"type": "native", "native": {"query": "x", "template-tags": {
        "time_period": {"type": "dimension", "dimension": ["field", {}, 99]},
        "date": {"type": "dimension", "dimension": ["field", {}, 1]}}}}}
    new = {"dataset_query": {"type": "native", "native": {"query": "x", "template-tags": {
        "time_period": {"type": "temporal-unit", "dimension": ["field", {}, 99]},
        "date": {"type": "dimension", "dimension": ["field", {}, 1]}}}}}
    bad = conv_lib.incompatible_wired_tags(old, new, {"time_period", "date"})
    assert bad == {"time_period": ("dimension", "temporal-unit")}

def test_breakdown_conversion_type_vs_campaign_type():
    assert conv_lib.card_shape(_card("Conversions by conversion type", "pie"))[2] == ("conversion_type",)
    assert conv_lib.card_shape(_card("Conversions by campaign type", "pie"))[2] == ("type",)
    assert conv_lib.card_shape(_card("Conversions 1 by campaign", "pie"))[2] == ("campaign",)

def test_substitution_map():
    mapping = {0: "Purchases", 1: "Custom 1", 3: "Custom 2", 2: conv_lib.UNMAPPED}
    sub, unm = conv_lib.substitution_map(
        {"CONVERSIONS", "CONVERSION_VALUE", "CONVERSIONS_1", "CONVERSION_1_VALUE", "CONVERSIONS_3", "CONVERSIONS_2"}, mapping)
    assert sub["CONVERSIONS"] == "PURCHASES" and sub["CONVERSION_VALUE"] == "PURCHASES_VALUE"
    assert sub["CONVERSIONS_1"] == "CUSTOM_CONVERSIONS_1" and sub["CONVERSION_1_VALUE"] == "CUSTOM_CONVERSIONS_1_VALUE"
    assert sub["CONVERSIONS_3"] == "CUSTOM_CONVERSIONS_2"  # slot 3 -> Custom 2 (number differs!)
    assert "CONVERSIONS_2" in unm

def test_apply_substitution_whole_word_and_case():
    sub = {"CONVERSIONS_1": "CUSTOM_CONVERSIONS_1", "CONVERSIONS": "PURCHASES"}
    sql = "SUM(global.x.conversions_1) AS conversions_1, SUM(x.conversions) AS conversions, x.conversions_10"
    out = conv_lib.apply_substitution(sql, sub)
    assert out.count("custom_conversions_1") == 2
    assert "purchases" in out and "purchases_1" not in out  # base didn't bleed into conversions_1
    assert "conversions_10" in out  # different slot, not in map -> untouched

def test_apply_substitution_uppercase_viz():
    assert conv_lib.apply_substitution('["name","CONVERSIONS_1"]', {"CONVERSIONS_1": "CUSTOM_CONVERSIONS_1"}) \
        == '["name","CUSTOM_CONVERSIONS_1"]'

def test_series_display_map_masks_brand_excluded():
    # cas réel 27976 -> 42582 : la 4e série hors-brand doit être écartée du mapping
    old = ["CONVERSIONS_1", "CAC_1", "COST"]
    new = ["CUSTOM_CONVERSIONS_1", "CAC_CUSTOM_CONVERSIONS_1", "COST",
           "CAC_CUSTOM_CONVERSIONS_1_BRAND_EXCLUDED"]
    assert conv_lib.series_display_map(old, new) == \
        ["CUSTOM_CONVERSIONS_1", "CAC_CUSTOM_CONVERSIONS_1", "COST"]

def test_series_display_map_brand_excluded_wanted():
    # si l'ANCIENNE série est déjà hors-brand, on mappe vers la variante hors-brand
    old = ["CAC_1_BRAND_EXCLUDED"]
    new = ["CAC_CUSTOM_CONVERSIONS_1", "CAC_CUSTOM_CONVERSIONS_1_BRAND_EXCLUDED"]
    assert conv_lib.series_display_map(old, new) == ["CAC_CUSTOM_CONVERSIONS_1_BRAND_EXCLUDED"]

def test_series_display_map_refuses_ambiguous_or_missing():
    # deux candidates CAC non hors-brand -> ambigu -> None
    assert conv_lib.series_display_map(["CAC_1"], ["CAC_A", "CAC_B"]) is None
    # nature absente de la nouvelle carte -> None
    assert conv_lib.series_display_map(["ROAS"], ["CUSTOM_CONVERSIONS_1"]) is None
    # deux anciennes séries qui tomberaient sur la même nouvelle -> None (non injectif)
    assert conv_lib.series_display_map(["CONVERSIONS", "CONVERSIONS_1"], ["CUSTOM_CONVERSIONS_1"]) is None

def test_fix_brand_clause_single_wrong_atom():
    # règle finale (user 2026-06-12) : paire type LIKE '%brand%' + category == 'brand' STRICT
    sql = "AND CASE WHEN b.brand_included = 'no' THEN LOWER(coalesce(reports.campaign_details.campaign_location,'')) NOT LIKE '%brand%' ELSE 1 = 1 END"
    out = conv_lib.fix_brand_clause(sql)
    assert "LOWER(coalesce(reports.campaign_details.campaign_type,'')) NOT LIKE '%brand%'" in out
    assert "LOWER(TRIM(coalesce(reports.campaign_details.campaign_category,''))) != 'brand'" in out
    assert "campaign_location" not in out
    assert out.count("NOT LIKE '%brand%'") == 1 and out.count("!= 'brand'") == 1

def test_fix_brand_clause_chain_collapses():
    # cas réel cité par l'utilisateur : channel AND category(LIKE) -> UNE paire canonique
    sql = ("CASE WHEN b.brand_included = 'no' THEN "
           "LOWER(coalesce(reports.campaign_details.campaign_channel,'')) NOT LIKE '%brand%' "
           "AND LOWER(coalesce(reports.campaign_details.campaign_category,'')) NOT LIKE '%brand%' "
           "ELSE 1 = 1 END")
    out = conv_lib.fix_brand_clause(sql)
    assert out.count("NOT LIKE '%brand%'") == 1 and out.count("!= 'brand'") == 1
    assert "campaign_channel" not in out and "campaign_category,'')) NOT LIKE" not in out

def test_fix_brand_clause_category_plus_type_dedupes():
    sql = ("THEN LOWER(coalesce(cd.campaign_category,'')) NOT LIKE '%brand%'\n"
           "    AND LOWER(coalesce(cd.campaign_type,'')) NOT LIKE '%brand%' ELSE")
    out = conv_lib.fix_brand_clause(sql)
    assert out.count("NOT LIKE '%brand%'") == 1 and out.count("!= 'brand'") == 1
    assert "LOWER(coalesce(cd.campaign_type,'')) NOT LIKE '%brand%'" in out
    assert "LOWER(TRIM(coalesce(cd.campaign_category,''))) != 'brand'" in out

def test_fix_brand_clause_idempotent_and_upgrades_v1():
    # idempotent sur sa propre sortie, et la sortie v1 (type seul) est promue en paire
    v1 = "THEN LOWER(coalesce(reports.campaign_details.campaign_type,'')) NOT LIKE '%brand%' ELSE"
    out = conv_lib.fix_brand_clause(v1)
    assert out.count("!= 'brand'") == 1
    assert conv_lib.fix_brand_clause(out) == out

def test_strip_brand_atoms_makes_clause_variants_equal():
    # le gate du batch : stripped(old) == stripped(new) ssi seule la clause brand change
    old = ("SELECT x FROM t WHERE 1=1 AND CASE WHEN b.brand_included = 'no' THEN "
           "LOWER(coalesce(cd.campaign_channel,'')) NOT LIKE '%brand%' "
           "AND LOWER(coalesce(cd.campaign_category,'')) NOT LIKE '%brand%' ELSE 1 = 1 END")
    new = conv_lib.fix_brand_clause(old)
    assert new != old
    assert conv_lib.strip_brand_atoms(old) == conv_lib.strip_brand_atoms(new)

def test_strip_brand_atoms_detects_collateral_change():
    old = "THEN LOWER(coalesce(cd.campaign_type,'')) NOT LIKE '%brand%' ELSE SUM(cost) AS spend"
    tampered = "THEN LOWER(coalesce(cd.campaign_type,'')) NOT LIKE '%brand%' ELSE SUM(revenue) AS spend"
    assert conv_lib.strip_brand_atoms(old) != conv_lib.strip_brand_atoms(tampered)

def test_strip_brand_atoms_idempotent_on_canonical_pair():
    canon = ("THEN LOWER(coalesce(cd.campaign_type,'')) NOT LIKE '%brand%' "
             "AND LOWER(TRIM(coalesce(cd.campaign_category,''))) != 'brand' ELSE")
    bare = "THEN §B§ ELSE"
    assert conv_lib.strip_brand_atoms(canon) == bare

# --- swap de tableaux multi-slot : mapping de colonnes vers la famille mixte ---
NEW49104 = {  # colonnes réelles (extrait) du tableau mixte « by date »
    "CURRENT_TIME_PERIOD", "CURRENT_IMPRESSIONS", "CURRENT_CTR", "CURRENT_CLICKS", "CURRENT_CPC", "CURRENT_COST",
    "CURRENT_PURCHASES", "CURRENT_PURCHASES_CR", "CURRENT_PURCHASES_CAC", "CURRENT_PURCHASES_VALUE",
    "CURRENT_AVG_PURCHASES_VALUE", "CURRENT_PURCHASES_ROAS",
    "CURRENT_CUSTOM_CONVERSIONS_1", "CURRENT_CUSTOM_CONVERSIONS_1_CR", "CURRENT_CUSTOM_CONVERSIONS_1_CAC",
}
PN = {0: "Purchases", 1: "Custom 1", 3: "Custom 2"}

def test_table_column_map_main_slot_and_base():
    old = ["DATE", "COST", "IMPRESSIONS", "CONVERSIONS", "CONV_RATE", "CAC",
           "AVG_CONV_VALUE", "CONVERSION_VALUE", "ROAS"]
    m, un = conv_lib.map_table_columns(old, PN, NEW49104, "CURRENT_TIME_PERIOD")
    assert m["DATE"] == "CURRENT_TIME_PERIOD"
    assert m["COST"] == "CURRENT_COST" and m["IMPRESSIONS"] == "CURRENT_IMPRESSIONS"
    assert m["CONVERSIONS"] == "CURRENT_PURCHASES"
    assert m["CONV_RATE"] == "CURRENT_PURCHASES_CR"
    assert m["CAC"] == "CURRENT_PURCHASES_CAC"
    assert m["AVG_CONV_VALUE"] == "CURRENT_AVG_PURCHASES_VALUE"
    assert m["CONVERSION_VALUE"] == "CURRENT_PURCHASES_VALUE"
    assert m["ROAS"] == "CURRENT_PURCHASES_ROAS"
    assert un == []

def test_table_column_map_positional_slot_via_client_mapping():
    old = ["CONVERSIONS_1", "CR_1", "CAC_1"]
    m, un = conv_lib.map_table_columns(old, PN, NEW49104, "CURRENT_TIME_PERIOD")
    # slot 1 -> Custom 1 (PAS custom_conversions_1 par hasard : c'est le mapping Airtable)
    assert m["CONVERSIONS_1"] == "CURRENT_CUSTOM_CONVERSIONS_1"
    assert m["CR_1"] == "CURRENT_CUSTOM_CONVERSIONS_1_CR"
    assert m["CAC_1"] == "CURRENT_CUSTOM_CONVERSIONS_1_CAC"
    assert un == []

def test_table_column_map_current_prefixed_source():
    # carte 5710 : colonnes déjà préfixées CURRENT_
    old = ["CURRENT_CONVERSIONS", "CURRENT_CAC_1", "CURRENT_COST"]
    m, _ = conv_lib.map_table_columns(old, PN, NEW49104, "CURRENT_TIME_PERIOD")
    assert m["CURRENT_CONVERSIONS"] == "CURRENT_PURCHASES"
    assert m["CURRENT_CAC_1"] == "CURRENT_CUSTOM_CONVERSIONS_1_CAC"
    assert m["CURRENT_COST"] == "CURRENT_COST"

def test_table_column_map_alias_names_and_bare_dim():
    # variantes de nommage rencontrées chez Goodiespub
    new = NEW49104 | {"CURRENT_CAMPAIGN_CHANNEL"}
    old = ["CHANNEL", "CONVERSION_RATE", "REVENUE", "AVG_REVENUE"]
    m, un = conv_lib.map_table_columns(old, PN, new, "CURRENT_CAMPAIGN_CHANNEL")
    assert m["CHANNEL"] == "CURRENT_CAMPAIGN_CHANNEL"          # dimension nue
    assert m["CONVERSION_RATE"] == "CURRENT_PURCHASES_CR"      # alias de CONV_RATE
    assert m["REVENUE"] == "CURRENT_PURCHASES_VALUE"           # alias de CONVERSION_VALUE
    assert m["AVG_REVENUE"] == "CURRENT_AVG_PURCHASES_VALUE"   # alias de AVG_CONV_VALUE
    assert un == []

def test_table_column_map_evolution_columns():
    # tableaux « KPIs evolution » : colonnes _EVOLUTION (sans préfixe CURRENT_ côté neuf)
    new = NEW49104 | {"COST_EVOLUTION", "PURCHASES_EVOLUTION", "PURCHASES_CAC_EVOLUTION",
                      "AVG_PURCHASES_VALUE_EVOLUTION", "CUSTOM_CONVERSIONS_1_CR_EVOLUTION"}
    old = ["COST_EVOLUTION", "CONVERSIONS_EVOLUTION", "CAC_EVOLUTION",
           "AVG_CONV_VALUE_EVOLUTION", "CR_1_EVOLUTION"]
    m, un = conv_lib.map_table_columns(old, PN, new, "CURRENT_TIME_PERIOD")
    assert m["COST_EVOLUTION"] == "COST_EVOLUTION"
    assert m["CONVERSIONS_EVOLUTION"] == "PURCHASES_EVOLUTION"
    assert m["CAC_EVOLUTION"] == "PURCHASES_CAC_EVOLUTION"
    assert m["AVG_CONV_VALUE_EVOLUTION"] == "AVG_PURCHASES_VALUE_EVOLUTION"
    assert m["CR_1_EVOLUTION"] == "CUSTOM_CONVERSIONS_1_CR_EVOLUTION"
    assert un == []

def test_table_column_map_unmapped_slot_and_missing_target():
    # slot 2 non mappé chez PN (new_type absent) -> unmapped ; cible inexistante -> unmapped
    old = ["CONVERSIONS_2", "CONVERSIONS_3"]  # slot2=∅, slot3=Custom 2 mais absent de NEW49104
    m, un = conv_lib.map_table_columns(old, PN, NEW49104, "CURRENT_TIME_PERIOD")
    assert "CONVERSIONS_2" in un  # pas de mapping client
    assert "CONVERSIONS_3" in un  # mappé Custom 2 mais colonne absente de la carte cible

def test_displayed_cells_restricts_and_sorts():
    cols = ["DATE", "CONVERSIONS_1", "CAC_1", "EXTRA"]
    rows = [["2026-05-04", 10.0, 2.5, 99.0], ["2026-05-11", 20.0, 1.25, 99.0]]
    assert conv_lib.displayed_cells(cols, rows, ["conversions_1", "CAC_1"]) == [1.25, 2.5, 10.0, 20.0]
    # sans restriction : toutes les cellules numériques
    assert 99.0 in conv_lib.displayed_cells(cols, rows, None)


def test_split_pairs_single():
    assert conv_lib.split_multiselect_pairs("Main conversion", "Purchases") == ([("Main conversion", "Purchases")], False)

def test_split_pairs_equal_multi_positional():
    pairs, amb = conv_lib.split_multiselect_pairs("Add to cart,3rd conversion", "Add to cart,Custom 2")
    assert pairs == [("Add to cart", "Add to cart"), ("3rd conversion", "Custom 2")] and amb is False

def test_split_pairs_type_without_new_type_is_unmapped_not_ambiguous():
    assert conv_lib.split_multiselect_pairs("2nd conversion", "") == ([("2nd conversion", None)], False)

def test_split_pairs_cardinality_mismatch_flags_ambiguous():
    pairs, amb = conv_lib.split_multiselect_pairs("Main conversion,1st conversion", "Purchases")
    assert pairs == [("Main conversion", None), ("1st conversion", None)] and amb is True

def test_split_pairs_trims_whitespace_and_empty_type():
    assert conv_lib.split_multiselect_pairs(" Main conversion , 1st conversion ", "Purchases, Custom 1")[0] == \
        [("Main conversion", "Purchases"), ("1st conversion", "Custom 1")]
    assert conv_lib.split_multiselect_pairs("", "") == ([], False)

def _visualizer_viz(src_cid):
    return {"visualization": {"display": "line", "columnValuesMapping": {
        "COLUMN_1": [{"sourceId": f"card:{src_cid}", "originalName": "CPC", "name": "COLUMN_1"}],
        "COLUMN_2": [{"sourceId": f"card:{src_cid}", "originalName": "TIME_PERIOD", "name": "COLUMN_2"}]},
        "settings": {"graph.metrics": ["COLUMN_1"]}}}

def test_repoint_visualizer_rewrites_all_source_refs():
    out = conv_lib.repoint_visualizer_source(_visualizer_viz(2116), 2116, 49953)
    refs = {m[0]["sourceId"] for m in out["visualization"]["columnValuesMapping"].values()}
    assert refs == {"card:49953"}

def test_repoint_visualizer_noop_when_no_visualizer():
    viz = {"graph.dimensions": ["TIME_PERIOD"], "graph.metrics": ["CPC"]}
    assert conv_lib.repoint_visualizer_source(viz, 2116, 49953) == viz

def test_repoint_visualizer_does_not_touch_other_cards():
    # une réf vers une AUTRE carte (card:21160) ne doit pas être altérée par old=2116
    viz = {"visualization": {"columnValuesMapping": {
        "C1": [{"sourceId": "card:21160", "originalName": "X", "name": "C1"}]}}}
    out = conv_lib.repoint_visualizer_source(viz, 2116, 49953)
    assert out["visualization"]["columnValuesMapping"]["C1"][0]["sourceId"] == "card:21160"

def test_repoint_visualizer_noop_old_equals_new_and_none():
    viz = _visualizer_viz(2116)
    assert conv_lib.repoint_visualizer_source(viz, 2116, 2116) is viz
    assert conv_lib.repoint_visualizer_source(None, 2116, 49953) is None

def test_substitute_viz_preserves_human_labels_but_swaps_column_refs():
    viz = {
        "card.title": "Conversions",                       # libellé humain -> INCHANGÉ
        "graph.metrics": ["conversions", "cac"],           # réfs colonnes -> substituées
        "graph.x_axis.title_text": "Conversions par jour", # libellé axe -> INCHANGÉ
        "scalar.field": "conversions",                     # réf colonne -> substituée
        "series_settings": {"conversions": {"title": "Mes Conversions", "color": "#fff"}},
        "column_settings": {'["name","CONVERSIONS"]': {"column_title": "Conversions", "number_style": "decimal"}},
    }
    out = conv_lib.substitute_viz(viz, {"CONVERSIONS": "PURCHASES"})
    assert out["card.title"] == "Conversions"                       # titre préservé
    assert out["graph.metrics"] == ["purchases", "cac"]            # réfs substituées
    assert out["graph.x_axis.title_text"] == "Conversions par jour"
    assert out["scalar.field"] == "purchases"
    assert "purchases" in out["series_settings"]                    # clé série substituée
    assert out["series_settings"]["purchases"]["title"] == "Mes Conversions"  # titre série préservé
    assert '["name","PURCHASES"]' in out["column_settings"]         # clé column_settings substituée
    assert out["column_settings"]['["name","PURCHASES"]']["column_title"] == "Conversions"  # column_title préservé

def test_substitute_viz_noop_on_empty():
    assert conv_lib.substitute_viz({}, {"CONVERSIONS": "PURCHASES"}) == {}
    assert conv_lib.substitute_viz(None, {"CONVERSIONS": "PURCHASES"}) is None

def test_conversion_display_names_maps_slots_and_skips_unmapped():
    cmap = {0: "Purchases", 1: "__UNMAPPED__", 2: "Custom 2"}
    assert conv_lib.conversion_display_names({"CONVERSIONS": "PURCHASES"}, cmap) == {"Purchases"}
    assert conv_lib.conversion_display_names(["CONVERSIONS_2"], cmap) == {"Custom 2"}
    assert conv_lib.conversion_display_names(["CONVERSIONS_1"], cmap) == set()  # __UNMAPPED__ ignoré

def test_relabel_generic_title_to_named_conversion():
    assert conv_lib.relabel_conversion_title("Conversions", {"Purchases"}) == "Purchases"
    assert conv_lib.relabel_conversion_title("conversion", {"Leads"}) == "Leads"

def test_relabel_preserves_business_label_and_rates():
    assert conv_lib.relabel_conversion_title("Demandes de devis", {"Purchases"}) == "Demandes de devis"
    assert conv_lib.relabel_conversion_title("Conversion rate", {"Purchases"}) == "Conversion rate"

def test_relabel_preserves_when_ambiguous_or_no_display():
    assert conv_lib.relabel_conversion_title("Conversions", {"Purchases", "Leads"}) == "Conversions"
    assert conv_lib.relabel_conversion_title("Conversions", set()) == "Conversions"

def test_is_required_param_error_recognizes_benign_cases():
    assert conv_lib.is_required_param_error('Cannot run the query: missing required parameters: #{"bonus"}')
    assert conv_lib.is_required_param_error("You'll need to pick a value for 'Breakdown'")
    assert conv_lib.is_required_param_error("This parameter is required before this query can run")

def test_is_required_param_error_false_on_real_sql_error():
    assert not conv_lib.is_required_param_error("SQL compilation error: invalid identifier 'CONVERSIONS_X'")
    assert not conv_lib.is_required_param_error("")
    assert not conv_lib.is_required_param_error(None)

def test_normalize_period_label_aligns_week_formats():
    assert conv_lib.normalize_period_label("2026 - W22") == conv_lib.normalize_period_label("2026_22") == (2026, 22)
    assert conv_lib.normalize_period_label("2026-05") == (2026, 5)
    assert conv_lib.normalize_period_label("Total") == "TOTAL"  # sans chiffre -> libellé exact


def test_drop_conversion_selects_removes_unmapped_positional():
    # brique b : après substitution des slots mappés, retirer les items SELECT des slots NON mappés
    # (y compris les dérivés cac_N qui référencent conversions_N) -> 0 colonne positionnelle (Iron Law).
    sql = ("SELECT\n"
           "  SUM(purchases) AS purchases,\n"
           "  SUM(conversions_2) AS conversions_2,\n"
           "  COALESCE(SUM(cost)/NULLIF(SUM(conversions_2),0),0) AS cac_2,\n"
           "  SUM(conversion_2_value) AS conversion_2_value\n"
           "FROM data")
    out = conv_lib.drop_conversion_selects(sql)
    assert conv_lib.old_conversion_columns(out) == set()   # plus aucune colonne positionnelle
    assert "purchases" in out                              # la conversion nommée (mappée) reste
    assert "cac_2" not in out                              # le dérivé référençant conversions_2 part aussi
    assert not re.search(r",\s*FROM", out)                 # pas de virgule pendante avant FROM


def test_drop_conversion_selects_noop_when_no_positional():
    sql = "SELECT SUM(purchases) AS purchases,\n  SUM(clicks) AS clicks\nFROM data"
    assert conv_lib.drop_conversion_selects(sql) == sql


def test_drop_conversion_selects_keeps_named_columns_around_dropped():
    sql = ("SELECT\n"
           "  channel,\n"
           "  SUM(conversions_3) AS conversions_3,\n"
           "  SUM(clicks) AS clicks\n"
           "FROM data")
    out = conv_lib.drop_conversion_selects(sql)
    assert conv_lib.old_conversion_columns(out) == set()
    assert "channel" in out and "clicks" in out and "conversions_3" not in out


def test_drop_conversion_selects_preserves_named_and_literals():
    # named (custom_conversions_1, lookbehind '_') + littéral 'conversions_2' -> rien à retirer
    sql = ("SELECT\n"
           "  SUM(custom_conversions_1) AS custom_conversions_1,\n"
           "  'conversions_2' AS note,\n"
           "  SUM(clicks) AS clicks\n"
           "FROM data")
    assert conv_lib.drop_conversion_selects(sql) == sql


def test_drop_conversion_selects_cascades_derived_passthrough():
    # KPIs-evolution : conversions_2 (non mappé) alimente l'alias DÉRIVÉ current_conversions_2,
    # passé tel quel dans un CTE aval. La CASCADE retire toute la chaîne (plus de no-op) -> SQL propre.
    sql = ("WITH agg AS (\n"
           "  SELECT\n"
           "    SUM(conversions_2) AS current_conversions_2,\n"
           "    SUM(clicks) AS clicks\n"
           "  FROM data\n"
           ")\n"
           "SELECT\n"
           "  current_conversions_2,\n"
           "  clicks\n"
           "FROM agg")
    out = conv_lib.drop_conversion_selects(sql)
    assert conv_lib.old_conversion_columns(out) == set()
    assert "current_conversions_2" not in out
    assert "clicks" in out


def test_drop_conversion_selects_cascades_multiline_case():
    # le slot non mappé alimente une colonne d'évolution définie par un CASE MULTI-LIGNES ->
    # l'item CASE entier doit être retiré (sinon CASE orphelin = SQL cassé).
    sql = ("WITH agg AS (\n"
           "  SELECT\n"
           "    SUM(conversions_2) AS current_conversions_2,\n"
           "    SUM(clicks) AS clicks\n"
           "  FROM data\n"
           ")\n"
           "SELECT\n"
           "  clicks,\n"
           "  CASE\n"
           "    WHEN current_conversions_2 = 0 THEN 0\n"
           "    ELSE current_conversions_2 / clicks\n"
           "  END AS conversions_2_evolution\n"
           "FROM agg")
    out = conv_lib.drop_conversion_selects(sql)
    assert conv_lib.old_conversion_columns(out) == set()
    assert "conversions_2_evolution" not in out and "current_conversions_2" not in out
    assert "CASE" not in out  # pas de CASE orphelin
    assert "clicks" in out


def test_drop_conversion_selects_keeps_mapped_slot_cascade():
    # purchases (slot mappé, déjà substitué) garde son dérivé ; seul le cascade du slot NON mappé part.
    sql = ("WITH agg AS (\n"
           "  SELECT\n"
           "    SUM(purchases) AS current_purchases,\n"
           "    SUM(conversions_2) AS current_conversions_2,\n"
           "    SUM(clicks) AS clicks\n"
           "  FROM data\n"
           ")\n"
           "SELECT\n"
           "  current_purchases,\n"
           "  CASE WHEN clicks=0 THEN 0 ELSE current_purchases/clicks END AS purchases_cr,\n"
           "  CASE WHEN clicks=0 THEN 0 ELSE current_conversions_2/clicks END AS conversions_2_cr\n"
           "FROM agg")
    out = conv_lib.drop_conversion_selects(sql)
    assert conv_lib.old_conversion_columns(out) == set()
    assert "current_purchases" in out and "purchases_cr" in out       # slot mappé + dérivé préservés
    assert "current_conversions_2" not in out and "conversions_2_cr" not in out  # slot non mappé retiré
    assert "clicks" in out


def test_value_diffs_none_when_identical():
    oc = ["DATE", "CONVERSIONS"]; nc = ["DATE", "PURCHASES"]
    rows = [["w1", 10], ["w2", 20]]
    assert conv_lib.value_diffs(oc, rows, nc, [["w1", 10], ["w2", 20]], {"CONVERSIONS": "PURCHASES"}) == []


def test_value_diffs_flags_mismatched_column():
    oc = ["DATE", "CONVERSIONS"]; nc = ["DATE", "PURCHASES"]
    d = conv_lib.value_diffs(oc, [["w1", 10], ["w2", 20]], nc, [["w1", 10], ["w2", 18]],
                             {"CONVERSIONS": "PURCHASES"})
    assert len(d) == 1 and d[0][0] == "CONVERSIONS" and d[0][1] == "PURCHASES"
    assert d[0][2] == 30 and d[0][3] == 28      # (old_sum, new_sum)


def test_value_diffs_ignores_row_order():
    # comparaison par SOMME -> insensible à l'ordre des lignes (pas de faux positif)
    oc = ["D", "CONVERSIONS"]; nc = ["D", "PURCHASES"]
    d = conv_lib.value_diffs(oc, [["a", 10], ["b", 20]], nc, [["b", 20], ["a", 10]],
                             {"CONVERSIONS": "PURCHASES"})
    assert d == []


def test_value_diffs_tolerates_float_noise():
    oc = ["D", "CONVERSIONS"]; nc = ["D", "PURCHASES"]
    assert conv_lib.value_diffs(oc, [["a", 1.0000000001]], nc, [["a", 1.0]],
                                {"CONVERSIONS": "PURCHASES"}) == []


def test_value_diffs_flags_when_sum_changes_via_rows():
    # moins de lignes -> somme nommée < positionnel -> écart détecté
    oc = ["D", "CONVERSIONS"]; nc = ["D", "PURCHASES"]
    d = conv_lib.value_diffs(oc, [["a", 1], ["b", 2]], nc, [["a", 1]], {"CONVERSIONS": "PURCHASES"})
    assert len(d) == 1 and d[0][0] == "CONVERSIONS"


def test_value_diffs_skips_missing_column():
    oc = ["D", "CONVERSIONS"]; nc = ["D"]   # carte générée sans la colonne nommée -> non comparable
    assert conv_lib.value_diffs(oc, [["a", 1]], nc, [["a"]], {"CONVERSIONS": "PURCHASES"}) == []


def test_has_dashboard_questions_detects_embedded_card():
    dash = {"dashcards": [{"card": {"id": 1}}, {"card": {"id": 2, "dashboard_id": 99}}]}
    assert conv_lib.has_dashboard_questions(dash) is True


def test_has_dashboard_questions_false_when_none():
    dash = {"dashcards": [{"card": {"id": 1}}, {"card": {"id": 2, "dashboard_id": None}}]}
    assert conv_lib.has_dashboard_questions(dash) is False


def test_has_dashboard_questions_handles_ordered_cards_and_missing_card():
    assert conv_lib.has_dashboard_questions({"ordered_cards": [{"card": {}}, {}]}) is False
    assert conv_lib.has_dashboard_questions({}) is False


TESTS = [test_native_and_tags_legacy_format, test_native_and_tags_stages_format,
         test_has_dashboard_questions_detects_embedded_card, test_has_dashboard_questions_false_when_none,
         test_has_dashboard_questions_handles_ordered_cards_and_missing_card,
         test_drop_conversion_selects_removes_unmapped_positional,
         test_drop_conversion_selects_noop_when_no_positional,
         test_drop_conversion_selects_keeps_named_columns_around_dropped,
         test_drop_conversion_selects_preserves_named_and_literals,
         test_drop_conversion_selects_cascades_derived_passthrough,
         test_drop_conversion_selects_cascades_multiline_case,
         test_drop_conversion_selects_keeps_mapped_slot_cascade,
         test_value_diffs_none_when_identical, test_value_diffs_flags_mismatched_column,
         test_value_diffs_ignores_row_order, test_value_diffs_tolerates_float_noise,
         test_value_diffs_flags_when_sum_changes_via_rows, test_value_diffs_skips_missing_column,
         test_native_and_tags_legacy_query_fallback, test_old_columns_detects_positional_not_custom,
         test_old_columns_base_not_matched_inside_positional, test_old_columns_ignores_conversion_type_filter,
         test_new_columns_named_and_custom, test_slot_old_columns, test_type_to_slot,
         test_new_type_columns_custom_and_named, test_build_client_mappings_resolves_consistent_and_flags_unmapped_conflict,
         test_metric_kind, test_card_shape, test_card_shape_ignores_dims_on_scalar_displays,
         test_conversion_source, test_series_kind_cost_not_cos, test_resolve_picks_by_metric_kind_on_scalar,
         test_resolve_disambiguates_without_brand_smartscalar, test_resolve_disambiguates_by_kpi_set_chart,
         test_resolve_is_display_agnostic, test_resolve_prefers_same_display_then_multi,
         test_resolve_new_card_source_mismatch_goes_to_review,
         test_resolve_new_card_multi_slot_combo_goes_to_review, test_resolve_new_card_value_card_uses_value_columns,
         test_tag_rename_map_matches_by_field_id,
         test_resolve_new_card_unmapped_slot, test_resolve_new_card_no_shape_match_goes_to_review,
         test_substitution_map, test_apply_substitution_whole_word_and_case, test_apply_substitution_uppercase_viz,
         test_literals_never_detected_nor_rewritten, test_metric_kind_french, test_series_kind_avg_before_value,
         test_conversion_source_deterministic_with_alias, test_has_opaque_refs,
         test_incompatible_wired_tags_temporal_unit, test_breakdown_conversion_type_vs_campaign_type,
         test_series_display_map_masks_brand_excluded, test_series_display_map_brand_excluded_wanted,
         test_series_display_map_refuses_ambiguous_or_missing, test_displayed_cells_restricts_and_sorts,
         test_fix_brand_clause_single_wrong_atom, test_fix_brand_clause_chain_collapses,
         test_fix_brand_clause_category_plus_type_dedupes, test_fix_brand_clause_idempotent_and_upgrades_v1,
         test_strip_brand_atoms_makes_clause_variants_equal, test_strip_brand_atoms_detects_collateral_change,
         test_strip_brand_atoms_idempotent_on_canonical_pair, test_table_column_map_main_slot_and_base,
         test_table_column_map_positional_slot_via_client_mapping, test_table_column_map_current_prefixed_source,
         test_table_column_map_evolution_columns, test_table_column_map_alias_names_and_bare_dim,
         test_table_column_map_unmapped_slot_and_missing_target,
         test_split_pairs_single, test_split_pairs_equal_multi_positional,
         test_split_pairs_type_without_new_type_is_unmapped_not_ambiguous,
         test_split_pairs_cardinality_mismatch_flags_ambiguous, test_split_pairs_trims_whitespace_and_empty_type,
         test_repoint_visualizer_rewrites_all_source_refs, test_repoint_visualizer_noop_when_no_visualizer,
         test_repoint_visualizer_does_not_touch_other_cards, test_repoint_visualizer_noop_old_equals_new_and_none,
         test_substitute_viz_preserves_human_labels_but_swaps_column_refs, test_substitute_viz_noop_on_empty,
         test_conversion_display_names_maps_slots_and_skips_unmapped, test_relabel_generic_title_to_named_conversion,
         test_relabel_preserves_business_label_and_rates, test_relabel_preserves_when_ambiguous_or_no_display,
         test_is_required_param_error_recognizes_benign_cases, test_is_required_param_error_false_on_real_sql_error,
         test_normalize_period_label_aligns_week_formats]

def run():
    failures = 0
    for t in TESTS:
        try:
            t(); print(f"PASS  {t.__name__}")
        except Exception as e:
            failures += 1; print(f"FAIL  {t.__name__}: {e!r}")
    print(f"\n{len(TESTS) - failures}/{len(TESTS)} tests passés")
    sys.exit(1 if failures else 0)

if __name__ == "__main__":
    run()
