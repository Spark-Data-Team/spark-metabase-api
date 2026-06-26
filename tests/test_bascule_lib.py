#!/usr/bin/env python3
"""Tests de bascule_lib (bascule du filtre temps category -> temporal-unit).
Usage : python3 tests/test_bascule_lib.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import bascule_lib

TIME_TARGET = ["dimension", ["template-tag", "time_period"]]

def _dash():
    return {
        "id": 25567,
        "parameters": [
            {"id": "fc917174", "name": "Time period", "slug": "time_period", "type": "category",
             "default": ["week"], "values_source_type": "static-list",
             "values_source_config": {"values": ["week", "day", "month", "year"]}},
            {"id": "759220c7", "name": "Date", "slug": "date", "type": "date/all-options"},
        ],
        "dashcards": [
            # tuile sur ANCIEN mécanisme (tag dimension) câblée au filtre temps + date
            {"id": 1, "card_id": 100, "parameter_mappings": [
                {"parameter_id": "fc917174", "card_id": 100, "target": TIME_TARGET},
                {"parameter_id": "759220c7", "card_id": 100, "target": ["dimension", ["template-tag", "date"]]}]},
            # tuile migrée : câblage MORT (la carte n'a aucun tag time_period)
            {"id": 2, "card_id": 200, "parameter_mappings": [
                {"parameter_id": "fc917174", "card_id": 200, "target": TIME_TARGET}]},
            # tuile temporal-unit PAS câblée au filtre temps -> à câbler
            {"id": 3, "card_id": 300, "parameter_mappings": []},
            # tuile sans rapport avec le temps
            {"id": 4, "card_id": 400, "parameter_mappings": []},
            # tuile texte (pas de carte)
            {"id": 5, "card_id": None, "parameter_mappings": []},
        ],
    }

TAGS = {
    100: {"time_period": {"type": "dimension", "widget-type": "category"}, "date": {"type": "dimension"}},
    200: {"date": {"type": "dimension"}},
    300: {"time_period": {"type": "temporal-unit"}},
    400: {"clients": {"type": "dimension"}},
    1000: {"time_period": {"type": "temporal-unit"}, "date": {"type": "dimension"}},
}

# --- time_param_payload ---

def test_payload_dimension_tag():
    p = bascule_lib.time_param_payload(TAGS[100], "week")
    assert p == {"type": "category", "value": ["week"], "target": TIME_TARGET}

def test_payload_temporal_unit_tag():
    p = bascule_lib.time_param_payload(TAGS[300], "month")
    assert p == {"type": "temporal-unit", "value": "month", "target": TIME_TARGET}

def test_payload_absent_or_text():
    assert bascule_lib.time_param_payload(TAGS[200], "week") is None
    assert bascule_lib.time_param_payload({"time_period": {"type": "text"}}, "week") is None

# --- find_time_param / build_temporal_unit_param ---

def test_find_time_param():
    p = bascule_lib.find_time_param(_dash())
    assert p and p["id"] == "fc917174"

def test_find_time_param_ignores_temporal_unit():
    d = _dash()
    d["parameters"][0]["type"] = "temporal-unit"
    assert bascule_lib.find_time_param(d) is None

def test_find_time_param_accepts_string_eq_type():
    # Metabase a renommé 'category' -> 'string/=' : même filtre 'Time period', doit être détecté
    d = _dash()
    d["parameters"][0]["type"] = "string/="
    p = bascule_lib.find_time_param(d)
    assert p and p["id"] == "fc917174"

def test_find_time_param_ignores_other_string_eq_params():
    # un autre filtre texte (pas 'Time period') ne doit pas être pris pour le filtre temps
    d = _dash()
    d["parameters"][0]["type"] = "string/="
    d["parameters"][0]["slug"] = "channel"
    d["parameters"][0]["name"] = "Channel"
    assert bascule_lib.find_time_param(d) is None

def test_build_temporal_unit_param_keeps_id_and_default():
    new = bascule_lib.build_temporal_unit_param(_dash()["parameters"][0])
    assert new["id"] == "fc917174" and new["type"] == "temporal-unit"
    # le défaut category est une LISTE (['week']) -> temporal-unit veut une string
    assert new["default"] == "week" and new["slug"] == "time_period"
    assert new["temporal_units"] == ["day", "week", "month", "quarter", "year"]
    assert new["sectionId"] == "temporal-unit"
    assert "values_source_type" not in new and "values_source_config" not in new

def test_build_temporal_unit_param_default_fallback():
    assert bascule_lib.build_temporal_unit_param({"id": "x", "default": None})["default"] == "week"
    assert bascule_lib.build_temporal_unit_param({"id": "x", "default": ["month"]})["default"] == "month"
    assert bascule_lib.build_temporal_unit_param({"id": "x", "default": "day"})["default"] == "day"

# --- bascule_plan ---

def test_plan_classifies_everything():
    plan = bascule_lib.bascule_plan(_dash(), TAGS)
    assert plan["old_param"]["id"] == "fc917174"
    assert [b["card_id"] for b in plan["blockers"]] == [100]
    assert plan["dead_mappings"] == [(2, "fc917174")]
    assert plan["to_wire"] == [(3, 300)]

def test_plan_no_time_param():
    d = _dash()
    d["parameters"] = [d["parameters"][1]]
    assert bascule_lib.bascule_plan(d, TAGS) is None

def test_plan_blocker_resolved_by_swap():
    plan = bascule_lib.bascule_plan(_dash(), TAGS, swaps={100: 1000})
    assert plan["blockers"] == []
    assert plan["swaps"] == {100: 1000}

# --- apply_bascule ---

def test_apply_rewrites_everything():
    d = _dash()
    plan = bascule_lib.bascule_plan(d, TAGS, swaps={100: 1000})
    params, dcs = bascule_lib.apply_bascule(d, plan)
    # paramètre remplacé sur place, même id
    tp = [p for p in params if p["id"] == "fc917174"][0]
    assert tp["type"] == "temporal-unit" and len(params) == 2
    by_id = {dc["id"]: dc for dc in dcs}
    # swap : card_id repointé, mappings suivent (card_id mis à jour, targets conservés)
    assert by_id[1]["card_id"] == 1000
    assert all(pm["card_id"] == 1000 for pm in by_id[1]["parameter_mappings"])
    assert any(pm["target"] == TIME_TARGET for pm in by_id[1]["parameter_mappings"])
    # câblage mort supprimé
    assert by_id[2]["parameter_mappings"] == []
    # carte temporal-unit non câblée -> câblée au param temps
    wires = by_id[3]["parameter_mappings"]
    assert wires == [{"parameter_id": "fc917174", "card_id": 300, "target": TIME_TARGET}]
    # tuiles sans rapport : intactes
    assert by_id[4]["parameter_mappings"] == []

def test_apply_refuses_unresolved_blockers():
    d = _dash()
    plan = bascule_lib.bascule_plan(d, TAGS)
    try:
        bascule_lib.apply_bascule(d, plan)
        assert False, "aurait dû refuser (blocker non résolu)"
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
