# Tier-0 v3: blind test results, (a) burned OOS and (b) U2

> **COUNTERFACTUAL WITH ASSUMED DATA.** Assumed: licensed live feed + courtside camera, not purchased;
> parameters from our measurements. No live ATP/WTA point feed was bought or used, and we have no camera footage
> of any match. Historical prices, results, fees and venue delays are real (public Polymarket tapes). The tier-0
> trader's timing, fills and call accuracy are modelled with the verified model (`src/tier0.py`, `CORRECTED`) plus
> the frozen v3 rule. No orders were placed. Do not describe these numbers as coming from real ATP/WTA live data.

Pre-registration: `PREREG.md` (commit `ba0c3d4`). Implementation notes logged before the runs: `DEVIATIONS.md`
D4–D8. Post-run bookkeeping: D9. Code: `scripts/tier0_v3_blind.py`. Outputs: `results/tier0_v3/blind.json`,
`results/tier0_v3/{burned_oos,u2}/` and `results/tier0_v3/equity_is_oos_u2.png`. Runs were logged in
`results/oos_peeks.log`: a START line for (a) at 20:25:01 UTC and for (b) at 20:26:40 UTC, then DONE.

**What was tested.** The frozen v3 rule was `th0.9|hold|lev|z0.05-0.95|X2c`: θ 0.90, hold to resolution, leverage
sizing, zone [0.05, 0.95] and a limit at stale + 2c. It ran on the revised primary: own 120 fps camera, stamp
lag 2.0 s, R drawn per tournament, φ 0.5, 10 matches/day, p_event 0.95, net cap 100, $1k per order, fills
priced from the live book. Every number is a 20-seed mean ± SD, and CI bounds are averaged over seeds.

## Verdicts (as defined in PREREG §4–5)

| test set | per-share net > 0 | match-CI low > 0 | day-CI low > 0 | **verdict** | underpowered? | profitable days (benchmark > 50 %) |
|---|---|---|---|---|---|---|
| **U2-IS period** (primary) | no (−0.22c) | no (−3.13) | no (−3.05) | **FAIL** | no (300 matches, 92.6 trade days) | 47.7 %: **not met** |
| **U2-OOS period** (primary) | no (−0.52c) | no (−7.46) | no (−7.57) | **FAIL** | no (102 matches, 35.8 trade days) | 47.3 %: **not met** |
| **U2 overall** | | | | **FAIL**: out-of-universe generalisation fails in **both** periods | | |
| burned OOS (non-blind) | yes (+0.68c) | no (−0.44) | no (−0.47) | **FAIL** | no (246 matches, 40 trade days) | 57.1 %: met |

The forward test (c) was not run here. It belongs to `scripts/tier0_v3_forward.py` and may not run before
2026-10-04 11:30 UTC.

## Gates (all passed before any v3 number)

* **Pinned code and inputs.** All 16 SHA-256 hashes in PREREG.md match the files on disk, re-checked at every
  step.
* **Burned-OOS reproduction gate.** The v3 simulator with `V2_HEADLINE` on the tier-0 v2 OOS tables gives
  **+0.5755c ± 0.3715 [−0.0764, 1.2097], $46.43 ± 38.97/day**. That is the tier-0 v2 headline
  (`results/tier0/results.json`) to within 5 × 10⁻⁵. It also matches `T.simulate(CORRECTED)` row for row at seeds
  1000 (8,256 calls, $1,006.74) and 1007 ($1,544.42).
* **Builder check (U1 IS, 2026-08-10 → 08-13).** It covered 125 matches and 2,873 jumps.
  * Every column is identical to `tier0_jumps_is` / `tier0_post30_is`: onset, detect, direction, size, `ref`,
    `ref_short`, post30, volume, fee, delay, resolution, start, gender and region.
  * The pre-start volumes and the 30-match coverage set are also identical.
  * The IS frozen-v3 trades reproduce row for row at seeds 0 and 7.

## U2 build (the one U2 run)

| | U2-IS period | U2-OOS period |
|---|---|---|
| 1 s-delay markets | 7,388 | 3,564 |
| with in-play prints (≥ 20 in-play prints) | 5,290 | 2,392 |
| ≥ 4c jumps | 39,850 | 13,572 |
| covered markets (top 10 per UTC day by pre-start volume) | 962 | 385 |
| covered markets with jumps | 600 | 229 |
| covered jumps | 6,200 | 1,537 |
| days | 103 (05-16 → 08-26) | 40 (08-25 → 10-03) |

The U2 tables were built from:

* **Prints:** 963,147 in-play prints over 7,682 markets (`data/expand_prints.parquet`).
* **Tournaments:** 552 tournament codes over all 11,307 U2 rows.
* **Pre-start volumes:** read from all 10,952 cached tapes. The median is $73, and 1,466 markets have none.

The gender rule gives 2,275 women-labelled, 2,671 men-labelled and 6,006 unlabelled markets. That matches
PREREG §4.

## Primary results

| | burned OOS (non-blind) | **U2-IS period** | **U2-OOS period** |
|---|---|---|---|
| seeds | 1000–1019 | 2000–2019 | 3000–3019 |
| calls | 7,872 | 5,385 | 1,341 |
| trades | 2,209 ± 1,003 | 1,386 ± 145 | 346 ± 55 |
| covered matches with trades | 245.7 ± 25.1 | 300.0 ± 16.2 | 102.4 ± 8.8 |
| share of covered markets with any trade | 62 % of 396 | 31.2 % ± 1.7 of 962 | 26.6 % ± 2.3 of 385 |
| fill rate (filled correct calls / calls) | 23.9 % ± 12.9 | 21.2 % ± 2.7 | 21.1 % ± 4.3 |
| wrong calls, share of trades | 19.5 % | 17.8 % | 18.9 % |
| median $ per fill | $23.9 | $3.30 | $3.01 |
| **net per share** | **+0.68c ± 0.54** | **−0.22c ± 1.16** | **−0.52c ± 2.50** |
| match-clustered 95 % CI | [−0.44, 1.74] | [−3.13, 2.62] | [−7.46, 6.15] |
| day-clustered 95 % CI | [−0.47, 1.81] | [−3.05, 2.63] | [−7.57, 6.04] |
| tournament-clustered 95 % CI (robustness) | [−1.03, 1.71] | [−3.24, 2.68] | [−7.57, 5.99] |
| **$ P&L** | **$998 ± 908** | **−$72 ± 369** | **−$33 ± 173** |
| **$/day** | **$24.9 ± 22.7** | **−$0.70 ± 3.58** | **−$0.83 ± 4.32** |
| of which correct / wrong calls | +$1,603 / −$605 | +$417 / −$489 | +$59 / −$92 |
| daily Sharpe (√365) | 4.9 ± 4.3 | −0.31 ± 1.57 | −0.41 ± 2.17 |
| Sortino (√365; per-seed mean / pooled) | 12.5 ± 13.8 / 9.3 | −0.21 / −0.44 | −0.13 / −0.60 |
| max drawdown | −$401 ± 230 | −$513 ± 275 | −$259 ± 102 |
| worst / best day | −$159 / +$246 | −$132 / +$144 | −$94 / +$112 |
| **profitable days (of trade days)** | **57.1 % ± 10.2** | **47.7 % ± 4.6** | **47.3 % ± 7.5** |
| profitable days (of calendar days) | 57.1 % | 42.9 % | 42.4 % |
| trade days | 40 of 40 | 92.6 of 103 | 35.8 of 40 |
| profitable trades | 53.0 % | 54.3 % | 52.0 % |
| months positive | 2.05 of 3 | 1.95 of 4 | 1.5 of 3 |
| monthly P&L | Aug +$348 / Sep +$644 / Oct +$6 | May −$3 / Jun +$74 / Jul −$38 / Aug −$105 | Aug +$6 / Sep −$42 / Oct +$2 |
| capital (3 × peak locked) | $9.4k ± 4.3k | $2.5k ± 0.6k | $1.2k ± 0.4k |
| return on capital, period / annualised | 8.6 % / 79 % | −1.8 % / −6.5 % | −1.9 % / −17 % |

U2 dollars are small, as PREREG §4 expected: depth is scaled by min(1, V/V_live), so the median fill is about $3.
The per-share net and the profitable-days share are the primary readings, and both are negative or below the
benchmark in each U2 period.

**Comparators for the burned OOS.**

* **Tier-0 v2 corrected headline** in the same window: +0.58c [−0.08, 1.21], $46/day.
* **Frozen v3 over all IS months** (optimistic): +1.34c [0.85, 1.84], $49.2/day, 67.5 % profitable days.
* **Stitched IS walk-forward:** +0.52c [0.19, 0.84], $22.3/day, 55.2 % profitable days.

Frozen v3 on burned OOS earns more per share than the v2 headline (+0.68c against +0.58c). It makes about half the
dollars, because leverage sizing and the 2c limit send roughly half the shares. Its CIs are wider and both
include 0.

## Reported with every test set, never used for a verdict

### Reference and D2 stress (same scenario as the primary)

| | burned OOS | U2-IS | U2-OOS |
|---|---|---|---|
| frozen v3 + limit also enforced in the historical frame (D2) | +0.09c [−1.84, 2.01], $3.3 ± 13.0/day | −1.22c [−5.64, 3.17], −$2.15 ± 3.28/day | −1.82c [−11.49, 7.80], −$1.77 ± 4.03/day |
| tier-0 v2 headline (reference; sweeps to the realised new mid, **not ex-ante**) | +0.58c [−0.08, 1.21], $46.4 ± 39.0/day | −0.12c [−1.66, 1.41], −$0.77 ± 5.01/day | −0.62c [−4.43, 3.14], −$2.61 ± 6.87/day |

The non-ex-ante v2 headline also loses money on U2 in both periods. So the U2 failure is not caused by the v3 rule
choices (θ, sizing, zone, limit): the modelled edge does not carry over to these markets.

### 48-scenario bracket for frozen v3 (unmeasured timing; reported, never optimised)

The bracket is stamp lag {1.0, 2.0, 3.0, 3.142} × R reading {tournament, point, stamp} × truncation {0, R − 0.5 s} ×
queue {0, ≥ 0.25 s}.

| | burned OOS | U2-IS | U2-OOS |
|---|---|---|---|
| $/day, min / median / max | −$28.5 / $19.9 / $91.0 | −$7.20 / −$0.11 / $6.69 | −$3.93 / −$0.57 / $5.42 |
| per share, min / median / max | −4.64c / +0.54c / +1.16c | −6.01c / −0.02c / +0.88c | −5.32c / −0.56c / +1.22c |
| scenarios with P&L > 0 | 65 % | 48 % | 46 % |
| scenarios with match-CI low > 0 / day-CI low > 0 | 46 % / 42 % | 0 % / 0 % | 0 % / 0 % |
| median per share by stamp lag 1.0 / 2.0 / 3.0 / 3.14 | −1.20 / 0.00 / +0.91 / +0.95c | −1.97 / −0.58 / +0.56 / +0.63c | −1.56 / −1.24 / +0.63 / +0.76c |
| median per share by reading: tournament / point / stamp | +0.75 / +0.57 / −1.53c | +0.04 / +0.28 / −2.51c | −0.24 / −0.11 / −2.24c |

**Verifier stresses at lag 2.0, tournament reading:**

| | burned OOS | U2-IS | U2-OOS |
|---|---|---|---|
| queue ≥ 0.25 s before the reprice (finding e) | +0.19c [−1.27, 1.60], $14.8/day | −0.68c [−3.85, 2.42], −$1.74/day | −1.10c [−8.77, 6.04], −$1.61/day |
| stamp truncation R − 0.5 s | +0.02c [−1.73, 1.74], $8.6/day | −0.48c [−4.00, 3.11], −$0.96/day | −1.17c [−9.60, 6.85], −$1.60/day |
| both | −0.08c [−2.00, 1.77], $6.2/day | −0.74c [−4.52, 3.02], −$1.43/day | −1.03c [−9.92, 7.37], −$1.29/day |

None of the 144 U2 scenario-period cells (48 scenarios × 3 sets) has a U2 CI that excludes 0. On U2 the sign
again depends on the unmeasured stamp lag: positive only at lag ≥ 3 s.

### Per-share decomposition (20 seeds pooled; hold to resolution)

| | burned OOS correct | burned OOS wrong | U2-IS correct | U2-IS wrong | U2-OOS correct | U2-OOS wrong |
|---|---|---|---|---|---|---|
| share of trades / of shares | 85 % / 81 % | 15 % / 19 % | 82 % / 64 % | 18 % / 36 % | 82 % / 62 % | 18 % / 38 % |
| live-book edge (+) / cost (−) | +2.76c | −2.00c | +2.61c | −2.42c | +2.61c | −2.37c |
| fee | −1.03c | −1.02c | −0.86c | −0.84c | −1.01c | −0.96c |
| payout − post-jump price | −0.12c | +0.37c | +0.37c | −1.15c | −0.30c | −0.02c |
| net | **+1.62c** | **−2.64c** | **+2.12c** | **−4.41c** | **+1.30c** | **−3.35c** |

**Reading (descriptive).** A correct call on U2 earns as much book edge as on U1 (+2.6c). What changes is how
shares split between correct and wrong calls: wrong calls carry 36–38 % of U2 shares, against 19 % on burned OOS.
The fill sizes show why:

| | burned OOS | U2 (both periods) |
|---|---|---|
| mean / median shares, wrong fill | 69 / 87 | 44–46 / 34–37 |
| mean / median shares, correct fill | 53 / 56 | 16–17 / 5 |
| fills near the 100-share cap (≥ 75 shares), wrong / correct | 69 % / 42 % | 35–36 % / 7–8 % |

In U2's thin books the volume-scaled depth binds before the 100-share leverage cap. The model gives a correct call
only φ = 0.5 of the limit-reachable stale depth on the point-winner's side, because it competes with the fast tier.
A wrong call draws on the opposite side of the book, which nobody competes for. So in small markets the model sizes
wrong calls much larger than correct ones. That is a property of the frozen model on small markets, not a tuned
effect. It is reported here and changes no verdict.

In live-frame terms, 59 % (burned OOS), 63 % (U2-IS) and 65 % (U2-OOS) of correct-fill shares are priced above
stale + 2c in the historical frame: the D2 caveat. The median τ of correct fills is 0.77 / 0.81 / 0.71 s before the
reprice.

### P&L by realised jump size (DIAGNOSTIC ONLY: the detector selects on realised moves; finding d)

| bucket | burned OOS: share of shares, net | U2-IS | U2-OOS |
|---|---|---|---|
| 4–5c | 50 %, +0.37c | 38 %, −1.36c | 35 %, −0.85c |
| 5–7c | 31 %, +0.84c | 34 %, +1.50c | 35 %, −0.20c |
| 7–10c | 13 %, +1.74c | 19 %, −0.54c | 20 %, −1.77c |
| ≥ 10c | 5 %, +2.58c | 9 %, −1.30c | 11 %, +2.40c |

### U2 splits (descriptive; not tested)

Per-share figures are means ± SD of per-seed values, with the share of all shares in parentheses. $/day is pooled.

| split | U2-IS | U2-OOS |
|---|---|---|
| ITF | −0.22c ± 1.16 (100 %), −$0.70/day | −0.53c ± 2.53 (99.8 %), −$0.87/day |
| ATP/WTA (< $5k) | 0.35 trades per seed (negligible) | 2 trades per seed (negligible) |
| women-labelled | −1.16c ± 4.58 (15 %), −$0.38/day | −1.59c ± 4.05 (47 %), −$1.17/day |
| men's mix (men-labelled + unlabelled) | −0.12c ± 1.34 (85 %), −$0.32/day | +0.38c ± 4.11 (54 %), +$0.34/day |
| region mapped | +0.45c ± 2.17 (29 %), +$0.21/day | +3.54c ± 8.19 (28 %), +$2.20/day |
| region unmapped (100 ms assumed) | −0.42c ± 1.65 (71 %), −$0.91/day | −2.40c ± 3.48 (72 %), −$3.04/day |
| fee 3 % | +0.83c ± 1.65 (38 %), +$0.83/day | (none) |
| fee 5 % | −0.78c ± 1.48 (62 %), −$1.52/day | −0.52c ± 2.50 (100 %), −$0.83/day |

The mapped-region subset is positive in both periods, but its CIs are wide, and region was never a v3 dimension. A
rule that trades only mapped venues, or only 3 %-fee markets, would be a **new hypothesis** chosen on U2. It would
need its own pre-registration and fresh data (PREREG §2).

## Figure

`results/tier0_v3/equity_is_oos_u2.png` shows cumulative P&L as a 20-seed mean, with a band from the seeds' 10th to
90th percentile:

* **Left panel (U1):** the IS stitched walk-forward (+$2,301), followed by frozen v3 on burned OOS (+$998).
* **Right panel (U2):** the U2-IS period (−$71.66), followed by the U2-OOS period (−$33.40). This panel has its
  own $ scale.

## Bottom line

* **U2, the primary blind test, FAILS in both periods.** On 10,952 unseen one-second-delay markets (mostly ITF),
  the frozen v3 rule loses 0.22c (IS period) and 0.52c (OOS period) per share. Its match- and day-clustered CIs
  sit well around 0, and fewer than half of the trade days are profitable (47.7 % and 47.3 %, against a > 50 %
  benchmark).
* **The failure is not about the v3 rule choices.** The non-ex-ante v2 headline also loses on U2.
* **Burned OOS** (non-blind; it cannot confirm v3 on its own) shows +0.68c and $24.9/day with 57 % of days
  profitable. Both CIs include 0, so it **FAILS** the same three-condition rule.
* **The sign still hinges on unmeasured timing.** Across the bracket it turns on the stamp lag: negative at
  1.0 s, near zero at 2.0 s, positive at ≥ 3 s, on every test set.

## Notes

* Never place orders on the basis of these numbers.
* The forward test (c) is still pending. It is secondary and runs once, after 2026-10-04 11:30 UTC.
