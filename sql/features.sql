-- Build the wijk × year model table from processed parquet files.
-- Run through hcm.features.build(); shown here as plain SQL so it can be read on its own.
--
-- Inputs (DuckDB views registered by the caller):
--   conv      conversions.parquet   vbo_id, pand_id, wijk_code, pattern, event_date, reg_date, oppervlakte
--   stock     stock.parquet         wijk_code, year, nonres_vbo, nonres_floor_area, nonres_share_1965_1995,
--                                   office_vbo, retail_vbo, res_vbo   (as of 1 Jan of `year`)
--   cbs       cbs.parquet           wijk_code, year, population, density, income_pp, woz_value  (crosswalked)
--   nb        neighbours.parquet    wijk_code, nb_wijk_code  (queen contiguity on reference boundaries)
--
-- Leakage rule: every feature for row (wijk, year) may only use conversions with
-- reg_date <= 31 Dec of `year - 1`. The target uses event_date in `year`.

WITH years AS (
    SELECT DISTINCT year FROM stock
),
grid AS (
    SELECT w.wijk_code, y.year
    FROM (SELECT DISTINCT wijk_code FROM stock) w CROSS JOIN years y
),
-- conversions as the register knew them at the forecast date (end of previous year)
conv_known AS (
    SELECT g.wijk_code, g.year,
           count(*) FILTER (WHERE year(c.event_date) = g.year - 1)                       AS conversions_lag1,
           count(*) FILTER (WHERE year(c.event_date) BETWEEN g.year - 3 AND g.year - 1)  AS conversions_lag3,
           sum(c.oppervlakte) FILTER (WHERE year(c.event_date) = g.year - 1)             AS conv_floor_lag1
    FROM grid g
    LEFT JOIN conv c
      ON c.wijk_code = g.wijk_code
     AND c.reg_date <= make_date(g.year - 1, 12, 31)
    GROUP BY g.wijk_code, g.year
),
-- spatial lag: same quantities over neighbouring wijken
nb_known AS (
    SELECT g.wijk_code, g.year,
           avg(ck.conversions_lag1) AS nb_conversions_lag1,
           avg(ck.conversions_lag3) AS nb_conversions_lag3
    FROM grid g
    JOIN nb ON nb.wijk_code = g.wijk_code
    JOIN conv_known ck ON ck.wijk_code = nb.nb_wijk_code AND ck.year = g.year
    GROUP BY g.wijk_code, g.year
),
-- target: what actually happened in `year` (event date)
target AS (
    SELECT wijk_code, year(event_date) AS year, count(*) AS n_conversions
    FROM conv GROUP BY 1, 2
)
SELECT
    g.wijk_code,
    g.year,
    -- supply side (BAG stock at 1 Jan)
    s.nonres_vbo                       AS nonres_stock,
    s.nonres_floor_area,
    s.nonres_share_1965_1995,
    s.office_vbo,
    s.retail_vbo,
    s.res_vbo,
    s.office_vbo * 1.0 / nullif(s.nonres_vbo, 0) AS office_share,
    -- momentum
    coalesce(ck.conversions_lag1, 0)   AS conversions_lag1,
    coalesce(ck.conversions_lag3, 0)   AS conversions_lag3,
    coalesce(ck.conv_floor_lag1, 0)    AS conv_floor_lag1,
    coalesce(nk.nb_conversions_lag1, 0) AS nb_conversions_lag1,
    coalesce(nk.nb_conversions_lag3, 0) AS nb_conversions_lag3,
    -- CBS covariates from the previous year (already crosswalked to reference boundaries)
    cb.population, cb.density, cb.income_pp, cb.woz_value,
    -- baseline and target
    coalesce(ck.conversions_lag1, 0)   AS baseline_seasonal_naive,
    coalesce(t.n_conversions, 0)       AS n_conversions_next_year
FROM grid g
LEFT JOIN stock s       ON s.wijk_code = g.wijk_code AND s.year = g.year
LEFT JOIN conv_known ck ON ck.wijk_code = g.wijk_code AND ck.year = g.year
LEFT JOIN nb_known nk   ON nk.wijk_code = g.wijk_code AND nk.year = g.year
LEFT JOIN cbs cb        ON cb.wijk_code = g.wijk_code AND cb.year = g.year - 1
LEFT JOIN target t      ON t.wijk_code = g.wijk_code AND t.year = g.year
ORDER BY g.wijk_code, g.year;
