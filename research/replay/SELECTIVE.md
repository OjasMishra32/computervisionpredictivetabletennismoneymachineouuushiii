# Match replay, selective variant: trade only points with a large ex-ante swing

> **EXPLORATORY, added after seeing the all-points replay; not pre-registered; one day, 9 matches; backtest replay on real recorded book; assumed feed latency; paper only.**

**Status: declared, not yet run.** No result of this variant has been computed. This file is overwritten by
`scripts/match_replay_selective.py` when it runs; the declaration below is carried over verbatim (§ Declaration).

## Declaration (committed before the first run)

Declared in this file and in `scripts/match_replay_selective.py` (constants block) and committed before the
first run. The design was written after the all-points replay's P&L had been seen, so it is exploratory.

* **Filter.** Trade an official point only if its **ex-ante Markov swing** is ≥ T, **T ∈ {2c, 4c, 6c}**;
  **4c is the reference** (the latency sweep's ≥ 4c jump detector, `src/tier0.py` `JUMP_MIN`). Points below T
  are removed before the replay: no call, no order, no use of the net cap.
* **Swing.** |P(A wins the match | A wins the point) − P(A wins the match | B wins the point)| from
  `src/markov.py`, women's best of 3 with 7-point tiebreaks (`Format()`, as `engine/run.py`), computed through
  `engine/fair/value.py` `MatchFair`: the score before the point is rebuilt from the official winners of the
  match's earlier points; the server is not in the data, so the belief starts at 0.5 and is Bayes-updated
  after every point (`MatchFair.apply_point`); the serve/return point-win probabilities are refit
  (`MatchFair.recalibrate`, tour WTA) so that fair value at that score equals the outcome-0 mid at the
  **pre-point instant = the previous point's official stamp + 2 s** (first point of a match: its stamp − 30 s).
  A mid is usable if a book snapshot was seen, its spread is ≤ 10c (the engine's `max_spread`), the market had
  a message in the last 60 s and the instant is not inside a recorder outage; otherwise the match's last
  calibration is kept, and a point with no calibration yet is not eligible.
* **Everything else unchanged** from `scripts/match_replay.py` (imported, not copied): stamp lag **2.0 s
  primary, 3.0 s** also; **V ∈ {0, 0.5, 1.0} s**; model CV lead; Florida 67 ms; **20 seeds** (0-19; seed 0 is
  the shown replay and carries the CIs); net cap 100 shares per match; limit = stale (reference) ask + 1c;
  wrong calls 5 % (precision 0.95); 1 s taker delay; fee; +30 s mark; hold to result; outage rule D1.
* **Reported** per T × V × lag: points eligible, calls, fills, share of calls beating the book, net per share
  marked and held with the match-clustered 95 % CI, $ P&L marked and held, 20-seed mean ± SD, and as a
  diagnostic the realised book move (`m1_points.D`) of traded vs not-traded points. The all-points cells are
  reported alongside and must reproduce `results/replay/replay.json`.
