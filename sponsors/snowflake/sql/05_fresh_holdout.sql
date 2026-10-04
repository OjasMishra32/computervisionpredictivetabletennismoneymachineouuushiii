-- Fresh holdout (matches after the cut-off, the licensed 0.5 s scenario) and the showcase match.
-- Rows: results/fresh_holdout/seed_daily_paths.csv (one row per cell per day, one column per seed) and
-- results/fresh_holdout/showcase_trades_all_seeds.csv (every simulated trade on the showcase match, all seeds).
-- Definitions: $/day = mean over 20 seeds of each seed's mean daily P&L; showcase = total P&L over all 20 seeds / 20
-- (a seed with no trade counts as $0). The printed fresh-holdout CIs are not re-derived: they are not seed
-- percentiles of these rows (bootstrap over matches, which are not in these files).
WITH r AS (
    SELECT strategy, reading, V_s, date, COLUMNS('pnl_usd_seed_k\d\d')
    FROM read_csv_auto('results/fresh_holdout/seed_daily_paths.csv')
    WHERE period = 'fresh' AND coverage = 'cov10'
),
u AS (UNPIVOT r ON COLUMNS('pnl_usd_seed_k\d\d') INTO NAME seed VALUE pnl),
s AS (SELECT strategy, reading, V_s, seed, AVG(pnl) AS m FROM u GROUP BY ALL),
cell AS (SELECT strategy, reading, V_s, AVG(m) AS usd, COUNT(*) AS seeds FROM s GROUP BY ALL),
showcase AS (
    SELECT CASE WHEN reading LIKE 'pre-registered%' THEN 'pre' ELSE 'cal' END AS rd, SUM(pnl_usd) / 20 AS usd
    FROM read_csv_auto('results/fresh_holdout/showcase_trades_all_seeds.csv')
    WHERE strategy = 'S2' AND V_s = 0.5
    GROUP BY 1
)
SELECT 'fresh.' || lower(strategy) || '.' || reading || '.v' || CASE V_s WHEN 0.5 THEN '05' WHEN 1 THEN '1' ELSE '3' END
           || '.usd' AS paper_key,
       usd AS sql_value, NULL::DOUBLE AS sql_value2, 'mean over ' || seeds || ' seeds of mean daily P&L' AS how
FROM cell
UNION ALL SELECT 'fresh.show.' || rd, usd, NULL, 'showcase match, S2 at 0.5 s: total P&L over 20 seeds / 20' FROM showcase
ORDER BY paper_key;
