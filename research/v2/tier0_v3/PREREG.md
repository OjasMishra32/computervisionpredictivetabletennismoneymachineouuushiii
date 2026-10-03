# Tier-0 v3: frozen rule and its blind tests (pre-registration)

> **COUNTERFACTUAL WITH ASSUMED DATA.** Assumed: licensed live feed + courtside camera, not purchased;
> parameters from our measurements. No live ATP/WTA point feed was bought or used, and we have no camera footage
> of any match. Historical prices, results, fees and venue delays are real (public Polymarket tapes). The tier-0
> trader's timing, fills and call accuracy are modelled with the verified model of `research/v2/tier0/RESULTS.md`
> (`src/tier0.py`, `CORRECTED`). Every output of every test below carries this label. No orders are placed.

Written 2026-10-03, about 20:00–21:00 UTC, on top of `114c722`. The commit that adds this file also adds
`GRID.md` (written at 19:34 UTC, before any v3 computation, and committed here for the first time) and
`scripts/tier0_v3_forward.py`. At this commit:

* **v3 has been evaluated on in-sample data only:** 1 s-delay matches, 2026-05-15 → 2026-08-25 14:15 UTC.
* **Burned OOS** (U1 matches with start ≥ 2026-08-25 14:15 UTC) has been read for v1, v2 and tier-0 v2
  (`results/oos_peeks.log`), but never with any v3 rule.
* **U2** (`data/expand_*.parquet`) was loaded once, for v2's out-of-universe test (`research/v2/expand`,
  17:31 UTC). No tier-0 quantity of any version has been computed on it. This file uses only U2 catalogue
  metadata: start, delay, series, league, title, volume and fee.
* **Forward window** (start ≥ 2026-10-03 14:00 UTC): no tier-0 or v3 code has read it. The only forward-window
  check so far was a dry run of the forward script on an **in-sample** window (§6).

## 1. The frozen v3 rule (exactly as returned by the optimiser; chosen on IS only)

**COUNTERFACTUAL WITH ASSUMED DATA:** licensed live feed and courtside camera assumed, not purchased; parameters
from our measurements. In sample only: 1 s-delay matches, 2026-05-15 → 2026-08-25 14:15 UTC, 103 days. No burned
OOS, no U2 and no forward data were read; `results/oos_peeks.log` was not touched. Every number is a 20-seed
mean ± SD, and per-share CIs are match-clustered bootstrap CIs averaged over seeds.

**FROZEN v3 RULE** (chosen for August using May–July):

- **Threshold:** fire only on calls with precision ≥ 0.90. This skips lead-0 tracker out-calls (precision 0.888).
- **Exit:** hold to resolution.
- **Sizing:** leverage-weighted. Order = min($1k/q, φ·depth/q, w(q)·100 shares), where w falls from 1.00 at
  q = 0.05 to 0.78 at q = 0.90. w was fitted on 3 s-regime IS jumps, never on the traded points.
- **Zone:** pre-point price q in [0.05, 0.95].
- **Limit price:** stale + 2c, for both correct and wrong calls.
- **Held at the revised primary:** own 120 fps camera, stamp lag 2.0 s, R drawn per tournament, φ 0.5,
  10 matches/day, p_event 0.95, net cap 100, live-book fill pricing.

**In code** (`scripts/tier0_v3_optimise.py`): `V3(theta=0.90, exit_d=None, sizing="lev", zone=(0.05, 0.95),
limit=0.02)`, variant name `th0.9|hold|lev|z0.05-0.95|X2c` (= `walkforward.json → frozen_v3`), run by
`simulate_v3` on `T.CORRECTED`:

* own120, stamp lag 2.0 s, φ 0.5, coverage 10, p_event 0.95, net cap 100, trade cap $1,000;
* regional latency, live pool D ≥ 3c, depth × min(1, V/V_live), stale = `ref` + 0.5c;
* regime delay1, live-book prices on both sides, limit-order fills;
* R drawn per tournament, no stamp truncation, no queue offset.

The leverage weight w(q) is `results/tier0_v3/is/inputs/leverage_table.csv`, in 5c bins from q = 0.05:
1.000, 0.977, 0.952, 0.940, 0.938, 0.923, 0.907, 0.898, 0.896, 0.892, 0.886, 0.878, 0.875, 0.868, 0.852, 0.830,
0.796, 0.781. It is applied to the stale price of the token the trader buys.

**Walk-forward choices** (monthly, pooled-seed Sortino, eligibility ≥ 50% of the default's $/day):

| Month | Variant used | That month's $/day |
|---|---|---|
| May | pre-declared default: θ0.85, lock-in 5 s, flat, X 2c | −$18.6 |
| Jun | θ0.95, lock-in 30 s, leverage, X 2c | +$7.0 |
| Jul | frozen v3 rule | +$40.2 |
| Aug | frozen v3 rule | +$46.4 |

The default lost money in May, so the eligibility bar was its own negative $/day, and 338–343 of 360 variants
qualified each month.

**Stitched IS result (the honest IS number):**

- **Per share:** +0.52c ± 0.24 [0.19, 0.84] over 7,529 ± 1,057 trades.
- **P&L:** $2,301 ± 1,131 in total, $22.3 ± 11.0 per day.
- **Risk:** Sharpe 5.2 ± 2.4; Sortino 12.4 ± 7.0 (11.1 pooled); max drawdown −$453 ± 126; worst day −$164 ± 35.
- **Hit rates:** 55.2% of days profitable, 53.6% of trades profitable, 2.85 of 4 months positive.
- **By month:** May −$316, Jun +$211, Jul +$1,247, Aug +$1,160.
- **Capital:** $8.6k ± 1.0k; return 26% for the period, 93% annualised.

**Frozen v3 over all IS months.** May–July were its selection months, so this is optimistic:

- **Per share:** +1.34c [0.85, 1.84].
- **P&L:** $49.2 ± 13.5 per day.
- **Risk:** Sharpe 9.0, Sortino 22.8, max drawdown −$434.
- **Capital:** $12.4k; return 42% for the period (149% annualised).
- **Months positive:** 3.9 of 4.
- **Days profitable:** 67.5%.

**Comparisons:**

- **v2 headline:** reproduced exactly (+1.10c, $88.8/day, Sharpe 11.4). It isn't ex-ante: it buys every stale level
  up to the realised new mid, which a live order can't know.
- **Default (lock-in 5 s):** −$35.8/day.

**What the grid showed:**

- **Exit:** all 72 hold variants are positive ($1–$57/day). No lock-in variant makes more than $0.6/day, and every
  2 s and 5 s lock-in loses: the second fee plus the half spread eats the ~2.7c edge.
- **Limit:** 2c is the best value offered (0.5c gives $26/day, 1c $29, 2c $57), and it sits at the edge of the
  grid. Wider limits weren't tested because they weren't pre-registered (`DEVIATIONS.md` D3).

**IS caveats carried into every test:**

- **Limit frame (`DEVIATIONS.md` D2).** With the limit enforced in the historical-price frame as well, IS falls to
  $18.2 ± 11.3/day, +0.96c [0.01, 1.89]. The truth probably lies between that figure and the headline.
- **IS bracket.** Over the unmeasured bracket, the frozen v3 makes −$32 / $46 / $136 per day (min / median /
  max), and 69% of scenarios are positive.
  - At stamp lag 1.0 s it is flat to negative.
  - Under the stamp-noise reading of R it is −$19/day at lag 2.0.

## 2. What is fixed, what is only bracketed, and what is never used (verifier findings a–f)

| finding | how every test below respects it |
|---|---|
| (a) fill price | Fills are priced from the measured live book (`results/tier0/inputs/live_edge_curve.csv`, the edge of the first N stale shares at the matching τ). The limit-reachable prefix comes from `results/tier0_v3/is/inputs/live_limit_curve.csv`. Fills are never priced at the 60 s VWAP of all stale depth. |
| (b) seeds | Every headline number is a 20-seed mean ± SD. CIs are bootstrap CIs computed per seed and averaged over seeds. |
| (c) unmeasured timing | Stamp lag, the R reading and stamp truncation are fixed at the revised primary (2.0 s, per tournament, none) for every verdict. The frozen v3 is also run over the full 48-scenario bracket on every test set, reported and never used for a verdict or any choice: stamp lag {1.0, 2.0, 3.0, 3.14} × R reading {tournament, point, stamp} × truncation {0, R − 0.5 s} × queue {0, ≥ 0.25 s}. |
| (d) realised jump size | The trade set is still the historical ≥ 4c detector set, which is selected on realised moves and so is not ex-ante for a live trader. No selection or sizing input uses the traded point's realised size. P&L by realised size bucket (4–5, 5–7, 7–10, ≥ 10c) is reported as a diagnostic only. |
| (e) queue priority | The "arrive ≥ 0.25 s before the reprice" stress is reported on every test set, as part of the bracket. |
| (f) limit price | A limit at stale + 2c applies to correct and wrong calls (GRID.md §5). The D2 historical-frame stress is reported on every test set. |

Nothing in v3 changes after this commit. That covers the rule, the base scenario, the leverage table, the live
inputs, the seeds and the metrics. A result on any test set never feeds back into v3. A rule tuned on U2, the
burned OOS or the forward window would be a new hypothesis, with its own pre-registration and fresh data.

### Pinned code and inputs (SHA-256)

As instructed, this commit contains only `GRID.md`, `PREREG.md` and `scripts/tier0_v3_forward.py`. The v3
simulator and its inputs are therefore pinned by hash. A change to any of these files must be logged in
`DEVIATIONS.md` before the affected test runs. `scripts/tier0_v3_forward.py` refuses to run if a hash differs,
unless `--ack-deviation` names that entry, and it logs the mismatch.

| file | SHA-256 |
|---|---|
| `scripts/tier0_v3_optimise.py` (v3 simulator; not yet committed) | `ee867e6f8562ea82eefdd10ec66bfb6537be0ef5aa2b586f557972b9ab60b6af` |
| `src/tier0.py` (at `114c722`) | `7aec73c8055368a53ceb1b040b612ce02bfb69414ae72e5a3e40dfa41371b16f` |
| `src/tiers.py` (jump detector, prints) | `46a79d75409fd416fdfc2e026c25f02d9ebb3a188a9de1a6ac353561f656363e` |
| `src/tape.py` | `4627f5a8d13ec8d0f51acb0f77ecc0a0651d95cfe18eb10f7af0c8f1a9a3cb77` |
| `src/polymarket.py` | `f42bb0d84b4d69aa3c16949d5a1093c6a32f5616b14d939fe9201a92e2a09ab3` |
| `scripts/forward_test.py` (HYPOTHESIS_V2 window) | `68e5271ddd8eda2b9fb12896331611ad2cd5ce1e3383fcacdf3e4b69d3e47083` |
| `results/tier0/inputs/live_edge_curve.csv` | `32e758a1a6a021694861dac7047b2f2d8bdce5124ec142b5850825a32a3ce782` |
| `results/tier0/inputs/live_match_volumes.csv` | `3a1d3f49cf056c333945669eb4dda564ff2f222c742599f370d7d6a7168d2b62` |
| `results/tier0/inputs/point_mix.json` | `b646fa9ffe419a0491307d1bbaf2677f94e91496551cb15caacc503b55e2bc02` |
| `results/tier0_v3/is/inputs/leverage_table.csv` | `d9dc68f96951c2c6a85e2f0039895a0092df3d77d997f988829639461476c647` |
| `results/tier0_v3/is/inputs/live_limit_curve.csv` | `be88a988b1b9b133ef00a0951a87661e67f2f2a75ec283acb4eaaa26609fb93d` |
| `results/tier0_v3/is/inputs/bundle/pool_D3c.parquet` | `03ca284787cc83cd61fcf42ba490e2d469400665167d12837025e2b9c2a36be8` |
| `results/tier0_v3/is/inputs/bundle/pool_all.parquet` | `cc4094bcd6195d6b8ef64849490cef3721b83933b29aed192ebe87d543e2429e` |
| `results/tier0_v3/is/inputs/bundle/limit_curve.parquet` | `d37f501e5a9b8cca7337b816de1498b5686b637160e2c5d1941153c630700a2f` |
| `results/tier0_v3/is/inputs/bundle/lev.parquet` | `c4e95b3fb8990bb8669239488e8c08c731aacc3dc21746098bb3660da4c5760c` |
| `results/tier0_v3/is/inputs/bundle/meta.json` (CV tables, point mix, stamp-lag calibration) | `ef2f68a84db07bc0ff2b7741da17ebcc7edbae81f27f26ed776b79828715fcf9` |

The live book behind these inputs comes from 9 WTA matches on 2026-10-03 that started 07:30–12:30 UTC. None of
them is in U1's burned OOS (latest U1 start 07:10 UTC), in U2 (latest start 02:00 UTC) or in the forward window
(start ≥ 14:00 UTC).

## 3. Common evaluation (all three test sets)

**Simulator.** `O.simulate_v3(T.CORRECTED, FROZEN, T.draws(n_rows, seed, n_tour))`, unchanged. Each test set
supplies its own jump table, universe and days to the simulator context. The shared measured inputs are taken from
the pinned IS bundle: live pools with limit columns, CV tables, point mix, stamp-lag calibration and leverage table.
Hold to resolution only, so no exit-price table is needed.

**Seeds** (fixed now, never re-drawn):

| test set | seeds |
|---|---|
| burned OOS | 1000–1019 (the tier-0 v2 OOS streams) |
| U2-IS period | 2000–2019 |
| U2-OOS period | 3000–3019 |
| forward | 4000–4019 |

**Jumps, prices and coverage (tier-0 rules, unchanged).**

* **Jumps:** `src.tiers.jump_onsets` (≥ 4c, 10 s vs 60 s VWAP, 60 s refractory) on each match's in-play prints.
* **Stale prices:** `ref` / `ref_short` from `T._refs`, plus the +0.5c correction.
* **Post-jump price:** the 30 s post-jump VWAP, used for pricing only.
* **Match facts:** taken from the universe table. Region comes from `T.region_of`; unmapped venues get 100 ms.
* **Tournament codes:** `T.tournament_codes` over the test set's universe.
* **Coverage:** `T.coverage_set(M, 10, "delay1")`. Per UTC start date, the 10 one-second-delay matches with the
  highest pre-start volume. Pre-start volume is the $ traded before the scheduled start (`T.prestart_volume` rule).
  Ties are broken by `cond`. Both periods of a universe are ranked together, so the split day gets 10 cameras,
  not 20 (DEVIATIONS V6).
* **Depth:** scaled by min(1, match volume / live-day volume).
* **Builder check:** `scripts/tier0_v3_forward.py` builds these tables. Its builder (`jump_table`, `post30`,
  `prestart_usd`) was checked on an IS window (2026-08-10 → 08-13; 125 matches, 2,873 jumps). Every column was
  identical to `data/derived/tier0_jumps_is.parquet` / `tier0_post30_is.parquet`:
  * onset, detect, direction, size, `ref`, `ref_short`, post30, volume, fee, delay and resolution;
  * pre-start volumes, and the 30-match coverage set.

  With IS row and tournament indices, it reproduced the IS frozen-v3 trades row for row at seeds 0 and 7.

**Period assignment.** A trade belongs to the period of its match's start (cutoff 2026-08-25 14:15 UTC). Days are
`T.period_days`: every calendar day from the first to the last 1 s-delay jump date of that period, zero-filled.

**Per-seed metrics** (`O.metrics_v3`, plus three additions):

* **Per-share net:** 100 × Σ P&L / Σ shares, held to resolution, after each match's own taker fee.
* **Match-clustered 95% CI:** bootstrap over matches, 1,000 draws, rng seed 0, as in `O.metrics_v3`.
* **Day-clustered 95% CI (wallet-agnostic):** bootstrap over UTC trade dates with ≥ 1 trade, resampling whole days,
  1,000 draws, rng seed 0. The tier-0 book has no wallet dimension, unlike the wallet-clustered CI of v2 (PM review
  P07). This CI therefore resamples whole days regardless of wallet, and it captures same-day correlation across
  matches.
* **Profitable-days share:** days with P&L > 0, as a share of days with ≥ 1 trade and of calendar days.
* **Also reported:**
  * calls, trades, matches, fill rate and wrong-call share;
  * $ P&L, $/day, daily Sharpe and Sortino (√365, zero-filled);
  * max drawdown, worst day, profitable trades, monthly P&L and months positive;
  * capital (3 × peak locked, 4 h lock) and return on capital.
* **Robustness, never part of a verdict:** a tournament-clustered CI. R is drawn per tournament, and tournaments
  span days.

**Aggregation.** Each metric is the mean ± SD over the 20 seeds. CI bounds are averaged over seeds, as in
tier-0 v2 and GRID.md.

**Reported with every test set, never used for a verdict:**

1. the 48-scenario bracket for frozen v3 (§2c), including the queue ≥ 0.25 s (e), truncation and combined stresses
   at lag 2.0 / tournament;
2. the D2 stress (`hist_limit=True`);
3. P&L by realised jump-size bucket (diagnostic, §2d) and the per-share decomposition (book edge, fee,
   payout − post-jump price) for correct and wrong calls;
4. the v2 tier-0 headline (`V2_HEADLINE`) as a reference only, labelled not ex-ante.

## 4. PRIMARY TEST: U2 unseen markets, both periods (test b)

**Universe.** `data/expand_universe.parquet` (11,307 markets; `research/v2/expand/PREREG.md`), restricted to the
tier-0 regime `delay == 1`. Catalogue metadata gives:

* **Size:** 10,952 markets, of which 10,809 are ITF, 117 ATP (< $5k) and 26 WTA (< $5k).
* **Periods:** **U2-IS period** = start < 2026-08-25 14:15 UTC (7,388 markets, first start 2026-05-16). **U2-OOS
  period** = start ≥ the cutoff (3,564 markets, last start 2026-10-03 02:00).
* **Fee:** 3% until early July, then 5%; each match's own fee is used.
* **Region:** 8,248 of 10,952 are unmapped by `T.region_of` and get 100 ms, which is conservative for the many
  European ITF venues.

Both periods are unseen by every tier-0 version. The "IS/OOS" names refer to the calendar split only.

**Prints and tables.**

* **Prints:** `data/expand_prints.parquet`, the in-play prints from `tiers.match_prints`, built by
  `research/v2/expand/build_u2.py` with the same code as `data/is_prints.parquet`.
* **Jump table:** built per period with `tier0_v3_forward.jump_table(prints, universe rows)`. Rows are numbered
  within the period, and tournament codes come from `T.tournament_codes` over all U2 rows.
* **Pre-start volume:** `tier0_v3_forward.prestart_usd`, read from the cached raw U2 tapes (trades before the
  scheduled start only).
* **Coverage:** `T.coverage_set` over U2 1 s-delay markets of both periods, 10 per UTC day. U1 matches never
  enter U2's ranking.

**Gender, the one U2-specific data rule** (needed because ITF is filed as series `itf`). The tier-0 rule (men =
series ∈ {atp, challenger}) would give every ITF match the women's point mix. Instead:

* a U2 match is **women** if its series is `wta`, or if its league or title prefix matches `\bwomen\b` or
  `\bW\d{2,3}\b` (case-insensitive);
* otherwise it gets the **men's** mix (out balls 36.2% vs 41.3%).

This leaves 2,275 women-labelled matches and 2,671 men-labelled matches. The 6,006 unlabelled ones (for example
"ITF Kursumlijska Banja") take the men's mix. That is the conservative choice, because fewer out balls means fewer
early CV calls. P&L by gender label is reported as a diagnostic.

**Size of the numbers.** U2 matches are small: median volume $4.4k against the live-day matches' $142k–$1.29M.
With depth scaled by min(1, V/V_live), fills are a few shares, so **dollar P&L will be small** (likely cents to a
few dollars per day). **The primary is per-share net and the profitable-days share, not dollars.**

**Primary (pass/fail), per period:** U2-IS and U2-OOS separately, frozen v3 at the revised primary scenario.

* **PASS** in a period only if all three hold:
  1. the 20-seed mean per-share net is **> 0**;
  2. the seed-averaged **match-clustered** 95% CI lower bound is **> 0**;
  3. the seed-averaged **day-clustered** 95% CI lower bound is **> 0**.
* **Underpowered** if a period has fewer than 30 covered matches with trades or fewer than 20 trade days (20-seed
  means). This label is reported and never turns a FAIL into a PASS.
* **U2 verdict:** PASS only if both periods pass. Otherwise the result is a FAILURE of out-of-universe
  generalisation for the failing period(s), reported as such.

**Co-primary metric (reported with a stated benchmark; it does not change the pass/fail above):** the
profitable-days share, as the 20-seed mean ± SD of days with P&L > 0 among days with ≥ 1 trade. The benchmark is
**> 50%**, reported as met or not met per period. The IS comparators are 67.5% for frozen v3 over all IS months
(optimistic) and 55.2% for the stitched IS walk-forward.

**Also reported for U2 (not tested):**

* everything in §3;
* splits by series (ITF vs ATP/WTA), gender label, region mapped vs unmapped, and fee rate;
* the share of covered markets with any trade.

## 5. Test (a): burned OOS, labelled non-blind

U1 1 s-delay matches with start ≥ 2026-08-25 14:15 UTC: the 40-day tier-0 v2 burned OOS, 2026-08-25 →
2026-10-03, using its tables.

* `T.jump_table("oos")`, `T.post_prices("oos")`.
* U1 universe with `T.prestart_volume`, coverage ranked over both U1 periods, `T.tournament_codes(universe())`.
* Seeds 1000–1019.

**Reproduction gate, before any v3 number.** With the v3 simulator and `V2_HEADLINE` on these tables, the tier-0
v2 burned-OOS headline must reproduce: +0.58c ± 0.37 [−0.08, 1.21], $46 ± 39/day (`results/tier0/results.json →
headline`, rounded as printed). It must also match `T.simulate(CORRECTED)` row for row at seeds 1000 and 1007. If
it does not, the plumbing is fixed and logged in `DEVIATIONS.md` before frozen v3 is computed.

**Reading.**

* **Rule:** the same three per-share conditions and the same profitable-days benchmark as §4, applied to this one
  period.
* **Label:** "burned OOS, non-blind window (seen by v1/v2/tier-0 v2); v3 chosen on IS only". A pass here cannot by
  itself confirm v3.
* **Comparators:** the tier-0 v2 corrected headline in this window (+0.58c, $46/day) and frozen v3 IS.

## 6. Test (c): forward window (secondary; reported, not tested)

* **Window.** HYPOTHESIS_V2.md with A1 (`scripts/forward_test.window_universe`, unchanged): ATP/WTA singles
  moneylines with volume ≥ $5k, start ≥ **2026-10-03 14:00 UTC**, resolved at run time.
  * Tier-0 regime: 1 s delay only.
  * Coverage: per UTC start date, the 10 window matches with the highest pre-start volume.
  * Seeds 4000–4019.
* **Run.** Once, by `scripts/tier0_v3_forward.py`, **not before 2026-10-04 11:30 UTC** (the planned v2 forward
  run). The window ends at the run time.
* **Tapes.** A cached tape written before its match ended is moved to `data/raw/trades_stale/` (never deleted) and
  refetched.
* **Guards.** The script refuses to run if any of these holds:
  * `results/forward_peeks.log` already holds a `tier0 v3 forward test ... START` line;
  * `results/tier0_v3/forward/results.json` exists;
  * the start is not 14:00 UTC;
  * it is earlier than 11:30 UTC on 2026-10-04;
  * a pinned hash differs (unless `--ack-deviation` names the `DEVIATIONS.md` entry).

  It writes the START line before reading any forward tape, so a crash after that point still uses up the one run.
  It appends a DONE line at the end.
* **Blind sub-window.** v3 was frozen and pre-registered after the window opened (14:00 UTC), although no v3 or
  tier-0 code read it. The script therefore also reports matches starting ≥ **2026-10-03 22:00 UTC** separately.
  The full-window figure is labelled as including matches that started before v3 was pre-registered.
* **Reported.** Everything in §3, for the full window and the blind sub-window. Readings use the §4 conditions as
  labels only (per-share > 0; match CI > 0; day CI > 0 when there are ≥ 10 trade days, otherwise "n/a"; days
  > 50%; underpowered if < 30 covered matches with trades). With about a day of matches this is expected to be
  underpowered, and it is reported either way.
* **Outputs.** `results/tier0_v3/forward/` (`results.json`, `trades_frozen_v3.parquet`, `daily_frozen_v3_*.csv`).
* **Plumbing check.** A dry run on an in-sample window (`--dry --start 2026-08-10T00:00 --end 2026-08-13T00:00`,
  written to `results/tier0_v3/forward_dry/`, not logged) completed in 114 s. A second dry run on the same window,
  with a mock sub-window boundary of 2026-08-11 12:00, exercised the blind sub-window path. A dry run refuses any
  window outside IS.

## 7. Order, logging and reporting

1. **Test (a), burned OOS:** the reproduction gate, then frozen v3, once. A START line goes to
   `results/oos_peeks.log` before the OOS tables are read for v3.
2. **Test (b), U2, once:**
   * first the builder check on U1 IS data;
   * a START line goes to `results/oos_peeks.log` before any U2 tier-0 table is built;
   * the U2 jump/pre-start build counts as part of the one run.
3. **Test (c), forward, once,** after 2026-10-04 11:30 UTC (`results/forward_peeks.log`).

Grids may run on HiPerGator: a SLURM array, ≤ 8 CPUs, `--account=ai-workshop --qos=ai-workshop`, code and pinned
inputs rsynced to `/blue/ai-workshop/ojasvamishra/courtside/v3/`. The bracket, at 48 × 20 runs per period, is the
part to send there. Before remote results are used, local and remote runs of the same job must agree exactly on a
check job.

The code for (a) and (b) is written after this commit and must implement §§3–5 exactly. Any departure goes in
`DEVIATIONS.md` before the run.

**Outputs:**

* `results/tier0_v3/{burned_oos,u2}/results.json` and the forward folder;
* the write-up in `research/v2/tier0_v3/TEST_RESULTS.md`.

Every file carries the COUNTERFACTUAL label. The write-up states the verdicts as defined here (U2 PASS/FAIL per
period; burned OOS non-blind; forward secondary), whatever they are, and never describes the data as real ATP/WTA
live data.
