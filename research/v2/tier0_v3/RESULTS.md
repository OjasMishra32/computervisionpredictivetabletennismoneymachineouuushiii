# Tier-0 v3: in-sample optimisation of the trader's rules

> **COUNTERFACTUAL WITH ASSUMED DATA.** Assumed: licensed live feed + courtside camera, not purchased;
> parameters from our measurements. No live ATP/WTA point feed was bought or used. Historical prices, results, fees
> and venue delays are real (public Polymarket tapes). The tier-0 trader's timing, fills and call accuracy are
> modelled with the verified model of `research/v2/tier0/RESULTS.md`. **In sample only:** 1 s-delay matches,
> 2026-05-15 → 2026-08-25 14:15 UTC (103 days). No burned OOS, no U2 and no forward data were read.

> **Blind tests, run after the freeze (`ba0c3d4`): FAIL.** U2, the primary test, fails in both periods: −0.22c
> [−3.13, 2.62] and −0.52c [−7.46, 6.15] per share, with 47.7 % and 47.3 % of trade days profitable. Burned OOS
> (non-blind) shows +0.68c [−0.44, 1.74] and $24.9/day, and also fails. See "Blind tests" at the end and
> `TEST_RESULTS.md`.

Pre-registration: `GRID.md` (written before any v3 computation). Post-hoc items: `DEVIATIONS.md`. Code:
`scripts/tier0_v3_optimise.py`. Outputs: `results/tier0_v3/is/`. Every number is a mean ± SD over 20 Monte Carlo
seeds. The per-share CI is the match-clustered bootstrap 95 % CI, averaged over seeds.

## Frozen v3 rule (chosen for August from May–July)

**θ 0.90 · hold to resolution · leverage sizing · zone [0.05, 0.95] · limit stale + 2c**

In words:

* Fire only on calls with precision ≥ 0.90. This skips lead-0 tracker out-calls (precision 0.888) and keeps
  event calls (0.95) and early calls at 25–100 ms.
* Place a limit order at the stale price + 2c, on both correct and wrong calls.
* Size each order at min($1k/q, φ × depth / q, w(q) × 100 shares). w(q) is the ex-ante leverage weight, fitted on
  3 s-regime IS jumps: 1.00 at q = 0.05 falling to 0.78 at q = 0.90.
* Keep the 100-share net cap per match. Hold to resolution.

Everything else stays at the verified primary: own 120 fps camera, stamp lag 2.0 s, R drawn per tournament, φ 0.5,
10 matches/day, p_event 0.95, live-book pricing.

## Walk-forward (monthly, pooled-seed Sortino, eligibility ≥ 50 % of the default's $/day)

| month | variant used | why | that month's $/day |
|---|---|---|---|
| May | θ0.85 · lock-in 5 s · flat · [0.05,0.95] · X 2c | pre-declared default | −$18.6 |
| Jun | θ0.95 · lock-in 30 s · lev · [0.05,0.95] · X 2c | best Sortino on May (31.9; the hold variants scored 30.2–30.8) | +$7.0 |
| Jul | θ0.90 · hold · lev · [0.05,0.95] · X 2c | best Sortino on May–Jun (24.7) | +$40.2 |
| Aug | θ0.90 · hold · lev · [0.05,0.95] · X 2c (**frozen v3**) | best Sortino on May–Jul (21.0) | +$46.4 |

The default lost money in May, so the eligibility bar was its own negative $/day. That let 338–343 of the 360
variants qualify each month.

## Results, in sample

| | **stitched walk-forward (the IS result)** | frozen v3, all IS months (in-sample-selected) | default (lock-in 5 s) | v2 headline (reference; not ex-ante) |
|---|---|---|---|---|
| trades | 7,529 ± 1,057 | 7,030 ± 948 | 8,679 ± 1,185 | 6,447 ± 827 |
| **net per share [95 % CI]** | **+0.52c ± 0.24 [0.19, 0.84]** | +1.34c ± 0.27 [0.85, 1.84] | −0.65c ± 0.11 [−0.76, −0.53] | +1.10c ± 0.16 [0.82, 1.38] |
| **$ P&L** | **$2,301 ± 1,131** | $5,067 ± 1,388 | −$3,687 ± 684 | $9,146 ± 2,196 |
| **$/day** | **$22.3 ± 11.0** | $49.2 ± 13.5 | −$35.8 ± 6.6 | $88.8 ± 21.3 |
| daily Sharpe (√365) | 5.2 ± 2.4 | 9.0 ± 2.6 | −14.4 ± 1.7 | 11.4 ± 2.5 |
| Sortino (√365; per-seed mean / pooled) | 12.4 ± 7.0 / 11.1 | 22.8 ± 9.5 / 20.7 | −11.7 / −11.6 | 37.0 / 34.4 |
| max drawdown | −$453 ± 126 | −$434 ± 146 | −$3,681 ± 673 | −$473 ± 164 |
| worst day | −$164 ± 35 | −$181 ± 43 | −$209 ± 36 | −$229 ± 61 |
| profitable days | 55.2 % ± 6.9 | 67.5 % ± 6.5 | 16.7 % | 71.7 % |
| profitable trades | 53.6 % ± 0.7 | 53.9 % ± 0.4 | 43.2 % | 52.7 % |
| months positive (of 4) | 2.85 ± 0.36 | 3.9 ± 0.3 | 0.05 | 3.9 |
| May / Jun / Jul / Aug P&L | −$316 / +$211 / +$1,247 / +$1,160 | +$1,244 / +$1,417 / +$1,247 / +$1,160 | — | — |
| capital (3 × peak locked) | $8.6k ± 1.0k | $12.4k ± 2.8k | $0.46k | $29.0k ± 6.5k |
| return on capital, period / annualised | 26 % / 93 % | 42 % / 149 % | n/m | 32 % / 115 % |

Every day has at least one trade, so profitable days are the same share of active and of calendar days. Lock-in
positions lock capital for seconds, not 4 h, which makes the default's capital and return on capital meaningless.

## What the grid shows (360 variants, `grid.csv`, `monthly.csv`)

* **Hold beats lock-in everywhere.** All 72 hold variants are positive ($1–$57/day; median $25). No lock-in
  variant makes more than $0.6/day, and every 2 s and 5 s lock-in loses. Lock-in pays a second taker fee (~0.6–0.8c)
  and the half spread (0.5c). That leaves the correct calls' ~2.7c book edge barely positive, while the wrong calls
  still cost ~4c. The tape also keeps moving in the jump direction after the reprice: at t_rep + 2 / 5 / 10 / 30 s it
  sits −0.88 / −0.70 / −0.10 / +0.06c from the 30 s post-jump VWAP the fill model anchors on, so short lock-ins exit
  before the move completes.
* **Limit price.** X = 2c is clearly best (hold, θ0.85, flat: X 0.5c $26/day, 1c $29, 2c $57). The frozen rule sits
  at the edge of the grid. The v2 sweep up to the realised new mid makes $89/day, but no live order can know that
  price.
* **Leverage sizing** raises Sortino and cuts drawdown at a small cost in $/day. For example θ0.85 · hold · X 2c:
  flat $57.2/day, Sortino 19.9, max DD −$543; leverage $50.4/day, Sortino 21.3, max DD −$415. The weight is mild
  (0.78–1.00).
* **θ** barely moves results between 0.85 and 0.95: per share +1.16 → +1.19c (flat), $57 → $52/day. At θ 0.97 only
  lead-100 calls remain (~420 trades in IS, $4.8/day).
* **Zone.** Narrowing to [0.20, 0.80] costs $/day ($57 → $46) without improving per-share P&L.

## Unmeasured quantities: frozen v3 across the full bracket (`bracket.csv`; never optimised)

Stamp lag {1.0, 2.0, 3.0, 3.14} × R reading {tournament, point, stamp} × stamp truncation {0, −0.5 s} × queue {0, ≥
0.25 s before the reprice}. 48 scenarios, 20 seeds each, IS.

| | frozen v3 | default | v2 headline |
|---|---|---|---|
| $/day min / median / max | −$32 / **$46** / $136 | −$68 / −$44 / −$14 | −$62 / $76 / $242 |
| scenarios positive / per-share CI > 0 | 69 % / 56 % | 0 % / 0 % | 69 % / 58 % |
| median $/day by stamp lag 1.0 / 2.0 / 3.0 / 3.14 s | −$4 / $12 / $83 / $97 | | |
| median $/day by reading: tournament / point / stamp | $54 / $49 / −$10 | | |

Verifier stresses at the primary (lag 2.0, tournament):

| frozen v3 | c/share [CI] | $/day | Sharpe |
|---|---|---|---|
| primary | +1.34 [0.85, 1.84] | $49.2 ± 13.5 | 9.0 |
| queue: arrive ≥ 0.25 s before reprice | +0.76 [0.01, 1.47] | $20.4 ± 13.0 | 3.8 |
| stamps truncated (R − 0.5 s) | +0.63 [−0.23, 1.50] | $14.3 ± 10.6 | 2.8 |
| truncation + queue | +0.52 [−0.44, 1.45] | $10.9 ± 9.2 | 2.1 |
| R spread = stamp noise (lag 2.0) | — | −$19.1 | — |

At lag 2.0, the tournament reading with no truncation and no queue the v2 headline numbers reproduce exactly
($88.8/day). Its queue, truncation and combined stresses also match `research/v2/tier0/RESULTS.md` ($36 / $28 /
$22 per day).

## Caveats

* **The limit binds in the live-book frame only (DEVIATIONS D2).** The fill model takes the edge from the live
  book and anchors it on the historical post-jump price. Historical moves average ~6c, live moves 4.6c. So for 56 %
  of the frozen v3's correct-fill shares the modelled price sits above stale + 2c in historical terms. Enforcing the
  limit in that frame as well gives **$18.2 ± 11.3/day, +0.96c [0.01, 1.89], Sharpe 3.7** for the frozen v3, and
  $15.9/day for the best-$/day variant. The truth is probably between this figure and the headline.
* **Trade set not ex-ante (V8).** The calls are the historical ≥ 4c detector set. No v3 rule uses the traded point's
  realised move. The per-share P&L by realised size bucket (diagnostic only; frozen v3, 20 seeds pooled) is
  4–5c +1.56c (55 % of shares), 5–7c +0.74c, 7–10c +1.88c, ≥ 10c +1.80c.
* **The stitched series carries the walk-forward's costs:** a losing pre-declared default in May and a lock-in
  choice in June. The frozen v3 over all IS months (+$49/day) is selected on May–July, so it is optimistic.
* **Absolute level.** The verified fill model anchors on the 30 s post-jump VWAP. The tape at t_rep + 3 s sits
  0.79c short of that anchor in the jump direction, so every variant is conservative on correct calls and generous
  on wrong calls by about that much. The comparison between exits is unaffected.
* **The sign still depends on unmeasured timing.** At stamp lag 1.0 s, or under the stamp-noise reading at 2.0 s,
  the frozen v3 is flat to negative. Small dollars: about $49/day on about $12k of capital in the best IS case,
  before data licence, camera and colocation costs.

## Reproduce

```bash
.venv/bin/python scripts/tier0_v3_optimise.py --build        # inputs + bundle (~90 s)
.venv/bin/python scripts/tier0_v3_optimise.py --check        # v3 simulator == v2 CORRECTED, v2 headline 20 seeds
.venv/bin/python scripts/tier0_v3_optimise.py --grid         # or the HiPerGator array: hpg/tier0_v3.sbatch (JOBS=grid)
.venv/bin/python scripts/tier0_v3_optimise.py --collect      # grid.csv, walk-forward, stitched, frozen v3, bracket jobs
sbatch --export=ALL,JOBS=bracket hpg/tier0_v3.sbatch         # bracket (or --part i --nparts 8 --jobs bracket locally)
.venv/bin/python scripts/tier0_v3_optimise.py --report       # bracket.csv, results.json, equity_stitched_IS.png
.venv/bin/python scripts/tier0_v3_optimise.py --posthoc      # DEVIATIONS D2 stress
```

Inputs added by v3 (`results/tier0_v3/is/inputs/`):

* `live_limit_curve.csv`: the limit-reachable live book. It reproduces `live_edge_curve.csv` and `stale_depth.csv`
  exactly.
* `exit_prices_is.parquet`: tape reprice time and exit prices per IS 1 s-regime jump. The reprice print is found
  for 97.7 % of jumps.
* `leverage_table.csv`.

The grid (7,240 runs) and bracket (2,880 runs) ran on HiPerGator as 8 × 1-CPU array tasks. The code and inputs are
identical to the local ones, and local and remote runs give identical results on the check runs.


## Blind tests (a) burned OOS and (b) U2, run after the freeze

> **COUNTERFACTUAL WITH ASSUMED DATA.** Assumed: licensed live feed + courtside camera, not purchased; parameters
> from our measurements. No live ATP/WTA point feed was used. Historical prices, results, fees and delays are real
> public Polymarket tapes; the trader is modelled.

These are PREREG.md §4–5, run once on 2026-10-03 by `scripts/tier0_v3_blind.py` with frozen v3 unchanged. The
pinned hashes all matched. Implementation notes were logged before the runs (DEVIATIONS D4–D8). Logged in
`results/oos_peeks.log`. Full write-up: `TEST_RESULTS.md`. Numbers: `results/tier0_v3/blind.json`. Figure:
`results/tier0_v3/equity_is_oos_u2.png`.

**Gates passed.** The burned-OOS reproduction gate gives the v2 headline at +0.5755c ± 0.3715 [−0.0764, 1.2097],
$46.43/day, and matches T.simulate row for row at seeds 1000 and 1007. The U1 IS builder check covers 125
matches and 2,873 jumps; every column is identical and the frozen-v3 trades match row for row at seeds 0 and 7.

| test set (seeds) | net per share [match CI] [day CI] | $/day | profitable days | trades / matches | verdict |
|---|---|---|---|---|---|
| **U2-IS period** (2000–2019): 7,388 markets, 962 covered | **−0.22c ± 1.16** [−3.13, 2.62] [−3.05, 2.63] | −$0.70 ± 3.58 | 47.7 % (benchmark > 50 %: not met) | 1,386 / 300 | **FAIL** |
| **U2-OOS period** (3000–3019): 3,564 markets, 385 covered | **−0.52c ± 2.50** [−7.46, 6.15] [−7.57, 6.04] | −$0.83 ± 4.32 | 47.3 % (not met) | 346 / 102 | **FAIL** |
| **U2 overall** | | | | | **FAIL** (both periods) |
| burned OOS (1000–1019), non-blind | +0.68c ± 0.54 [−0.44, 1.74] [−0.47, 1.81] | $24.9 ± 22.7 | 57.1 % (met) | 2,209 / 246 | **FAIL** |

Neither U2 period is underpowered. Other figures from `TEST_RESULTS.md`:

* **v2 headline on U2.** Even this non-ex-ante reference loses: −0.12c (U2-IS) and −0.62c (U2-OOS).
* **D2 stress** (limit also enforced in the historical frame): +0.09c (burned OOS), −1.22c (U2-IS), −1.82c
  (U2-OOS).
* **Bracket medians:** burned OOS $19.9/day; U2 −$0.11 and −$0.57/day. No U2 bracket scenario has a CI that
  excludes 0, and on every set the sign turns on the unmeasured stamp lag.
