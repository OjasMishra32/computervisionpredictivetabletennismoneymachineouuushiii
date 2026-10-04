# COURTSIDE Warehouse (Snowflake)

All of COURTSIDE's committed results live in one Snowflake schema: the profit-vs-feed-delay sweep, the
capital-capacity grid, the v2 backtest metrics, our computer-vision calls, the end-to-end pipeline's stage
timestamps, 10 minutes of recorded public order-book messages, and the paper's own number file. `queries.sql`
recomputes the paper's headline numbers in SQL, and `check.py` runs it on Snowflake and checks every number against
the paper.

**Result: 62 / 62 paper numbers reproduced in SQL on Snowflake**: 20 recomputed from rows (break-even feed delay,
capital where Sharpe halves, pipeline latency percentiles), 42 looked up from stored metrics (Sharpe, $/day and
¢/share at a 0.5 / 1 / 3 s feed; v2 headline). Full table: [`out/checks.md`](out/checks.md) (Snowflake run) and
[`out/checks_offline.md`](out/checks_offline.md) (the same SQL on DuckDB, a check that needs no account).

This folder is optional and separate from the paper's pipeline: nothing in `reproduce.sh`, `run_all.py`, `src/`,
`scripts/` or `tests/` uses it, it has its own requirements, and it writes only to `sponsors/snowflake/out/`.

## Independent re-derivation from row-level files (`sql/`, `rederive.py`)

The paper's headline numbers recomputed in SQL straight from row-level files in git, without the team's Python:
v2's daily P&L (`results/rigor/psr_daily.csv`), the CV trader's 20 per-seed sweep cells and daily paths
(`results/tier0/latency_sweep_seeds.csv`), the frozen CV rule v3's blind trades (`results/tier0_v3/u2/*.parquet`), the
fresh holdout's per-seed daily paths and showcase trades (`results/fresh_holdout/`), and the capacity grid's per-seed
cells (`results/capacity/cv_seeds.parquet`). Each `sql/*.sql` states its definitions in its header and runs on its own
from the repo root (`duckdb -c ".read sponsors/snowflake/sql/01_v2_daily.sql"`); `rederive.py` only runs them and
compares each value with the printed text:

```bash
sponsors/snowflake/.venv/bin/python sponsors/snowflake/rederive.py
```

Output: [`out/independent_rederivation.md`](out/independent_rederivation.md) (paper key, printed, SQL value, ✓/✗,
SQL file, definition; every ✗ explained).

## Every number in the paper (`check_all.py`)

`check_all.py` checks all of the paper's printed numbers, not just the 62 above. It reads
`results/note_numbers.json` (else `results/paper/numbers.json`), resolves each entry's `source` from the committed
files (JSON paths, CSV rows through DuckDB, derived formulas, code lines, git history), formats the value the way the
paper prints it and compares it with the printed text. Where row-level data is committed it recomputes instead of
reading a stored summary (v2's Sharpe from `results/lowloss/daily.csv`). It also lists numbers on PDF pages 1-5 that
the numbers file doesn't contain, and digits typed straight into `docs/paper/note.tex.j2` that equal a printed result.
No account needed:

```bash
sponsors/snowflake/.venv/bin/python sponsors/snowflake/check_all.py              # or --root <checkout> --pdf <file>
```

Output: [`out/check_all.md`](out/check_all.md) (summary line, every mismatch, every unresolvable source, matches that
needed a looser rule such as a x100 percent scale, PDF and template scans).

## Run it (Python 3.11+, own venv, your own Snowflake account)

```bash
python3 -m venv sponsors/snowflake/.venv && sponsors/snowflake/.venv/bin/pip install -r sponsors/snowflake/requirements.txt
cat sponsors/snowflake/.env.example >> .env      # fill in YOUR account + user in .env (gitignored); key pair: see Sign-in
sponsors/snowflake/.venv/bin/python sponsors/snowflake/load.py     # create COURTSIDE.WAREHOUSE, load 8 tables (~30 s)
sponsors/snowflake/.venv/bin/python sponsors/snowflake/check.py    # run queries.sql on Snowflake, ✓/✗ vs the paper
```

No account? `sponsors/snowflake/.venv/bin/python sponsors/snowflake/check.py --offline` runs the same SQL on an
in-memory DuckDB copy of the same tables, with no credentials.

The connector gets its own venv because its pandas extra pins pandas < 3 and an older pyarrow; installing it into the
main venv would replace the pins the paper's numbers were produced with.

## Tables (`load.py`, all built from files in git)

| table | rows | from |
|---|---|---|
| `LATENCY_SWEEP` | 944 | `results/tier0/latency_sweep.csv`: 20-seed-mean P&L, Sharpe, ¢/share vs feed delay, per reading and period |
| `CAPACITY_GRID` | 1,848 | `results/capacity/cv_cells.csv`: CV strategy size cells (capital, Sharpe, $/day) |
| `BACKTEST_METRICS` | 343 | `results/v2/{causal,cost_stress,note_metrics}.json`, one row per JSON leaf |
| `CV_CALLS` | 172 | `results/engine/online_events_L4.jsonl`: real-time CV calls (NVIDIA L4, table-tennis test footage) |
| `PIPELINE_STAGES` | 132 | `results/e2e/trace.jsonl`: raw stage timestamps per call; 24 complete order traces |
| `CLOB_SAMPLE` / `CLOB_TOKENS` | 329,430 / 260 | `tests/fixtures/live_sample.jsonl.gz`: one row per message level |
| `PAPER_NUMBERS` | 670 | `results/paper/numbers.json`: every number printed in the paper, with its source |
| `VULTR_PROBE` | (optional) | `sponsors/vultr/out/summary.json`, loaded only if that folder is present |

## Queries (`queries.sql`)

| # | query | kind | paper numbers |
|---|---|---|---|
| Q1 | Sharpe, $/day, ¢/share at a 0.5 / 1 / 3 s feed, both readings, IS and burned OOS | lookup | 36 |
| Q2 | break-even feed delay: first zero crossing of the seed-mean $/day curve, interpolated | recomputed | 6 |
| Q3 | capital where Sharpe halves along the size path, linear in log capital, and $/day there | recomputed | 8 |
| Q4 | pipeline: ours (frame -> order ready), network, total with the 1 s feed, p99, margin to 3 s, n | recomputed | 6 |
| Q5 | v2 headline: Sharpe, max drawdown, ¢/share, IS and burned OOS | lookup | 6 |
| Q6 | pipeline waterfall: median ms per stage | descriptive | |
| Q7 | CV calls by lead before the bounce | descriptive | |
| Q8 | recorded order-book sample: server-to-receive lag, moneyline spread | descriptive | |

The interpolation rules are the same as the Python ones (`scripts/tier0_latency_sweep.py::first_crossing`,
`scripts/capacity_study.py::capacity_answer`); the percentiles are linear (numpy's default, `PERCENTILE_CONT`).

## Honesty notes

- This is a read-only copy of results already in the repo. Nothing here reads market data, changes a result or
  trades; every P&L is paper (simulated) and the CV numbers rest on an assumed feed latency (licensed feed and
  licensed video not purchased), as in the paper.
- *Lookup* rows check that the paper quotes the stored value correctly; only *recomputed* rows re-derive a number.
- Capacity: `cv_cells.csv` stores Sharpe to 4 decimals, while `capacity.json` was computed from unrounded values, so
  the SQL capital differs from the stored one by under $1 ($73,288.56 vs $73,288). The paper's own Python rule on the
  same CSV gives the SQL value; both print as $73,000.
- `CV_CALLS` has no ground-truth labels, so Q7 profiles the calls; it does not measure precision.
- `CLOB_SAMPLE` lag (receive time minus server stamp) includes the recording laptop's clock offset; it is a 10-minute
  mechanics sample, not a latency result.
- Not included: a natural-language analyst on Snowflake Cortex was planned, but Snowflake blocks every Cortex AI
  function on trial accounts (error 399258, "not available for trial accounts"; tested `COMPLETE`, `AI_COMPLETE`,
  `SUMMARIZE`, `SENTIMENT`, `AI_CLASSIFY`, `AI_FILTER`), so we ship only what we ran.

## Sign-in

Scripts sign in with a key pair, so there is no password in `.env` and no MFA prompt. Make the key outside the repo
(commands in `.env.example`), then register its public half once in a Snowsight SQL worksheet. The quotes in the first
line matter when your user name is an email address:

```sql
SET me = '"' || CURRENT_USER() || '"';
ALTER USER IDENTIFIER($me) SET RSA_PUBLIC_KEY = '<public key body, one line, no BEGIN/END lines>';
```

`SNOWFLAKE_AUTHENTICATOR=externalbrowser` works only for accounts with SAML single sign-on; on a plain trial account it
fails with error 390190 ("SAML Identity Provider account parameter"). If `load.py` says "No active warehouse selected",
set `SNOWFLAKE_WAREHOUSE` to a warehouse from `SHOW WAREHOUSES` (new trials have `SNOWFLAKE_LEARNING_WH`).
