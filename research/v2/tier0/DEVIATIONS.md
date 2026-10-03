# Tier-0 counterfactual: deviations from PREREG.md

**COUNTERFACTUAL WITH ASSUMED DATA.** Assumed: licensed live feed + courtside camera, not purchased; parameters
from our measurements.

Part 1 (T1–T3) was logged by the builder after the first primary P&L run. Part 2 (V1–V10) applies the two
verifiers' fixes (skeptic and independent rebuild, both 2026-10-03). Every Part 2 change was made **after**
the verifiers had computed P&L for the pre-registered model and for several alternatives, so none of them is
pre-registered. Each one comes from a measurement or a modelling inconsistency the verifiers found. None is a
parameter chosen to improve P&L, and wherever a choice exists the other option is reported as a stress.

## Bookkeeping corrections

* **Timestamp of the first P&L run.** The original text below said "~17:35 UTC". File modification times
  show it happened earlier: PREREG.md 17:25:41, src/tier0.py 17:28:43, DEVIATIONS.md (quoting the first
  primary numbers) 17:29:12, equity_primary.csv 17:29:29, grid.csv 17:30:27, results.json 17:31:26. So the
  first primary P&L ran between 17:28:43 and 17:29:12 UTC. The pre-registration still came first.
* **Script edit after the outputs.** scripts/tier0_backtest.py was saved at 17:32:09, after grid.csv and
  results.json were written. The PNGs were written at 17:32:10–11, so this was most likely a figure-code edit
  followed by `--figures`. The skeptic re-ran the primary and 6 random grid rows with that version of the code
  and reproduced them exactly, so the edit changed no number.
* **Coverage count.** PREREG says N = 10 covers 1,011 IS matches; the per-period ranking actually covered
  1,012 (T1). Under the literal rule (V6) the counts are N = 3: 305 IS / 120 OOS, N = 10: 1,003 / 396,
  N = 30: 2,809 / 1,154. PREREG.md itself is left unedited.

## Part 1 (builder): changes after the first primary P&L run

No grid value, no primary-scenario parameter and no model rule changed in Part 1. Every change is either a
bug fix or an added view. The first run gave IS +3.19c/share, $341/day and burned OOS +2.49c/share, $254/day.

### T1. Coverage chose only among matches that later had a jump (look-ahead fix)

The first implementation ranked matches by pre-start volume using only matches present in the jump table,
so a match that produced no ≥ 4c jump could never take a camera slot. That is look-ahead: a jump is known
only after the match. Coverage now ranks **every universe match of the period** by pre-start volume.
107 of the 1,012 IS matches covered at N = 10 (52 of 397 OOS) have no jump; their slots go unused. Covered
jumps at N = 10 drop from 25,804 to 23,069 (IS). The fix was made before the full grid ran. (Superseded by V6,
which ranks across both periods.)

### T2. Added: the whole grid re-run with the near stale price (`ref_short`)

A diagnostic run after the first primary P&L (no P&L involved in it) showed that the pre-registered stale
price `ref` (VWAP over [onset−63 s, onset−3 s)) sits on average 1.37c (median 0.91c) further from the
post-jump price than the VWAP over [onset−33 s, onset−1 s). The builder read this as `ref` overstating the edge
by about 1c and called `ref_short` "probably the more realistic" price. **The live data contradict that
reading** (V4): against the true quote mid just before the point, `ref` overstates the edge by about 0.5c and
`ref_short` understates it by about 0.7c. `grid_ref_short.csv` is still produced as a record.

### T3. Reporting only

The share of calls arriving before or after the reprice, and the share of correct calls blocked by the net
cap, are computed on all calls instead of on filled trades only.

## Part 2: verifier corrections (post hoc; the corrected model is the headline)

The corrected configuration is `src/tier0.py: CORRECTED`. It keeps every pre-registered parameter value (own
120 fps camera, stamp lag 2.0 s, φ 0.5, 10 matches/day, p_event 0.95, net cap 100, $1k per order, regional
latency map, live pool D ≥ 3c, depth scaling min(1, V/V_live), 1 s regime) and changes the rules below. The
pre-registered model (`PRIMARY`) is still run and reported as the record.

### V1. Correct-call fill price from the measured book (skeptic issue 1)

The pre-registered fill price was the stale VWAP + 0.5c for every share. That credits every stale share with
the whole realised jump, about 6c gross per share, but the stale depth was counted at every level better
than the post-reprice mid. On the live day the first 100 stale shares earn only 2.3–2.7c against the new mid,
and the real fast tier earns 2.24c gross / 1.13c net per share. **New rule (`price="live"`):** a correct
fill pays the post-jump token price minus e, where e is the average edge against the new mid of the first n
shares resting on the sampled live point, at the same τ before the reprice. n is the number of shares we
actually send after the net cap, in a book scaled by min(1, V/V_live). The per-point cumulative edge curve
(N = 25 … 12,800 and all stale shares; 2 s / 1 s / 0.25 s snapshots) is rebuilt from the same book replay
as research/v2/latency: `src/tier0.py: live_edge_curve` → `results/tier0/inputs/live_edge_curve.csv`. It
reproduces the skeptic's first-100/200 numbers and `stale_depth.csv` exactly. Post-jump price = VWAP of
outcome-0 prints in [detect, detect + 30 s) (`data/derived/tier0_post30_{is,oos}.parquet`). It is used only
to price fills; no decision uses it. Per-share P&L then splits into the measured book edge, the market's
post-jump forecast error (payout − post-jump price, real resolution) and the fee. Stress: e scaled by
historical size / live D (generous).

### V2. Wrong calls priced from the same book (consistency; skeptic issue 7)

The pre-registered wrong call paid the loser's stale price + 0.5c, so it lost the whole realised historical
jump. That move is selected to be ≥ 4c (mean 6c), and on the live day the single-point move averages 4.6c.
Pricing correct calls from the book and wrong calls from the selected realised jump would be inconsistent.
**New rule (`wrong_price="live"`):** a wrong call pays the loser's post-jump price plus the measured cost of
the first n shares on the opposite side of the same live book (the winner token's bids, best first, against
the new mid). Measured first-100-share cost: 4.8–5.3c, which is close to D plus the spread. After the reprice
the cost falls linearly to half the 1c spread at +0.5 s, because the loser's book moves toward the order.
Wrong calls still always fill, with full depth and no φ. Stress: pre-registered wrong-call pricing.

### V3. Timing: three readings of the data, and P&L as a function of t_reprice − t_bounce (skeptic issues 2 and 6)

The model needs t_reprice − t_bounce = (t_reprice − t_stamp) + (t_stamp − t_bounce). Only the first term is
measured, as a per-point distribution R (median −1.32 s, p10 −2.93, p90 +0.07). The pre-registered model
draws R per point and adds a constant stamp lag. That assigns all of R's spread to the book's timing, and
draws it independently across points, which drives daily Sharpe to 30–50. Now `r_mode` selects one of:

* `point`: pre-registered.
* `tournament`: R is drawn **once per tournament** (league with qualifying and ATP/WTA suffixes merged,
  split at gaps over 4 days; 266 tournaments). The marginal is the same as `point`, but the timing regime
  persists. **This is the headline reading**: it keeps the pre-registered timing model's centre and adds
  the model risk.
* `stamp`: R's spread is umpire-stamp noise, so t_reprice − t_bounce = median(R) + stamp lag is constant.

The corrected grid adds `r_mode ∈ {tournament, stamp}` as a dimension. Every other level is unchanged
(432 × 2 = 864 scenarios). The headline is reported next to the `stamp` reading. We also run a curve of
P&L against t_reprice − t_bounce ∈ {0.6 … 2.5 s} under all three readings, with the calibrated inference
(1.35 s under the stamp reading, stamp lag 3.14 s under the others) marked. Daily Sharpe is reported but is
not a headline.

### V4. Stale-price correction (skeptic issue 5)

On the 102 live detector jumps matched to an official point, `ref` overstates the edge against the true
quote mid just before the point by +0.56c mean / +0.49c median. **New rule:** the point-winner token's stale
price is `ref` + 0.5c (`stale_adj = 0.005`). Under V1 this affects only the zone filter, the wrong-call price
before the reprice when `wrong_price="ref"`, and the fallback when no post-jump print exists (none do).
Stresses: no correction; `ref_short`.

### V5. Order type: a limit order, with no fills at a moved price (skeptic issue 7)

With a 1 s venue delay the order cannot see the book, so "never chase" has to be a property of the order. A
correct call is a limit order that sweeps only stale levels. It fills only if it arrives before the reprice
(τ ≥ 0), so it gets no decay-window fills (`order="limit"`). Stresses: decay-window fills with the edge
falling to 0 over 0.5 s; **queue priority** behind the existing fast tier, filling only if we arrive ≥ 0.25 s
before the reprice (rebuild issue 3), alone and combined with stamp lag 1.0 s and with stamp truncation.

### V6. Coverage ranks the whole universe per UTC date (rebuild issue 1)

PREREG says "on each UTC start date, the N matches with the highest pre-start volume". The code ranked
within each period, so the split day 2026-08-25 got 2N cameras. Coverage now ranks both periods together,
then splits by period. This applies to both models. Its effect on the pre-registered primary is inside
Monte Carlo noise (IS $308 → $305/day at seed 0).

### V7. Multi-seed reporting (rebuild issue 2)

The headline, the readings and every stress are 20-seed means ± SD (seeds 0–19). Every grid cell and the
timing curve are 10-seed means (seeds 0–9). The per-share CI is the match-clustered bootstrap CI averaged over
seeds. The seed-0 draw is also stored in full in results.json.

### V8. The trade set is not ex-ante (skeptic issue 4)

PREREG called the ≥ 4c restriction ex-ante knowledge for a feed holder. It is not. The detector compares the
next 10 s of prints with the previous 60 s. On the live day only 63 % of detector jumps map to one
same-direction official point, 42 % of windows hold 2+ points, and a third of matched single-point moves are
under 4c. A Markov filter would pick a different set. Text and code no longer call it ex-ante, and per-share
P&L is reported by realised jump-size bucket. V1 removes most of the selection effect from the edge, because
the book edge comes from live single points and not from the historical size.

### V9. Stamp resolution (skeptic issue 3)

All 994 official stamps end in 000 ms. If they are truncated rather than rounded, R is overstated by about
0.5 s. Stress: R − 0.5 s.

### V10. Headline changed from PRIMARY to CORRECTED

The pre-registered primary is no longer presented as an estimate, because its fill price double-counts the
edge (V1). It is kept, with literal coverage and 20 seeds, as `prereg_record` in results.json, with
`grid.csv` and `grid_ref_short.csv`. The corrected headline uses the same parameter values. Its new rules
were all specified by the verifiers. The one place where we chose between two verifier-acceptable options
is V2 (book-priced vs pre-registered wrong calls), and both are reported.
