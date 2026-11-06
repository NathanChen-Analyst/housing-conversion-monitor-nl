-- Queries behind the headline numbers in the README, runnable on the published CSVs with DuckDB:
--   duckdb -c ".read sql/analysis.sql"
-- Inputs: docs/data exported CSVs (wijk_year_conversions.csv, gemeente_year_conversions.csv)
-- Suppressed cells are NULL in the wijk file and absent from the sums below; national totals use the
-- gemeente file, which needs no suppression.

CREATE OR REPLACE VIEW wijk AS SELECT * FROM read_csv_auto('data/processed/wijk_year_conversions.csv');
CREATE OR REPLACE VIEW gem  AS SELECT * FROM read_csv_auto('data/processed/gemeente_year_conversions.csv');

-- 1. National total and peak year
SELECT sum(n) AS dwellings_2012_2024 FROM gem;
SELECT year, sum(n) AS dwellings FROM gem GROUP BY year ORDER BY dwellings DESC LIMIT 1;

-- 2. Year-by-year series with year-on-year change
SELECT year, sum(n) AS dwellings,
       sum(n) - lag(sum(n)) OVER (ORDER BY year) AS yoy_change,
       round(100.0 * sum(n) / sum(sum(n)) OVER (), 1) AS share_pct
FROM gem GROUP BY year ORDER BY year;

-- 3. Top 10 neighbourhoods, 2012–2024, with national share
WITH tot AS (SELECT sum(n) AS t FROM gem)
SELECT wijk_code, sum(n) AS dwellings, round(100.0 * sum(n) / (SELECT t FROM tot), 2) AS share_pct,
       bool_or(suppressed) AS has_suppressed_years
FROM wijk GROUP BY wijk_code ORDER BY dwellings DESC LIMIT 10;

-- 4. Concentration: share of all dwellings in the top 10 / top 50 neighbourhoods
WITH ranked AS (
  SELECT wijk_code, sum(n) AS d, row_number() OVER (ORDER BY sum(n) DESC) AS rk FROM wijk GROUP BY wijk_code),
tot AS (SELECT sum(n) AS t FROM gem)
SELECT round(100.0 * sum(d) FILTER (WHERE rk <= 10) / (SELECT t FROM tot), 1) AS top10_pct,
       round(100.0 * sum(d) FILTER (WHERE rk <= 50) / (SELECT t FROM tot), 1) AS top50_pct
FROM ranked;

-- 5. Municipalities: totals, and which ones peaked after 2019 (late movers)
WITH g AS (SELECT GM_NAAM AS gemeente, year, sum(n) AS d FROM gem GROUP BY 1, 2),
peak AS (SELECT gemeente, arg_max(year, d) AS peak_year, sum(d) AS total FROM g GROUP BY gemeente)
SELECT gemeente, total, peak_year FROM peak WHERE total >= 200 ORDER BY peak_year DESC, total DESC LIMIT 15;

-- 6. How much the small-cell suppression hides, per year
SELECT year, count(*) FILTER (WHERE suppressed) AS suppressed_cells,
       count(*) FILTER (WHERE n > 0) AS visible_cells
FROM wijk GROUP BY year ORDER BY year;
