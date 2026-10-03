# Tier-0 v3: optimisation grid and walk-forward rule (written before any v3 computation)

> **COUNTERFACTUAL WITH ASSUMED DATA.** Assumed: licensed live feed + courtside camera, not purchased;
> parameters from our measurements. No live ATP/WTA point feed was bought or used. Historical prices, results,
> fees and venue delays are real (public Polymarket tapes); the tier-0 trader's timing, fills and call accuracy
> are modelled (`src/tier0.py`, the verified `CORRECTED` model of `research/v2/tier0/RESULTS.md`).

Written 2026-10-03, before any v3 input table, simulation or P&L was computed. Anything changed after the first
v3 P&L goes in `DEVIATIONS.md` in this folder.

## Scope

* **In sample only.** IS = 1 s-delay matches with start < 2026-08-25 14:15 UTC, trade days 2026-05-15 → 2026-08-25
  (103 calendar days). The script reads only `data/derived/tier0_jumps_is.parquet`,
  `data/derived/tier0_post30_is.parquet`, `data/is_prints.parquet` and the frozen measured inputs. It never reads
  `data/locked/*`, the burned-OOS jump/post tables, `data/expand_*` (U2) or anything after 2026-08-25 14:15.
  Coverage ranking uses universe metadata (pre-start volume) per UTC date exactly as v2 (DEVIATIONS V6), which
  touches the split day's later matches only through their pre-start volume (ex-ante metadata, no prices or results).
* **Fixed at the revised primary (never optimised):** own 120 fps camera, stamp lag 2.0 s, R drawn once per
  tournament, no stamp truncation, no queue offset, φ 0.5, coverage 10 matches/day, p_event 0.95, net cap 100
  shares/match, $1,000 per order, stale-price correction +0.5c, live-book fill pricing on both sides (fills priced
  from `results/tier0/inputs/live_edge_curve.csv` at the matching τ, never at the VWAP of all stale depth),
  limit-order fills only before the reprice for correct calls, regional latency, live pool D ≥ 3c, depth × min(1,
  V/V_live). Trade set = the historical ≥ 4c detector set (selected on realised moves; see "What is not ex-ante").
* **Seeds.** Every number is a mean ± SD over 20 Monte Carlo seeds (IS seeds 0–19, same streams as v2), with the
  per-share CI = match-clustered bootstrap 95 % CI (1,000 draws) averaged over seeds.

## Dimensions (4 × 5 × 2 × 3 × 3 = 360 variants)

| # | dimension | values | primary / default |
|---|---|---|---|
| 1 | fire threshold θ: skip calls whose call precision < θ | 0.85, 0.90, 0.95, 0.97 | 0.85 (= no filter) |
| 2 | exit | hold to resolution; lock-in D = 2, 5, 10, 30 s | default: lock-in 5 s |
| 3 | sizing | flat; leverage (ex-ante) | flat |
| 4 | pre-point price zone (point-winner token's stale price q) | [0.05, 0.95], [0.10, 0.90], [0.20, 0.80] | [0.05, 0.95] |
| 5 | limit price: stale + X, correct and wrong calls | X = 0.5c, 1c, 2c | 2c |

### 1. Fire threshold θ

A call's precision is known when it is made: an early out call by the tracker at lead L has the measured
precision at that lead (own 120 fps: 0 ms 0.888, 25 ms 0.945, 50 ms 0.959, 100 ms 0.971; longer leads unused as in
v2); every other call (event detection at lead 0) has p_event = 0.95. A call with precision < θ (tolerance 1e-9)
sends no order: no fill and no use of the net cap. θ = 0.85 keeps everything; 0.90 drops lead-0 tracker calls;
0.95 also drops lead-25 calls; 0.97 keeps only lead-100 calls. Skipped calls are not re-routed to the event detector.

### 2. Exit

* **hold**: v2 (real resolution, one fee, capital locked 4 h).
* **lock-in D**: sell the whole position at t_reprice + D.
  * *Tape clock.* The detector's `onset_ts` is the first print of a 10 s window and can precede the reprice, so the
    reprice time in the tape is t_rep = the first outcome-0 print in [onset_ts, detect_ts] that has moved ≥ 2c (half
    the detector's 4c threshold) from the stale price `ref` in the jump direction; fallback detect_ts. A live trader
    sees the reprice in its undelayed market-data feed, so a timer started at the reprice is causal.
  * *Exit time.* t_exit = t_rep + max(D, −τ), rounded up to the next point of the offset grid {2, 3, …, 10, 15, 20, 30,
    45, 60} s. The max only matters for wrong calls that fill after the reprice (τ < 0): they are sold once filled.
  * *Exit price, using no information after t_exit.* Outcome-0 reference = VWAP of outcome-0 prints in
    [max(t_rep, t_exit − 5 s), t_exit]; if that window is empty, the last print at or before t_exit. The held token's
    price is that value (outcome-0 token) or 1 minus it. This is the "stale price + realised jump" read off the tape at
    t_exit, not the detector's `size` (which uses prints up to detect_ts) and not the 30 s post-jump VWAP.
  * *Sell price* = token price − 0.5c (half the measured 1c spread), clipped to [0.01, 0.99]. A second taker fee
    rate × s × (1 − s) per share is paid. Exit depth for ≤ 100 shares is assumed available at that price.
  * Wrong calls are exited the same way (at a loss).
  * Net cap: an open lock-in position counts toward the match's net from entry until t_exit; entries are checked
    against the positions still open. Capital is locked from entry to t_exit. P&L is dated at the trade date (as v2).
  * Diagnostic: per-share decomposition = book edge − half spread − 2 fees + (tape exit price − post-30 s price used
    by the fill model), so the tape-drift term is visible.

### 3. Sizing

* **flat** (v2): order = min($1,000 / q, φ × depth / q); then the net cap.
* **leverage**: order = min($1,000 / q, φ × depth / q, w(q) × 100 shares); then the same net cap. w(q) = lev(q) /
  max lev over [0.05, 0.95]. lev(q) = E[|point move| | pre-point price] estimated ex-ante as the mean detector move of
  **IS jumps from the 3 s-delay regime (match start < 2026-05-15)**, binned by the point-winner token's stale price
  (ref + 0.5c) in 5c bins on [0.05, 0.95] and smoothed with a centred 3-bin mean. Those jumps are never traded in the
  walk-forward (all traded months are 1 s regime), so the realised move of a traded point never enters its size.
  The trader applies w to the price of the token it believes won the point (q for a correct call, 1 − q + 1c for a
  wrong call, i.e. the loser's stale price with the same +0.5c correction). The $1k/order and 100-share net caps are
  unchanged, so leverage sizing can only shrink lower-leverage orders.

### 4. Pre-point price zone

Trade only if the point-winner token's stale price q (ref + 0.5c, v2 convention) is inside the zone. Ex-ante.

### 5. Limit price stale + X (correct and wrong calls)

The fill price is measured in the live book (V1), so the limit is applied in the same book. On the sampled live
point (2026-10-03), at each snapshot 2 s / 1 s / 0.25 s before the reprice, with m0 = that point's pre-point mid
(`m1_points.m0`):

* a **correct** call can take only stale winner-token shares priced ≤ (winner's m0) + X;
* a **wrong** call can take only loser-token asks priced ≤ (loser's m0) + X (= winner-token bids ≥ m0 − X).

Levels are sorted best first, so the limit truncates the measured cumulative edge / cost curve: S_X shares and U_X
dollars are available, and the per-share edge (cost) of n shares is E(min(n, S_X)) / min(n, S_X) on the same curve.
U_X replaces the all-stale-depth dollars in the order size. τ is interpolated across snapshots as in v2. Correct
calls still fill only before the reprice. Wrong calls arriving after the reprice (τ < 0) meet a loser book that has
moved toward the order by the reprice (≥ 3c > X), so the limit does not bind there: depth and cost as v2.
The v2 headline (correct calls sweep every stale level below the realised new mid, wrong calls take any bid) is run
as a **reference only**: its limit is the realised post-reprice mid, which no live order can know.
The input table (S_X, U_X per point, snapshot, side) is rebuilt from the latency recorder's book replay and must
reproduce `live_edge_curve.csv` exactly on the unrestricted columns.

## Walk-forward selection (by month, IS 1 s-regime months)

Months by trade date (UTC, calendar days zero-filled): May (05-15 → 05-31, 17 d), Jun (30 d), Jul (31 d),
Aug (08-01 → 08-25, 25 d).

1. **May** uses the pre-declared **default**: θ 0.85, lock-in D = 5 s, flat, zone [0.05, 0.95], X = 2c (the primary
   scenario with lock-in 5 s; X = 2c is the loosest ex-ante limit, closest to the primary's sweep).
2. For month m ∈ {Jun, Jul, Aug}, over the days of all months < m and pooling the 20 seeds:
   * Sortino_v = mean(daily P&L) / sqrt(mean(min(daily P&L, 0)²)) × √365, both means over all (seed, day) pairs;
     a variant with no losing seed-day and positive mean ranks above every finite value;
   * P_v = mean daily P&L (20-seed mean);
   * eligible if P_v ≥ 0.5 × P_default (when P_default > 0; otherwise P_v ≥ P_default);
   * choose argmax Sortino_v among eligible; ties broken by higher P_v, then grid order.
3. **Stitched IS result**: per seed, month m's days come from the variant chosen for m; metrics on the stitched
   trades and daily series. This is the IS result.
4. **Frozen v3** = the variant chosen for August (selected on May–July).

## Reported (20-seed mean ± SD)

Per variant (all 360, `grid.csv`) and stitched: n calls, n trades, per-share net [CI], $ P&L, $/day, daily Sharpe
(√365, calendar days zero-filled), Sortino, max drawdown, worst day, profitable days % (of days with a trade, and of
calendar days), profitable trades %, months positive (of 4), capital (3 × peak locked), return on capital (period
and annualised). Monthly $/day and Sortino per variant (`monthly.csv`); the choice and eligibility per month
(`walkforward.json`).

## Unmeasured quantities: fixed, then bracketed (never optimised)

The frozen v3, the default and the v2 headline are re-run on IS over the full bracket: stamp lag {1.0, 2.0, 3.0,
3.14 calibrated} × R reading {tournament, point, stamp} × stamp truncation {0, R − 0.5 s} × queue {0, arrive ≥ 0.25 s
before the reprice} = 48 scenarios × 20 seeds. Not used for selection.

## What is not ex-ante

* The trade set is the historical ≥ 4c detector set, selected on realised moves (V8). No v3 selection or sizing
  dimension uses the realised move of the traded point: θ uses the call's precision, the zone the stale price,
  leverage sizing a function of the stale price fitted on other (3 s-regime) jumps, the limit the stale price.
  P&L by realised jump-size bucket is reported for frozen v3 as a **diagnostic only**.
* The lock-in clock starts at the reprice, which the trader observes live; the exit price uses tape prints up to
  t_exit only.

## Outputs

Code `scripts/tier0_v3_optimise.py`; outputs `results/tier0_v3/is/`: `grid.csv`, `monthly.csv`,
`walkforward.json`, `stitched_daily.csv`, `bracket.csv`, `results.json`, inputs under `results/tier0_v3/is/inputs/`.
Every file carries the COUNTERFACTUAL label.
