-- COURTSIDE Tick Store on Tiger Data (TimescaleDB).
--   psql "$TIGER_DATABASE_URL" -f sponsors/tigerdata/schema.sql
-- Safe to re-run: drops and recreates everything under the courtside schema.

DROP SCHEMA IF EXISTS courtside CASCADE;
CREATE SCHEMA courtside;
SET search_path = courtside, public;

-- One row per outcome token (each match has two: one per player). Plain table.
CREATE TABLE markets (
    asset_id    text PRIMARY KEY,
    market      text NOT NULL,          -- Polymarket condition id
    slug        text,
    title       text,
    outcome     text,                   -- player this token pays out on
    market_type text,                   -- moneyline, set handicap, totals, ...
    start_ts    timestamptz,
    winner      boolean                 -- set from market_resolved messages
);

-- Every order-book level from snapshots ('snapshot') and every level change ('change').
-- best_bid / best_ask = top of book right after this update (the venue sends them on changes;
-- for snapshots ingest computes them), so 1 s bars need no book rebuild in SQL.
CREATE TABLE book_updates (
    ts        timestamptz NOT NULL,     -- exchange timestamp
    rt        timestamptz NOT NULL,     -- our receive timestamp
    asset_id  text        NOT NULL,
    market    text        NOT NULL,
    side      text        NOT NULL,     -- 'bid' | 'ask'
    price     numeric(6,4) NOT NULL,
    size      numeric      NOT NULL,    -- 0 = level removed
    kind      text        NOT NULL,     -- 'snapshot' | 'change'
    best_bid  numeric(6,4),
    best_ask  numeric(6,4)
);
SELECT create_hypertable('book_updates', 'ts', chunk_time_interval => interval '1 hour');
CREATE INDEX ON book_updates (asset_id, ts DESC);

CREATE TABLE trades (
    ts        timestamptz NOT NULL,
    rt        timestamptz NOT NULL,
    asset_id  text        NOT NULL,
    market    text        NOT NULL,
    price     numeric(6,4) NOT NULL,
    size      numeric      NOT NULL,
    side      text,                     -- taker side: 'BUY' | 'SELL'
    source    text        NOT NULL
);
SELECT create_hypertable('trades', 'ts', chunk_time_interval => interval '1 hour');
CREATE INDEX ON trades (asset_id, ts DESC);

-- Computer-vision point-end calls from the live engine (table tennis footage; paper only).
CREATE TABLE cv_calls (
    ts       timestamptz NOT NULL,      -- when the engine emitted the call
    call     text        NOT NULL,      -- 'MISS' | 'BOUNCE'
    p_miss   double precision,
    lead_ms  double precision,          -- how long before contact the call was made
    source   text        NOT NULL
);
SELECT create_hypertable('cv_calls', 'ts', chunk_time_interval => interval '1 day');

-- End-to-end pipeline: duration of each stage (capture -> ... -> decision) and venue round trips.
CREATE TABLE pipeline_stages (
    ts     timestamptz NOT NULL,        -- wall time the stage ended
    run    text        NOT NULL,
    stage  text        NOT NULL,
    ms     double precision NOT NULL
);
SELECT create_hypertable('pipeline_stages', 'ts', chunk_time_interval => interval '1 day');
CREATE INDEX ON pipeline_stages (stage, ts DESC);

-- Compression: segment by asset so one match's ticks compress together, newest first.
ALTER TABLE book_updates SET (timescaledb.compress, timescaledb.compress_segmentby = 'asset_id',
                              timescaledb.compress_orderby = 'ts DESC');
ALTER TABLE trades SET (timescaledb.compress, timescaledb.compress_segmentby = 'asset_id',
                        timescaledb.compress_orderby = 'ts DESC');
SELECT add_compression_policy('book_updates', compress_after => interval '6 hours');
SELECT add_compression_policy('trades', compress_after => interval '6 hours');

-- 1-second bars of the top of book per token.
CREATE MATERIALIZED VIEW mid_1s WITH (timescaledb.continuous) AS
SELECT asset_id,
       time_bucket('1 second', ts)                        AS bucket,
       last(best_bid, ts)                                 AS bid,
       last(best_ask, ts)                                 AS ask,
       (last(best_bid, ts) + last(best_ask, ts)) / 2      AS mid,
       last(best_ask, ts) - last(best_bid, ts)            AS spread,
       count(*)                                           AS updates
FROM book_updates
WHERE best_bid IS NOT NULL AND best_ask IS NOT NULL
GROUP BY asset_id, bucket
WITH NO DATA;
SELECT add_continuous_aggregate_policy('mid_1s', start_offset => interval '1 day',
       end_offset => interval '1 second', schedule_interval => interval '10 seconds');

-- 1-second trade bars per token.
CREATE MATERIALIZED VIEW trades_1s WITH (timescaledb.continuous) AS
SELECT asset_id,
       time_bucket('1 second', ts)          AS bucket,
       sum(size)                            AS shares,
       sum(size * price)                    AS usd,
       count(*)                             AS n_trades,
       last(price, ts)                      AS last_price
FROM trades
GROUP BY asset_id, bucket
WITH NO DATA;
SELECT add_continuous_aggregate_policy('trades_1s', start_offset => interval '1 day',
       end_offset => interval '1 second', schedule_interval => interval '10 seconds');

-- Bars with trade volume joined in (spread, mid and volume in one place).
CREATE VIEW bars_1s AS
SELECT m.asset_id, m.bucket, m.bid, m.ask, m.mid, m.spread, m.updates,
       coalesce(t.shares, 0) AS shares, coalesce(t.usd, 0) AS usd, coalesce(t.n_trades, 0) AS n_trades
FROM mid_1s m
LEFT JOIN trades_1s t USING (asset_id, bucket);

-- The repo's jump detector, in SQL: the 10 s average mid vs the 60 s before it; a move of 4c or more
-- marks a point. Only the first second of each jump is kept.
CREATE VIEW jumps AS
WITH w AS (
    SELECT asset_id, bucket, mid,
           avg(mid) OVER (PARTITION BY asset_id ORDER BY bucket
                          RANGE BETWEEN interval '9 seconds' PRECEDING AND CURRENT ROW)                     AS mid_10s,
           avg(mid) OVER (PARTITION BY asset_id ORDER BY bucket
                          RANGE BETWEEN interval '70 seconds' PRECEDING AND interval '10 seconds' PRECEDING) AS mid_prior_60s
    FROM mid_1s
), f AS (
    SELECT *, mid_10s - mid_prior_60s AS move,
           abs(mid_10s - mid_prior_60s) >= 0.04 AS is_jump
    FROM w
)
SELECT asset_id, bucket AS detected_at, round(move * 100, 2) AS move_cents,
       CASE WHEN move > 0 THEN 'up' ELSE 'down' END AS direction
FROM (SELECT *, lag(is_jump) OVER (PARTITION BY asset_id ORDER BY bucket) AS was_jump FROM f) x
WHERE is_jump AND NOT coalesce(was_jump, false);

-- Latency of each pipeline stage.
CREATE VIEW pipeline_latency AS
SELECT stage,
       count(*)                                                 AS n,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY ms)         AS p50_ms,
       percentile_cont(0.90) WITHIN GROUP (ORDER BY ms)         AS p90_ms,
       percentile_cont(0.99) WITHIN GROUP (ORDER BY ms)         AS p99_ms
FROM pipeline_stages
GROUP BY stage;
