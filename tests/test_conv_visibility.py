#!/usr/bin/env python3
"""Tests de conv_visibility — script autonome. Usage : python3 tests/test_conv_visibility.py

effective_column_status(display, card_vs, dashcard_vs, col) -> 'visible' | 'hidden' | 'ambiguous'

Règle clé : la surcharge au niveau tuile (dashcard_vs) prime sur la carte (card_vs).
On ne déclare 'hidden' que si c'est PROUVÉ masqué ; sinon 'ambiguous' (jamais deviné visible).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import conv_visibility as cv


def _tbl(cols):  # cols: list of (name, enabled)
    return {"table.columns": [{"name": n, "enabled": e} for n, e in cols]}


# --- table: explicit enabled / disabled ---
def test_table_card_enabled_is_visible():
    assert cv.effective_column_status("table", _tbl([("CONVERSIONS_2", True)]), {}, "CONVERSIONS_2") == "visible"

def test_table_card_disabled_is_hidden():
    assert cv.effective_column_status("table", _tbl([("CONVERSIONS_2", False)]), {}, "CONVERSIONS_2") == "hidden"

# --- THE bug: dashcard override hides a card-enabled column ---
def test_dashcard_override_hides_card_enabled():
    assert cv.effective_column_status("table", _tbl([("CONVERSIONS_2", True)]),
                                      _tbl([("CONVERSIONS_2", False)]), "CONVERSIONS_2") == "hidden"

# --- dashcard override can also REVEAL a card-disabled column ---
def test_dashcard_override_reveals_card_disabled():
    assert cv.effective_column_status("table", _tbl([("CONVERSIONS_2", False)]),
                                      _tbl([("CONVERSIONS_2", True)]), "CONVERSIONS_2") == "visible"

# --- table with no explicit column list -> Metabase shows all query columns ---
def test_table_no_column_list_is_visible():
    assert cv.effective_column_status("table", {}, {}, "CONVERSIONS_2") == "visible"

# --- table lists columns but not this one -> can't prove -> ambiguous ---
def test_table_col_not_listed_is_ambiguous():
    assert cv.effective_column_status("table", _tbl([("CONVERSIONS", True)]), {}, "CONVERSIONS_2") == "ambiguous"

# --- charts driven by graph.metrics ---
def test_chart_metric_present_is_visible():
    assert cv.effective_column_status("line", {"graph.metrics": ["CONVERSIONS_2"]}, {}, "CONVERSIONS_2") == "visible"

def test_chart_metric_absent_is_hidden():
    assert cv.effective_column_status("bar", {"graph.metrics": ["CONVERSIONS"]}, {}, "CONVERSIONS_2") == "hidden"

def test_chart_no_metrics_is_ambiguous():
    assert cv.effective_column_status("line", {}, {}, "CONVERSIONS_2") == "ambiguous"

def test_chart_dashcard_metrics_override():
    assert cv.effective_column_status("area", {"graph.metrics": ["CONVERSIONS_2"]},
                                      {"graph.metrics": ["CONVERSIONS"]}, "CONVERSIONS_2") == "hidden"

# --- scalar family ---
def test_scalar_field_match_is_visible():
    assert cv.effective_column_status("scalar", {"scalar.field": "CONVERSIONS_2"}, {}, "CONVERSIONS_2") == "visible"

def test_scalar_field_other_is_hidden():
    assert cv.effective_column_status("smartscalar", {"scalar.field": "CONVERSIONS"}, {}, "CONVERSIONS_2") == "hidden"

def test_scalar_no_field_is_ambiguous():
    assert cv.effective_column_status("scalar", {}, {}, "CONVERSIONS_2") == "ambiguous"

# --- unknown display types can't be judged ---
def test_unknown_display_is_ambiguous():
    assert cv.effective_column_status("pie", {}, {}, "CONVERSIONS_2") == "ambiguous"

# --- case-insensitivity ---
def test_case_insensitive_match():
    assert cv.effective_column_status("table", _tbl([("CONVERSIONS_2", True)]), {}, "conversions_2") == "visible"

# --- None dashcard settings handled ---
def test_none_dashcard_settings():
    assert cv.effective_column_status("table", _tbl([("CONVERSIONS_2", False)]), None, "CONVERSIONS_2") == "hidden"

# --- defensive: stray None entries in metrics / column names must not crash ---
def test_chart_metrics_with_none_entry():
    assert cv.effective_column_status("line", {"graph.metrics": [None, "CONVERSIONS"]}, {}, "CONVERSIONS_2") == "hidden"
    assert cv.effective_column_status("line", {"graph.metrics": [None, "CONVERSIONS_2"]}, {}, "CONVERSIONS_2") == "visible"

def test_table_column_with_none_name():
    cols = {"table.columns": [{"name": None, "enabled": True}, {"name": "CONVERSIONS_2", "enabled": True}]}
    assert cv.effective_column_status("table", cols, {}, "CONVERSIONS_2") == "visible"


# --- is_conversion_metric: recognise slot-tied conversion columns, reject unrelated ---
def test_is_conversion_metric_true_cases():
    for n in ["CONVERSIONS", "CONVERSION_VALUE", "CONVERSIONS_2", "CONVERSION_2_VALUE",
              "CR_2", "CAC_2", "CURRENT_CONVERSIONS_5", "PREVIOUS_CR_3"]:
        assert cv.is_conversion_metric(n), n

def test_is_conversion_metric_false_cases():
    for n in ["CLICKS", "IMPRESSIONS", "COST", "DATE", "TOP_10_PRODUCTS", "CPC"]:
        assert not cv.is_conversion_metric(n), n

# --- tile_slot_status: a slot is visible if ANY of its conversion columns (incl. derived) shows ---
def test_tile_slot_visible_via_derived_column_when_base_hidden():
    # conversions_2 hidden but cr_2 shown -> slot 2 is effectively visible
    status = cv.tile_slot_status("table",
        _tbl([("CONVERSIONS_2", False), ("CR_2", True), ("CAC_2", True)]), {},
        ["CONVERSIONS_2", "CR_2", "CAC_2"], 2)
    assert status == "visible", status

def test_tile_slot_hidden_when_all_slot_columns_hidden():
    status = cv.tile_slot_status("table",
        _tbl([("CONVERSIONS_2", False), ("CR_2", False)]), {},
        ["CONVERSIONS_2", "CR_2"], 2)
    assert status == "hidden", status

def test_tile_slot_ambiguous_when_not_listed():
    status = cv.tile_slot_status("table",
        _tbl([("CONVERSIONS", True)]), {},
        ["CONVERSIONS_2"], 2)
    assert status == "ambiguous", status

def test_tile_slot_absent_when_no_slot_conversion_columns():
    status = cv.tile_slot_status("table", _tbl([("CLICKS", True)]), {}, ["CLICKS", "COST"], 2)
    assert status == "absent", status

def test_tile_slot_dashcard_override_hides_slot():
    # base card shows conversions_2, dashcard override hides every slot-2 column -> hidden
    status = cv.tile_slot_status("table",
        _tbl([("CONVERSIONS_2", True), ("CR_2", True)]),
        _tbl([("CONVERSIONS_2", False), ("CR_2", False)]),
        ["CONVERSIONS_2", "CR_2"], 2)
    assert status == "hidden", status


TESTS = [test_table_card_enabled_is_visible, test_table_card_disabled_is_hidden,
         test_dashcard_override_hides_card_enabled, test_dashcard_override_reveals_card_disabled,
         test_table_no_column_list_is_visible, test_table_col_not_listed_is_ambiguous,
         test_chart_metric_present_is_visible, test_chart_metric_absent_is_hidden,
         test_chart_no_metrics_is_ambiguous, test_chart_dashcard_metrics_override,
         test_scalar_field_match_is_visible, test_scalar_field_other_is_hidden,
         test_scalar_no_field_is_ambiguous, test_unknown_display_is_ambiguous,
         test_case_insensitive_match, test_none_dashcard_settings,
         test_chart_metrics_with_none_entry, test_table_column_with_none_name,
         test_is_conversion_metric_true_cases, test_is_conversion_metric_false_cases,
         test_tile_slot_visible_via_derived_column_when_base_hidden,
         test_tile_slot_hidden_when_all_slot_columns_hidden,
         test_tile_slot_ambiguous_when_not_listed, test_tile_slot_absent_when_no_slot_conversion_columns,
         test_tile_slot_dashcard_override_hides_slot]

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
