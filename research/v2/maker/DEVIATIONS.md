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

---

# After the run

## R1. Post-run audit of (A): wording corrections, no number or verdict changed (2026-10-03, about 20:55 UTC)
An independent recompute (`audit/indep_maker_oos.py`, peeks log 20:11 UTC) matched every fill. Its findings
changed the RESULTS.md text only. **No OOS number was recomputed or replaced. The primary stays +1.87c/share
[−0.14, +3.86], 2,207 fills, 524 matches: FAILURE.** The script was not re-run, and `oos_test.py run` was not
invoked.

| item | before | after |
|---|---|---|
| Verdict wording | "FAILURE. The CI's lower bound is below 0" | FAILURE, **borderline: z about 1.9, two-sided p about 0.06**. Audit: cluster-robust SE 1.00c, t-CI [−0.09, +3.82]; lower bound over 200 seeds −0.07c (sd 0.06), above 0 in 8.5% of seeds; day clusters [+0.10, +3.86]; side-market clusters [−0.04, +3.68]. Seed 0 and match clusters were pre-registered in `c29734b` and govern |
| Power caveat | "This explains the result" | "This is consistent with the result" |
| Placebo | "The signal still points the right way OOS" | "OOS, the lean book and the anti-lean placebo cannot be told apart (gap +1.15c [−1.42, +4.00])". Paired match-clustered bootstrap, P(gap ≤ 0) = 0.19; the IS gap of 3.31c is at the OOS bootstrap's 94th percentile |
| Cost label | "Cost-fragile. Stress (iv) −4.15c ≤ 0, on only 98 fills" | Cost-fragile, with (iv)'s CI [−13.45, +5.54] and n = 98 printed next to it. Also notes that IS already had (iv) at about 0: +0.10c on 513 fills (all regimes) and −1.76c on 156 fills (IS 1s/5%) |
| Stress table, IS column | IS Feb–Aug, all regimes only (book 1 +3.06c): a cell chosen in hindsight, about 1c high against the OOS regime | Adds an **IS 1s/5%** column, the OOS regime: book 1 +2.02 [+0.53, +3.48]; (i) +2.02; (ii) −1.61 [−8.36, +6.21], n = 156; (iii) +1.86 [+0.37, +3.33]; (iv) −1.76 [−8.51, +6.05], n = 156; (viii) −0.07 [−1.56, +1.40]. IS data only (`is_1s5_stress.py` → `is_reference_1s5.json`, run 20:50 UTC). It reproduces the IS 1s/5% book-1 figure (n = 4,159, +$3,269) and both diagnostics (−0.12c, −1.29c) exactly. The old column is kept and relabelled |
| Timing caveat | (absent) | Added. data-api block-time jitter, about 2.3 s, can let a later moneyline print into the cut ts − 1 s. Labelled post-hoc stricter cuts (audit): +1 s gives +1.67c (−$989), +2 s gives +1.61c (−$1,220), +5 s gives +1.02c (−$734). The edge fades gradually with no cliff, and any optimism is at most about 0.2–0.26c. It could only lower the estimate |

Original and corrected numbers: the OOS numbers are identical before and after. The only new numbers are the IS
1s/5% column and the audit's labelled post-hoc figures quoted above.

## R2. Live session (B): code fixes, stop and restart (2026-10-03 20:48 UTC)
The full timed record is in `DEVIATIONS_LIVE.md` L11–L14. In short:
- **The fixes.**
  - Discovery read only the first 100 of about 455 open tennis events, because Gamma caps pages at 100.
  - The CTRL-taker timer priced orders on a stale book under feed lag. On the hour-13 replay, oids 2892 and 3029
    filled at 0.7852 and 0.7534; on the venue book at t_exec they fill at 0.7223 and 0.6355.
  - Socket gaps left orders live on an unobserved queue. Quotes are now pulled at the gap and taker orders voided,
    and feed lag is recorded.
- **Stopped.** PID 65274 (run `20261003T193534Z`) at 20:48:00.72 UTC, with 0 quotes, 0 fills and 0 taker orders
  in every book. Its logs are kept.
- **Code.** `2c63112`.
- **Restarted.** At 20:48:12 UTC with the same command: PID 2001, run `20261003T204812Z`. The warm-up runs again,
  and quoting still stops at 2026-10-04 11:30 UTC.
