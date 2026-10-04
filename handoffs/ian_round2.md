# Ian: independent proof that our numbers are right (updated Sun Oct 4, ~3:30 AM; hard stop 8:30 AM EDT)

What is judged: the 5-page quant note (PDF) plus a public repo. The rubric caps Performance at 4/10 if judges can't
reproduce the note's numbers from our code. Your job is the strongest possible evidence against that: **re-derive
the paper's headline numbers yourself, in SQL (DuckDB or Snowflake), from row-level files, without our Python.** If
you match, the paper can say a teammate independently re-derived the headline numbers.

**Don't merge PRs into main.** It gets rewritten and force-pushed this morning. Push only your own branch, or send
results to Ojasva.

## Get the latest code (updated at 3:30 AM: includes the integrated paper numbers)
```bash
git clone --branch snapshot-0300 --single-branch https://github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii ian_check && cd ian_check
# if you already cloned it:  git pull
```
Every printed number is in `results/paper/numbers.json` (`numbers` → key → `text` + `source` file::key). Ojasva
sends the current PDF.

## 1. Re-derive the headline numbers from rows (main job; send a first table by about 5:00 AM)
These row-level files are in git, so you don't need the data download:

| Paper numbers | Row-level file in the repo | What to compute |
|---|---|---|
| v2 IS / OOS: $/day, Sharpe (annualised from daily), max drawdown, worst day | `results/rigor/psr_daily.csv` | daily P&L → mean, sd, Sharpe √365 (check which annualisation the paper uses), drawdown on capital |
| CV trader at 0.5 / 1 / 3 s, both readings, IS / OOS ($/day, ¢/share, Sharpe, % wrong) | `results/tier0/latency_sweep_seeds.csv` | mean over the 20 seeds per cell |
| Tier-0 v3 burned OOS and U2 blind (IS / OOS) | `results/tier0_v3/burned_oos/trades_frozen_v3_burned_oos.parquet`, `results/tier0_v3/u2/*.parquet`, `results/tier0_v3/*/daily*.csv` | per-share ¢, $/day, Sharpe |
| Fresh holdout (licensed 0.5 s scenario) and the showcase match | `results/fresh_holdout/seed_daily_paths.csv`, `showcase_trades_all_seeds.csv`, `daily.csv` | $/day per reading, showcase mean P&L |
| Capacity (CV) | `results/capacity/cv_seeds.parquet`, `market_daily.csv` | the size where Sharpe halves |

Output `sponsors/snowflake/out/independent_rederivation.md` with a table:
`paper key | printed | your SQL value | match (✓/✗) | SQL query file`.

For every ✗, write what differs: the definition (annualisation, capital base, seed averaging) or a real mismatch.
**Send Ojasva each ✗ as soon as you find it**, because the fix workflow running now can act on it. Commit the SQL
under `sponsors/snowflake/sql/` and push branch `sponsor/snowflake-final`.

## 2. Then: every other number (`check_all.py`)
Extend your existing checker to resolve every `source` in `numbers.json` (766 keys), compare it with `text`, and
list mismatches and anything unresolvable. Also flag any number printed on pages 1–5 of the PDF that isn't in
`numbers.json`; a hard-coded number is a red flag.

## 3. If time remains: quick path on your machine
Run `bash run.sh setup && bash run.sh redteam && bash run.sh tests`, and send your OS, Python version and any full
error.

Rules: no keys in git; no "Co-Authored-By" or AI trailer lines; report rather than editing the paper.
