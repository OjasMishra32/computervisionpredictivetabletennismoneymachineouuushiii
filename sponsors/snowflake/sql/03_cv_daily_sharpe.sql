-- Second, independent route to the CV trader's 1 s Sharpe and $/day: from its daily P&L paths, 20 seeds per cell.
-- Rows: results/rigor/psr_daily.csv, series cv_{pre,cal}_{is,oos}, one row per seed per calendar day.
-- Definition: per seed, mean / sample sd of daily P&L x sqrt(365); the cell is the mean over seeds. (The Sharpe of
-- the seed-averaged daily path is much higher, about 27 calibrated; the paper uses the per-seed mean.)
WITH s AS (
    SELECT series, seed, AVG(pnl_usd) AS m, STDDEV_SAMP(pnl_usd) AS sd
    FROM read_csv_auto('results/rigor/psr_daily.csv')
    WHERE series LIKE 'cv\_%' ESCAPE '\'
    GROUP BY ALL
),
c AS (
    SELECT replace(replace(series, 'cv_', 'cv.'), '_', '.') AS ck, AVG(m) AS usd, AVG(m / sd * SQRT(365)) AS sr
    FROM s GROUP BY series
)
SELECT ck || '.sr' AS paper_key, sr AS sql_value, NULL::DOUBLE AS sql_value2,
       'per-seed Sharpe from daily P&L, mean over 20 seeds' AS how FROM c
UNION ALL SELECT ck || '.usd', usd, NULL, 'mean daily P&L over seeds and days' FROM c
ORDER BY paper_key;
