# Handoff: Ian — Snowflake sponsor prize ("COURTSIDE Warehouse") + Solana stretch

**Owner:** Ian Hoang · **Load: full** · **Deadline:** branch pushed by **9:00 AM EDT Sun Oct 4** (Devpost closes 11:00 AM EDT)
**Prizes targeted (opt in on Devpost when submitting):**
1. **MLH: Best Use of Snowflake API** (Raspberry Pi 4).
2. *Stretch, only after §1 works:* **MLH: Best Use of Solana** (Ledger Nano S Plus) — see §2.

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
  `CLOB_SAMPLE` (from the fixture: one row per message level), and `VULTR_PROBE` from `sponsors/vultr/out/summary.json` if Yoan's branch has it (optional). Small tables only.
- `queries.sql`: 6 commented analysis queries that reproduce paper numbers in SQL, e.g. break-even feed latency per reading
  (first V where $/day < 0), Sharpe at 0.5 / 1 / 3 s, capital where Sharpe halves, pipeline p50 per stage and the 3 s budget,
  CV call precision by lead bucket, and (optional, if Yoan's Vultr data exists) London vs Florida feed latency. Check each against the JSON source and print
  ✓/✗.
- **Natural-language analyst on Snowflake Cortex** (`analyst.py`): use Snowflake Cortex (`SNOWFLAKE.CORTEX.COMPLETE` or Cortex
  Analyst) to answer questions like "What Sharpe do we get at a 0.5 s feed, pre-registered reading?" by generating a
  **read-only SELECT** (reject anything else in code), running it, and answering with the number + the SQL. If Cortex isn't
  available in your trial region, use the Snowflake SQL API + any LLM you have, but keep the queries in Snowflake.
- Optional: a Streamlit-in-Snowflake app with 3 charts (latency curve, capacity curve, pipeline waterfall).

## 2. STRETCH — Solana devnet "proof of pre-registration" (about 1 hour; only after §1 is done)
Our integrity story is that we wrote our hypotheses and rules down **before** seeing results (git timestamps). Make that
tamper-evident on a public chain:
- `sponsors/solana/anchor_prereg.py`: compute SHA-256 of each pre-registration file (`HYPOTHESIS.md`, `HYPOTHESIS_V2.md`,
  `HYPOTHESIS_TT.md`, `research/v2/*/PREREG.md`, `research/v2/maker/PREREG.md`, `research/v2/tier0_v3/PREREG.md`) together with
  the git commit hash and commit time that introduced each file (`git log --diff-filter=A --format="%H %cI" -- <file>`), and
  write one **Memo-program transaction per file on Solana devnet** (memo text: `COURTSIDE prereg <file> sha256=<...> commit=<...>`).
  Use `solana-py`/`solders` or the Solana CLI; fund the devnet keypair with `solana airdrop` (devnet SOL has no value).
- `sponsors/solana/verify.py`: re-hashes the files and checks each memo on devnet (via `getTransaction`), printing a table with
  explorer links (`https://explorer.solana.com/tx/<sig>?cluster=devnet`).
- Output `sponsors/solana/anchors.json` (file, sha256, commit, commit time, tx signature, slot, block time).
- Honest framing: the chain timestamp proves the file content existed **at anchoring time** (tonight); the git commit
  times are the evidence for "before results". Say exactly that in the README.
- Rules: devnet only (never mainnet, never real funds); the devnet keypair file goes in `sponsors/solana/.keys/` and is
  gitignored (`sponsors/solana/.gitignore`); folder ownership: only `sponsors/solana/` in addition to `sponsors/snowflake/`.
- Devpost line: "**Solana:** every pre-registration file in our repo is hashed and anchored on Solana devnet
  (<N> memo transactions, links in sponsors/solana/anchors.json), so anyone can check our rules weren't edited after the fact."

## 3. Rules (hard)
- **Folder ownership: you may only create/edit files under `sponsors/snowflake/` (and `sponsors/solana/` for the stretch).** Do NOT edit anything
  else (no edits to engine/, src/, scripts/, docs/, results/, README.md, requirements.txt). Zero merge conflicts.
- **Secrets:** only in `.env` (gitignored). Never print/commit/paste them. `git grep -n "SNOWFLAKE_PASSWORD="` must only show `.env.example` style placeholders, if any.
- **Honesty:** read-only data, paper trading only; no claims of real trading, licensed feeds or live match video.
- **Commits:** plain messages, **no "Co-Authored-By" / AI-attribution trailers** (team rule).

## 4. Setup
```bash
git clone https://github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii courtside && cd courtside
git checkout -b sponsor/snowflake
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt "snowflake-connector-python[pandas]" websockets
# put Snowflake creds in .env (never commit)
```

## 5. Hand back (no merge conflicts)
- Push: `git push origin sponsor/snowflake`; open a PR "Snowflake: COURTSIDE Warehouse".
- Do NOT merge or rebase main into your branch (main's history gets rewritten tonight). Ojasva copies your folders onto main
  with `git checkout sponsor/snowflake -- sponsors/snowflake sponsors/solana`.
- PR description: what you built, how to run (≤ 4 commands each), the query ✓/✗ table, Solana explorer links (if done),
  screenshots, and the Devpost text below filled in.

## 6. Definition of done
- [ ] `python sponsors/snowflake/load.py` creates and loads all tables; prints row counts.
- [ ] `queries.sql` reproduces ≥ 5 paper numbers in SQL with ✓ against the JSON sources.
- [ ] `python sponsors/snowflake/analyst.py "Sharpe at a 1 s feed, both readings?"` answers with the number and its SQL.
- [ ] (stretch) Solana: `sponsors/solana/anchors.json` + `verify.py` passing on devnet.
- [ ] READMEs in both folders with numbers and honesty notes; no secrets in git.

## 7. Devpost text (fill in and give to Ojasva)
**Snowflake — COURTSIDE Warehouse.** All of COURTSIDE's results live in Snowflake: the profit-vs-latency sweep, the
capital-capacity grid, our computer-vision calls and our pipeline's stage timings. Six SQL queries reproduce the paper's
headline numbers, and a Cortex-powered analyst answers questions like "what Sharpe do we get at a 0.5 s feed?" by writing a
read-only query and showing it.
**Solana (stretch).** Every pre-registration file in our repo is hashed and anchored on Solana devnet (<N> memo transactions, links in sponsors/solana/anchors.json), so anyone can check our rules weren't edited after the fact.
