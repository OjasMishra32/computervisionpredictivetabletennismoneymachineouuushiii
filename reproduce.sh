#!/usr/bin/env bash
# Every number and figure in docs/NOTE.pdf (the LaTeX paper) and the docs, from cached public data (bash run.sh data first).
# On a fresh clone, step 1 builds the locked OOS prints and appends one line to results/oos_peeks.log:
# that line records your run, not ours. Re-running on an existing checkout appends nothing.
# Not run here (cached outputs are committed): scripts/rigor_pack.py (DSR, PBO, bootstrap; it rewrites
# research/rigor/RESULTS.md), HiPerGator tracking (hpg/), live order-book recordings (src/live_recorder.py).
set -euo pipefail
cd "$(dirname "$0")"
PY=${PY:-.venv/bin/python}
$PY run_all.py --oos            # H1-H6, calibration, tiers, fast tier (v1)               -> paper \label{tab:A-all}, {fig:edge}a
$PY scripts/v2_causal.py        # v2 (causal window) on IS + burned OOS, slippage stress  -> paper \label{tab:head}
$PY scripts/v2_cost_stress.py   # v2 with fees / all costs doubled                        -> paper \label{tab:head}, {fig:edge}b
$PY scripts/note_metrics.py     # ann. return, vol, turnover, skew, bps, holdout, gaps    -> paper \label{tab:head}, sec:data, sec:method
$PY scripts/v2_figures.py       # results/figures (earlier note figure, kept for the deck)
$PY scripts/factor_regression.py
$PY scripts/leverage_stats.py
$PY scripts/paper_figures.py    # earlier figure set (results/paper/*.pdf; its loaders are shared with v2)
$PY scripts/rally_gate_eval.py  # rally gate on the engine's held-out call log (committed log, < 2 s) -> paper sec:method, Table A1
$PY scripts/data_coverage.py    # real matches behind every result (event listing + committed result files) -> paper tab:data
$PY scripts/v2_wallet_cap.py --is          # per-wallet cap grid, IS only (research/v2/risk/GRID_wallet_cap.md)  -> paper sec:risk
$PY scripts/v2_wallet_cap.py --oos --repro # the pre-registered cap's single burned-OOS run, recomputed (not a new peek) -> sec:risk
$PY scripts/impact_model.py     # price impact from public tapes + the live book, capacity re-run (~8 min)   -> paper sec:liq
$PY scripts/edge_persistence.py # edge decay, fee vs entrants, profit pool (IS prints + published OOS rows)  -> paper sec:hyp
$PY scripts/psr_mintrl.py       # PSR, MinTRL, haircut Sharpe at N = all variants, copier fill stress (~2 min) -> sec:summary, sec:results
$PY scripts/cv_cost_turnover.py # CV trader: return, vol, max DD, turnover, fee bps, fees x2 per Table-1 cell (~1 min; logs a read) -> tab:head
$PY scripts/sponsor_evidence.py # Vultr latency legs in the 3 s budget + Snowflake SQL re-check (SQL part needs duckdb on PYTHONPATH)
$PY scripts/cv_teaser_fig.py    # Fig. 1: the vision work (committed tracks and test bounce)                 -> paper fig:teaser
# The fresh holdout NEEDS NETWORK: it lists and downloads the newest finished matches from Polymarket's public Gamma
# and Data APIs (no keys) into data/fresh/ (gitignored). Run it with FRESH=1 bash reproduce.sh; otherwise the
# committed results/fresh_holdout/ are used. A new fetch has a new fetch time, so it is a new holdout, not ours.
if [ "${FRESH:-0}" = 1 ]; then
  $PY scripts/fresh_holdout.py --all          # G1, G2 gates, fetch, frozen run (PREREG research/v2/tier0_v3/fresh/PREREG_FRESH.md)
  $PY scripts/fresh_holdout_seed_paths.py     # every seed's daily P&L for the equity curves
fi
$PY scripts/firm_scenario_fig.py # Fig. 3: a firm with a licensed 0.5 s feed (from results/fresh_holdout/)  -> paper fig:firm
$PY scripts/build_paper.py     # the paper's figures (results/paper/v2, scripts/paper_figures_v2.py), numbers.json +
                                # LaTeX via tectonic -> docs/NOTE.pdf (+ NOTE.md); fails on > 5 main pages, < 11 pt
                                # text, margins, honesty grep; keeps the committed PDF (exit 0) if tectonic is missing
$PY scripts/build_docs.py       # README.md, docs/DEVPOST.md, docs/COMPLIANCE.md from results/paper/numbers.json
                                # and the paper's labels (also kept in results/paper/labels.json)
