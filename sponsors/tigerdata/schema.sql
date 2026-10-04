-- COURTSIDE Tick Store on Tiger Data (TimescaleDB).
--   psql "$TIGER_DATABASE_URL" -f sponsors/tigerdata/schema.sql
-- Safe to re-run: drops and recreates everything under the courtside schema.

SELECT delete_job(job_id) FROM timescaledb_information.jobs WHERE proc_schema = 'courtside';
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
    winner      boolean,                -- set from market_resolved messages
    source      text                    -- 'live_sample' (committed fixture) | 'live' (live_ingest.py)
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
CREATE MATERIALIZED VIEW mid_1s WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
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
CREATE MATERIALIZED VIEW trades_1s WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
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

-- ===================================================================================================
-- COURTSIDE Live Lab: the paper's question ("who gets paid in the seconds after a point?") answered
-- live, inside the database, while matches are being played.
-- ===================================================================================================

-- Every trade with the wallet that made it (Polymarket Data API, polled by live_ingest.py).
CREATE TABLE wallet_trades (
    ts        timestamptz NOT NULL,       -- venue trade time (1 s resolution)
    asset_id  text        NOT NULL,
    market    text        NOT NULL,
    wallet    text        NOT NULL,       -- public proxy wallet address
    side      text        NOT NULL,       -- 'BUY' | 'SELL' of this outcome token
    price     numeric(6,4) NOT NULL,
    size      numeric      NOT NULL,
    tx        text        NOT NULL
);
SELECT create_hypertable('wallet_trades', 'ts', chunk_time_interval => interval '1 day');
CREATE UNIQUE INDEX ON wallet_trades (tx, asset_id, wallet, side, price, size, ts);
CREATE INDEX ON wallet_trades (asset_id, ts DESC);
CREATE INDEX ON wallet_trades (wallet, ts DESC);

-- How fast ticks land: per flush, exchange timestamp -> row committed in Tiger Data.
CREATE TABLE ingest_lag (
    ts       timestamptz NOT NULL,        -- commit time
    stream   text        NOT NULL,        -- 'book' | 'trade' | 'wallet'
    n        int         NOT NULL,
    p50_ms   double precision,
    p99_ms   double precision
);
SELECT create_hypertable('ingest_lag', 'ts', chunk_time_interval => interval '1 day');

-- Tick lifecycle: raw ticks kept 30 days, bars kept forever.
SELECT add_retention_policy('book_updates', drop_after => interval '30 days');

-- Hierarchical continuous aggregate: 1-minute candles built from the 1-second bars, not from raw ticks.
CREATE MATERIALIZED VIEW candles_1m WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT asset_id,
       time_bucket('1 minute', bucket) AS minute,
       first(mid, bucket) AS open, max(mid) AS high, min(mid) AS low, last(mid, bucket) AS close,
       avg(spread) AS avg_spread, sum(updates) AS updates
FROM mid_1s
GROUP BY asset_id, minute
WITH NO DATA;
SELECT add_continuous_aggregate_policy('candles_1m', start_offset => interval '1 day',
       end_offset => interval '1 minute', schedule_interval => interval '1 minute');

-- Points, detected inside the database: a scheduled job (every 5 s) runs the jump detector over the newest
-- 1 s bars and appends each new jump here, so later queries join an indexed table, not a window scan.
CREATE TABLE jump_events (
    detected_at timestamptz NOT NULL,
    asset_id    text        NOT NULL,
    move_cents  numeric,
    direction   text,
    PRIMARY KEY (asset_id, detected_at)
);
SELECT create_hypertable('jump_events', 'detected_at', chunk_time_interval => interval '1 day');

CREATE PROCEDURE detect_jumps(job_id int DEFAULT 0, config jsonb DEFAULT '{}') LANGUAGE sql AS $$
    INSERT INTO courtside.jump_events (detected_at, asset_id, move_cents, direction)
    WITH since AS (SELECT coalesce(max(detected_at) - interval '2 minutes', '-infinity') AS t FROM courtside.jump_events),
    w AS (
        SELECT asset_id, bucket,
               avg(mid) OVER (PARTITION BY asset_id ORDER BY bucket
                              RANGE BETWEEN interval '9 seconds' PRECEDING AND CURRENT ROW)                     AS m10,
               avg(mid) OVER (PARTITION BY asset_id ORDER BY bucket
                              RANGE BETWEEN interval '70 seconds' PRECEDING AND interval '10 seconds' PRECEDING) AS m60
        FROM courtside.mid_1s, since WHERE bucket > since.t - interval '80 seconds'
    ), f AS (
        SELECT *, m10 - m60 AS move, abs(m10 - m60) >= 0.04 AS is_jump,
               lag(abs(m10 - m60) >= 0.04) OVER (PARTITION BY asset_id ORDER BY bucket) AS was_jump
        FROM w
    )
    SELECT bucket, asset_id, round(move * 100, 2), CASE WHEN move > 0 THEN 'up' ELSE 'down' END
    FROM f, since WHERE is_jump AND NOT coalesce(was_jump, false) AND bucket > since.t
    ON CONFLICT DO NOTHING
$$;
SELECT add_job('courtside.detect_jumps', interval '5 seconds');

-- Time travel: the full order book of any token at any millisecond (last snapshot + every change since).
CREATE FUNCTION book_at(p_asset text, p_at timestamptz)
RETURNS TABLE (side text, price numeric, size numeric) LANGUAGE sql STABLE AS $$
    WITH snap AS (
        SELECT max(ts) AS s FROM book_updates
        WHERE asset_id = p_asset AND kind = 'snapshot' AND ts <= p_at
    ), lv AS (
        SELECT DISTINCT ON (b.side, b.price) b.side, b.price, b.size
        FROM book_updates b, snap
        WHERE b.asset_id = p_asset AND b.ts >= snap.s AND b.ts <= p_at
        ORDER BY b.side, b.price, b.ts DESC, b.kind DESC
    )
    SELECT side, price, size FROM lv WHERE size > 0
    ORDER BY side, CASE WHEN side = 'bid' THEN -price ELSE price END
$$;

-- Every wallet trade, marked to market: where the mid was 5 s and 30 s later, signed by the trader's side,
-- and how many seconds after the most recent price jump (= point) it happened.
CREATE VIEW markouts AS
SELECT t.ts, t.asset_id, t.market, t.wallet, t.side, t.price, t.size, t.size * t.price AS usd,
       j.detected_at AS jump_at,
       extract(epoch FROM t.ts - j.detected_at) AS secs_after_jump,
       (m5.mid  - t.price) * CASE WHEN t.side = 'BUY' THEN 1 ELSE -1 END AS markout_5s,
       (m30.mid - t.price) * CASE WHEN t.side = 'BUY' THEN 1 ELSE -1 END AS markout_30s
FROM wallet_trades t
LEFT JOIN LATERAL (SELECT detected_at FROM jump_events j WHERE j.asset_id = t.asset_id
                   AND detected_at <= t.ts AND detected_at > t.ts - interval '10 minutes'
                   ORDER BY detected_at DESC LIMIT 1) j ON true
LEFT JOIN LATERAL (SELECT mid FROM mid_1s WHERE mid_1s.asset_id = t.asset_id
                   AND bucket <= t.ts + interval '5 seconds' ORDER BY bucket DESC LIMIT 1) m5 ON true
LEFT JOIN LATERAL (SELECT mid FROM mid_1s WHERE mid_1s.asset_id = t.asset_id
                   AND bucket <= t.ts + interval '30 seconds' ORDER BY bucket DESC LIMIT 1) m30 ON true
WHERE t.ts <= (SELECT max(ts) FROM book_updates) - interval '30 seconds';  -- only trades whose 30 s outcome is known

-- The paper's Figure 1, live: average profit per share by how soon after a point the trade was made.
CREATE VIEW who_gets_paid AS
SELECT CASE WHEN secs_after_jump IS NULL THEN 'no recent point'
            WHEN secs_after_jump < 3  THEN '0-3 s'
            WHEN secs_after_jump < 10 THEN '3-10 s'
            WHEN secs_after_jump < 60 THEN '10-60 s'
            ELSE '60 s+' END                       AS after_point,
       count(*)                                    AS trades,
       count(DISTINCT wallet)                      AS wallets,
       round(sum(usd), 0)                          AS usd,
       round(avg(markout_5s)  * 100, 2)            AS cents_per_share_5s,
       round(avg(markout_30s) * 100, 2)            AS cents_per_share_30s
FROM markouts WHERE markout_30s IS NOT NULL
GROUP BY 1;

-- The fast tier, live: wallets that trade in the first 3 s after points, ranked by what they make.
CREATE VIEW fast_tier AS
SELECT wallet,
       count(*)                                    AS fast_trades,
       count(DISTINCT asset_id)                    AS tokens,
       round(sum(usd), 0)                          AS usd,
       round(avg(markout_30s) * 100, 2)            AS cents_per_share_30s,
       round(sum(markout_30s * size), 2)           AS pnl_usd_30s
FROM markouts
WHERE secs_after_jump < 3 AND markout_30s IS NOT NULL
GROUP BY wallet
HAVING count(*) >= 3
ORDER BY pnl_usd_30s DESC;
