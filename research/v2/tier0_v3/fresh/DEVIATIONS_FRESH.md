# Fresh holdout: deviations and additions

> **COUNTERFACTUAL WITH ASSUMED DATA.** Real prices, fills, results, fees and venue delays; simulated camera/CV calls
> at an assumed licensed-feed delay V. No feed bought, no video watched, no orders placed.

Pre-registration: `PREREG_FRESH.md`, commit `dc95717` (2026-10-04 05:34:34 UTC).

## Departures from the pre-registration

None. The window, exclusions, universe rule, strategies, parameters, V grid, readings, seeds, coverage rules,
metrics, showcase rule and gates ran as written. Both gates passed before the fresh window was read
(`results/fresh_holdout/equivalence_check.json`).

## Additions after the first run (descriptive; no reported number changes)

* **A1. All-seed showcase trades.** The pre-registered ledger seed (4000) has no filled trade on the showcase match in
  any of the four V = 0.5 s cells (every call reaches the book after the modelled reprice, or the wrong calls find no
  depth). `results/fresh_holdout/showcase_trades_all_seeds.csv` lists every filled trade on that match for all 20
  seeds of the same four cells, so the trades behind the 20-seed mean are visible. The ledger at seed 4000 is kept
  as pre-registered.
* **A2. Matches left out as unresolved.** A catalogue-only Gamma query (no tape, no price) counts the matches that had
  started in the window but were not closed at the fetch time: 6 (4 ATP, 2 WTA; `data/fresh/unresolved_check.json`,
  copied into `results.json`). They are out under the pre-registered rule and stay out.
* **A3. Sharpe display.** The 2-day window makes the daily Sharpe meaningless (the SD of two daily P&Ls), as
  PREREG §3 anticipated. The raw value stays in `results.json → cells`; the summary table shows
  "not meaningful (2 days < 10)" in `sharpe_display`.
* **A4. Re-run.** `--run` was re-run once on the same cached data and seeds to write A1-A3 (logged as RE-RUN in
  `results/oos_peeks.log`). The simulation is deterministic, and every cell matches the first run.
