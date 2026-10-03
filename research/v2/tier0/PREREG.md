# Tier-0 counterfactual: pre-registration

Written 2026-10-03 17:25 UTC, **before any P&L was computed**. Inputs that are not P&L (timing, depth,
calibration, point mix, CV tables, coverage counts) were computed first and are frozen below. Changes made
after the first P&L run go in `DEVIATIONS.md` in this folder.

## What this is

**COUNTERFACTUAL WITH ASSUMED DATA.** Assumed: licensed live feed + courtside camera, not purchased;
parameters from our measurements. We did not buy or use a live ATP/WTA point feed, and we have no footage
of these matches. The question: if we had a courtside camera, our own CV model, a licensed live point feed
and a London-colocated gateway, what would we have made on Polymarket tennis moneylines? Real inputs:
historical prices, results, fees and venue delays from the public Polymarket tapes. Modelled inputs: our
timing, fills and call accuracy. Every output file carries the label above. No document produced from this
work may say that live ATP/WTA data was used.

A tier-0 trader knows who won the point, and through the live feed plus `src/markov.py` it knows the
fair-value move the point implies. So limiting trades to points with a move of at least 4c (the historical
jump set) uses only ex-ante knowledge in this counterfactual. Nobody without that feed has that knowledge.

## Measured inputs (frozen)

| input | value | source |
|---|---|---|
| historical jumps, in sample | 221,842 jumps (move ≥ 4c), 9,581 matches; `onset_ts, dir, size` | `data/derived/jumps_is.parquet` |
| historical jumps, burned OOS | 46,503 jumps, 2,345 matches. `src.tiers.jump_onsets` per match on `data/locked/oos_prints.parquet` (on 25 IS matches it reproduces `jumps_is` exactly) | `data/derived/tier0_jumps_oos.parquet` |
| stale price | `ref` = VWAP of outcome-0 prints in [onset−63 s, onset−3 s). Token price = ref (dir > 0) or 1−ref | as `research/v2/sizing/features.py` |
| outcomes / fees / delays | each match's real `res0`, `fee_rate` and `delay` | `src.tape.universe()` |
| t_reprice − t_stamp | per-point empirical distribution. Pool = live points with move D ≥ 3c (n = 265; median −1.32 s, p10 −2.93, p90 +0.07). The all-points pool (n = 482, median −1.16 s) is a sensitivity | `research/v2/latency/out/m1_points.csv` |
| stale depth | per-point $ resting at prices better than the post-reprice mid, at 2 s, 1 s and 0.25 s before the reprice and 0.5 s after (D ≥ 3c pool: median $810 / $614 / $353 / $0; mean $4,255 / $2,480 / $1,646 / $150). Sampled jointly with that point's timing | `research/v2/latency/out/stale_depth.csv` |
| live-day match volumes | 9 matches, $142k–$1.29M, median by point $475k (pool D ≥ 3c). Used to scale depth | `results/tier0/inputs/live_match_volumes.csv` (public Gamma API) |
| moneyline spread | median 1c on the live day → taker slippage 0.5c over the stale mid | latency RESULTS.md §4 |
| Polymarket one-way from Florida | 67 ms (not used: the gateway is co-located) | `docs/NOTE.md` |
| CV, own camera 120 fps | out-call recall by lead (test, snapshot): 0 ms 0.585, 25 ms 0.463, 50 ms 0.268, 100 ms 0.146. Precision pooled test + train-OOF: 0.888 / 0.945 / 0.959 / 0.971. Leads above 100 ms are not used (pooled precision < 0.95; decided on precision only) | `results/tracking/summary.json` |
| CV, own camera pessimistic | no early calls. Recall at the bounce = test online rule 0.195; precision = worst measured lead-0 value 0.855 (train OOF); inference 50 ms | same |
| CV, Hawk-Eye-class 340 fps | recall by lead (0–400 ms) × distance-out bin, precision 0.968–0.979 per lead | `results/hawkeye_tennis_calls.csv` |
| out-distance mix | physics near-line population (out balls only): 0–2 cm 3.2 %, 2–5 4.8 %, 5–10 7.1 %, 10–20 11.4 %, 20–40 23.8 %, 40–100 49.7 % | `src/hawkeye.py` generator, seed 7 → `results/tier0/inputs/physics_out_bins.json` |
| point-ending mix | **men** (547,478 points, 3,337 matches, 2020–26): out ball 36.2 %, net error 25.2 %, winner/ace/unreturned serve 35.2 %, other 3.5 % (double faults 3.4 %, of which out 1.9 pts). **women** (353,755 points, 2,552 matches): out 41.3 %, net 26.0 %, winner 29.2 %, other 3.6 % (DF 4.9 %, out 2.9 pts) | Jeff Sackmann, Match Charting Project, `charting-{m,w}-points-2020s.csv`, CC BY-NC-SA 4.0 → `results/tier0/inputs/point_mix.json` |

### Data-calibrated stamp lag (an inference, not a measurement)

Prints that land 0–0.5 s before a reprice are 97.7 % with the move (91 prints, 49 points). Assume they come
from courtside humans who react 0.25 s after the ball lands and pay the 1 s venue delay plus 67 ms of network.
For each point, take the earliest such print: t_reprice − t_bounce = (t_reprice − t_print) + 1 + 0.067 + 0.25.
Then t_stamp − t_bounce = (t_reprice − t_bounce) − (t_reprice − t_stamp). **Median stamp lag = 3.14 s.** Over
reaction {0.20, 0.25, 0.30} s × network {0.010, 0.067, 0.150} s the median runs from 3.04 to 3.28 s (IQR
across points about 2.2–3.2 s). Implied t_reprice − t_bounce = 1.35 s. This value enters the grid as a
fourth stamp-lag level.

## Assumptions (stated, not measured)

1. **t_stamp − t_bounce** (official stamp lag) ∈ {1.0, 2.0, 3.0, 3.14 calibrated} s.
2. **Venue → London one-way latency.** Europe (incl. Turkey and North Africa) 10 ms, Americas 40 ms, Asia 100 ms, Oceania 140 ms, Middle
   East 50 ms, sub-Saharan Africa 80 ms, unmapped 100 ms. Tournaments are mapped by keyword on `league` and
   title (`src/tier0.py: REGION_KEYS`). In the primary regime only the Laver Cup is unmapped. Gateway 2 ms. CV
   inference 20 ms (50 ms for the pessimistic camera).
3. Tennis out calls are at least as easy as table-tennis misses at the same frame rate (own camera). The
   pessimistic variant drops that.
4. MCP does not record how far out a ball lands, so out balls follow the physics model's near-line population.
5. Points that do not end in an out ball (winners, aces, net errors, double faults into the net, other), and
   out balls the tracker does not call early, are called **at the event** (lead 0) by CV event detection
   with precision `p_event` ∈ {0.95, 0.99}.
6. The book's reprice timing and stale depth measured on 2026-10-03 (1 s delay, 5 % fee, mostly WTA Beijing)
   hold for the historical matches. Depth is scaled to the match: × min(1, V_match / V_live), where V_live is
   the volume of the live match the depth was sampled from. Depth is never scaled up.
7. **Primary regime = matches with a 1 s venue delay** (2026-05-15 onward). Timing and depth were measured in
   this regime only. Earlier matches (3 s delay) run only as a sensitivity, using the same 1 s-regime timing.
   That makes them almost unfillable by construction, so the result is not informative about that regime.

## Model (per historical jump = one point with |move| ≥ 4c)

Origin t = 0 is the ball landing (point end).

* Ending type ~ point mix (men: ATP/Challenger series, women: WTA).
* Out ball: draw u ~ U(0,1). Recall is made monotone in lead (callable at L ⇒ callable at any shorter lead).
  The call lead L* is the longest usable lead with recall ≥ u, and precision is the CV system's precision at
  L*. If u > recall(0), the ball is called at the event (lead 0) with precision p_event. Other endings are
  lead 0 with precision p_event. Hawk-Eye-class draws a distance bin first.
* t_call = −L* + inference. Arrival at the matching engine = t_call + venue→London + 2 ms + the match's
  order delay (1 s).
* t_reprice = (t_reprice − t_stamp) from a sampled live point + stamp lag. τ = t_reprice − arrival.
* **Correct call** (probability = precision). If τ ≥ 0: fill at the stale token price + 0.5c. Size =
  min($1,000 / q, φ × depth(τ) / q). depth(τ) is the sampled point's measured curve, piecewise linear
  through 2 / 1 / 0.25 s, flat beyond 2 s and between 0.25 s and the reprice. If −0.5 ≤ τ < 0: depth decays
  linearly from its 0.25 s value to its +0.5 s value. The price has already moved (0.5 + |τ|) × jump size.
  If τ < −0.5 s: no trade (never chase).
* **Wrong call** (1 − precision): we buy the losing token at its stale price + 0.5c. Nobody competes, so there
  is no φ, and the fill is min($1,000 / q, depth(max(τ, 0)) / q). If we arrive after the reprice, the book
  has moved toward us, so we fill at the moved price (same fraction as above). These wrong-call fills are
  always taken.
* Zone: act only if the stale price of the token we would buy is in [0.05, 0.95] (v2 rule).
* Hold to resolution. P&L = shares × (payout − q) − shares × fee_rate × q × (1 − q), with each match's real
  `res0` and `fee_rate`. No exits.
* Per-match net cap: |net outcome-0 shares| ≤ cap. Trades in time order; a trade may always reduce exposure
  (v2 `engine.apply_caps` semantics).
* Coverage: on each UTC start date, the N matches with the highest **pre-start** volume (dollars traded
  before the scheduled start, from the raw tape). This is ex-ante. Covered (primary regime, IS / OOS): N = 3
  → 308 / 120 matches; N = 10 → 1,011 / 397; N = 30 → 2,802 / 1,154. The median final volume of covered
  matches at N = 10 is $422k IS and $384k OOS, close to the live-day matches.
* Capital = 3 × peak locked dollars (each position locks shares × price for 4 h). Return on capital =
  P&L / capital, also annualised.
* Monte Carlo: one draw per jump (seed 0), with common random numbers across scenarios. For the primary
  scenario we also run seeds 1–20 to report the simulation SD.

## Metrics (per scenario, IS and burned OOS separately)

IS = match start < 2026-08-25 14:15 UTC; burned OOS = on or after (opened before for v1/v2, so this is not
blind). Reported: calls, trades, fill rate (filled correct calls / calls), per-share net with a
match-clustered bootstrap 95 % CI (1,000 draws), $ P&L, $/day, daily Sharpe (calendar days zero-filled,
× √365), max drawdown, worst day, months positive, peak locked, capital, return on capital, capacity (φ-share
of the stale dollars reachable per day before the trade cap) and the share of fills at the trade cap.

## Scenario grid (frozen)

| dimension | values | primary |
|---|---|---|
| CV system | own120, own120_pess, hawkeye340 | **own120** |
| stamp lag (s) | 1.0, 2.0, 3.0, 3.14 (calibrated) | **2.0** |
| φ (our share of stale depth vs the fast tier) | 0.25, 0.5, 1.0 | **0.5** |
| coverage (matches/day) | 3, 10, 30 | **10** |
| p_event (precision at lead 0) | 0.95, 0.99 | **0.95** |
| per-match net cap (shares) | 100, 1000 | **100** |

3 × 4 × 3 × 3 × 2 × 2 = **432 scenarios**, each on IS and on burned OOS. Fixed across the grid: trade cap
$1,000, slippage 0.5c, regional latency map, live pool D ≥ 3c, depth scaling min(1, V/V_live), stale price
`ref`, regime = 1 s delay, seed 0.

**Median scenario:** the grid medians of each metric, and the single scenario whose IS $/day is the grid
median (nearest if tied).

**Sensitivities (primary scenario only, IS and OOS):** slippage 0 (the literal "fill at the stale price")
and 1c; live pool = all 482 points; depth scaling off, and symmetric capped at 3×; all venues at 100 ms;
stale price = VWAP [onset−33 s, onset−1 s); all regimes including 3 s-delay matches; trade cap $250 and
$5,000; no net cap; seeds 1–20.

## Outputs

`results/tier0/results.json` (label, inputs, primary, median scenario, sensitivities, grid ranges),
`results/tier0/grid.csv` (every scenario × period), `results/tier0/equity_primary.png` (IS + burned OOS),
`results/tier0/sharpe_heatmap.png` (stamp lag × φ, other dimensions at primary values, IS and OOS).
`research/v2/tier0/RESULTS.md` holds the write-up and the commands to reproduce.
