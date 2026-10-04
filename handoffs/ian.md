# Handoff: Ian — Tiger Data sponsor prize ("COURTSIDE Tick Store") + optional Vultr

**Owner:** Ian Hoang · **Deadline:** branch pushed by **9:00 AM EDT Sun Oct 4** (Devpost closes 11:00 AM EDT)
**Prize targeted (opt in on Devpost when submitting):** **MLH: Best Use of Tiger Data** (Stream Deck Mini) — Tiger Data
extends PostgreSQL for real-time data and time-series metrics (hypertables, continuous aggregates, compression).
**Optional stretch:** **MLH: Best Use of Vultr** (portable screens) — only if you have Vultr credits; see §1d.

Give this whole file to your AI coding agent as its brief. It is self-contained.

---

## 0. What COURTSIDE is (read this first, 2 minutes)

COURTSIDE is our Gator Quant Hacks 2026 Systematic Trading submission (team: Ojasva Mishra, Yoan Exposito, Rafael Penhas,
Ian Hoang). Thesis: in-play tennis prices on Polymarket are set by whoever learns the point first; we measure who that is
and what each second of speed is worth, and our computer vision calls points before the ball lands. Our core data is
exactly what Tiger Data is built for: **high-frequency order-book and trade ticks** (Polymarket CLOB websocket messages,
millisecond timestamps) and **latency metrics**. Everything is **paper/read-only** (event rule: no funded accounts).
Ojasva is finalising the paper/video/deck; **you do not touch them**.

Repo: https://github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii

Already built (you only READ these):
- `src/live_recorder.py` — records the public Polymarket CLOB websocket (book snapshots, `price_change`, `last_trade_price`)
  for live tennis markets to JSONL. Public, no keys. Run: `.venv/bin/python -m src.live_recorder --hours 1`.
- `engine/market/clob.py` + `engine/market/book.py` — our live websocket client and L2 book rebuild (reuse to parse messages).
- `tests/fixtures/live_sample.jsonl.gz` — **2.1 MB committed sample** of real recorded CLOB messages (~10 min, public data):
  start here so you have data before any live run.
- `results/engine/online_events_L4.jsonl` — 172 CV calls (JSON lines: `call, frame, t_frame, t_emit, p_miss, lead_ms`).
- `results/e2e/trace.jsonl` — per-stage timestamps of the end-to-end pipeline (frame -> order-ready -> network -> fill).
- `research/v2/latency/` — our latency study (the book reprices ~1.2 s before the official umpire stamp; public score
  feeds lag 28–44 s). You can reproduce one headline metric in SQL as a showcase (see §1c).
- Public APIs (no auth): Gamma `https://gamma-api.polymarket.com/events?tag_id=...` (tennis markets), Data API trades
  `https://data-api.polymarket.com/trades?market=<conditionId>` (≤ 4 concurrent requests, back off on 429).

## 1. What you build: "COURTSIDE Tick Store" on Tiger Data

### 1a. Schema + ingest (must have) — `sponsors/tigerdata/`
- Create a free **Tiger Cloud** service (TimescaleDB). Put the connection string ONLY in `.env` at the repo root as
  `TIGER_DATABASE_URL=postgres://...` (gitignored). Never commit or print it.
- `schema.sql`: hypertables
  - `book_updates(ts timestamptz, asset_id text, market text, side text, price numeric, size numeric, kind text)` — one row per
    price level change / snapshot level;
  - `trades(ts timestamptz, asset_id text, market text, price numeric, size numeric, side text, source text)`;
  - `cv_calls(ts timestamptz, call text, p_miss double precision, lead_ms double precision, source text)`;
  - `pipeline_stages(ts timestamptz, run text, stage text, ms double precision)` (from `results/e2e/trace.jsonl`);
  - `markets(asset_id text primary key, market text, title text, outcome text, start_ts timestamptz)` (plain table).
  Use `create_hypertable(..., 'ts')`, sensible chunk intervals, indexes on `(asset_id, ts desc)`, and **compression** policies
  (`ALTER TABLE ... SET (timescaledb.compress, timescaledb.compress_segmentby = 'asset_id')` + `add_compression_policy`).
- `ingest.py`: load `tests/fixtures/live_sample.jsonl.gz` (+ any extra recordings you make) using our parsers, plus
  `online_events_L4.jsonl` and `e2e/trace.jsonl`. Batch inserts with `COPY` (psycopg 3); report rows/s.
- `live_ingest.py` (real-time): subscribe to the live Polymarket websocket for in-play tennis markets (reuse
  `engine/market/clob.py` or `src/live_recorder.py`'s market discovery) and write ticks **straight into Tiger Data** as they
  arrive; print end-to-end ingest latency (exchange timestamp -> committed row) p50/p99.

### 1b. Continuous aggregates (must have)
- `mid_1s`: 1-second bars per asset (best bid/ask/mid/spread/trade volume) via `time_bucket('1 second', ts)` continuous aggregate
  + `add_continuous_aggregate_policy`.
- `jumps`: a view/query that flags price jumps (≥ 4¢ move of the 10 s mid vs the prior 60 s — our detector definition) per market.
- `pipeline_latency`: p50/p90/p99 per stage from `pipeline_stages` (`percentile_cont`).

### 1c. Showcase queries + mini dashboard (must have)
- `queries.sql` with 5 commented, fast queries, e.g.: replay a match's 1 s mid path; list every jump with its size and the
  CV calls around it; compression ratio achieved (`hypertable_compression_stats`); ingest throughput; our pipeline latency
  waterfall (sum of stage p50s vs the 3 s bar).
- `dashboard.py` → `sponsors/tigerdata/out/dashboard.html` (static HTML with charts rendered from query results; matplotlib
  PNGs embedded or a tiny Chart.js page): live mid + jumps for one market, compression stats, ingest latency, pipeline latency.
- Report measured numbers in the README (rows stored, compression ratio, query latency, ingest latency).

### 1d. Optional stretch — Vultr (only with credits; skip if none)
- Deploy `live_ingest.py` (read-only recorder) on a **Vultr London** instance (closest region to Polymarket's matching engine)
  and measure websocket message latency from London vs a Florida laptop into the same Tiger Data table (`source` column).
  This directly supports our latency thesis. Never put keys on the box except the DB URL via env.

## 2. Rules (hard)
- **Folder ownership: you may only create/edit files under `sponsors/tigerdata/`** (and `sponsors/vultr/` for 1d). Do NOT edit
  anything else (no edits to engine/, src/, scripts/, docs/, results/, README.md, requirements.txt). Zero merge conflicts.
- **Keys:** `TIGER_DATABASE_URL` (and any Vultr token) only in `.env` (gitignored). Never print/commit/paste them.
- **Data:** only public Polymarket data and our committed files. Respect API rate limits. Do not commit large data
  (put dumps under `sponsors/tigerdata/out/` and gitignore them; keep the repo light).
- **Honesty:** read-only market data, paper only; no claim of real trading, licensed feeds or live match video.
- **Commits:** plain messages, **no "Co-Authored-By" / AI-attribution trailers** (team rule).

## 3. Setup
```bash
git clone https://github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii courtside && cd courtside
git checkout -b sponsor/tigerdata
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt "psycopg[binary]>=3.2" websockets
echo 'TIGER_DATABASE_URL=<your Tiger Cloud connection string>' >> .env   # never commit
.venv/bin/python -c "import gzip,json; print(sum(1 for _ in gzip.open('tests/fixtures/live_sample.jsonl.gz')))"  # sample rows
```

## 4. Hand back (no merge conflicts)
- Push: `git push origin sponsor/tigerdata`; open a PR "Tiger Data: COURTSIDE Tick Store".
- Do NOT merge or rebase main into your branch (main's history gets rewritten tonight). Ojasva copies your folder onto main
  with `git checkout sponsor/tigerdata -- sponsors/tigerdata`.
- PR description: what you built, how to run (≤ 4 commands), measured numbers, screenshots of the dashboard, and the Devpost
  text below filled in.

## 5. Definition of done
- [ ] `psql "$TIGER_DATABASE_URL" -f sponsors/tigerdata/schema.sql` creates hypertables, compression and continuous aggregates.
- [ ] `python sponsors/tigerdata/ingest.py` loads the fixture + CV calls + pipeline trace; prints rows and throughput.
- [ ] `python sponsors/tigerdata/live_ingest.py --minutes 10` streams live ticks into Tiger Data; prints ingest latency.
- [ ] `queries.sql` runs; `dashboard.py` writes `out/dashboard.html` with 4 panels.
- [ ] `sponsors/tigerdata/README.md` with numbers (rows, compression ratio, query ms, ingest ms) and honesty notes.
- [ ] No secrets in git (`git grep -n "postgres://"` returns nothing).

## 6. Devpost text (fill in and give to Ojasva)
**Tiger Data — COURTSIDE Tick Store.** COURTSIDE lives on millisecond ticks: every Polymarket order-book change and trade
during live tennis matches. We stream them straight from the public websocket into Tiger Data hypertables (<N> rows,
<ratio>x compression), build 1-second bars and our price-jump detector as continuous aggregates, and store our
computer-vision calls and pipeline stage timings next to the market data, so one SQL query shows the race between our model
and the market. Ingest latency p50 <X> ms; the jump query over a full match runs in <Y> ms. Read-only data, paper trading only.
