-- COURTSIDE Tick Store: showcase queries. Run all of them with timings:
--   python sponsors/tigerdata/run_queries.py
-- Each query starts with a "-- name:" line; run_queries.py splits on those.

-- name: match_replay
-- Replay one match second by second: the moneyline token with the most book activity, its 1 s mid, spread
-- and trade volume (continuous aggregates, joined in the bars_1s view).
SET search_path = courtside, public;
WITH busiest AS (
    SELECT b.asset_id FROM bars_1s b JOIN markets m USING (asset_id)
    WHERE m.market_type = 'moneyline'
    GROUP BY b.asset_id ORDER BY sum(b.updates) DESC LIMIT 1
)
SELECT m.title, m.outcome, b.bucket, round(b.mid, 4) AS mid, round(b.spread, 4) AS spread, b.updates, round(b.usd, 2) AS usd
FROM bars_1s b JOIN busiest USING (asset_id) JOIN markets m USING (asset_id)
ORDER BY b.bucket;

-- name: points_and_who_trades
-- Every point the in-database job found (jump_events), and the trading that follows: dollars traded in the
-- first 3 s after detection vs the next 27 s. The thesis says the first seconds are where the money moves.
SET search_path = courtside, public;
SELECT m.title, m.outcome, j.detected_at, j.move_cents, j.direction,
       coalesce(sum(t.size * t.price) FILTER (WHERE t.ts <  j.detected_at + interval '3 seconds'), 0)  AS usd_first_3s,
       coalesce(sum(t.size * t.price) FILTER (WHERE t.ts >= j.detected_at + interval '3 seconds'), 0)  AS usd_next_27s
FROM jump_events j
JOIN markets m USING (asset_id)
LEFT JOIN trades t ON t.asset_id = j.asset_id AND t.ts >= j.detected_at AND t.ts < j.detected_at + interval '30 seconds'
GROUP BY m.title, m.outcome, j.detected_at, j.move_cents, j.direction
ORDER BY abs(j.move_cents) DESC;

-- name: who_gets_paid
-- The paper's Figure 1, recomputed from live wallet trades: cents per share 5 s and 30 s after the trade,
-- by how soon after a point it was made.
SET search_path = courtside, public;
SELECT * FROM who_gets_paid
ORDER BY array_position(ARRAY['0-3 s','3-10 s','10-60 s','60 s+','no recent point'], after_point);

-- name: fast_tier
-- Wallets that trade within 3 s of points, ranked by marked-to-market P&L.
SET search_path = courtside, public;
SELECT left(wallet, 6) || '...' || right(wallet, 4) AS wallet, fast_trades, tokens, usd, cents_per_share_30s, pnl_usd_30s
FROM fast_tier LIMIT 10;

-- name: time_travel_book
-- Rebuild the full order book at any instant (book_at): the biggest point, 10 s before, at detection and
-- 10 s after. Shows the book emptying and refilling around a point.
SET search_path = courtside, public;
WITH j AS (SELECT e.asset_id, e.detected_at FROM jump_events e
           WHERE e.detected_at - interval '10 seconds' >= (SELECT min(ts) FROM book_updates b
                                                           WHERE b.asset_id = e.asset_id AND b.kind = 'snapshot')
           ORDER BY abs(e.move_cents) DESC, e.detected_at DESC LIMIT 1)
SELECT v.moment, v.at,
       max(b.price) FILTER (WHERE b.side = 'bid') AS best_bid,
       min(b.price) FILTER (WHERE b.side = 'ask') AS best_ask,
       round(sum(b.size) FILTER (WHERE b.side = 'bid' AND b.price >= (SELECT max(price) FROM book_at(j.asset_id, v.at) WHERE side = 'bid') - 0.05)) AS bid_shares_within_5c,
       round(sum(b.size) FILTER (WHERE b.side = 'ask' AND b.price <= (SELECT min(price) FROM book_at(j.asset_id, v.at) WHERE side = 'ask') + 0.05)) AS ask_shares_within_5c
FROM j,
     LATERAL (VALUES (1, '10 s before', j.detected_at - interval '10 seconds'), (2, 'at detection', j.detected_at),
                     (3, '10 s after', j.detected_at + interval '10 seconds')) AS v(k, moment, at),
     LATERAL book_at(j.asset_id, v.at) b
GROUP BY v.k, v.moment, v.at, j.asset_id ORDER BY v.k;

-- name: candles_1m
-- Hierarchical continuous aggregate: 1-minute candles built from the 1-second bars.
SET search_path = courtside, public;
SELECT c.minute, m.title, m.outcome, round(c.open, 3) AS open, round(c.high, 3) AS high, round(c.low, 3) AS low,
       round(c.close, 3) AS close, round(c.avg_spread, 4) AS avg_spread, c.updates
FROM candles_1m c JOIN markets m USING (asset_id)
WHERE m.market_type = 'moneyline'
ORDER BY c.high - c.low DESC LIMIT 10;

-- name: compression
-- How much Tiger Data's columnar compression saves on tick data.
SET search_path = courtside, public;
SELECT h AS hypertable,
       pg_size_pretty(sum(before_compression_total_bytes)) AS before,
       pg_size_pretty(sum(after_compression_total_bytes))  AS after,
       round(sum(before_compression_total_bytes)::numeric / nullif(sum(after_compression_total_bytes), 0), 1) AS ratio
FROM unnest(ARRAY['book_updates', 'trades']) AS h,
     LATERAL hypertable_compression_stats(('courtside.' || h)::regclass)
GROUP BY h;

-- name: feed_rate
-- What the recorder sees: messages per second of market time and the receive delay (exchange stamp to our
-- receive stamp), by update kind.
SET search_path = courtside, public;
SELECT kind,
       count(*) AS rows,
       round(count(*) / extract(epoch FROM max(ts) - min(ts))::numeric, 1) AS rows_per_s,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM rt - ts) * 1000)::numeric, 1) AS recv_delay_p50_ms,
       round(percentile_cont(0.99) WITHIN GROUP (ORDER BY extract(epoch FROM rt - ts) * 1000)::numeric, 1) AS recv_delay_p99_ms
FROM book_updates GROUP BY kind
UNION ALL
SELECT 'trade', count(*), round(count(*) / extract(epoch FROM max(ts) - min(ts))::numeric, 2),
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM rt - ts) * 1000)::numeric, 1),
       round(percentile_cont(0.99) WITHIN GROUP (ORDER BY extract(epoch FROM rt - ts) * 1000)::numeric, 1)
FROM trades;

-- name: pipeline_waterfall
-- The race in one table: median time of each pipeline stage, camera frame to a fill against the live book
-- (paper; order built, not sent), with a running total against the organisers' 3,000 ms bar.
SET search_path = courtside, public;
WITH s AS (
    SELECT stage, p50_ms, n,
           array_position(ARRAY['capture->send_start', 'send_start->frame_sent', 'frame_sent->rx_first_packet',
               'rx_first_packet->frame_received', 'frame_received->decode_start', 'decode_start->decoded',
               'decoded->handoff', 'handoff->prepped', 'prepped->detected', 'detected->call_emitted',
               'call_emitted->callback', 'callback->decision', 'decision->risk_checked', 'risk_checked->order_ready',
               'order_ready->probe_start', 'probe_start->network_arrival', 'network_arrival->probe_end',
               'probe_end->executable', 'executable->fill'], stage) AS step
    FROM pipeline_latency
)
SELECT step, stage, n, round(p50_ms::numeric, 2) AS p50_ms,
       round(sum(p50_ms) OVER (ORDER BY step)::numeric, 1) AS cumulative_ms,
       3000 - round(sum(p50_ms) OVER (ORDER BY step)::numeric, 1) AS headroom_vs_3s_ms
FROM s WHERE step IS NOT NULL ORDER BY step;

-- name: cv_calls_summary
-- The vision engine's calls: how many, how confident, and how far ahead of contact.
SET search_path = courtside, public;
SELECT call, count(*) AS n,
       round(avg(p_miss)::numeric, 3) AS mean_p_miss,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY lead_ms)::numeric, 1) AS lead_p50_ms,
       min(ts) AS first_call, max(ts) AS last_call
FROM cv_calls GROUP BY call ORDER BY n DESC;
