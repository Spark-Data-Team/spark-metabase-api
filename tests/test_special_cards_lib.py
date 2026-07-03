#!/usr/bin/env python3
"""Tests de special_cards_lib (déploiement des cartes « sélecteur » #87 -> 49788 :
swap dashcard, retarget du mapping metric dimension->variable, custom list sur le
filtre Metric du DASHBOARD). Usage : python3 tests/test_special_cards_lib.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import special_cards_lib as scl

OLD, NEW = 87, 49788
PID = "e2dc0f95"  # "Metric Left Tables" sur 6846

# tags présents sur la carte NEW (49788) ; le mapping vers une tag absente doit être droppé
NEW_TAGS = {"metric", "dimension_1", "clients", "date", "time_period",
            "campaign_type", "campaign_category", "campaign_channel"}

# le param metric de la carte NEW (source de la custom list)
SOURCE_PARAM = {
    "slug": "metric", "name": "Metric", "type": "category",
    "values_query_type": "list", "values_source_type": "static-list",
    "isMultiSelect": False, "default": "cost",
    "target": ["variable", ["template-tag", "metric"]],
    "values_source_config": {"values": [["cost", "Cost"], ["clickthrough_rate", "CTR"],
                                        ["purchases", "Purchases"], ["cac_purchases", "CAC Purchases"]]},
}


def _dc(dcid, card_id, mappings):
    return {"id": dcid, "card_id": card_id,
            "parameter_mappings": [{"parameter_id": p, "card_id": card_id, "target": t}
                                   for p, t in mappings]}


def _dim(tag):
    return ["dimension", ["template-tag", tag], {"stage-number": 0}]


def _dash():
    """Mini-dashboard fidèle à 6846 : 3 dashcards carte 87 + 1 carte non-87 indépendante."""
    return {
        "id": 99999,
        "parameters": [
            {"id": PID, "name": "Metric Left Tables", "slug": "metric_left_tables",
             "type": "category", "default": ["clickthrough_rate"]},
            {"id": "404215d", "name": "Date Filter", "slug": "date_filter", "type": "date/all-options"},
        ],
        "dashcards": [
            _dc(51676, OLD, [(PID, _dim("metric")), ("404215d", _dim("date"))]),
            _dc(51675, OLD, [(PID, _dim("metric")), ("404215d", _dim("date"))]),
            # une carte 87 dont un mapping pointe une tag ABSENTE de NEW (à dropper)
            _dc(51671, OLD, [(PID, _dim("metric")), ("404215d", _dim("date")),
                             ("zzz", _dim("ghost_tag"))]),
            # carte indépendante non-87, non concernée
            _dc(51682, 1427, [("404215d", _dim("date"))]),
        ],
    }


# --- parsing du target ---
def test_target_tag_dimension():
    assert scl._target_tag(_dim("metric")) == "metric"

def test_target_tag_variable():
    assert scl._target_tag(["variable", ["template-tag", "metric"]]) == "metric"

def test_target_tag_none_on_garbage():
    assert scl._target_tag(["dimension", ["field", 1]]) is None
    assert scl._target_tag(None) is None


# --- repérage des dashcards / params ---
def test_selector_dashcards_only_old_card():
    ids = [dc["id"] for dc in scl.selector_dashcards(_dash(), OLD)]
    assert ids == [51676, 51675, 51671]

def test_metric_param_ids():
    assert scl.metric_param_ids(_dash(), OLD) == {PID}

def test_foreign_metric_consumers_empty_on_6846_shape():
    # PID ne pilote que des cartes 87 -> aucun consommateur étranger
    assert scl.foreign_metric_consumers(_dash(), {PID}, OLD) == []

def test_foreign_metric_consumers_flags_shared_param():
    d = _dash()
    # la carte indépendante 1427 mappe AUSSI le param metric -> conflit à signaler
    d["dashcards"][3]["parameter_mappings"].append(
        {"parameter_id": PID, "card_id": 1427, "target": _dim("metric")})
    assert scl.foreign_metric_consumers(d, {PID}, OLD) == [(51682, 1427)]


# --- réécriture d'un dashcard sélecteur ---
def test_rewrite_dashcard_swaps_card_id():
    nd = scl.rewrite_selector_dashcard(_dash()["dashcards"][0], OLD, NEW, {PID}, NEW_TAGS)
    assert nd["card_id"] == NEW
    assert all(pm["card_id"] == NEW for pm in nd["parameter_mappings"])

def test_rewrite_dashcard_flips_metric_to_variable():
    nd = scl.rewrite_selector_dashcard(_dash()["dashcards"][0], OLD, NEW, {PID}, NEW_TAGS)
    metric_pm = [pm for pm in nd["parameter_mappings"] if pm["parameter_id"] == PID][0]
    assert metric_pm["target"] == ["variable", ["template-tag", "metric"]]

def test_rewrite_dashcard_keeps_other_dimension_mappings():
    nd = scl.rewrite_selector_dashcard(_dash()["dashcards"][0], OLD, NEW, {PID}, NEW_TAGS)
    date_pm = [pm for pm in nd["parameter_mappings"] if pm["parameter_id"] == "404215d"][0]
    assert date_pm["target"][0] == "dimension" and scl._target_tag(date_pm["target"]) == "date"

def test_rewrite_dashcard_drops_mapping_to_absent_tag():
    nd = scl.rewrite_selector_dashcard(_dash()["dashcards"][2], OLD, NEW, {PID}, NEW_TAGS)
    assert all(scl._target_tag(pm["target"]) != "ghost_tag" for pm in nd["parameter_mappings"])

def test_rewrite_dashcard_is_pure():
    src = _dash()["dashcards"][0]
    scl.rewrite_selector_dashcard(src, OLD, NEW, {PID}, NEW_TAGS)
    assert src["card_id"] == OLD  # l'entrée n'est pas mutée


# --- équipement du param Metric du dashboard ---
def test_equip_metric_param_sets_static_list_single_select():
    np = scl.equip_metric_param(_dash()["parameters"][0], SOURCE_PARAM, scl.source_tokens(SOURCE_PARAM))
    assert np["values_source_type"] == "static-list"
    assert np["values_query_type"] == "list"
    assert np["isMultiSelect"] is False
    assert np["values_source_config"]["values"][0] == ["cost", "Cost"]

def test_equip_metric_param_keeps_old_default_when_valid():
    # default existant clickthrough_rate est un token valide -> conservé (unwrap de la liste)
    np = scl.equip_metric_param(_dash()["parameters"][0], SOURCE_PARAM, scl.source_tokens(SOURCE_PARAM))
    assert np["default"] == "clickthrough_rate"

def test_equip_metric_param_falls_back_to_source_default():
    p = dict(_dash()["parameters"][0], default=["conversions"])  # token disparu côté new
    np = scl.equip_metric_param(p, SOURCE_PARAM, scl.source_tokens(SOURCE_PARAM))
    assert np["default"] == "cost"


# --- orchestration ---
def test_apply_selector_deploy_end_to_end():
    params, dcs = scl.apply_selector_deploy(_dash(), OLD, NEW, NEW_TAGS, SOURCE_PARAM)
    # les 3 dashcards 87 -> 49788, la carte 1427 intacte
    by_id = {dc["id"]: dc for dc in dcs}
    assert by_id[51676]["card_id"] == NEW and by_id[51682]["card_id"] == 1427
    # param metric équipé
    mp = [p for p in params if p["id"] == PID][0]
    assert mp["values_query_type"] == "list" and mp["default"] == "clickthrough_rate"

def test_card_id_falls_back_to_embedded_card_object():
    # dashcard sans card_id mais avec card={id:...} (forme API alternative)
    dc = {"id": 1, "card": {"id": OLD}, "parameter_mappings": []}
    assert scl._card_id(dc) == OLD

def test_selector_dashcards_handles_embedded_card_object():
    d = _dash()
    d["dashcards"].append({"id": 51999, "card": {"id": OLD}, "parameter_mappings": []})
    assert 51999 in [dc["id"] for dc in scl.selector_dashcards(d, OLD)]

def test_foreign_consumers_catches_embedded_card_object():
    d = _dash()
    d["dashcards"].append({"id": 51998, "card": {"id": 1427},
                           "parameter_mappings": [{"parameter_id": PID, "card_id": 1427, "target": _dim("metric")}]})
    assert (51998, 1427) in scl.foreign_metric_consumers(d, {PID}, OLD)

def test_source_tokens_handles_plain_strings():
    assert scl.source_tokens({"values_source_config": {"values": ["cost", "clicks"]}}) == ["cost", "clicks"]

def test_source_tokens_handles_pairs():
    assert scl.source_tokens(SOURCE_PARAM)[:2] == ["cost", "clickthrough_rate"]

def test_dashcard_metric_pid_returns_mapped_param():
    dc = _dash()["dashcards"][0]
    assert scl.dashcard_metric_pid(dc) == PID

def test_dashcard_metric_pid_none_when_unmapped():
    dc = _dc(7, OLD, [("404215d", _dim("date"))])
    assert scl.dashcard_metric_pid(dc) is None


def _dash_mixed():
    """Dashboard avec une tuile carte 87 SÉLECTEUR (metric piloté) ET une tuile carte 87
    À MÉTRIQUE FIXE (aucun mapping metric -> metric = défaut de la carte). La fixe ne doit
    PAS être swappée (49788 a un défaut différent + cible nommée client-spécifique)."""
    d = _dash()
    d["dashcards"].append(_dc(51699, OLD, [("404215d", _dim("date"))]))  # carte 87 sans mapping metric
    return d

def test_metric_driven_dashcards_excludes_fixed_metric():
    ids = [dc["id"] for dc in scl.metric_driven_dashcards(_dash_mixed(), OLD)]
    assert ids == [51676, 51675, 51671] and 51699 not in ids

def test_fixed_metric_dashcards_lists_them():
    ids = [dc["id"] for dc in scl.fixed_metric_dashcards(_dash_mixed(), OLD)]
    assert ids == [51699]

def test_apply_leaves_fixed_metric_dashcard_on_old_card():
    params, dcs = scl.apply_selector_deploy(_dash_mixed(), OLD, NEW, NEW_TAGS, SOURCE_PARAM)
    by_id = {dc["id"]: dc for dc in dcs}
    assert by_id[51676]["card_id"] == NEW      # sélecteur migré
    assert by_id[51699]["card_id"] == OLD      # à métrique fixe : laissée sur 87

def test_replacement_ids_from_registry_entries():
    # new_ids des cartes spéciales déjà migrées -> generate_fallback doit les SKIPPER
    entries = [{"old_id": 87, "new_id": 49788, "verified": True},
               {"old_id": 4854, "new_id": 49755, "verified": True},
               {"old_id": 9, "new_id": 99, "verified": False}]   # non vérifié -> exclu
    assert scl.replacement_ids(entries) == {49788, 49755}

def test_replacement_ids_empty():
    assert scl.replacement_ids([]) == set()

def test_apply_preserves_dashboard_tab_id():
    d = _dash()
    d["dashcards"][0]["dashboard_tab_id"] = 7001
    _, dcs = scl.apply_selector_deploy(d, OLD, NEW, NEW_TAGS, SOURCE_PARAM)
    swapped = [dc for dc in dcs if dc["id"] == 51676][0]
    assert swapped["card_id"] == NEW and swapped["dashboard_tab_id"] == 7001

def test_apply_selector_deploy_raises_when_old_card_absent():
    d = _dash()
    for dc in d["dashcards"]:
        if dc["card_id"] == OLD:
            dc["card_id"] = 12345
    try:
        scl.apply_selector_deploy(d, OLD, NEW, NEW_TAGS, SOURCE_PARAM)
        assert False, "aurait dû lever (carte 87 absente)"
    except ValueError:
        pass


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

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
