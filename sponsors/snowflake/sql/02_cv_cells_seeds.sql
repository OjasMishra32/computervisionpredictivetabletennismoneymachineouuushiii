-- The CV trader at 0.5 / 1 / 3 s feed delay, both stamp-lag readings, IS and burned OOS (paper Table 2), from the
-- 20 per-seed rows of every cell. Rows: results/tier0/latency_sweep_seeds.csv (source video, cv own120).
-- Definitions: each cell is the mean over its 20 seeds of the per-seed statistic; the $/day interval is the
-- 2.5-97.5 % range of the 20 seed values; drawdown % = mean drawdown / mean capital; trades a day = mean trades /
-- mean days. Readings: 'tournament' = pre-registered 2.0 s stamp lag (pre), 'tournament_lagcal' = post hoc (cal).
WITH s AS (
    SELECT CASE reading WHEN 'tournament' THEN 'pre' ELSE 'cal' END AS rd,
           CASE period WHEN 'IS' THEN 'is' ELSE 'oos' END AS per, *
    FROM read_csv_auto('results/tier0/latency_sweep_seeds.csv')
    WHERE source = 'video' AND cv = 'own120' AND reading IN ('tournament', 'tournament_lagcal')
      AND x_s IN (0.5, 1, 3)
),
c AS (
    SELECT rd, per, x_s, COUNT(*) AS seeds,
           AVG(pnl_per_day_usd) AS usd, AVG(per_share_c) AS cps, AVG(sharpe_ann) AS sr,
           AVG(wrong_call_share_of_trades) AS wrong,
           QUANTILE_CONT(pnl_per_day_usd, 0.025) AS usd_lo, QUANTILE_CONT(pnl_per_day_usd, 0.975) AS usd_hi,
           AVG(per_share_ci95_c_lo) AS c_lo, AVG(per_share_ci95_c_hi) AS c_hi,
           AVG(max_dd_usd) AS dd, AVG(capital_usd) AS cap, AVG(worst_day_usd) AS worst_day,
           AVG(n_trades) AS trades, AVG(days) AS n_days
    FROM s GROUP BY ALL
),
k AS (
    SELECT 'sc.' || rd || '.' || per || '.v' || CASE x_s WHEN 0.5 THEN '05' WHEN 1 THEN '1' ELSE '3' END AS sk,
           'cv.' || rd || '.' || per AS ck, *
    FROM c
)
SELECT sk || '.usd' AS paper_key, usd AS sql_value, NULL::DOUBLE AS sql_value2, '20-seed mean of $/day' AS how FROM k
UNION ALL SELECT sk || '.c', cps, NULL, '20-seed mean of net cents/share' FROM k
UNION ALL SELECT sk || '.sr', sr, NULL, '20-seed mean of the per-seed Sharpe' FROM k
UNION ALL SELECT sk || '.uci', usd_lo, usd_hi, '2.5-97.5 % of the 20 seed $/day values' FROM k
UNION ALL SELECT sk || '.cci', c_lo, c_hi, '20-seed mean of the per-seed cents/share CI bounds' FROM k
UNION ALL SELECT ck || '.usd', usd, NULL, '20-seed mean of $/day, 1 s' FROM k WHERE x_s = 1
UNION ALL SELECT ck || '.c', cps, NULL, '20-seed mean of cents/share, 1 s' FROM k WHERE x_s = 1
UNION ALL SELECT ck || '.sr', sr, NULL, '20-seed mean of Sharpe, 1 s' FROM k WHERE x_s = 1
UNION ALL SELECT ck || '.wrong', wrong, NULL, '20-seed mean share of trades on wrong calls, 1 s' FROM k WHERE x_s = 1
UNION ALL SELECT ck || '.dd', dd / cap * 100, NULL, 'mean drawdown / mean capital, %, 1 s' FROM k WHERE x_s = 1
UNION ALL SELECT ck || '.worstday', worst_day, NULL, '20-seed mean of the worst day, 1 s' FROM k WHERE x_s = 1
UNION ALL SELECT ck || '.tpd', trades / n_days, NULL, 'mean trades / mean days, 1 s' FROM k WHERE x_s = 1
ORDER BY paper_key;
