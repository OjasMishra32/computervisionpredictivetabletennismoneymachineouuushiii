# Tier-0 counterfactual: courtside camera + own CV + licensed live feed + London gateway

> **COUNTERFACTUAL WITH ASSUMED DATA.** Assumed: licensed live feed + courtside camera, not purchased;
> parameters from our measurements. We did not buy or use any live ATP/WTA point feed, and we have no camera
> footage of these matches. Historical prices, results, fees and venue delays are real (public Polymarket
> tapes). The tier-0 trader's timing, fills and call accuracy are modelled from our own measurements plus the
> assumptions in §8. Pre-registration: `PREREG.md` (written before any P&L). Post-hoc changes, including
> every verifier fix: `DEVIATIONS.md`.

## How to describe this in the paper

Something like: *"We simulate a trader that has a licensed live point feed, a courtside camera running our
CV model and a London-colocated gateway. We did not buy the feed or the camera. The simulation is
parameterised from our own measurements (482 official WTA points with the live Polymarket book, our tracking
results, the Match Charting Project) and backtested on historical Polymarket tapes."* Do **not** write that
live ATP/WTA data was used. It was not. A paper that says it was would misstate the method, and every number
below depends on the assumptions in §8.

## 0. What changed after verification

Two verifiers reproduced the pre-registered model exactly and then found that its fill price double-counts
the edge. It credited every stale share with the whole realised jump: about 6c gross per share. On the live
day, the shares actually resting before a reprice earn only 2.3–2.7c against the new mid, and the real fast
tier earns 2.24c gross / 1.13c net. The headline below therefore uses the **corrected model**:

* fills priced from the measured live book on both sides (V1, V2);
* limit-order fills (V5);
* reprice timing drawn once per tournament (V3);
* measured stale-price correction (V4);
* literal coverage (V6);
* 20-seed means (V7).

The corrected model keeps every pre-registered parameter value. **The pre-registered headline ($297/day IS,
Sharpe 34) overstated the corrected one by about 3× in sample and 5× out of sample.** It is kept as the
record in §6.

## 1. Headline (corrected model, pre-registered parameters)

Own 120 fps camera, stamp lag 2.0 s, φ 0.5, 10 matches/day, p_event 0.95, net cap 100 shares/match, $1k per
order, 1 s-delay matches only. IS = 2026-05-15 → 2026-08-25 (103 days). Burned OOS = 2026-08-25 → 2026-10-03
(40 days, not blind). Values are means ± SD over 20 Monte Carlo seeds. The CI is the match-clustered bootstrap
95 % CI, averaged over seeds.

| | IS | burned OOS |
|---|---|---|
| calls (covered points with move ≥ 4c, in zone) | 22,517 | 8,256 |
| calls arriving before the reprice / in the 0.5 s after / later | 44 % / 10 % / 46 % | 35 % / 12 % / 53 % |
| trades | 6,447 ± 827 | 1,969 ± 863 |
| fill rate (filled correct calls / calls) | 25.1 % ± 3.7 | 20.3 % ± 10.7 |
| wrong calls, share of trades | 12.6 % | 19.1 % |
| median $ per fill | $54 | $57 |
| **net per share [95 % CI]** | **+1.10c ± 0.16 [0.82, 1.38]** | **+0.58c ± 0.37 [−0.08, 1.21]** |
| **$ P&L** | **$9,146 ± 2,196** | **$1,857 ± 1,559** |
| **$/day** | **$89 ± 21** | **$46 ± 39** |
| of which correct / wrong calls | +$13,088 / −$3,942 | +$3,099 / −$1,241 |
| daily Sharpe (√365; see §7) | 11.4 ± 2.5 | 7.3 ± 5.9 |
| max drawdown | −$473 ± 164 | −$444 ± 260 |
| worst day | −$229 ± 61 | −$193 ± 68 |
| months positive | 3.9 / 4 | 2.35 / 3 |
| capital (3 × peak locked, 4 h lock) | $29.0k ± 6.5k | $21.4k ± 10.0k |
| return on capital, period / annualised | 32 % / 115 % | 7 % / 66 % |
| capacity: φ-share of stale $ reachable per day | $86k | $73k |

Over the 20 seeds, IS P&L runs from $4,355 to $12,387 and OOS from −$328 to $4,914
(`results/tier0/equity_primary.png`). The seed-0 draw is stored in full in `results.json → headline.*.seed0`.
It gives IS +0.95c [0.67, 1.22], $79/day, and OOS +0.80c [−0.32, 1.83], $25/day.

**Where the per-share P&L comes from** (all 20 seeds pooled):

| | IS correct | IS wrong | OOS correct | OOS wrong |
|---|---|---|---|---|
| share of trades | 87.7 % | 12.3 % | 85.2 % | 14.8 % |
| measured book edge (+) / cost (−) vs new mid | +2.31c | −2.95c | +2.33c | −2.58c |
| payout − post-jump price (real resolutions) | +0.28c | −0.33c | +0.05c | +0.05c |
| fee | −0.80c | −0.80c | −1.03c | −1.02c |
| net | **+1.80c** | **−4.08c** | **+1.35c** | **−3.55c** |

The modelled correct fill earns 2.3c of book edge. The real fast tier earns 2.24c gross per share in the same
window (52 live prints). So the edge now matches the only direct measurement of what a fast courtside
participant gets. Wrong calls cost less than the 4.8–5.3c first-100-share book cost because most of them
arrive after the reprice, when the loser's book has already moved toward the order.

## 2. The sign depends on one unmeasured number: t_reprice − t_bounce

Our order reaches the matching engine about 1.03 s after the ball lands (Europe: 20 ms inference + 10 ms +
2 ms gateway + the 1 s venue delay). We fill only if the book has not repriced by then. The book's reprice
relative to the official stamp, R = t_reprice − t_stamp, is measured: median −1.32 s, p10 −2.93, p90 +0.07.
The stamp's lag behind the bounce is **not** measured. The data support two opposite readings of R's 3 s
spread, and the answer flips between them:

| at the pre-registered stamp lag 2.0 s | IS c/share [CI] | IS $/day | OOS c/share [CI] | OOS $/day |
|---|---|---|---|---|
| **R drawn per tournament (headline)**: spread is book timing, persistent per tournament | +1.10 [0.82, 1.38] | $89 ± 21 | +0.58 [−0.08, 1.21] | $46 ± 39 |
| R drawn per point (pre-registered timing model) | +0.89 [0.57, 1.21] | $66 ± 10 | +0.31 [−0.26, 0.91] | $20 ± 22 |
| **R spread = umpire-stamp noise** (t_reprice − t_bounce constant = 0.68 s) | −3.25 [−5.28, −1.26] | **−$30 ± 7** | −2.97 [−6.42, 0.34] | **−$26 ± 12** |

Under the stamp-noise reading at lag 2.0, the book always reprices before our order arrives. No correct call
fills, and only wrong calls trade. **P&L against t_reprice − t_bounce** (10 seeds,
`results/tier0/pnl_vs_reprice_timing.{csv,png}`; for the drawn readings this is the median):

| t_reprice − t_bounce (s) | 0.6 | 0.8 | 1.0 | 1.1 | 1.2 | 1.35 | 1.5 | 1.75 | 2.0 | 2.5 |
|---|---|---|---|---|---|---|---|---|---|---|
| IS, stamp-noise reading | −$23 | −$41 | −$38 | $191 | $193 | $201 | $214 | $237 | $258 | $277 |
| IS, per-tournament | $49 | $85 | $102 | $112 | $117 | $135 | $143 | $204 | $221 | $249 |
| OOS, stamp-noise reading | −$18 | −$34 | −$48 | $80 | $130 | $134 | $145 | $167 | $187 | $208 |
| OOS, per-tournament | $27 | $56 | $64 | $70 | $78 | $81 | $83 | $116 | $130 | $156 |

The breakeven is at t_reprice − t_bounce ≈ 1.03–1.1 s, which is our arrival time. The pre-registered primary
sits at a median of 0.68 s, below breakeven. The **data-calibrated value is an inference, not a measurement.**
Prints that land 0–0.5 s before a reprice are 98 % with the move. If they come from courtside humans with a
0.25 s reaction who pay the 1 s delay and 67 ms of network, then t_reprice − t_bounce ≈ 1.35 s. At that value
the strategy makes **IS $199 ± 10/day (+1.19c [1.04, 1.34]) and OOS $133 ± 15/day (+0.83c [0.60, 1.07])**
under the stamp reading, and about the same under the tournament reading at stamp lag 3.14 s (IS $199, OOS
$129). If the fast tier is machine-fast and not human, the true value is shorter and the edge shrinks toward
breakeven.

## 3. Stresses (corrected headline, one change at a time, 20 seeds)

| variant | IS c/share [CI] | IS $/day | OOS c/share [CI] | OOS $/day |
|---|---|---|---|---|
| **headline** | **+1.10 [0.82, 1.38]** | **$89 ± 21** | **+0.58 [−0.08, 1.21]** | **$46 ± 39** |
| official stamps truncated, R − 0.5 s | +0.61 [0.08, 1.14] | $28 ± 19 | −0.02 [−1.22, 1.09] | $15 ± 36 |
| queue: fill only if ≥ 0.25 s before the reprice | +0.63 [0.17, 1.07] | $36 ± 24 | +0.11 [−0.84, 1.02] | $25 ± 43 |
| stamp lag 1.0 s | +0.40 [−0.32, 1.08] | $15 ± 15 | −0.38 [−2.08, 1.20] | $4 ± 30 |
| stamp lag 1.0 s + queue 0.25 s | −0.76 [−2.07, 0.48] | −$6 ± 18 | −1.83 [−4.71, 0.84] | −$16 ± 22 |
| stamp truncation + queue 0.25 s | +0.50 [−0.11, 1.07] | $22 ± 17 | −0.18 [−1.55, 1.06] | $10 ± 34 |
| live pool = all 482 points (not D ≥ 3c) | +0.65 [0.36, 0.96] | $50 ± 19 | +0.25 [−0.35, 0.86] | $20 ± 20 |
| all venues 100 ms | +0.87 [0.48, 1.25] | $51 ± 21 | +0.35 [−0.47, 1.13] | $34 ± 39 |
| own camera, pessimistic | +0.97 [0.67, 1.27] | $73 ± 23 | +0.31 [−0.42, 1.02] | $32 ± 37 |
| Hawk-Eye-class 340 fps | +1.29 [1.03, 1.55] | $110 ± 24 | +0.80 [0.23, 1.39] | $64 ± 44 |
| p_event 0.99 | +1.50 [1.24, 1.76] | $116 ± 23 | +1.09 [0.45, 1.72] | $71 ± 43 |
| φ 0.25 / φ 1.0 | +1.11 / +1.07 | $80 / $94 | +0.52 / +0.57 | $40 / $48 |
| coverage 3/day | +0.95 [0.46, 1.45] | $24 ± 9 | +0.54 [−0.73, 1.65] | $18 ± 19 |
| coverage 30/day | +0.92 [0.75, 1.10] | $188 ± 42 | +0.55 [0.17, 0.93] | $107 ± 76 |
| net cap 1,000 shares | +0.47 [0.03, 0.93] | $203 ± 101 | −0.22 [−1.25, 0.82] | −$51 ± 127 |
| no net cap | +0.12 [−1.73, 2.08] | $65 ± 875 | −0.50 [−3.97, 3.04] | −$361 ± 980 |
| wrong calls priced as pre-registered (lose whole realised jump) | +1.10 [0.82, 1.38] | $89 ± 21 | +0.59 [−0.06, 1.23] | $46 ± 38 |
| decay-window fills allowed (edge → 0 over 0.5 s) | +1.04 [0.80, 1.29] | $96 ± 21 | +0.62 [0.12, 1.11] | $56 ± 40 |
| live edge scaled by historical size / live D (generous) | +1.50 [1.23, 1.78] | $121 ± 25 | +1.08 [0.42, 1.70] | $80 ± 54 |
| no stale-price correction / near stale price `ref_short` | +1.10 / +1.12 | $89 / $85 | +0.58 / +0.56 | $47 / $41 |

What the stresses show:

* The two unmeasured timing quantities, stamp truncation and queue position against the existing fast tier,
  each roughly halve the edge. Together with a short stamp lag they remove it.
* The camera matters less than the timing. p_event 0.99 is worth more than Hawk-Eye.
* Loosening the net cap buys dollars only by taking on directional match risk, and OOS it loses.
* Wrong-call pricing and the stale-price choice no longer matter much, because fills are priced from the
  book.

**By realised jump size** (V8; the trade set is selected on realised market moves, so it is not ex-ante):

| bucket | IS share of shares | IS net c/share | OOS share | OOS net c/share |
|---|---|---|---|---|
| 4–5c | 55 % | +1.11 | 50 % | −0.45 |
| 5–7c | 30 % | +0.96 | 31 % | +1.80 |
| 7–10c | 11 % | +1.35 | 13 % | +1.24 |
| ≥ 10c | 4 % | +1.56 | 5 % | +3.68 |

Under the live-book price, per-share P&L depends only weakly on the realised size in sample. Under the
pre-registered price it ran from 2.3c to 10.5c across these buckets. On the live day, only 63 % of detector
jumps mapped to one official point, and a third of matched single-point moves were under 4c. A Markov filter
on the true score would trade a different and probably larger set at a similar or smaller edge per share.

## 4. Grid: 432 pre-registered scenarios × 2 timing readings × IS and burned OOS (corrected model)

`results/tier0/grid_corrected.csv`. Each cell is a 10-seed mean. Ranges are min / median / max.

| | IS | burned OOS |
|---|---|---|
| $/day, both readings (864) | −$570 / **$107** / $2,615 | −$471 / **$57** / $1,653 |
| net c/share, both readings | −5.41 / 0.81 / 1.81 | −7.34 / 0.33 / 1.61 |
| daily Sharpe, both readings | −9.8 / 7.6 / 45.2 | −8.7 / 3.4 / 49.8 |
| scenarios with P&L > 0 / per-share CI excluding 0 | 76 % / 64 % | 69 % / 38 % |
| per-tournament reading only (432): $/day, share > 0 | −$241 / $155 / $2,326 · 94 % | −$309 / $60 / $1,184 · 83 % |
| stamp-noise reading only (432): $/day, share > 0 | −$570 / $78 / $2,615 · 58 % | −$471 / $40 / $1,653 · 56 % |

**What drives it.** Grid medians, IS $/day (share of scenarios positive), with OOS in brackets:

| dimension | values |
|---|---|
| stamp lag | 1.0 s: −$6 (39 %) [−$18, 25 %] · 2.0 s: $48 (65 %) [$10, 56 %] · 3.0 s: $316 (100 %) [$183, 97 %] · 3.14 s: $354 (100 %) [$202, 99.5 %] |
| timing reading | per tournament: $155 (94 %) [$60] · stamp noise: $78 (58 %) [$40] |
| CV system | own 120 fps $85 · pessimistic $79 · Hawk-Eye-class $184 |
| p_event | 0.95: $82 · 0.99: $176 |
| coverage | 3/day $60 · 10/day $210 · 30/day $472 |
| net cap | 100: $75, 1.24c/share, Sharpe 15.5 · 1000: $202, 0.55c/share, Sharpe 4.8 |
| φ | 0.25: $85 · 0.5: $106 · 1.0: $139 |

**Median scenario** (IS $/day at the grid median): own 120 fps, stamp lag 1.0 s, φ 0.5, 30 matches/day,
p_event 0.99, net cap 1,000, per-tournament timing. IS: +0.35c [−0.40, 1.05], $108/day (SD across seeds
$128), Sharpe 1.6, max DD −$12.7k, capital $165k. OOS: −0.29c, −$4/day, Sharpe −0.5.

Heatmap of stamp lag × φ for both readings, IS and OOS, Sharpe with $/day in each cell:
`results/tier0/sharpe_heatmap.png`.

## 5. Inputs

* **Live book (2026-10-03, 9 WTA matches, 1 s / 5 % regime).** Rebuilt from the latency recorder's book
  replay into `results/tier0/inputs/live_edge_curve.csv`: per point and snapshot (2 s / 1 s / 0.25 s before
  the reprice), the cumulative edge of the first N stale shares and the cumulative cost of the first N
  opposite-side shares. D ≥ 3c pool (265 points), first 100 shares:
  * correct-side edge 2.74 / 2.62 / 2.36c;
  * wrong-side cost 5.27 / 5.23 / 4.77c;
  * all stale shares 1.59 / 1.75 / 2.00c;
  * live mean move D 4.56c.

  It reproduces `stale_depth.csv` and the verifier's first-100/200 table exactly. Timing (R) and depth are
  sampled jointly per point as pre-registered. Under the tournament reading, R comes from a separate draw per
  tournament (266 tournaments).
* **Post-jump price:** VWAP of outcome-0 prints in [detect, detect + 30 s), used only to price fills.
  Available for every jump. Cached in `data/derived/tier0_post30_{is,oos}.parquet`; the OOS read is logged
  in `results/oos_peeks.log`.
* **Point-ending mix:** Jeff Sackmann, Match Charting Project
  (https://github.com/JeffSackmann/tennis_MatchChartingProject), `charting-{m,w}-points-2020s.csv`,
  CC BY-NC-SA 4.0.
  * Men: out ball 36.2 %, net 25.2 %, winner/ace/unreturned 35.2 %, other 3.5 % (DF 3.4 %).
  * Women: out 41.3 %, net 26.0 %, winner 29.2 %, other 3.6 % (DF 4.9 %).

  MCP has no out-distance, so the physics near-line population is used.
* **CV:**
  * own 120 fps: `results/tracking/summary.json`, leads ≤ 100 ms, pooled precision ≥ 0.95;
  * pessimistic: lead 0 only, precision 0.855, 50 ms inference;
  * Hawk-Eye-class: `results/hawkeye_tennis_calls.csv`.
* **Coverage** (top N per UTC date by pre-start volume, whole universe):
  * N = 3: 305 IS / 120 OOS matches;
  * N = 10: 1,003 / 396;
  * N = 30: 2,809 / 1,154.
* **Historical jumps:** `data/derived/jumps_is.parquet`. Burned OOS: `src.tiers.jump_onsets` on
  `data/locked/oos_prints.parquet`.

## 6. Pre-registered model (the record; superseded as an estimate)

Same parameters, the pre-registered fill price (stale + 0.5c), literal coverage, 20 seeds:

* **IS:** +3.13c [2.87, 3.39], $30,565 ($297 ± 9/day), Sharpe 34.0 ± 2.1, fill 32 %, capital $18.5k.
* **Burned OOS:** +2.55c [2.13, 2.98], $9,227 ($231 ± 19/day), Sharpe 31.9 ± 3.2.

Pre-registered grid, 432 scenarios at 10 seeds (`grid.csv`):

* IS $/day $12 / $728 / $12,543, OOS $7 / $632 / $11,528;
* 100 % of scenarios positive;
* median scenario Hawk-Eye-class, lag 3.0, φ 1.0, 10/day, p_event 0.95, net 100: IS $721/day, Sharpe 47.

Every pre-registered sensitivity is in `results.json → prereg_record.sensitivities`. Examples: calibrated
stamp lag $640/day; no net cap $4,397/day at Sharpe 8.4. The `ref_short` grid is `grid_ref_short.csv`.
These numbers come from a fill price that the live book contradicts (§0).

## 7. What this does not show

* **This is not a measurement of tier-0 profits.** It combines our measured market microstructure with an
  assumed information advantage. The result's sign depends on t_reprice − t_bounce, which nobody here has
  measured. It also depends on our queue position against the existing fast tier, which is unmeasured too.
* **Daily Sharpe is not a forecast.** Even with timing drawn per tournament, it treats ~60 small bets a day
  as independent apart from that one shared regime. It ignores model risk: the readings in §2 move the
  result from −$30 to +$200 a day. Read it as a ranking.
* **One live day** (9 WTA matches, mostly WTA 1000 Beijing) supplies all timing and book data. ATP,
  Challenger, other venues and other times of year may reprice differently.
* **Small dollars.** $89/day in sample means about $32k/year on $29k of capital at the 100-share net cap.
  That is before the cost of a data licence, camera access and colocation, which this backtest does not
  deduct. Courtside data collection without the organiser's licence breaches tournament terms.

## 8. Every assumption

1. **The tier-0 trader exists:** licensed feed + courtside camera + own CV, not purchased.
2. **The trade set** is the historical ≥ 4c detector set. It is selected on realised moves, so it is not
   ex-ante (V8).
3. **Stamp lag** t_stamp − t_bounce is unmeasured: grid {1, 2, 3} s plus the 3.14 s inference. The spread of
   R is read three ways (V3).
4. **One-day transfer.** Book reprice timing, stale depth and the book's price levels from the one live day
   (2026-10-03, 1 s / 5 % regime) apply to every historical 1 s-regime match. Depth and book are scaled by
   min(1, V/V_live).
5. **Correct fills** pay the post-jump price minus the measured edge of the first n stale shares. We are first
   in the queue for the best levels; the queue stress removes that.
6. **Wrong calls** always fill, with full depth and no φ. They pay the measured opposite-side book cost,
   which falls to half the spread after the reprice.
7. **Limit orders:** correct calls fill only before the reprice.
8. **φ** (our share against the fast tier) ∈ {0.25, 0.5, 1}, unmeasured.
9. **Venue → London one-way latency:** Europe 10 ms, Americas 40 ms, Asia 100 ms, Oceania 140 ms, Middle East
   50 ms, Africa 80 ms, unmapped 100 ms. Gateway 2 ms. CV inference 20 ms.
10. **CV calls:** tennis out calls are at least as easy as table-tennis misses at 120 fps; the pessimistic
    camera drops this. Points not called early are called at the event with precision p_event.
11. **Hold to resolution** with the real result and fee. Each position locks capital for 4 h; capital =
    3 × peak locked.
12. **No reaction** from market makers to a new fast participant. No outages. The venue delay is the real
    per-match value.

## Reproduce

```bash
.venv/bin/python scripts/tier0_backtest.py --primary   # headline + pre-registered primary, 20 seeds, printed (~10 s)
.venv/bin/python scripts/tier0_backtest.py             # everything -> results/tier0/ (~70 min on 3 workers)
.venv/bin/python scripts/tier0_backtest.py --figures   # redraw figures from results/tier0/
```

The first run builds cached inputs:

* `results/tier0/inputs/live_edge_curve.csv`, from the latency recorder's raw books, ~35 s;
* `data/derived/tier0_post30_{is,oos}.parquet`;
* the earlier caches `data/derived/tier0_{jumps_is,jumps_oos,prestart_volume,jumps_burned_oos}.parquet` and
  `results/tier0/inputs/{point_mix,physics_out_bins,live_match_volumes}.json/csv`. These need
  `data/external/mcp/charting-{m,w}-points-2020s.csv` and the public Gamma API.

Outputs in `results/tier0/`:

* `results.json`: label, headline, readings, stresses, timing curve, size buckets, corrected grid summary
  and the pre-registered record;
* `grid_corrected.csv`, `grid.csv`, `grid_ref_short.csv`;
* `pnl_vs_reprice_timing.{csv,png}`;
* `equity_primary.{png,csv}` and `equity_corrected_{IS,burned_OOS}.csv`;
* `sharpe_heatmap.png`.

Code: `src/tier0.py` (`PRIMARY`, `CORRECTED`, `simulate`, `live_edge_curve`) and
`scripts/tier0_backtest.py`. The verifiers' scripts are `verify_realism.py` and `rebuild.py`, with outputs in
`verify_out/` and `rebuild_out/`.
