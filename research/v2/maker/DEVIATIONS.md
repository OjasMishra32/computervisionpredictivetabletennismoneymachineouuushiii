# maker v1 (A): deviations and pre-run decisions

Written 2026-10-03 at about 18:45 UTC. At that point the catalogue had been fetched, the tapes were downloading,
and the IS parity check had passed. This file was written before the single OOS run (`oos_test.py run`). When it was
written, no OOS fill, P&L or markout had been computed or looked at. Nothing below was chosen from OOS results.

## D1. The conditional 8th variant is triggered (PREREG §2.9). How the fee is charged
**Metadata.**
- All 35,092 side markets in the OOS catalogue have Gamma `makerBaseFee = 1000` and `takerBaseFee = 1000`. That
  includes the 3,116 that pass the §2.1 selection.
- All of them also have `feeSchedule = {rate 0.05, rebateRate 0.15, takerOnly true}`.
- No market has `takerOnly` false.

**Trigger.** PREREG §2.9 adds a stress when `takerOnly` is false **or** `makerBaseFee > 0`. The `makerBaseFee`
condition alone is met. The 8th stress is therefore added, as pre-registered. The decision uses metadata only.

**How the fee is charged.** PREREG does not say, so it is fixed here before the run:
- The field is read as basis points and plugged into the venue's fee formula:
  maker fee per share = (`makerBaseFee` / 10,000) × px × (1 − px) = **0.10 × px(1 − px)**.
- That is at most 2.5c/share, at px = 50c.
- It is charged on every fill of book 1. Nothing else changes, and the rebate is kept.
- This is the harshest reading of the field: twice the taker rate.

**What the field probably means.** VENUE_RULES.md §2 notes that the docs compute fees from `feeSchedule`, and that
makers pay nothing when `takerOnly` is true. The 1000 bps fields are read there as legacy fields. Stress 8 is
therefore a conservative bound, not the expected cost.

**What it does not affect.** It plays no part in the §2.5 PASS/FAIL or in the §2.7 cost-robust / cost-fragile label.

**One derived number, not a variant.** The break-even maker fee rate on book 1: the rate r at which
mean(pnl_ps − r·px(1−px)) = 0.

## D2. How some under-specified details are read (no rule changed)
- **Trade-through (ii), age limit.** "At most 120 s old" is measured from the information cut t* = ts_j − d. That is
  the same cut the signal uses.
- **Trade-through (ii), price band.** The band 0.02 < L_j < 0.98 applies to the fill price L_j. It replaces the band on
  the print's own price.
- **Trade-through (ii), which prints.** Print j must be a contrary print in the same signal state as book 1: lean side,
  |impl| ≥ 4c.
- **Diagnostics (§2.8).** They are computed exactly as the quoted IS values were (`analyze.lean_diagnostics`):
  - per print, with no 20% / $250 / $2,000 sizing;
  - the mean is taken over prints, with a match-clustered CI.

  This keeps them comparable with IS 1s/5%: −0.12c for the unconditional maker and −1.29c for the anti-lean placebo.
- **Months positive per share.** A calendar month counts if its fill-weighted mean pnl_ps is > 0.
- **Max drawdown ($) and worst day ($).** Both come from the zero-filled daily series that `src.backtest.stats`
  uses, from the first fill date to the last.

## N1. Printing of the frozen b_T (no effect)
- In PREREG §1.3, `tennis_match_totals` = 1.8243248664803704.
- The walk-forward 2026-08 row in `beta_walkforward.csv` gives 1.8243248664803706.
- The two differ by 1 ulp (2.2e-16).
- The run uses the PREREG value, and the script asserts its sha256.
- The parity check compares the table with the re-computed row at a relative tolerance of 1e-12. Every other entry is
  bit-identical.

## N2. File locations
PREREG names these files:
- `research/v2/maker/oos_build.py`
- `research/v2/maker/oos_test.py`
- `data/v2_maker/oos/` for the data cache
- `research/v2/maker/oos/` for the outputs

The workflow that ran this test asked for four more:
- `scripts/maker_oos.py`, a one-command entry point that calls the two scripts;
- `results/maker/oos.json`, a copy of `research/v2/maker/oos/results.json`;
- `results/maker/equity_is_oos.png`;
- `data/v2_crossmarket_oos/`, a symlink to `data/v2_maker/oos/`.

None of this changes the test.

## N3. Extra checks run on IS only, before the OOS run
- **Build-code parity.** `oos_build.process` rebuilt 400 random IS events from the IS tapes. Every column it produces
  in the per-print and interval tables equals the IS tables exactly (22,866 prints, 18,137 intervals).
- **§2.3 parity.** n = 10,171 fills and $5,326.05, with relative error 0. The IS 1s/5% diagnostics were also reproduced
  exactly.
- **Code test of the full evaluation.** `oos_test.py istest` ran book 1, the stresses and the diagnostics on IS
  Feb–Aug.
  - The output is in `is_reference.json`.
  - RESULTS.md reports it as a labelled IS reference.
  - It was computed after the freeze and changes nothing.

## Re-run rule
- `oos_test.py run` refuses to run a second time.
- A re-run first needs an entry in this file giving its reason. It is then started with `--rerun "<reason>"` and logs
  its own peeks line.
- The first run's numbers are kept and reported next to any re-run.
