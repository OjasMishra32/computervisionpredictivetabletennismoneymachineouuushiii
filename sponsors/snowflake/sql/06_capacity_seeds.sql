-- Capacity of the CV book from the per-seed size cells: where the Sharpe halves, the most it earns, and the Sharpe
-- at the smallest size. Rows: results/capacity/cv_seeds.parquet (one row per size cell per seed).
-- Definitions: a cell is the mean over its seeds; the size path is net cap 50 -> 5,000 shares at $250 a order;
-- 'where Sharpe halves' = the first cell at or below half the smallest size's Sharpe, interpolated linearly in log
-- capital (and $/day linearly); 'most it earns' = the cell with the highest mean $/day. Main configuration:
-- phi 0.5, growth 1, best allocation, fixed model; top-10 matches a day ('10') or all matches ('all').
WITH cell AS (
    SELECT reading, coverage, period, net_cap, order_cap,
           AVG(capital_usd) AS cap, AVG(sharpe_ann) AS sr, AVG(pnl_per_day_usd) AS usd, COUNT(*) AS seeds
    FROM read_parquet('results/capacity/cv_seeds.parquet')
    WHERE phi = 0.5 AND growth = 1 AND alloc = 'best' AND model = 'fixed' AND coverage IN ('10', 'all')
    GROUP BY ALL
    HAVING AVG(capital_usd) > 0
),
path AS (
    SELECT *, FIRST_VALUE(sr) OVER w AS sr0, LAG(cap) OVER w AS cap_prev, LAG(sr) OVER w AS sr_prev,
           LAG(usd) OVER w AS usd_prev
    FROM cell WHERE order_cap = 250
    WINDOW w AS (PARTITION BY reading, coverage, period ORDER BY net_cap)
),
half AS (
    SELECT *, (sr0 / 2 - sr_prev) / (sr - sr_prev) AS t
    FROM path WHERE sr <= sr0 / 2 AND sr_prev IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (PARTITION BY reading, coverage, period ORDER BY net_cap) = 1
),
pmax AS (
    SELECT * FROM cell
    QUALIFY ROW_NUMBER() OVER (PARTITION BY reading, coverage, period ORDER BY usd DESC) = 1
),
keyed AS (
    SELECT CASE coverage WHEN '10' THEN 'half' ELSE 'halfall' END || '.' || CASE period WHEN 'IS' THEN 'is' ELSE 'oos' END AS k, *
    FROM half WHERE reading = 'lagcal'
)
SELECT 'capcv.' || k AS paper_key, EXP(LN(cap_prev) + t * (LN(cap) - LN(cap_prev))) AS sql_value,
       NULL::DOUBLE AS sql_value2, 'capital where the seed-mean Sharpe halves (log-linear)' AS how FROM keyed
UNION ALL SELECT 'capcv.' || k || '.day', usd_prev + t * (usd - usd_prev), NULL, '$/day where Sharpe halves' FROM keyed
UNION ALL
SELECT 'capcv.' || CASE reading WHEN 'prereg' THEN 'pre.' ELSE '' END || 'sr0.' || CASE period WHEN 'IS' THEN 'is' ELSE 'oos' END,
       sr0, NULL, 'seed-mean Sharpe at the smallest size (top-10 matches)'
FROM path WHERE coverage = '10' AND net_cap = (SELECT MIN(net_cap) FROM path p2 WHERE p2.reading = path.reading
                                               AND p2.coverage = path.coverage AND p2.period = path.period)
UNION ALL
SELECT 'capcv.pmax.' || CASE period WHEN 'IS' THEN 'is' ELSE 'oos' END, cap, NULL, 'capital of the highest-$/day cell'
FROM pmax WHERE reading = 'lagcal' AND coverage = '10'
UNION ALL
SELECT 'capcv.pmax.' || CASE period WHEN 'IS' THEN 'is' ELSE 'oos' END || '.day', usd, NULL, 'highest seed-mean $/day'
FROM pmax WHERE reading = 'lagcal' AND coverage = '10'
UNION ALL
SELECT 'capcv.pmax.' || CASE period WHEN 'IS' THEN 'is' ELSE 'oos' END || '.sr', sr, NULL, 'Sharpe of the highest-$/day cell'
FROM pmax WHERE reading = 'lagcal' AND coverage = '10'
ORDER BY paper_key;
