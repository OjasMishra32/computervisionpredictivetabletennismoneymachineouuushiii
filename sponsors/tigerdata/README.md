# COURTSIDE Tick Store on Tiger Data

COURTSIDE runs on millisecond ticks: every Polymarket order-book change and trade during live tennis matches.
This folder puts them in Tiger Data (TimescaleDB) next to our computer-vision calls and pipeline timings, so one
SQL query shows the race between our model and the market. Read-only public data, paper trading only.

## Run it (4 commands)

```bash
.venv/bin/pip install "psycopg[binary]>=3.2" matplotlib            # once
echo 'TIGER_DATABASE_URL=postgres://...' >> .env                     # your Tiger Cloud service; .env is gitignored
.venv/bin/python sponsors/tigerdata/ingest.py                        # schema + load + compress, prints rows/s
.venv/bin/python sponsors/tigerdata/run_queries.py && .venv/bin/python sponsors/tigerdata/dashboard.py
```

`ingest.py` applies `schema.sql` itself (no `psql` needed); `--no-reset` appends instead.

## What is stored

| Table | Kind | Rows | Source |
|---|---|---|---|
| `book_updates` | hypertable, 1 h chunks, compressed by `asset_id` | 329,014 | `tests/fixtures/live_sample.jsonl.gz`: 10 min of the public CLOB websocket, 14 tennis events (992 snapshots, 139,437 change messages) |
| `trades` | hypertable, compressed | 366 | same recording (`last_trade_price`) |
| `markets` | plain table | 260 outcome tokens | the recorder's token index + 6 resolutions |
| `cv_calls` | hypertable | 172 | `results/engine/online_events_L4.jsonl` (live engine, table-tennis footage) |
| `pipeline_stages` | hypertable | 3,236 | `results/e2e/trace.jsonl`: per-stage durations of each call + venue round trips |

Continuous aggregates and views:

- `mid_1s`: 1-second top-of-book bars per token (bid, ask, mid, spread), refreshed every 10 s.
- `trades_1s`: 1-second trade bars; `bars_1s` joins both.
- `jumps`: the repo's detector in SQL. The 10 s average mid is compared with the 60 s before it, and a 4¢ move marks a point.
- `pipeline_latency`: p50, p90 and p99 per stage (`percentile_cont`).

## Measured numbers

<!-- filled from ingest.py / run_queries.py output -->
| Metric | Value |
|---|---|
| Rows stored | TBD |
| Ingest throughput (COPY, laptop to Tiger Cloud) | TBD rows/s |
| Compression, `book_updates` | TBD |
| Query: 1 s replay of a match | TBD ms |
| Query: all jumps + volume after each | TBD ms |
| Pipeline, camera frame to decision (p50) | 51.6 ms |
| Pipeline, camera frame to fill against the live book (p50, paper) | 1,119 ms |

## Queries (`queries.sql`)

1. `match_replay`: one match's 1 s mid, spread and dollar volume.
2. `jumps_and_who_trades`: every jump, with dollars traded in the first 3 s vs the next 27 s.
3. `compression`: before/after size per hypertable.
4. `feed_rate`: messages per second and receive delay (exchange stamp to our stamp), by kind.
5. `pipeline_waterfall`: median of each stage, camera frame to fill, cumulative against the 3,000 ms bar.
6. `cv_calls_summary`: calls by type, confidence and lead time.

## Honesty notes

- Market data is the public, unauthenticated Polymarket websocket; nothing here signs or sends an order.
- The CV calls are from table-tennis footage (OpenTTGames); no tennis match video is used.
- Pipeline stage times are measured on our laptop. The fill is simulated against the recorded live book after the
  venue's 1 s hold. A licensed feed was not purchased, so any feed delay is an assumption.
- Pipeline wall times are mapped from `time.monotonic()` with the trace's own clock offsets (about 1 s precision;
  durations are exact).
