granularity AS (

    -- Derives the selected temporal unit from the 'time_period' temporal-unit template-tag.
    -- The tag expands to utils.calendar.date truncated to the chosen unit, so the number
    -- of distinct buckets over calendar year 2023 identifies it:
    -- day -> 365, week -> ~53, month -> 12, quarter -> 4, year -> 1.
    SELECT CASE
            WHEN n >= 200 THEN 'day'
            WHEN n >= 40 THEN 'week'
            WHEN n >= 10 THEN 'month'
            WHEN n >= 3 THEN 'quarter'
            ELSE 'year'
        END AS name
    FROM (
        SELECT COUNT(DISTINCT {{time_period}}) AS n
        FROM utils.calendar
        WHERE utils.calendar.date BETWEEN TO_DATE('2023-01-01') AND TO_DATE('2023-12-31')
    )

),

