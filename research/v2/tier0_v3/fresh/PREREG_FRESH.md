# Fresh holdout: "a firm with a licensed 0.5 s feed" on matches played after the burned OOS (pre-registration)

> **COUNTERFACTUAL WITH ASSUMED DATA.** Real: Polymarket prices, fills (public trade tapes), match results, taker
> fees and the venue's 1 s order delay. Simulated: the camera/CV calls, made at an **assumed licensed-feed delay V**
> (0.5, 1 or 3 s). No feed or video was bought, received or watched, we have no footage of these matches, and no
> order is placed. Every output and figure of this test carries this label.

Written 2026-10-04 at about 05:35 UTC, **before** any trade tape, price or result of the fresh window was fetched
or read, on top of `bd13f92`. The commit that adds this file is the pre-registration timestamp. Code:
`scripts/fresh_holdout.py` (written after this commit). Outputs: `results/fresh_holdout/`. Raw data:
`data/fresh/` (gitignored, never committed).

This is a new, separately pre-registered test. It is **not** the tier-0 v3 forward test (c) of
`research/v2/tier0_v3/PREREG.md` §6, which the team decided not to run (`HYPOTHESIS_V2.md` A5). No forward-window
data has been read for any tier-0 rule so far (`results/forward_peeks.log` has no START line).

## 1. Window and universe (fixed now)

* **Start.** Matches whose scheduled start (Gamma `startTime`) is **after 2026-10-03 07:10:00 UTC**. That is the
  latest start in the U1 universe (`src.tape.universe()`, 13,084 matches, catalogue fetched 2026-10-03 09:50 UTC),
  so it is the end of the burned OOS. Any market already in U1 is dropped.
* **End.** The fetch time T_f (recorded in `results.json`). A match is in if it started before T_f, its event is
  closed and resolved at T_f (`res0` in {0, 0.5, 1}), and its finish time is at least 10 minutes before T_f (so
  its public tape is complete).
* **Universe rule (same as the backtest).** `scripts/forward_test.window_universe` (HYPOTHESIS_V2 A1, unchanged):
  Gamma `tag_slug=tennis` moneyline markets, series atp / wta / challenger, Polymarket volume >= $5k. This is
  `src.tape.universe()`'s rule (same tag, same series, same `MIN_VOL`).
* **Pre-declared exclusion.** The 9 WTA matches of 2026-10-03 whose live books built the model's measured inputs
  (timing R, stale depth, live edge curves; `results/tier0/inputs/live_match_volumes.csv`) and which the match
  replay (`research/replay`) also used: `wta-rybakin-charaev-2026-10-01`, `wta-kartal-wa-2026-10-01`,
  `wta-bouzkov-birrell-2026-10-01`, `wta-zhen-kalinsk-2026-10-01`, `wta-bencic-zakharo-2026-10-01`,
  `wta-su-bucsa-2026-10-02`, `wta-jovic-dart-2026-10-02`, `wta-rakhimo-fernand-2026-10-01`,
  `wta-andree-boisson-2026-10-03`. They are removed before coverage is ranked. Their outcomes were seen, and the
  model was calibrated on their books, so they cannot be holdout.
* **Tier-0 regime.** Calls only on 1 s-delay matches (`regime = delay1`), as in every tier-0 run.
* **Coverage (primary).** Per UTC start date, the 10 eligible 1 s-delay window matches with the highest pre-start
  volume (`T.coverage_set`, `T.prestart_volume` rule via `tier0_v3_forward.prestart_usd`). This is the frozen
  coverage of 10 matches a day.
* **Coverage (secondary, labelled).** Every eligible 1 s-delay window match. A firm with a licensed video feed is not
  limited to 10 cameras, and this gives a larger sample. It is reported next to the primary, never instead of it.
* **Sub-window (reported).** Matches starting at or after 2026-10-03 14:00 UTC (the start of the forward window
  that was never run), reported separately.

## 2. Strategies, parameters and readings (frozen; nothing is chosen on this window)

Two strategies are reported side by side. Neither is selected after the fact.

| | strategy | rule | frozen at |
|---|---|---|---|
| **S1** | frozen tier-0 v3 | `th0.9\|hold\|lev\|z0.05-0.95\|X2c`: precision >= 0.90, hold to resolution, leverage sizing, zone [0.05, 0.95], limit stale + 2c. `O.simulate_v3` (`scripts/tier0_v3_optimise.py`) on `T.CORRECTED`; shared inputs from the pinned IS bundle (`results/tier0_v3/is/inputs/bundle`). | rule `ba0c3d4` (PREREG.md), code `11d1016` |
| **S2** | the paper's CV trader (Table 2) | the tier-0 revised primary, `T.simulate(..., T.CORRECTED, ...)`: fires on every covered jump with the token's stale price in [0.05, 0.95] (no precision threshold), takes the stale depth with no limit price (up to the realised new mid, so not ex-ante; = v3's `V2_HEADLINE` reference), $1k per order, hold to resolution. This is the model behind `results/tier0/latency_sweep.json` and the paper's Table 2. | model `a5769c7`, sweep `84c3898` |

Both run on the revised primary scenario (`T.CORRECTED`): own 120 fps CV model (`own120`), φ 0.5, net cap 100
shares, trade cap $1,000, live-book fill prices on both sides, limit-order fills, +0.5c stale correction, R drawn
once per tournament, regional venue-to-London latency, 2 ms gateway, the venue's 1 s order delay.

* **Feed delay V = 0.5, 1 and 3 s.** Implemented exactly as `scripts/tier0_latency_sweep.cell("video", ...)`:
  the CV table's inference time `t_inf` becomes `t_inf + V`. Nothing else changes. V = 0.5 s is the "firm with a
  licensed 0.5 s feed" case (the best vendor claim, not shown for tennis).
* **Readings of the unmeasured stamp lag.** Pre-registered: 2.0 s (`T.CORRECTED.stamp_lag`). Post hoc: 3.142 s,
  the calibrated central value (`T.calibrate_stamp_lag()["central"]`), reading `tournament_lagcal` of the sweep.
  Both are reported in every table, the pre-registered one first.
* **Seeds 4000-4019** (`T.draws(n_jumps, 4000 + k, n_tour)`), the seeds `PREREG.md` §3 fixed for forward data.
  The same seeds are used for every strategy, V and reading.
* **Jumps, prices, match facts.** The tier-0 builder pinned in `scripts/tier0_v3_forward.py` and checked against
  the IS tables: in-play prints from `tiers.match_prints`, `jump_onsets` (>= 4c, 10 s vs 60 s VWAP, 60 s
  refractory), `ref` / `ref_short` from `T._refs`, the 30 s post-jump VWAP (pricing only), region from
  `T.region_of`, tournament codes from `T.tournament_codes` over the window. Days: `T.period_days`.
* **Code change since the v3 pins.** `src/tier0.py` differs from its pinned hash: `6ecc04d` added capacity-study
  options whose defaults are the committed model. Gate G1 (§4) checks that the current code reproduces the stored
  results exactly before anything is run on the window.

## 3. Metrics (per strategy x V x reading x coverage; 20-seed means, CIs averaged over seeds)

* **Per-share net** (cents, held to resolution, after each match's own taker fee), with the match-clustered
  bootstrap 95 % CI (1,000 draws, rng seed 0; `T.metrics` / `O.metrics_v3`).
* **$ P&L and $/day.** Days = every UTC calendar day from the first to the last 1 s-delay jump date of the window,
  zero-filled (`T.period_days`). $/day 95 % CI = the match-bootstrap CI of total P&L / days (seed-averaged); the
  2.5-97.5 % range over seeds is also given.
* **Sharpe** (daily, √365, zero-filled), with the 2.5-97.5 % range over seeds. With fewer than 10 days it is
  printed with the flag "not meaningful (n days)".
* **Hit rate** (share of trades with P&L > 0), wrong-call share, trades, matches with trades, covered matches,
  calls, capital (3 x peak locked).
* **Per-day P&L** (mean over seeds, 10th and 90th percentile).
* **Minimum sample.** If the 20-seed mean of matches with trades is below 30, the cell is labelled **anecdotal**:
  numbers are reported, but no claim of an edge (or of its absence) is made from them. One day of matches is
  expected to fall below this bar.
* **No pass/fail verdict.** This is reported, not tested. Labels only: per-share > 0; match-CI low > 0.

**We report whatever comes out**: every cell above, including the ones that lose. No window boundary, exclusion,
parameter, V, reading, seed, strategy or coverage rule changes after any fresh outcome is read. A departure would be
written to `research/v2/tier0_v3/fresh/DEVIATIONS_FRESH.md` before the affected numbers are produced, and both
versions reported.

## 4. Gates before the fresh run (no fresh outcome is read before both pass)

* **G1, code reproduction (already-read data).** With today's code: S2 on IS (seeds 0-19) and burned OOS
  (1000-1019) at V = 0.5, 1, 3 s, both readings, must equal `results/tier0/latency_sweep_seeds.csv` seed for seed
  ($/day and per-share to 1e-6). S1 at V = 0 on burned OOS must equal `results/tier0_v3/burned_oos/results.json`
  (20-seed per-share and $/day to 5e-4 relative).
* **G2, pipeline equivalence (one burned-OOS day, non-blind, logged).** Rebuild 2026-10-02 (U1 matches starting
  that UTC day) from a fresh Gamma listing and freshly fetched Data API tapes (`data/fresh/raw`, never the cached
  `data/raw`) with the fresh-window code path. Compare with the stored tables: match list and facts, in-play prints,
  jump count and every jump column, post-jump prices, pre-start volumes, the coverage set, and the seed-1000 P&L of
  that day (S1 at V = 0 against the stored burned-OOS trades; S1 and S2 at V = 0.5 s, both readings, fresh
  tables against stored tables with the OOS row and tournament indices). Any disagreement is explained in
  `equivalence_check.json` before the fresh window is run.

## 5. Showcase match (fixed now, not chosen on P&L)

The eligible, covered (primary coverage) 1 s-delay window match with the **highest in-play traded volume** (sum of
$ of the in-play prints that `tiers.match_prints` keeps). For it, `showcase_ledger.csv` holds the 1 s price path
from the tape and every simulated call of S1 and S2 at V = 0.5 s, both readings, at the first seed (4000): jump
onset, side (correct / wrong call), modelled timing against the reprice (τ), fill price, shares, fee, exit
(resolution payout) and P&L. The 20-seed mean P&L of the match is reported next to it.

## 6. Also computed (from data already read; burned-OOS reads logged)

* The daily P&L series at V = 0.5 s (S1 and S2, both readings; mean over seeds and 10-90 % band) for IS
  (seeds 0-19) and burned OOS (seeds 1000-1019), so a figure can show IS -> burned OOS -> fresh. S1 IS and burned
  OOS at V = 0.5, 1 and 3 s are new cells on burned data: non-blind, no parameter chosen.
* Licence-cost break-even at V = 0.5 s: the most a firm could pay for the feed per month and still break even,
  $/day x 30.42 - $77.42 (London VPS, central), as `scripts/redteam_derived.py` does for `cv.*.maxlic` at 1 s.

## 7. Logging

`results/oos_peeks.log` gets a line before the G2 burned-OOS read, before the burned-OOS history cells, before the
first fetch of the fresh window (the catalogue carries results), and before the first fresh-window simulation.

## 8. Caveats carried into every output

* **The trades are selected on outcomes.** Calls are the historical >= 4c detector jumps, which are found with prices
  up to 10 s after the point. A live trader would not know this set in advance.
* **The calls are simulated.** Call timing, accuracy and fill depth come from our measurements (one live day for the
  book, table-tennis video for the CV) and an assumed feed delay; no camera saw these matches.
* **Sample size.** Roughly one day of matches; expected anecdotal under §3.
* **Model inputs.** Live-book depth and timing come from 9 WTA matches on one day (excluded here).
