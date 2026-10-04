# COURTSIDE Live Lab on Tiger Data

**Our paper asks who gets paid in the seconds after a tennis point. Tiger Data answers it live, while the
matches are being played.**

COURTSIDE's finding comes from a year of historical trades: on Polymarket tennis markets, only traders who act
within about 3 seconds of a point make money. The Live Lab re-measures that finding in real time, in the database:

1. **Stream:** every order-book tick of every live tennis match goes from Polymarket's public websocket into Tiger
   Data hypertables. COPY runs four times a second, and the lag from the exchange's timestamp to a stored row is recorded.
2. **Detect points in SQL:** a 1-second real-time continuous aggregate (`mid_1s`) feeds a scheduled in-database
   job (`detect_jumps`, every 5 s), which flags each point as a 4¢ jump. This is the repo's detector, ported to SQL.
3. **Score every trader:** public wallet-level trades (Data API) land in `wallet_trades`. The `markouts` view marks
   each trade to the mid 5 s and 30 s later and tags how soon after a point it was made.
4. **Show the answer live:** `who_gets_paid` is the paper's Figure 1 recomputed from live data. `fast_tier` is a
   leaderboard of the wallets that win in the first 3 s. A local dashboard re-reads both every 3 s.

Read-only public data; nothing here signs or sends an order.

## Run it

```bash
.venv/bin/pip install "psycopg[binary]>=3.2" matplotlib websockets requests     # once
echo 'TIGER_DATABASE_URL=postgres://...' >> .env                                  # your Tiger Cloud service; gitignored
.venv/bin/python sponsors/tigerdata/ingest.py                                     # schema + committed sample + compress
.venv/bin/python sponsors/tigerdata/live_ingest.py --minutes 120                  # stream live matches (terminal 1)
.venv/bin/python sponsors/tigerdata/live_dashboard.py                             # http://localhost:8790 (terminal 2)
.venv/bin/python sponsors/tigerdata/run_queries.py                                # showcase queries, timed
```

`live_ingest.py --dry-run` streams without a database (parse and count only).

## Tiger Data features used, and why

| Feature | Where | Why it matters here |
|---|---|---|
| Hypertables | `book_updates`, `trades`, `wallet_trades`, `jump_events`, `cv_calls`, `pipeline_stages`, `ingest_lag` | About 450 order-book rows a second per evening of tennis; time-chunked so "last 20 minutes" stays fast |
| Columnar compression, segmented by token | `book_updates`, `trades` | One match's ticks compress together; ratio measured below |
| Real-time continuous aggregates | `mid_1s`, `trades_1s` | 1-second bars that include the newest ticks, so no query scans raw ticks |
| Hierarchical continuous aggregate | `candles_1m` built on `mid_1s` | 1-minute candles from bars, not from ticks |
| Scheduled job (`add_job`) | `detect_jumps` every 5 s | Point detection runs inside the database, next to the data |
| Retention policy | raw ticks 30 days, bars forever | The tick firehose stays bounded |
| SQL function over a hypertable | `book_at(token, instant)` | Time travel: the full order book at any millisecond |

## What is stored

| Table | Rows | Source |
|---|---|---|
| `book_updates` | 329,014 from the committed sample, plus live | `tests/fixtures/live_sample.jsonl.gz` (10 min, 14 events) and the live websocket |
| `trades` | 366 + live | same |
| `wallet_trades` | live | Polymarket Data API (public proxy wallets) |
| `jump_events` | computed | `detect_jumps` job |
| `cv_calls` | 172 | `results/engine/online_events_L4.jsonl` (live engine, table-tennis footage) |
| `pipeline_stages` | 3,236 | `results/e2e/trace.jsonl` (each stage, camera frame to fill) |
| `markets` | 260 + live | recorder token index; Gamma for live matches |

## Measured numbers

<!-- filled from ingest.py, live_ingest.py and run_queries.py output -->
| Metric | Value |
|---|---|
| Live stream (dry run, no database, 1 min) | 16 live matches, about 450 book rows/s, 1,438 wallet trades |
| Rows stored | TBD |
| Exchange timestamp to stored row, p50 / p99 | TBD |
| Compression, `book_updates` | TBD |
| `who_gets_paid` over the live session | TBD |
| Dashboard: all 6 queries | TBD ms |
| Pipeline, camera frame to decision (p50) | 51.6 ms |
| Pipeline, camera frame to fill against the live book (p50, paper) | 1,119 ms |

## Queries (`queries.sql`, run by `run_queries.py`)

`match_replay`, `points_and_who_trades`, `who_gets_paid`, `fast_tier`, `time_travel_book`, `candles_1m`,
`compression`, `feed_rate`, `pipeline_waterfall`, `cv_calls_summary`.

## Honesty notes

- Market data is Polymarket's public, unauthenticated websocket and Data API. Wallets are public proxy addresses.
  Nothing signs or sends an order.
- Points are inferred from price jumps (4¢ move of the 10 s mean vs the 60 s before), not from an official score.
- Markouts are marked to the mid at 5 s and 30 s, not realised P&L. Data API trade times have 1 s resolution.
- The CV calls are from table-tennis footage (OpenTTGames); no tennis match video is used. Pipeline times are
  measured on our laptop; the fill is simulated against a recorded live book after the venue's 1 s hold.
