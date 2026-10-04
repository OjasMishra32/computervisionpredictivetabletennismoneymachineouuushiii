-- Frozen CV rule v3 on the blind U2 universe (markets never examined): net cents a share, IS and OOS, from the trades.
-- Rows: results/tier0_v3/u2/trades_frozen_v3_u2_{is,oos}.parquet (one row per simulated trade, 20 seeds).
-- Definition: per seed, total P&L / total shares (in cents); the set is the mean over seeds.
WITH t AS (
    SELECT 'is' AS per, seed, pnl, shares FROM read_parquet('results/tier0_v3/u2/trades_frozen_v3_u2_is.parquet')
    UNION ALL
    SELECT 'oos', seed, pnl, shares FROM read_parquet('results/tier0_v3/u2/trades_frozen_v3_u2_oos.parquet')
),
s AS (SELECT per, seed, SUM(pnl) / SUM(shares) * 100 AS c FROM t GROUP BY ALL)
SELECT 't3.' || per || '.c' AS paper_key, AVG(c) AS sql_value, NULL::DOUBLE AS sql_value2,
       'per-seed total P&L / total shares, mean over ' || COUNT(*) || ' seeds' AS how
FROM s GROUP BY per
ORDER BY paper_key;
