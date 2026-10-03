# v2-safe: results of the pre-registered tests

The tests below follow `PREREG.md` as committed in 342d515 (2026-10-03 17:30:44 UTC). The run
started at 17:36:52 UTC on that same HEAD, using `scripts/lowloss_test.py`, and took 56 s in a
single process. Raw numbers are in `results/lowloss/results.json` and `results/lowloss/daily.csv`;
the figure is `results/lowloss/daily_pnl.png`. No orders were placed.

## Verdict
- **(b) U2, the blind primary test, is a FAIL.**
  - U2-IS passes: P1 lower bound +1.37¢, P2 lower bound 56.8%.
  - U2-OOS fails both checks. P1: the per-share CI is [−0.02, +2.43]¢. P2: v2-safe made money on
    24 of 40 days (60.0%), with a Wilson lower bound of 44.6%.
  - Under the PREREG rule, that is a FAILURE of v2-safe's out-of-universe claim for the OOS period.
    Neither period is underpowered.
- **(a) Burned OOS (non-blind):** v2-safe made money on 27 of 40 days (67.5%), against 24 of 40
  (60.0%) for v2. Its worst day was −$224 against −$469. It would pass P1 and P2 here, but this
  data was not blind, so that pass is for information only.
- **v2-safe does what GRID.md predicted.** On every book it roughly halves the worst day and the
  max drawdown, and it keeps 59–70% of v2's dollars. It does not reliably make losing days rarer.
  The paired change in the share of profitable days runs from −2.5 to +7.5 pp across books, and no
  confidence interval excludes zero. On the unseen U2-OOS matches the change is exactly 0.
- **v2-safe does not reach the goal of barely losing.** Out of sample, 30–40% of days still lose
  money.

## Checks before any statistic
- **v2 reproduces exactly in both joint runs.** The v2 trades from each run are identical, row for
  row, to the canonical `src.v2.run()` output:
  - (a) `data/v2_trades_is_oos.parquet`: 69,264 trades, $45,541.98.
  - (b) `data/expand_v2_trades.parquet`, written by the U2 expand test: 86,123 trades, $54,189.83.

  So building the features once and simulating both policies on them is the same as calling
  `v2.run` with `POLICY` swapped.
- **The rule matches the freeze.** v2-safe is `replace(src.v2.POLICY, name="v2_safe_n50",
  net_cap=50)`; the script asserts every other field equals v2's.
- **IS reproduces PREREG.** In run (a), the U1-IS book reproduces the PREREG IS table:
  - v2: 79.6% / 82.4% profitable days, −$551 worst day, $40,426.
  - v2-safe: 81.6% / 84.4%, −$284, $23,864.
- **One deviation (D1 in `DEVIATIONS.md`).** Six U2 ITF matches started on 25 Aug before the
  cutoff and were finished on 26 Aug. Their trades stay in U2-IS, so the U2-IS and Combined-IS
  calendars run to 26 Aug. The verdict is the same without them.

## (a) Burned OOS, NON-BLIND
Data: U1 prints, IS + OOS, in one joint walk-forward run. The book is the U1 matches starting on or
after 2026-08-25 14:15 UTC. The calendar is 2026-08-25 to 2026-10-03: 40 days, every one of them
active. v2's loss profile on this data was known before the grid was designed.

| | v2 | v2-safe |
|---|---|---|
| profitable days, calendar / active | 60.0% / 60.0% (24 of 40) | **67.5% / 67.5%** (27 of 40) |
| losing days | 40.0% | 32.5% |
| worst day | −$469 (7 Sep) | **−$224** (7 Sep) |
| worst month | −$434 (Oct, 3 days) | −$187 (Oct, 3 days) |
| max drawdown, $ and % of 3 × peak locked | −$469 (2.06% of $22,754) | −$253 (1.86% of $13,584) |
| Sharpe / Sortino (daily, ×√365) | 6.7 / 14.0 | 9.3 / 22.0 |
| $ P&L [match-clustered 95% CI] | $3,688 [$540, $6,890] | $2,533 [$904, $4,221] |
| per-share net [95% CI] | 0.60¢ [0.09, 1.13] | 0.69¢ [0.24, 1.15] |
| per-share at +½ tick / +1 tick | 0.10¢ / −0.40¢ | 0.19¢ / −0.31¢ |
| profitable matches | 55.6% of 2,003 | 56.2% of 2,003 |
| worst match | −$154 | −$77 |
| trades | 10,412 | 9,487 |
| P1 / P2 (information only) | P1 pass (CI lower bound 0.09¢); P2 fail (Wilson lower bound 44.6%) | P1 pass (0.24¢); P2 pass (52.0%) |

Paired comparison, v2-safe minus v2, on the same 40 days:
- **Profitable-day share:** +7.5 pp, day-bootstrap 95% CI [−5.0, +20.0].
- **Days that flipped:** on 5 days v2-safe made money while v2 lost; on 2 days the reverse.
- **Dollars:** v2-safe made 0.69× v2's P&L.

## (b) U2 unseen matches, BLIND (primary)
Data: one joint walk-forward run over U1 ∪ U2 prints (is + oos + expand, 10.53M prints, no dedup),
with ends from U1 and U2. The books are U2 matches only, split by match start at 2026-08-25 14:15
UTC.
- **Composition:** v2-safe traded 3,244 U2-IS matches (3,225 ITF, 19 ATP) and 1,549 U2-OOS matches
  (1,544 ITF, 5 ATP).
- **Gaps in U2-IS:** there are no U2 trades in March or April, and only a handful in February. U2-IS
  therefore has 104 active days out of 207 calendar days, which is why P2 uses active days.

### Primary
| | P1: per-share net, 95% CI lower bound > 0 | P2: Wilson 95% lower bound of profitable active-day share > 50% | result |
|---|---|---|---|
| U2-IS | +2.11¢ [**+1.37**, +2.88] → pass | 69 of 104 = 66.3%, lower bound **56.8%** → pass | PASS |
| U2-OOS | +1.21¢ [**−0.02**, +2.43] → fail | 24 of 40 = 60.0%, lower bound **44.6%** → fail | **FAILURE** |

**Verdict: FAIL.** The out-of-universe claim fails in the OOS period, with 1,549 matches and 40
active days, so the result is not underpowered.

### All metrics, U2
| | U2-IS v2 | U2-IS v2-safe | U2-OOS v2 | U2-OOS v2-safe |
|---|---|---|---|---|
| calendar | 2026-02-01 to 08-26 (207 d) | same | 2026-08-25 to 10-03 (40 d) | same |
| profitable days, calendar / active | 32.4% / 64.4% | 33.3% / 66.3% | 60.0% / 60.0% | 60.0% / 60.0% |
| active days, profitable / total | 67 / 104 | 69 / 104 | 24 / 40 | 24 / 40 |
| worst day | −$352 (19 Aug) | −$209 (19 Aug) | −$333 (1 Oct) | −$225 (1 Oct) |
| worst month | −$15 (Feb) | −$16 (Feb) | −$354 (Oct, 3 days) | −$209 (Oct, 3 days) |
| months positive | 4 of 7 (Mar, Apr: no trades) | 4 of 7 | 2 of 3 | 2 of 3 |
| max drawdown, $ and % of capital | −$664 (5.7%) | −$384 (5.8%) | −$805 (10.8%) | −$403 (8.9%) |
| Sharpe / Sortino | 5.1 / 12.2 | 6.0 / 16.4 | 5.3 / 11.3 | 5.5 / 13.0 |
| $ P&L [95% CI] | $7,437 [4,104, 10,678] | $5,091 [3,328, 6,900] | $2,117 [−320, 4,599] | $1,341 [−27, 2,672] |
| per-share net [95% CI] | 2.02¢ [1.14, 2.93] | 2.11¢ [1.37, 2.88] | 1.22¢ [−0.19, 2.65] | 1.21¢ [−0.02, 2.43] |
| +½ tick / +1 tick | 1.53¢ / 1.03¢ | 1.61¢ / 1.11¢ | 0.72¢ / 0.22¢ | 0.71¢ / 0.21¢ |
| profitable matches | 56.1% of 3,244 | 56.5% of 3,244 | 54.4% of 1,549 | 54.6% of 1,549 |
| worst match | −$130 | −$65 | −$142 | −$66 |
| trades | 10,764 | 10,115 | 4,616 | 4,196 |
| capital (3 × peak locked) | $11,692 | $6,578 | $7,432 | $4,524 |

Paired comparison, v2-safe minus v2, on the same U2 days:
- **U2-IS, profitable-day share:** +1.9 pp, CI [−3.8, +7.7]. The P&L ratio is 0.68, the worst day
  went from −$352 to −$209, and max drawdown from −$664 to −$384.
- **U2-OOS, profitable-day share:** 0.0 pp, CI [−12.5, +12.5]. On 3 days v2-safe made money while
  v2 lost, and on 3 days the reverse. The P&L ratio is 0.63, the worst day went from −$333 to
  −$225, and max drawdown from −$805 to −$403.
- **Stitched IS level (81.9% of active days):** U2 does not reach it in either period (66.3% and
  60.0%).

### Combined books (U1 ∪ U2) from the same run
| | Combined-IS v2 | Combined-IS v2-safe | Combined-OOS v2 | Combined-OOS v2-safe |
|---|---|---|---|---|
| profitable days, calendar / active | 80.2% / 83.0% | 82.1% / 85.0% | 67.5% / 67.5% | 70.0% / 70.0% |
| worst day | −$508 | −$265 | −$573 | −$253 |
| worst month | +$2,543 (Mar) | +$1,499 (Mar) | −$670 (Oct, 3 days) | −$327 (Oct, 3 days) |
| max drawdown | −$559 (1.7%) | −$265 (1.3%) | −$721 (2.7%) | −$327 (2.1%) |
| Sharpe / Sortino | 15.1 / 52.7 | 16.5 / 67.3 | 7.3 / 16.4 | 9.3 / 25.7 |
| $ P&L | $47,157 | $28,747 | $5,506 | $3,718 |
| per-share net [95% CI] | 1.42¢ [1.21, 1.65] | 1.40¢ [1.22, 1.59] | 0.67¢ [0.18, 1.21] | 0.75¢ [0.31, 1.21] |
| +½ tick / +1 tick | 0.92¢ / 0.42¢ | 0.90¢ / 0.40¢ | 0.17¢ / −0.33¢ | 0.25¢ / −0.25¢ |
| profitable matches | 57.1% of 10,890 | 57.6% of 10,890 | 54.9% of 3,595 | 55.4% of 3,595 |

Context only: U1 matches from the joint U1 ∪ U2 run, where U2 prints also feed wallet
qualification.
- **OOS:** v2-safe made money on 65.0% of days against 67.5% for v2 (−2.5 pp, CI [−12.5, +7.5]).
  Its worst day was −$245 against −$513.
- **What this means for (a):** the +7.5 pp gain in (a) does not survive a change in the training
  wallets. It is noise around zero, not an effect.

## Across all books: what the net cap changes
| book | change in profitable-day share [95% CI] | worst day, v2 → v2-safe | max DD, v2 → v2-safe | $ kept |
|---|---|---|---|---|
| U1-IS (in-sample for the selection) | +2.0 pp [−1.5, +5.5] | −$551 → −$284 | −$569 → −$284 | 59% |
| U1 burned OOS (non-blind) | +7.5 pp [−5.0, +20.0] | −$469 → −$224 | −$469 → −$253 | 69% |
| U1-OOS in the U1 ∪ U2 run (context) | −2.5 pp [−12.5, +7.5] | −$513 → −$245 | −$654 → −$248 | 70% |
| U2-IS (blind) | +1.9 pp [−3.8, +7.7] | −$352 → −$209 | −$664 → −$384 | 68% |
| U2-OOS (blind) | 0.0 pp [−12.5, +12.5] | −$333 → −$225 | −$805 → −$403 | 63% |

Halving the per-match net cap cuts the size of the worst day by 32–52% and of the max drawdown by
42–62%, consistently. It does not change how often a day loses. The per-share edge is unchanged
(within ±0.1¢ of v2's in every book), as GRID.md expected.

## Why no cap gets to "barely lose" (back-of-envelope, not a tested claim)
A day loses when the sum of its matches' resolution outcomes is negative. Treat a day's matches as
independent and roughly equal-sized. Then the share of profitable days is about Φ(√N · s), where N
is the number of matches traded per active day and s is the per-match edge divided by its standard
deviation. Backing s out of the observed numbers:

| book | matches per active day | profitable active days | implied s per match |
|---|---|---|---|
| U1-IS, v2-safe | 38 | 84.4% | 0.16 |
| U1 burned OOS, v2-safe | 50 | 67.5% | 0.06 |
| U2-IS, v2-safe | 31 | 66.3% | 0.08 |
| U2-OOS, v2-safe | 39 | 60.0% | 0.04 |

What the numbers say:
- **The OOS edge is smaller.** Out of sample, s is a quarter to 40% of its IS value.
- **Caps cannot change s.** They scale a match's P&L up or down, but they do not change the ratio
  of edge to noise within the match.
- **"Barely lose" needs a much larger s or N.** For 95% profitable days you need √N · s ≈ 1.65.
  At s = 0.04 that means about 1,700 independent matches a day; at the IS value, 0.16, about 100.

So a "barely lose" book has to raise the edge per match: better entries, or getting out before
resolution. Or it has to trade many more independent matches per day. Shrinking exposure does not
get there.

Any such change is a new hypothesis. It needs its own pre-registration and fresh data. U2 and the
burned OOS are now in-sample for it.

## Not run here
Test (c), the forward window of HYPOTHESIS_V2.md (blind part: matches starting at or after
2026-10-03 18:00 UTC), is secondary and needs those matches to resolve. It is not part of this run.

## Files
- `scripts/lowloss_test.py`: the test.
  - `--figure-only` redraws the figure from the saved outputs.
  - `--rebuild` ignores the feature caches.
- `results/lowloss/results.json`: every metric for every book and both policies, including
  `engine.metrics` as-is, P1/P2, and the paired statistics.
- `results/lowloss/daily.csv`: zero-filled daily P&L per run, book and policy.
- `results/lowloss/daily_pnl.png`: daily P&L bars, v2 against v2-safe, for U1 (IS plus burned OOS)
  and U2, with the OOS period shaded.
- `results/lowloss/run.log`, `research/v2/lowloss/RUN_LOG`, and `results/oos_peeks.log`, which got
  one line each for (a) and (b).
- `data/v2_lowloss/{features,whist}_{u1,u1u2}.parquet`: feature caches.
- `data/v2_lowloss/trades_{a,b}_{v2,v2_safe}.parquet`: the trade books.
