# Tier-0 v3: deviations from GRID.md

> **COUNTERFACTUAL WITH ASSUMED DATA.** Assumed: licensed live feed + courtside camera, not purchased;
> parameters from our measurements. In-sample optimisation only; no live ATP/WTA data was used.

No grid value, selection rule, default, fixed parameter or model rule in `GRID.md` was changed after the first v3
P&L. The first v3 P&L was a 3-variant timing run at seed 0 (v2 headline, the default, one other variant), followed
by a seed-0 decomposition of the default's lock-in P&L to check the exit arithmetic for bugs (none found). Both
happened before the grid ran. Everything below is bookkeeping or an added view.

## D1. Code fixes that change no number

* Job ids changed from `|`-joined strings to tuples, because variant names contain `|` (before the grid ran).
* Reference variants are keyed by their descriptive label in the job list and renamed to `V3.name()` when
  assembled (after the grid ran; affects only lookups).
* `_keep_job` returns every fired call rather than filled trades only, so that the stitched n_calls and fill rate
  count calls. This was changed before the stitched series was first computed.

## D2. Added after the grid: limit enforced in the historical-price frame (stress, not selectable)

GRID.md §5 applies the limit stale + X in the measured live book, the frame in which the verified model measures
the fill edge (V1). The model then prices a correct fill at the historical post-jump price minus the live edge.
Historical detector moves average about 6c (post-30 s VWAP − `ref`). The live day's moves average 4.6c. So for
**56 % of the frozen v3's correct-fill shares**, the modelled fill price sits above stale + 2c in historical terms.
That share was found in the collect step's diagnostics.

`V3.hist_limit=True` additionally drops those fills: correct calls with modelled price > stale + X, and wrong calls
with modelled price > loser's stale + X. It is run on the frozen v3 only, as a stress. It was not part of the grid or
the selection. Under it the frozen v3 makes $18.2 ± 11.3/day, +0.96c [0.01, 1.89], Sharpe 3.7 (20 seeds, IS). Without
it the figures are $49.2 ± 13.5/day, +1.34c [0.85, 1.84]. The historical-frame check is probably too strict,
because the 30 s post-jump VWAP includes drift after the reprice (tape at t_rep + 3 s sits 0.79c short of it in the
jump direction). The live-frame figure is probably too generous for the same reason, but in the other direction.
The truth is likely between the two.

## D3. Observations that the pre-registered rule handled as written

* The pre-declared default (lock-in 5 s, X 2c) lost money in May (−$18.6/day), so the eligibility bar in later
  months was the default's own (negative) P&L, as GRID.md specifies. 338–343 of 360 variants were eligible each
  month, so the bar did not bind.
* The frozen v3 sits at the edge of the grid in X (2c is the largest value offered). The v2 sweep, which uses the
  realised new mid as its limit and is not ex-ante, makes more in IS ($89/day). Wider ex-ante limits were not tested
  because they were not pre-registered.

---

# Blind tests (a) burned OOS and (b) U2: implementation notes, logged before the runs

> **COUNTERFACTUAL WITH ASSUMED DATA.** Assumed: licensed live feed + courtside camera, not purchased;
> parameters from our measurements. No live ATP/WTA point feed was used.

Written 2026-10-03 after the freeze commit `ba0c3d4` and **before** any burned-OOS or U2 table was read for v3. At
this point all 16 pinned SHA-256 hashes in PREREG.md match the files on disk. The U2 catalogue metadata reproduces
PREREG §4 exactly (10,952 one-second-delay markets: 7,388 before the split and 3,564 after; 8,248 unmapped regions;
gender labels 2,275 women / 2,671 men / 6,006 unlabelled). Code: `scripts/tier0_v3_blind.py`. None of the notes
below changes the rule, the base scenario, the seeds, the inputs or the pass rule.

## D4. Output names (bookkeeping)

PREREG §7 names `results/tier0_v3/{burned_oos,u2}/results.json` and `research/v2/tier0_v3/TEST_RESULTS.md`. The
task that runs the tests also asks for `results/tier0_v3/blind.json` (both test sets),
`results/tier0_v3/equity_is_oos_u2.png` and a blind-test section in `research/v2/tier0_v3/RESULTS.md`. All of
these are written. They hold the same numbers.

## D5. How the U2 tables are built (reading of PREREG §4, chosen before the run)

* **Rows.** The jump table of each period is built from the U2 rows with `delay == 1` only, because §4 restricts
  the universe to the tier-0 regime. Rows are numbered within the period, so the draws of a period have one entry
  per jump of that period.
* **Tournament codes.** `T.tournament_codes` runs over all 11,307 U2 rows, both periods and all delays. That is
  how U1 (`universe()`) and the forward script (the window) are coded. n_tour is the U2 maximum + 1.
* **Coverage.** The coverage table M is the 10,952 one-second-delay U2 markets of both periods with their pre-start
  volumes. U1 never enters it.
* **Pre-start volume.** `tier0_v3_forward.prestart_usd` (unchanged) reads each market's cached raw tape in
  `data/raw/trades`. All 11,307 U2 tapes are present (`data/expand_fetch.log`). The work is split over 3
  processes, which changes nothing in the result.
* **Prints.** In-play prints are `data/expand_prints.parquet` (`cond, ts, p, usd`), passed to the pinned
  `tier0_v3_forward.jump_table`. A market with no in-play prints has no jumps.
* **Gender rule.** `tier0_v3_forward.jump_table` sets `men` from the series. That column is then overwritten with
  the §4 rule: women if the series is `wta` or the league, or the title text before its first ':', matches
  `\bwomen\b` or `\bW\d{2,3}\b` (case-insensitive); everyone else gets the men's mix. Matching on the league
  alone, on league + title prefix, or on league + full title gives the same counts (2,275 / 2,671 / 6,006).

## D6. Order and logging (stricter than §7)

* **Burned OOS.** The START line is written to `results/oos_peeks.log` before the reproduction gate, because the
  gate also reads the OOS tables. §7 only requires it before frozen v3 runs.
* **U2.** The builder check (U1 IS, 2026-08-10 → 08-13) runs before the U2 START line. The START line is written
  before any U2 print or tape is read.
* **Builder-check inputs.** The check reads its prints from `data/is_prints.parquet`, because the U2 path reads
  prints from a prints parquet rather than from raw tapes. It compares every column with
  `data/derived/tier0_jumps_is.parquet` / `tier0_post30_is.parquet`, the pre-start volumes and the coverage set.
  It also reproduces the IS frozen-v3 trades row for row at seeds 0 and 7.

## D7. Pass-rule details (as written; stated here so they cannot move)

* **Inputs to the rule.** It uses the 20-seed mean per-share net and the seed-averaged lower bounds of the
  match-clustered and day-clustered 95 % CIs.
* **Missing CI.** A seed with fewer than 2 trade days has no day CI (NaN). It is left out of the seed average.
  If every seed lacks it, the condition fails.
* **Underpowered.** A period is labelled underpowered if the 20-seed mean of covered matches with trades is
  below 30, or the mean of trade days is below 20. The label is reported and never changes a verdict.
* **Burned OOS.** The same reading applies and is labelled non-blind.
* **Gate tolerance.** The reproduction gate compares the 20-seed V2_HEADLINE metrics with
  `results/tier0/results.json → headline.burned_OOS` (mean and SD of per-share and $/day, CI bounds, trades,
  Sharpe) to within 0.05 % relative. It also requires `T.simulate(CORRECTED)` to match row for row at seeds
  1000 and 1007.

## D8. Where the runs execute

Every (configuration, scenario, seed) job runs locally, with at most 3 processes. There are 50 per test set: frozen
v3 over the 48-scenario bracket, the D2 stress and the v2 reference, each × 20 seeds. HiPerGator is used only if
local time is excessive. In that case a check job (frozen v3 primary at the set's first seed) runs both locally and
remotely, the two must agree exactly, and this file records the result before remote output is used.

## D9. After the runs: bookkeeping only (no new simulation, no change to any number)

* **Second log line.** The collect step (`--collect`) was run twice from the same saved runs. The second run only
  fixed a pandas warning in the figure code. As a result `results/oos_peeks.log` holds two "tier0 v3 blind tests
  (a)+(b) DONE" lines (20:28:47 and 20:29:22 UTC) with identical verdicts. A later collect now writes
  "RE-COLLECT" instead.
* **Figure redraw.** The figure was redrawn from the saved daily CSVs to fix label placement and the
  negative-dollar format.
* **Added description.** The fill-size check in TEST_RESULTS.md (mean and median shares of correct against wrong
  fills) was computed afterwards from the saved trades. It is descriptive and changes no verdict.
* **No HiPerGator.** Every run was local: 3 processes, about 1 minute per test set, so HiPerGator was not used
  (D8).
