# Handoff: Ian — Snowflake + Vultr sponsor prizes ("COURTSIDE Warehouse" + "COURTSIDE London")

**Owner:** Ian Hoang · **Load: full** · **Deadline:** branch pushed by **9:00 AM EDT Sun Oct 4** (Devpost closes 11:00 AM EDT)
**Prizes targeted (opt in on Devpost when submitting):**
1. **MLH: Best Use of Snowflake API** (Raspberry Pi 4).
2. **MLH: Best Use of Vultr** (portable screens).

Give this whole file to your AI coding agent as its brief. It is self-contained.

---

## 0. What COURTSIDE is (read this first, 2 minutes)

COURTSIDE is our Gator Quant Hacks 2026 Systematic Trading submission (team: Ojasva Mishra, Yoan Exposito, Rafael Penhas,
Ian Hoang). Thesis: in-play tennis prices on Polymarket are set by whoever learns the point first; we measure who that is
and **what each second of speed is worth**, and our computer vision (CV) calls points before the ball lands. Latency is
the whole story: the book reprices ~1.2 s before the umpire's official stamp, public score feeds lag 28–44 s, our
pipeline turns a video frame into a ready order in 54 ms, and profit falls as feed latency rises (break-even ~1–2 s).
Everything is **paper/read-only** (event rule: no funded accounts). Ojasva is finalising the paper/video/deck; you do not
touch them.

Repo: https://github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii

You only READ these (committed, small):
- `results/tier0/latency_sweep.csv` + `results/tier0/latency_sweep.json` — profit / Sharpe vs feed latency (the centre of the paper).
- `results/capacity/` — capital-capacity grid (P&L, Sharpe vs size, coverage, capital).
- `results/v2/causal.json`, `results/v2/cost_stress.json`, `results/v2/note_metrics.json` — backtest metrics.
- `results/engine/online_events_L4.jsonl` — 172 CV calls (`call, frame, t_frame, t_emit, p_miss, lead_ms, ...`).
- `results/e2e/trace.jsonl` + `results/e2e/summary.json` — per-stage pipeline timings (frame -> order-ready -> network -> fill).
- `research/v2/latency/` — our latency study; `tests/fixtures/live_sample.jsonl.gz` — 2.1 MB of real recorded CLOB messages.
- `engine/market/clob.py`, `src/live_recorder.py` — public Polymarket websocket client / recorder (no keys).

## 1. Snowflake — "COURTSIDE Warehouse" (must have) — `sponsors/snowflake/`
- Free Snowflake trial (30 days). Credentials ONLY in `.env` at the repo root (`SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`,
  `SNOWFLAKE_PASSWORD` or key-pair path, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA`); gitignored; never
  print/commit them.
- `load.py`: create a `COURTSIDE` database/schema and load the committed result files with the Snowflake Python connector
  (`write_pandas`): `LATENCY_SWEEP`, `CAPACITY_GRID`, `BACKTEST_METRICS` (flattened JSON), `CV_CALLS`, `PIPELINE_STAGES`,
  `CLOB_SAMPLE` (from the fixture: one row per message level), `VULTR_PROBE` (§2, when it exists). Small tables only.
- `queries.sql`: 6 commented analysis queries that reproduce paper numbers in SQL, e.g. break-even feed latency per reading
  (first V where $/day < 0), Sharpe at 0.5 / 1 / 3 s, capital where Sharpe halves, pipeline p50 per stage and the 3 s budget,
  CV call precision by lead bucket, and (after §2) London vs Florida feed latency. Check each against the JSON source and print
  ✓/✗.
- **Natural-language analyst on Snowflake Cortex** (`analyst.py`): use Snowflake Cortex (`SNOWFLAKE.CORTEX.COMPLETE` or Cortex
  Analyst) to answer questions like "What Sharpe do we get at a 0.5 s feed, pre-registered reading?" by generating a
  **read-only SELECT** (reject anything else in code), running it, and answering with the number + the SQL. If Cortex isn't
  available in your trial region, use the Snowflake SQL API + any LLM you have, but keep the queries in Snowflake.
- Optional: a Streamlit-in-Snowflake app with 3 charts (latency curve, capacity curve, pipeline waterfall).

## 2. Vultr — "COURTSIDE London" latency probe (must have if you have Vultr credits; MLH usually provides a code)
Our edge is speed, and Polymarket's matching engine is in London (eu-west-2). Measure what a London server buys us.
- Spin up the smallest Vultr instance in **London** (and optionally one in **Miami/Atlanta** as the US comparison).
- `sponsors/vultr/probe.py` (runs on the instance; Python + websockets): subscribe read-only to the public Polymarket CLOB
  websocket for the in-play tennis markets (reuse the market-discovery logic from `src/live_recorder.py`), and for 30–60 min
  log, per message, `server_ts` (exchange timestamp in the message) vs local receive time (NTP-synced; record `chronyc tracking`
  offset), plus round-trip time of read-only `GET https://clob.polymarket.com/time` every 2 s.
- Also run the same probe on your laptop (Florida) at the same time. Output `sponsors/vultr/out/probe_<site>.jsonl` and a
  summary: one-way feed latency p50/p90/p99 per site, REST RTT per site, and the improvement London vs Florida in ms —
  then load it into Snowflake (`VULTR_PROBE`) so it shows in §1's queries.
- `sponsors/vultr/deploy.md`: exact steps (instance type, region, setup commands); destroy the instance afterwards and say so.
- Rules: read-only market data, no keys on the box other than what the probe needs (none for public feeds); the Vultr API
  token (if you script it) stays in `.env`.

## 3. Rules (hard)
- **Folder ownership: you may only create/edit files under `sponsors/snowflake/` and `sponsors/vultr/`.** Do NOT edit anything
  else (no edits to engine/, src/, scripts/, docs/, results/, README.md, requirements.txt). Zero merge conflicts.
- **Secrets:** only in `.env` (gitignored). Never print/commit/paste them. `git grep -n "SNOWFLAKE_PASSWORD="` must only show `.env.example` style placeholders, if any.
- **Honesty:** read-only data, paper trading only; no claims of real trading, licensed feeds or live match video.
- **Commits:** plain messages, **no "Co-Authored-By" / AI-attribution trailers** (team rule).

## 4. Setup
```bash
git clone https://github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii courtside && cd courtside
git checkout -b sponsor/snowflake-vultr
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt "snowflake-connector-python[pandas]" websockets
# put Snowflake creds in .env (never commit)
```

## 5. Hand back (no merge conflicts)
- Push: `git push origin sponsor/snowflake-vultr`; open a PR "Snowflake + Vultr: COURTSIDE Warehouse / London".
- Do NOT merge or rebase main into your branch (main's history gets rewritten tonight). Ojasva copies your folders onto main
  with `git checkout sponsor/snowflake-vultr -- sponsors/snowflake sponsors/vultr`.
- PR description: what you built, how to run (≤ 4 commands each), the query ✓/✗ table, the London vs Florida latency table,
  screenshots, and the Devpost text below filled in.

## 6. Definition of done
- [ ] `python sponsors/snowflake/load.py` creates and loads all tables; prints row counts.
- [ ] `queries.sql` reproduces ≥ 5 paper numbers in SQL with ✓ against the JSON sources.
- [ ] `python sponsors/snowflake/analyst.py "Sharpe at a 1 s feed, both readings?"` answers with the number and its SQL.
- [ ] Vultr: London (and Florida) probe results + summary table + `deploy.md`; instance destroyed.
- [ ] READMEs in both folders with numbers and honesty notes; no secrets in git.

## 7. Devpost text (fill in and give to Ojasva)
**Snowflake — COURTSIDE Warehouse.** All of COURTSIDE's results live in Snowflake: the profit-vs-latency sweep, the
capital-capacity grid, our computer-vision calls and our pipeline's stage timings. Six SQL queries reproduce the paper's
headline numbers, and a Cortex-powered analyst answers questions like "what Sharpe do we get at a 0.5 s feed?" by writing a
read-only query and showing it.
**Vultr — COURTSIDE London.** Our edge is speed, and Polymarket matches orders in London. We ran our read-only feed probe
on a Vultr London server next to a Florida laptop: London saw Polymarket's book updates <X> ms sooner at the median
(p99 <Y> ms), which is exactly the kind of gap our paper prices. Paper trading only.
