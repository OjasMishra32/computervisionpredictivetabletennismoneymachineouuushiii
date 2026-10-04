-- v2 (our copy of the fast tier's trades): headline metrics re-derived from its daily P&L rows.
-- Run from the repo root, e.g.  duckdb -c ".read sponsors/snowflake/sql/01_v2_daily.sql"
-- Rows: results/rigor/psr_daily.csv, series v2_is / v2_oos, one row per calendar day (zero-filled).
-- Definitions: Sharpe = mean / sample sd of daily P&L x sqrt(365); return and volatility are annualised and divided
-- by capital; drawdown = deepest fall of cumulative P&L below its running peak (from 0), divided by capital.
-- Capital (3 x peak dollars locked) needs the trade ledger, which is not in git: it is read from
-- results/v2/note_metrics.json and is the only stored input here.
-- psr_daily.csv labels each day one day earlier than results/lowloss/daily.csv (same P&L on Jan 31 vs Feb 1);
-- calendar months use date + 1, which is what the paper's months are.
WITH d AS (
    SELECT CASE series WHEN 'v2_is' THEN 'is' ELSE 'oos' END AS per, CAST(date AS DATE) + 1 AS day, pnl_usd AS pnl
    FROM read_csv_auto('results/rigor/psr_daily.csv')
    WHERE series IN ('v2_is', 'v2_oos')
),
cap AS (
    SELECT 'is' AS per, "is".capital_usd AS capital FROM read_json_auto('results/v2/note_metrics.json')
    UNION ALL
    SELECT 'oos', burned_oos.capital_usd FROM read_json_auto('results/v2/note_metrics.json')
),
cum AS (SELECT per, day, SUM(pnl) OVER (PARTITION BY per ORDER BY day) AS c FROM d),
draw AS (SELECT per, c - GREATEST(0, MAX(c) OVER (PARTITION BY per ORDER BY day)) AS dd FROM cum),
months AS (SELECT per, date_trunc('month', day) AS mo, SUM(pnl) AS m FROM d GROUP BY ALL),
s AS (
    SELECT d.per, COUNT(*) AS n_days, SUM(pnl) AS total, AVG(pnl) AS mean, STDDEV_SAMP(pnl) AS sd,
           SKEWNESS(pnl) AS skew, KURTOSIS(pnl) AS exkurt, MIN(pnl) AS worst_day,
           (SELECT MIN(dd) FROM draw WHERE draw.per = d.per) AS max_dd,
           (SELECT MIN(m) FROM months WHERE months.per = d.per) AS worst_month,
           ANY_VALUE(cap.capital) AS capital
    FROM d JOIN cap USING (per)
    GROUP BY d.per
)
SELECT 'v2.' || per || '.sr' AS paper_key, mean / sd * SQRT(365) AS sql_value, NULL::DOUBLE AS sql_value2,
       'mean / sample sd of daily P&L x sqrt(365)' AS how FROM s
UNION ALL SELECT 'v2.' || per || '.pnl', total, NULL, 'sum of daily P&L' FROM s
UNION ALL SELECT 'v2.' || per || '.days', n_days, NULL, 'calendar days' FROM s
UNION ALL SELECT 'tab.v2.' || per || '.usd', mean, NULL, 'mean daily P&L' FROM s
UNION ALL SELECT 'calc.' || per || '.mean', mean, NULL, 'mean daily P&L' FROM s
UNION ALL SELECT 'v2.' || per || '.ret', mean * 365 / capital * 100, NULL, 'mean daily P&L x 365 / capital, %' FROM s
UNION ALL SELECT 'v2.' || per || '.vol', sd * SQRT(365) / capital * 100, NULL, 'sd of daily P&L x sqrt(365) / capital, %' FROM s
UNION ALL SELECT 'v2.' || per || '.dd', max_dd / capital * 100, NULL, 'max drawdown of cumulative P&L / capital, %' FROM s
UNION ALL SELECT 'v2.' || per || '.worstday', worst_day / capital * 100, NULL, 'worst day / capital, %' FROM s
UNION ALL SELECT 'v2.' || per || '.worstmonth', worst_month, NULL, 'worst calendar month (dates + 1 day)' FROM s
UNION ALL SELECT 'v2.' || per || '.skew', skew, NULL, 'sample skewness of daily P&L' FROM s
UNION ALL SELECT 'v2.' || per || '.kurt', exkurt + 3, NULL, 'Pearson kurtosis = excess kurtosis + 3' FROM s
ORDER BY paper_key;
