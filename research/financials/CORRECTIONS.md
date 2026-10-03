# Corrections for the final paper pass

Written about 19:45 UTC Oct 3 by the PM-review compute pass (`research/financials/PM_REVIEW.md`). These are edits
to files this pass may not touch. Each item gives the file, the line as of `HEAD` at the time of writing, the old
text, the new text, and where the new number comes from. Line numbers drift as other workstreams edit, so match on
the quoted old text.

Sources used below:
- `pm_compute` = `results/financials/pm_compute.json`, written by `scripts/pm_compute.py` (`quick` and `sens` modes).
- `FINANCIALS` = `research/financials/FINANCIALS.md` / `results/financials/financials.json`, written by
  `scripts/financials.py` (re-run at 19:34 UTC; 26 reference checks, 0 failed).
- `RISK` = `docs/RISK.md` (updated in this pass).

Files fixed directly in this pass (no action needed): `research/financials/FINANCIALS.md` (via
`scripts/financials.py`), `docs/RISK.md`, `research/financials/PM_REVIEW.md`, `results/summary.json` (stale `v2`
key renamed `v2_onset_superseded`, P16).

## docs/NOTE.md (owner: note workstream)

| # | PM item | line | old | new | source |
|---|---|---|---|---|---|
| N1 | P07 | 120 | `† Clustered by copied wallet instead: [−0.60, 2.11];` | `† Clustered by copied wallet instead: [−0.45, 2.38] (in sample [0.57, 2.30]);` | `pm_compute` `p07_wallet_clustered_ci` (2,000 wallet draws, seed 0). The old value has no producing script and does not reproduce: across seeds 0/1/42/20261003 and 1,000–10,000 draws the bounds stay in [−0.53, −0.45] and [2.28, 2.41] |
| N2 | P19 | 94 | `**+0.6 to +2.4; 8/8 months > 0**` | `**+0.6 to +2.4; 9/9 months > 0**` | `results/summary.json` `is.h6_walkforward`: 9 rows, Dec 2025 – Aug 2026, net 30 s markout +0.60 to +2.41¢ |
| N3 | P19 | 94 | `**+0.4 to +0.8; 3/3 > 0**` | `**+0.4 to +0.8; 3/3 > 0** (Aug row mixes in-sample days; Oct = 3 days)` | `results/summary.json` `oos.h6_walkforward` (Aug +0.83, Sep +0.70, Oct +0.44¢; Oct resolution net −0.54¢) |
| N4 | P19 | 11 | `the fast tier beat the market in 3 of 3 held-out months` | `the fast tier beat the market in 3 of 3 held-out months (two of them partial)` | as N3 |
| N5 | P24 | 177–178 | `On Fama–French market, size, value and momentum (142 days): alpha +0.79%/day (t = 8.5), every beta insignificant (largest t = 1.33), R² = 3%.` | `On Fama–French market, size, value and momentum (in sample only, all 206 calendar days, returns in excess of the T-bill): alpha +0.68%/day (t = 9.5), every beta insignificant (largest t = 1.54, market beta 0.18), R² = 2%.` | `pm_compute` `p24_factor_regression_is.calendar_days_excess_x365`. The committed regression also used burned-OOS days to Aug 31, dropped weekends and annualised ×252 |
| N6 | P04 | 189–192 | `The sizing lens's frontier (1 s/5% regime, per 30 days, onset labels): $23k of capital trades $259k at Sharpe 16.8, $79k trades $1.10M at 6.6, $102k trades $1.65M at 6.0. So roughly **$100k** before Sharpe falls to ~6; beyond that,` | `Scaling every cap of the frozen rule (causal window): in sample 2× makes $316/day at Sharpe 12.8 on $45k and 5× $529/day at 10.4 on $80k; on the burned OOS 1× makes $92/day on $23k, 2× $82.5/day at Sharpe 3.2 on $34k, and 5× loses $24.5/day. So out-of-sample capacity is about **$23–34k** of capital; beyond that,` | `FINANCIALS` §2d. The old rows are onset-labelled (D9 bug), in-sample only, and the $102k row is the copy-everything Baseline, not v2 |
| N7 | P03 | §6, after line 192 (new sentence) | — | `**Fixed costs.** A licensed point feed has no public price (assumed $1,250–10,000 a month); with a London VPS v2 carries $167/day at the central assumption ($42–332). In today's 1 s / 5% regime in-sample v2 nets $179/day (+$12/day after costs); the burned OOS nets $92/day (−$75/day). With the book held fixed, the break-even taker fee on the burned OOS is 8.2% before fixed costs and 2.4% after central fixed costs, against 5% today.` | `FINANCIALS` headline, "How to read it" and §2a break-even fee table |
| N8 | P08 | Table 2 (lines 105–118), new column or row | — | `In sample, 1 s / 5% only (Jul 11 – Aug 25, 46 d): 15,120 trades; +1.02 [0.59, 1.45]; $179/day; Sharpe 11.2; max DD −2.0%; 2/2 months` | `FINANCIALS` headline row "IS, current 1 s / 5% regime only" (engine bootstrap, 1,000 draws; `results/financials/pm_checks.json` with 2,000 draws gives [0.60, 1.45]) |
| N9 | P01 | Summary (line 13) and Table 2 | — | add an "executable today" line: `Copying the same trades from a remote seat (3 s later, mid + half spread) loses −0.89¢ [−1.10, −0.68] in sample and −1.89¢ [−2.41, −1.36] on the burned OOS; the remote-executable side-market maker failed its blind test (−$379).` | `RISK` stress table (late entry); `results/maker/oos.json` |
| N10 | P06 | 172–174 | `Out of sample the top five copied wallets carry 98% of the blind-test profit;` | `Out of sample the top five copied wallets carry 98% of the blind-test profit and 142% of the burned-window profit (without them −0.34¢ [−1.24, 0.55]);` | `RISK` R2 (`results/risk/risk_stats.json` `concentration`) |
| N11 | P18 | 155 | `(`results/oos_peeks.log`, 19 lines)` | recount at submission. At 19:41 UTC the log had 28 lines; new since the note's count: maker live-engine replays and test runs, table tennis TT1–TT5 and diagnostics, this review's P07 (wallet CI) and P17 (clean-clone reproduction) | `results/oos_peeks.log` |
| N12 | P09 | 198–199 | `called 11 of 11 table-tennis misses correctly 50 ms before contact (recall 27%)` | `called 11 of 11 table-tennis misses correctly 50 ms before contact (Wilson 95% CI [0.74, 1.00]; recall 27%); after the label audit 8 of 8 (recall 38%), and the deployable online rule 3 of 3 (recall 7%)` | `RISK` R7 (`risk_stats` `cv_calls`), `DEVIATIONS.md` H3-D10 |
| N13 | P25 | 166–167 | `**De-risking (set in advance; not backtested).**` | `**De-risking (set in advance).** Replayed on in-sample days, the trailing-edge rule never fires (the causal 30-day edge stays ≥ +0.74¢), so it is untested on a decline.` (keep the rest) | `pm_compute` `p25_kill_rules_is` |
| N14 | P14 | 56–59, after "(our check is the blind test on 11,307 smaller markets, §4)" | — | `Rebuilt on a point-in-time universe (pre-start volume ≥ $5k), in-sample v2 still earns +1.29¢ [0.98, 1.59] (Sharpe 10.0), but only +0.44¢ [−0.14, 1.01] in today's 1 s / 5% regime.` | `pm_compute` `p15_sensitivity_is.runs["universe_prestart>=5000"]` |
| N15 | P15 | 136, after "(a plateau, not a spike)" | — | `Moving each signal threshold of the frozen rule one step (detector 3/6¢, short and long windows, 2–6 s entry window, qualification counts and t, n₀, price zone; 19 in-sample re-runs) keeps +1.21 to +1.46¢/share, every CI above 0.` | `pm_compute` `p15_sensitivity_is` |
| N16 | P26 | §1 (after line 34) or §4 | — | `Of the 1.99¢ gross in-sample edge, 1.56¢ [1.50, 1.62] is the fill against the mid 30 s later (the stale quote) and 0.43¢ [0.21, 0.64] is drift to resolution; in today's regime the drift CI includes 0 ([−0.04, 0.81]).` | `pm_compute` `p26_gross_edge_split_is` |
| N17 | P13 | 121–122 | `Returns are arithmetic, on capital with a 4 h lock per position` | `Returns are arithmetic, on each period's own capital with a 4 h lock per position (on the in-sample $28.3k, the burned-window return is 119% a year, not 148%)` | `FINANCIALS` §2c "on one capital fixed ex ante" row |
| N18 | P10 | §6 or §7 (new sentence) | — | `A courtside tier-0 counterfactual (feed and camera assumed, not bought) nets $89/day in sample and $46/day on the burned window after the verifier's corrections, against $1,151–7,215/day of fixed costs at 10 covered matches a day: uneconomic.` | `results/tier0/results.json` `headline` (20-seed means; `results/tier0/VERIFIED`); `FINANCIALS` §4 |
| N19 | P11 | 206–207 | `a side-market leaning maker (blind OOS +1.87¢ [−0.14, 3.86], a fail;` | `a side-market leaning maker (blind OOS +1.87¢ [−0.14, 3.86] per fill, −0.75¢ share-weighted and −$379, a fail;` | `results/maker/oos.json`; `FINANCIALS` §5 |
| N20 | P22 | 193 | `The book reprices 1.2 s *before* the official WTA point stamp (482 points)` | keep, but use one figure everywhere: 1.16 s (n = 482, `research/v2/latency/RESULTS.md`). Tier-0 uses −1.32 s (`results/tier0/results.json` `timing`) on a different sample; say so where it appears | latency RESULTS; tier-0 results |
| N21 | P28 | 123 (Table 2 note) | `Derived rows: `scripts/note_metrics.py`.` | `Daily P&L is booked on the entry date (positions resolve a median 1.25 h later). Derived rows: `scripts/note_metrics.py`.` | `FINANCIALS` §2b |
| N22 | P04 (table item 17) | 192 | `displacing the fast tier ($0.3–3.1M a month in the window)` | `displacing the fast tier ($0.45–2.7M a month over Feb–Aug, $3.1M in September)` | `results/risk/risk_stats.json` `liquidity_capital.fast_tier_0_3s_usd_by_month` (Mar $449,794 to Jul $2,726,479; Sep $3,115,142, onset-labelled). The old low end is the 3-day October |

## README.md (owner: README workstream)

| # | PM item | line | old | new | source |
|---|---|---|---|---|---|
| R1 | P19 | 15 | `beat the market in **11/11 months** (8 in sample, 3 out of sample)` | `beat the market in **every month: 9/9 in sample (Dec 2025 – Aug 2026) and 3/3 out of sample** (the Aug row mixes in-sample days; Oct is 3 days)` | `results/summary.json` `h6_walkforward` |
| R2 | P01, P03, P08 | 17 | (row starts `**in sample** +1.38¢/share`) | prepend: `**Executable today:** copying from a remote seat loses −1.89¢/share on the burned OOS; the remote maker failed its blind test (−$379). **Today's regime (1 s / 5%, in sample):** +1.02¢ [0.59, 1.45], $179/day vs $167/day of central fixed costs. **After fixed costs** the burned OOS is −$75/day.` | `RISK` stress table; `FINANCIALS` headline |
| R3 | P22 | 21 | `ESPN/Polymarket/WTA feeds are 27–43 s behind` | `ESPN/Polymarket/WTA feeds are 27–43 s behind the official stamp` | NOTE §6 (27.5, 29.1, 43.3 s after the stamp) |
| R4 | P05 | layout section | cites `engine/`, `scripts/live_paper.py`, tier-0 files | make sure every cited path is committed and pushed before 11:00 EDT Oct 4 | `git status` |

## docs/DEVPOST.md (owner: Devpost workstream)

| # | PM item | line | old | new | source |
|---|---|---|---|---|---|
| D1 | P01 | 24 | `In sample it earns **+1.38¢/share, Sharpe 14.5, max drawdown −2.0%, 7/7` | lead with: `At the fast tier's own fills (the prize for being that fast, not our execution today) in sample it earns **+1.38¢/share, Sharpe 14.5 …`; add after the sentence: `Copied from a remote seat it loses −1.89¢/share out of sample; after a $167/day central data-and-hosting cost the burned window is −$75/day.` | `RISK`; `FINANCIALS` |
| D2 | P09 | 34 | `11/11 correct (recall 27%)` | `11/11 correct (recall 27%; 8/8 after the label audit, 3/3 for the deployable online rule, recall 7%)` | `RISK` R7 |

## docs/COMPLIANCE.md (owner: compliance workstream)

| # | PM item | line | old | new | source |
|---|---|---|---|---|---|
| C1 | P18 | 49 (item 27) | `itemises all 15 log lines` | `itemises all N log lines` with N recounted at submission (28 at 19:41 UTC) | `results/oos_peeks.log` |
| C2 | P17 | 80 (item 53) | `Team: re-run `reproduce.sh` on a clean clone and diff against the note before submitting` | see "P17" below for what the clean-clone run found; keep "Partly met" until `run_all.py --oos` has been run end to end on a clone | `research/financials/PM_REVIEW.md` "Compute-now results" |

## Other files (not owned by this pass)

| # | PM item | file | change | why |
|---|---|---|---|---|
| O1 | P07 | `research/compliance/JUDGE.md` lines 257, 556 | `[−0.60, 2.11]` → `[−0.45, 2.38]` | as N1 |
| O2 | P24 | `scripts/factor_regression.py` | restrict to IS conds (it filters `month >= 2026-02` only, so Aug 25–31 burned-OOS days are in), zero-fill calendar days with factors and RF = 0 off trading days, regress the excess return, annualise ×365 (`scripts/pm_compute.py` `p24_factors` does exactly this); then re-run so `results/v2/factor_regression.json` matches N5 | P24 |
| O3 | P16 | `src/backtest.py` line 69 | `"best_month_share": float(monthly.max() / max(monthly.sum(), 1e-9))` → `float(monthly.max() / monthly.sum()) if monthly.sum() > 0 else None` | a negative total divides by 1e-9: −4.4×10¹² in `results/summary.json` `oos.h1`, 1.7×10¹¹ in `results/maker/oos.json` |
| O4 | P25 | `engine/risk/limits.py` `RiskConfig` | per-book `daily_stop_usd`: v2 1,000; v2-safe 545; maker v1 599 (each book's IS daily σ × 3.86, v2's ratio) | `RISK` "Per-book calibration"; `pm_compute` `p25_kill_rules_is.daily_stop_per_book` |
| O5 | P23 | `research/rigor/RESULTS.md` lines 43, 47 | `NOTE.md §8` → `NOTE.md §4` (the trial count and DSR convention are in §4 and §7; there is no §8) | P23 |
| O6 | P10 | `research/v2/tier0/RESULTS.md` | none: revised in commit `a5769c7` to lead with the corrected headline (+1.10¢ [0.82, 1.38], $89/day IS; +0.58¢ [−0.08, 1.21], $46/day OOS). Quote those, not the superseded §6 record | done by the tier-0 workstream |
| O7 | P17 | `reproduce.sh` line 10 onward | quote the interpreter: `"$PY" run_all.py --oos` etc. With `PY` set to a path containing spaces (this repo's own path does), every step fails with "Permission denied" | found by the clean-clone run |
| O8 | P17 | `src/backtest.py` `run(..., workers=8)` | default 8 workers; on a shared machine with a ≤ 2-process budget `run_all.py --oos` did not finish its first stage in 18 min at 1 worker. Expose `--workers` in `run_all.py` and document the runtime | clean-clone run |
