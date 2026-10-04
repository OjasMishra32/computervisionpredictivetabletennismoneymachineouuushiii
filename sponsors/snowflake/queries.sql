-- COURTSIDE Warehouse: the paper's numbers, recomputed in SQL on Snowflake.
-- Run all of them and compare with the paper: python sponsors/snowflake/check.py
-- A query that returns PAPER_KEY / SQL_VALUE is checked against results/paper/numbers.json (the paper's own number
-- file, which names each number's source file); the others are descriptive.
-- KIND says how much SQL does: 'recomputed' = SQL derives the number from rows (interpolation, percentiles,
-- ratios); 'lookup' = SQL selects a value the Python pipeline already stored (it checks the paper quotes it right).
-- Readings: 'tournament' = the pre-registered 2.0 s umpire-stamp lag; 'tournament_lagcal' = the post hoc calibrated
-- 3.14 s lag; 'stamp_calibrated' = stamp-noise reading. Periods: 'IS' = in sample, 'burned_OOS' = the out-of-sample
-- window already opened for v1 (non-blind for later variants). Every P&L is paper (simulated), never traded.

-- name: sharpe_and_pnl_by_feed_delay
-- Q1. Seed-mean annualised Sharpe, $/day and net cents/share when our call reaches the market 0.5 / 1 / 3 s late
-- (video delay V), both readings, both periods (paper Table 2, "speed scenarios"). KIND lookup.
WITH pts AS (
    SELECT 'sc.' || CASE reading WHEN 'tournament' THEN 'pre' ELSE 'cal' END
               || '.' || CASE period WHEN 'IS' THEN 'is' ELSE 'oos' END
               || '.v' || CASE x_s WHEN 0.5 THEN '05' WHEN 1 THEN '1' ELSE '3' END AS k,
           reading, period, x_s, sharpe_ann, pnl_per_day_usd, per_share_c
    FROM latency_sweep
    WHERE source = 'video' AND cv = 'own120'
      AND reading IN ('tournament', 'tournament_lagcal')
      AND x_s IN (0.5, 1, 3)
)
SELECT k || '.sr' AS paper_key, 'lookup' AS kind, reading, period, x_s, sharpe_ann AS sql_value FROM pts
UNION ALL
SELECT k || '.usd', 'lookup', reading, period, x_s, pnl_per_day_usd FROM pts
UNION ALL
SELECT k || '.c', 'lookup', reading, period, x_s, per_share_c FROM pts
ORDER BY paper_key;

-- name: breakeven_feed_delay
-- Q2. Break-even feed delay: the first V where the seed-mean $/day curve crosses zero, linear interpolation
-- between the last positive and the first non-positive grid point (V = 0-3 s at 0.05 s, then 5-60 s).
-- Same rule as scripts/tier0_latency_sweep.py::first_crossing. KIND recomputed.
WITH curve AS (
    SELECT reading, period, x_s, pnl_per_day_usd AS y,
           LAG(x_s) OVER (PARTITION BY reading, period ORDER BY x_s) AS x_prev,
           LAG(pnl_per_day_usd) OVER (PARTITION BY reading, period ORDER BY x_s) AS y_prev,
           FIRST_VALUE(pnl_per_day_usd) OVER (PARTITION BY reading, period ORDER BY x_s) AS y_first
    FROM latency_sweep
    WHERE source = 'video' AND cv = 'own120'
      AND reading IN ('tournament', 'tournament_lagcal', 'stamp_calibrated')
),
crossing AS (
    SELECT reading, period, x_prev, x_s, y_prev, y,
           x_prev + (x_s - x_prev) * y_prev / (y_prev - y) AS breakeven_s
    FROM curve
    WHERE y <= 0 AND x_prev IS NOT NULL AND y_first > 0
    QUALIFY ROW_NUMBER() OVER (PARTITION BY reading, period ORDER BY x_s) = 1
)
SELECT 'cv.' || CASE reading WHEN 'tournament' THEN 'pre' WHEN 'tournament_lagcal' THEN 'cal' ELSE 'stc' END
           || '.be.' || CASE period WHEN 'IS' THEN 'is' ELSE 'oos' END AS paper_key,
       'recomputed' AS kind, reading, period,
       x_prev AS last_positive_v_s, y_prev AS usd_day_there, x_s AS first_nonpositive_v_s, y AS usd_day_after,
       breakeven_s AS sql_value
FROM crossing
ORDER BY paper_key;

-- name: capital_where_sharpe_halves
-- Q3. Capacity: walking the size path (net cap 50 -> 5,000 shares at $250/order), the capital where the seed-mean
-- Sharpe falls to half the smallest size's, linear in log capital; and the $/day there. Calibrated reading,
-- phi 0.5, growth 1, top-10 matches/day ('10') and all matches ('all'). Same rule as
-- scripts/capacity_study.py::capacity_answer. KIND recomputed.
WITH path AS (
    SELECT coverage, period, net_cap, capital_usd, sharpe_ann, pnl_per_day_usd,
           FIRST_VALUE(sharpe_ann) OVER (PARTITION BY coverage, period ORDER BY net_cap) AS s_ref,
           LAG(capital_usd) OVER (PARTITION BY coverage, period ORDER BY net_cap) AS cap_prev,
           LAG(sharpe_ann) OVER (PARTITION BY coverage, period ORDER BY net_cap) AS s_prev,
           LAG(pnl_per_day_usd) OVER (PARTITION BY coverage, period ORDER BY net_cap) AS pnl_prev
    FROM capacity_grid
    WHERE reading = 'lagcal' AND phi = 0.5 AND growth = 1 AND order_cap = 250 AND capital_usd > 0
      AND coverage IN ('10', 'all')
),
half AS (
    SELECT coverage, period, s_ref, cap_prev, capital_usd, pnl_prev, pnl_per_day_usd,
           (s_ref / 2 - s_prev) / (sharpe_ann - s_prev) AS t
    FROM path
    WHERE sharpe_ann <= s_ref / 2 AND s_prev IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (PARTITION BY coverage, period ORDER BY net_cap) = 1
),
keyed AS (
    SELECT 'capcv.' || CASE coverage WHEN '10' THEN 'half' ELSE 'halfall' END
               || '.' || CASE period WHEN 'IS' THEN 'is' ELSE 'oos' END AS k, *
    FROM half
)
SELECT k AS paper_key, 'recomputed' AS kind, coverage, period, s_ref AS sharpe_smallest_size,
       EXP(LN(cap_prev) + t * (LN(capital_usd) - LN(cap_prev))) AS sql_value
FROM keyed
UNION ALL
SELECT k || '.day', 'recomputed', coverage, period, s_ref, pnl_prev + t * (pnl_per_day_usd - pnl_prev)
FROM keyed
ORDER BY paper_key;

-- name: pipeline_latency_budget
-- Q4. The timed end-to-end run: frame capture -> order ready (ours), order ready -> venue (network one way),
-- venue order delay, and the total with the simulated 1 s feed, over the 24 complete order traces, from raw
-- stage timestamps. Percentiles are linear (numpy's default = PERCENTILE_CONT). KIND recomputed.
WITH t AS (
    SELECT (t_order_ready - t_capture) * 1000 AS ours_ms,
           (t_network_arrival - t_order_ready) * 1000 AS network_ms,
           1000 + (t_executable - t_capture) * 1000 AS total_ms
    FROM pipeline_stages
    WHERE complete_order_trace
)
SELECT 'e2e.ours' AS paper_key, 'recomputed' AS kind, MEDIAN(ours_ms) AS sql_value FROM t
UNION ALL SELECT 'e2e.net', 'recomputed', MEDIAN(network_ms) FROM t
UNION ALL SELECT 'e2e.total', 'recomputed', MEDIAN(total_ms) FROM t
UNION ALL SELECT 'e2e.p99', 'recomputed', PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY total_ms) FROM t
UNION ALL SELECT 'e2e.margin', 'recomputed', MEDIAN(3000 - total_ms) FROM t
UNION ALL SELECT 'e2e.n', 'recomputed', COUNT(*) FROM t
ORDER BY paper_key;

-- name: v2_backtest_headline
-- Q5. The v2 strategy's headline backtest metrics, read from the metric files (paper Table 1). KIND lookup.
SELECT k.paper_key, 'lookup' AS kind, m.source_file, m.json_path, m.value_num AS sql_value
FROM backtest_metrics m
JOIN (VALUES
        ('v2.is.sr',  'note_metrics.json', 'is.sharpe_ann'),
        ('v2.oos.sr', 'note_metrics.json', 'burned_oos.sharpe_ann'),
        ('v2.is.dd',  'note_metrics.json', 'is.max_dd_pct'),
        ('v2.oos.dd', 'note_metrics.json', 'burned_oos.max_dd_pct'),
        ('v2.is.c',   'causal.json',       'causal/is_eval/slip0.0.per_share_c'),
        ('v2.oos.c',  'causal.json',       'causal/burned_oos/slip0.0.per_share_c')
     ) AS k(paper_key, source_file, json_path)
  ON m.source_file = k.source_file AND m.json_path = k.json_path
ORDER BY k.paper_key;

-- name: pipeline_waterfall
-- Q6. Descriptive: median milliseconds per pipeline stage over the 24 complete traces, in order (the waterfall).
WITH t AS (SELECT * FROM pipeline_stages WHERE complete_order_trace)
SELECT 1 AS step, 'sender: frame into encoder' AS stage, MEDIAN((t_frame_sent - t_capture) * 1000) AS p50_ms FROM t
UNION ALL SELECT 2, 'encode + WHIP + RTP in', MEDIAN((t_frame_received - t_frame_sent) * 1000) FROM t
UNION ALL SELECT 3, 'H.264 decode + handoff', MEDIAN((t_handoff - t_frame_received) * 1000) FROM t
UNION ALL SELECT 4, 'prep + queue + detector', MEDIAN((t_detected - t_handoff) * 1000) FROM t
UNION ALL SELECT 5, 'tracker + features + classifier', MEDIAN((t_call_emitted - t_detected) * 1000) FROM t
UNION ALL SELECT 6, 'strategy rule (fair value, edge)', MEDIAN((t_decision - t_call_emitted) * 1000) FROM t
UNION ALL SELECT 7, 'risk check', MEDIAN((t_risk_checked - t_decision) * 1000) FROM t
UNION ALL SELECT 8, 'unsigned order built', MEDIAN((t_order_ready - t_risk_checked) * 1000) FROM t
UNION ALL SELECT 9, 'network one-way (RTT/2)', MEDIAN((t_network_arrival - t_order_ready) * 1000) FROM t
UNION ALL SELECT 10, 'venue order delay', MEDIAN((t_executable - t_network_arrival) * 1000) FROM t
ORDER BY step;

-- name: cv_calls_by_lead
-- Q7. Descriptive: the real-time CV engine's 172 calls (NVIDIA L4, table-tennis test footage) by how early they
-- came before the predicted bounce. These calls carry no ground-truth labels, so this is a profile, not precision.
SELECT call,
       CASE WHEN lead_ms < 25 THEN 1 WHEN lead_ms < 50 THEN 2 WHEN lead_ms < 100 THEN 3 ELSE 4 END AS bucket,
       CASE WHEN lead_ms < 25 THEN '0-25 ms' WHEN lead_ms < 50 THEN '25-50 ms'
            WHEN lead_ms < 100 THEN '50-100 ms' ELSE '100+ ms' END AS lead_before_bounce,
       COUNT(*) AS n_calls,
       MEDIAN(latency_ms) AS median_emit_latency_ms,
       AVG(p_miss) AS mean_p_miss
FROM cv_calls
GROUP BY 1, 2, 3
ORDER BY call, bucket;

-- name: clob_sample_profile
-- Q8. Descriptive: the 10-minute recorded Polymarket book sample (Oct 3, 11:23-11:33 UTC, public websocket).
-- Server-stamp-to-receive lag per message type (includes the recording laptop's clock offset) and the median
-- moneyline spread. A mechanics demo, not evidence of an edge.
SELECT s.event,
       COUNT(*) AS n_rows,
       COUNT(DISTINCT s.line_no) AS n_messages,
       MEDIAN(s.rt_ms - s.ts_ms) AS median_server_to_receive_ms,
       PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY s.rt_ms - s.ts_ms) AS p90_server_to_receive_ms,
       MEDIAN(CASE WHEN tk.market_type = 'moneyline' AND s.event = 'pc'
                   THEN (s.best_ask - s.best_bid) * 100 END) AS median_moneyline_spread_c
FROM clob_sample s
LEFT JOIN clob_tokens tk ON tk.asset_idx = s.asset_idx
GROUP BY s.event
ORDER BY n_rows DESC;
