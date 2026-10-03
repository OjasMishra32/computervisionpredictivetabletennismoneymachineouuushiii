# v2-safe: frozen rule and pre-registered tests

Written 2026-10-03 ~17:30 UTC on top of 7358313, after the IS-only grid in `GRID.md` (sha256
6f162222…cafa6b at run time) was run by `scripts/lowloss_select.py`. It is committed before any of
the tests below is run.

What has been looked at so far:
- **v2-safe and the other 23 grid variants:** only IS data (`data/is_prints.parquet`). This
  workflow has not loaded any burned-OOS print, U2 print or forward-window print for any of them.
- **The frozen v2:** its burned-OOS loss profile (60% profitable days, worst day −$469) was already
  known before the grid. So the burned OOS is non-blind for v2-safe too.

## The frozen rule
**v2-safe = frozen v2 (HYPOTHESIS_V2.md including A1, `src/v2.py`, `causal=True`) with the per-match
net-exposure cap lowered from 100 to 50 shares.** Everything else is unchanged:
- causal 0–3 s window, walk-forward fast-tier qualification, fee-aware wallet filter;
- risk-parity size with deploy_frac 0.5, price zone 0.05–0.95, $1,000 per-trade cap, $3,000 per-match
  gross cap;
- 4 h ex-ante capital lock, no daily stop, hold to resolution.

In code, `V2_SAFE = dataclasses.replace(src.v2.POLICY, name="v2_safe_n50", net_cap=50)`, run through
`src.v2.run` with `POLICY` replaced by `V2_SAFE`. Grid name: `n50_d50_z05-95_sinf`.

How it was chosen (GRID.md rule): walk-forward meta-selection over 24 variants, which maximises the
share of profitable days subject to mean daily P&L ≥ 50% of v2's, using only earlier months. That rule
picked `n50_d50_z05-95_sinf` for May, June, July and August. August is the frozen choice; the same
rule with Jan–Aug history picks it too.

The margins were thin. In August's history, v2-safe led the runner-up by 0.47 pp, which is one day in
212. Across the whole grid the profitable-days share stays between 75% and 82%, while the size of
losing days scales with exposure. **v2-safe changes how much a bad day costs; it does not change how
often a day is bad.** The edge per share is the same as v2's.

## IS results (Feb–Aug 2026, 206 calendar days, causal, hold to resolution)
| | stitched meta-selection (honest IS) | frozen v2 (baseline) | v2-safe, full IS (in-sample for the selection; context only) |
|---|---|---|---|
| profitable days, calendar / active | 79.1% / 81.9% | 79.6% / 82.4% | 81.6% / 84.4% |
| losing days, calendar | 17.5% | 17.0% | 15.0% |
| worst day | −$373 | −$551 | −$284 |
| worst month | +$1,596 | +$2,543 | +$1,499 |
| max drawdown | −$373 (1.6% of capital) | −$569 (2.0%) | −$284 (1.6%) |
| Sharpe / Sortino (daily, ×√365) | 14.0 / 48.9 | 14.5 / 46.4 | 15.7 / 58.2 |
| $ P&L | $25,530 | $40,426 | $23,864 |
| per-share net, 95% CI | 1.33¢ [1.13, 1.55] | 1.38¢ [1.17, 1.59] | 1.33¢ [1.16, 1.52] |
| profitable matches | 58.1% of 7,597 | 57.7% of 7,639 | 58.2% of 7,639 |
| capital (3 × peak locked) | $24,039 | $28,302 | $17,681 |

How to read the table:
- **Calendar vs active days.** Calendar days count a day with no trade as not profitable. Active
  days are days with at least one trade (199 of 206). The "82%" quoted for v2 earlier is the
  active-day figure.
- **Months chosen for the stitched series:** Feb n25_d50_z15-85_sinf; Mar and Apr v2; May to Aug
  v2-safe.
- **The honest IS number is the stitched column.** The loss-averse search did not raise the share
  of profitable days (79.1% vs 79.6%). It cut the worst day by about a third and kept 63% of v2's
  dollars.
- **Duplicates in the grid.** net_cap 25 makes deploy_frac irrelevant, so d25 and d50 give
  identical books at that cap.

Full tables: `research/v2/lowloss/out/` (variants, monthly, daily, selection, results.json).

## Tests
In every test below, v2-safe is run exactly as frozen. No parameter is changed in response to any
result. The frozen v2 is run on the same data for the paired comparison.

Metrics, defined as in GRID.md:
- profitable days % (calendar and active), losing days %;
- worst day $, worst month $, max DD $ and as % of 3 × peak locked;
- Sharpe and Sortino of daily P&L ×√365;
- $ P&L, per-share net with the `engine.metrics` match-clustered 95% CI (1,000 draws, seed 0);
- profitable matches %, trades, matches;
- per-share net at +½ tick and +1 tick of entry slippage (`pnl_ps − 0.005`, `pnl_ps − 0.01`).

### (a) Burned OOS, non-blind
- **Data:** `concat(data/is_prints.parquet, data/locked/oos_prints.parquet)`, ends from
  `src.tape.universe()`, one joint walk-forward run, as in `scripts/v2_causal.py`.
- **Book:** trades in matches with `universe().oos`. The calendar runs from 2026-08-25 to the last
  OOS trade date.
- **Logging:** the run appends a line to `results/oos_peeks.log`.
- **Label:** this number is labelled **non-blind** wherever it appears. The v2 loss profile on this
  data was known before the grid was designed.
- **Reporting:** every metric, next to v2 on the same run (previously reported: 60% profitable days,
  worst day −$469), with both day definitions shown. P1 and P2 from (b) are computed for information. They are
  not a pass or fail.

### (b) U2 unseen matches, blind. This is the primary test.
- **Data and run:** same as `research/v2/expand/PREREG.md`, steps 1–3. That means
  `P = concat(is_prints, oos_prints, expand_prints)`, no dedup, ends from U1 ∪ U2, one joint
  walk-forward run of v2-safe.
- **Period:** each trade's period is its match's start. IS if start < 2026-08-25 14:15 UTC, OOS
  otherwise. Months before 2026-02 are excluded.
- **Books:** U2-IS and U2-OOS are U2 matches only.
- **Calendars:** U2-IS runs 2026-02-01 to 2026-08-25. U2-OOS runs 2026-08-25 to the last U2-OOS
  trade date.
- **Order:** this run happens only after this file is committed. It may share a process with the
  expand PREREG's v2 run, but no U2 statistic of v2 or of v2-safe may be viewed before this commit.

**Primary (v2-safe passes only if all four hold):**
- **P1, per-share net.** `per_share_c` 95% CI lower bound > 0 in U2-IS **and** U2-OOS.
- **P2, profitable-days share.** Measured over active days, meaning UTC days with at least one
  v2-safe U2 trade in that period. Let s = days with summed P&L > 0 / active days. The Wilson 95%
  lower bound of s must be > 50% in U2-IS **and** U2-OOS.
  - Active days are used because U2 coverage (mostly ITF, $1k+ volume) may leave days with no
    qualifying trade. A day with no trade is neither a win nor a loss.
  - The calendar-day share is also reported.

**Labels:**
- A period with fewer than 30 U2 matches with v2-safe trades, or fewer than 20 active days, is
  labelled "underpowered". The label does not turn a fail into a pass.
- A fail of P1 or P2 in either period is reported as a FAILURE of v2-safe's out-of-universe claim
  for that period.

**Secondary (reported, not tested):**
- Every metric for U2-IS, U2-OOS, Combined-IS and Combined-OOS.
- v2-safe minus v2 on the same U2 days: the difference in profitable-active-day share, with a
  2,000-draw day bootstrap (seed 0), plus the worst day, max DD and $ P&L ratio.
- Whether U2's profitable-active-day share reaches the stitched IS level, about 82%.

### (c) Forward window of HYPOTHESIS_V2.md (secondary)
- **Window:** matches starting at or after 2026-10-03 14:00 UTC, resolved by the run.
- **Data:** the same data path as `scripts/forward_test.py`.
- **Run:** v2-safe in the same joint run setup as v2. Window-match trades are reported.
- **Reported, not tested:** per-share net held to resolution with a match-clustered CI, $ P&L,
  profitable matches %, worst match, and the 30 s net markout (Primary B's statistic).
- **Blind sub-window.** This file is committed after the window opened. The blind part for
  v2-safe is therefore matches starting at or after **2026-10-03 18:00 UTC**, or the first full
  hour after this commit if the commit is later. It is reported separately. The full window is also
  reported, labelled "includes matches that started before v2-safe was frozen".
- **Power:** less than one day of matches cannot measure a profitable-days share, so none is
  claimed.

## Rules
- v2-safe is not re-tuned on (a), (b) or (c). A different cap, a stop, or any rule fitted to
  OOS/U2/forward data is a new hypothesis. It would need its own pre-registration and fresh data.
- Deviations go in `research/v2/lowloss/DEVIATIONS.md`, with the reason, before any re-run.
- Every result is reported whatever it shows, including a fail.
