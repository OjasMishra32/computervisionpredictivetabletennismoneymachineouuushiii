# v2 loss-averse variants: grid and selection rule, declared before any computation

Written 2026-10-03 ~17:25 UTC on top of 7358313. Nothing in this file has been computed yet. Before
this file existed, the only v2 results anyone had seen were the frozen v2 (`G_50pct_net100`, causal)
numbers already in the repo: IS 82% profitable days, worst day −$551, 58% profitable matches; burned
OOS 60% profitable days, worst day −$469. No variant below has been run on any data.

## Goal
Reduce losing days and losing matches of v2 without giving up most of its edge. v2's losses come
mostly from resolution variance: positions are held to the binary match result. The levers are
smaller per-match exposure, smaller tickets, dropping extreme prices, and a daily stop.

## Data: IS only
- Prints: `data/is_prints.parquet` (U1 matches starting before 2026-08-25 14:15 UTC). Nothing from
  `data/locked/` or `data/expand_*` is read.
- Ends: `src.tape.universe()` `end`, indexed by `cond`.
- Pipeline: `src.v2.run(..., causal=True)` unchanged up to the policy. Causal 0–3 s window
  (`add_causal_bucket`), walk-forward fast-tier qualification, `build_features`, `prepare`, 4 h ex-ante
  capital lock, wallet history = causal 0–3 s prints. The features are built once and every variant
  runs on them through `engine.simulate(f, pol, "res", "actual", whist, sigma_by_month)`.
- Simulated months: 2026-01 to 2026-08 (`engine.RUN_START`). Evaluation months: 2026-02 to 2026-08.
  Every month m only learns from months before m, as in the frozen rule.
- `scripts/lowloss_select.py` writes the tables to `research/v2/lowloss/out/`.

## Grid: 3 × 2 × 2 × 2 = 24 variants
| lever | values |
|---|---|
| `net_cap` (per-match \|net outcome-0 shares\|) | 100, 50, 25 |
| `deploy_frac` | 0.5, 0.25 |
| `zone` | "0.05-0.95", "0.15-0.85" |
| `stop_k` | inf, 1.5 |

Everything else is `G_50pct_net100`: `sizing="risk_parity"`, `wallet="filter"` (fee-aware: shrunk past
30 s markout > the match's own fee rate × q(1−q)), `usd_cap=1000`, `match_cap=3000`, no day or
wallet-day cap, measure `res` (hold to resolution), fee mode `actual`.

Name: `n{net_cap}_d{deploy%}_z{lo}-{hi}_s{stop_k}`. The baseline is `n100_d50_z05-95_sinf`, which is
`G_50pct_net100`. Grid order, used for tie-breaks: the baseline first, then net_cap 100, 50, 25 ×
deploy 0.5, 0.25 × zone 0.05-0.95, 0.15-0.85 × stop inf, 1.5, nested in that order, skipping the
baseline.

Daily stop (`stop_k = 1.5`): engine semantics. Within a UTC day, if the day's mark-to-market P&L
(30 s markout at entry + 30 s, the rest at the 4 h lock end) falls below −1.5·σ_m, no new trades for
the rest of that day. Open positions are still held to resolution. σ_m is `engine.sigma_from_history`
of the variant's no-stop twin (same variant with `stop_k = inf`, also in the grid): the std of its
zero-filled daily P&L over all days of months before m. It is inf when there are fewer than 10 such
days, so January has no stop.

## Daily P&L and metrics
- A trade's P&L (held to resolution, net of the match's fee) is booked on the UTC date of entry, as in
  `engine.daily_series`.
- Calendar: every UTC date from 2026-02-01 to the last IS trade date of any variant, zero-filled and
  identical for all variants. For the selection history, January uses 2026-01-01 to 2026-01-31.
- Reported per variant and for the stitched series, Feb–Aug 2026:
  - **profitable days %**: days with P&L > 0 / calendar days. A day with no trade is not
    profitable. The share of active days (≥ 1 trade) with P&L > 0 is also shown, for information.
  - **worst day $**, **worst month $** (sum of trade P&L by calendar month).
  - **max DD $** on cumulative daily P&L, and as % of 3 × peak locked capital (`engine.metrics`
    convention).
  - **Sharpe** = mean / std of daily P&L × √365. **Sortino** = mean / √(mean(min(d, 0)²)) × √365.
  - **$ P&L**, **per-share net** (¢, Σpnl / Σshares) with the match-clustered 95% CI of
    `engine.metrics` (1,000 draws, seed 0).
  - **profitable matches %**: traded matches with summed P&L > 0 / traded matches.
  - Monthly P&L for every variant, and the daily P&L series.

## Selection rule: walk-forward meta-selection
For each evaluation month m in 2026-02 … 2026-08:
1. History H = simulated months from 2026-01 up to m−1. January counts: its trades are themselves
   walk-forward, trained on December 2025 only. For February, H is January alone.
2. For every variant v on H's calendar days: `share_v` = profitable-days share, `mean_v` = mean daily
   P&L. `mean_base` is the baseline's.
3. Feasible: `mean_v ≥ 0.5 × mean_base`.
4. Choose the feasible variant with the highest `share_v`. Ties go to the higher `mean_v`, then the
   earlier grid position. If nothing is feasible, or H has fewer than 10 days with a baseline trade,
   choose the baseline.
5. Month m of the stitched series is the chosen variant's own trades in month m. Each variant is
   simulated continuously over all months, so its caps, stop and walk-forward state are its own.
   Selection only picks which variant's month-m trades are used. A match that spans a month
   boundary keeps each side's trades from that side's chosen variant.

**The stitched Feb–Aug series is the honest IS number for the loss-averse search.** Per-variant
full-period numbers are in-sample for the selection and are reported only for context.

**Frozen "v2-safe" = the variant chosen for the last month (2026-08, history Jan–Jul).** For
information only, the choice the same rule would make with history Jan–Aug is also printed. It does
not replace the frozen choice.

## Sanity check, not a selection input
The baseline variant run IS-only must reproduce the IS part of the frozen causal v2
(`results/v2/causal.json`, `causal/is_eval/slip0.0`: 55,662 trades, +1.381¢/share, $40,426). If it
does not, the run stops and the cause is found before any variant is looked at.

## After this
`research/v2/lowloss/PREREG.md` freezes v2-safe and pre-registers its tests: burned OOS (non-blind),
U2 unseen matches (blind), and the HYPOTHESIS_V2.md forward window (secondary). It is committed before
any of those is run.
