from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import convert_generic_temporal as temporal


def test_transform_supports_historical_time_period_cte():
    sql = """WITH t AS (
      SELECT * FROM metabase_filters.time_periods
      WHERE {{time_period}} LIMIT 1
    ), final AS (SELECT t.name FROM t)
    SELECT * FROM final
    """

    transformed, count = temporal.transform(sql)

    assert count == 1
    assert "t AS (SELECT name FROM granularity LIMIT 1)" in transformed
    assert "metabase_filters.time_periods" not in transformed
    assert "granularity AS" in transformed


def test_inline_baseline_supports_historical_time_period_cte():
    sql = (
        "WITH t AS (SELECT * FROM metabase_filters.time_periods "
        "WHERE {{ time_period }} LIMIT 1) SELECT t.name FROM t"
    )
    baseline = temporal.inline_baseline_sql(sql, "week")
    assert "t AS (SELECT 'week' AS name)" in baseline
    assert "metabase_filters.time_periods" not in baseline


def test_transform_supports_time_period_cte_selecting_name():
    sql = """WITH t AS (
      SELECT name
      FROM metabase_filters.time_periods
      WHERE {{time_period}}
      LIMIT 1
    ), final AS (SELECT t.name FROM t)
    SELECT * FROM final
    """
    transformed, count = temporal.transform(sql)
    assert count == 1
    assert "t AS (SELECT name FROM granularity LIMIT 1)" in transformed
