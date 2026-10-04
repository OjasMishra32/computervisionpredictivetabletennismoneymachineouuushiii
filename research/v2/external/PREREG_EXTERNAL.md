# X1: predeclared out-of-universe validation of the frozen corrected v2 copier

Written 2026-10-04 10:25 UTC on top of commit 0d04048 (main), which contains the corrected copier:
844a978 (strict executable timing and the executable copier) and a63ec74 (rejection of copier fills after the
recorded tape ends), merged in 8891248. This file and its runner `research/v2/external/x1_test.py` are
committed together before any X1 trade tape is fetched. This is a prospective check of a policy that was
designed after exploratory and OOS (non-blind) analysis. It is NOT the organizer's out-of-sample test of the
declared universe (latest 20% by time of the ATP/WTA/Challenger >= $5k history: from 2026-07-23 06:08 UTC,
72.043 days, 4,386 matches, all previously read) and is not presented as one.

## What has been looked at

Only catalogue metadata of X1 (cond, tokens, slug, title, series, league, start_time, finished/closed_time,
volume, seconds_delay, fee_rate, event_id, game_id, tick) from
`data/raw/events_tennis_2025-07-01_2026-10-03.parquet`
(sha256 03986becf3cfd0ce22ed8e65c0dd9bbd0a684f621e744d53aa742eebd534cfd5). No X1 trade, print, book, price
history, score or resolution has been fetched or read. On 2026-10-04 an ID scan of 36,706 repo files, and an
independent scan of 36,796 working-tree files plus `git grep` over all 13 branch tips, found X1 ids only in the
catalogue. The HiPerGator copy was not inspected; no repo code path on any branch fetches series other than
atp/wta/challenger (or itf without doubles) before 2026-10-03, so none could have fetched X1 tapes there.

The runner was exercised once with `--selftest` before this commit: it runs the evaluation code on U1
in-sample prints only (stand-in window: U1 in-sample matches starting on or after 2026-07-18 18:00 UTC) and
reads no X1 tape, no X1 resolution and no held-out file. Its output is a plumbing check and chose nothing.

## Policy under test (frozen)

src.v2 at commit 0d04048: POLICY G_50pct_net100 (risk-parity sizing, 50% deploy fraction, 0.05-0.95 price
zone, wallet filter, net cap 100, 4 h ex-ante capital lock) with the corrected copier timing and every risk
control that `research/v2/sizing/engine.py` executes at that commit. The copier acts only on prints known to
come after the print that fired the detector: tapes carry no within-second order, so the trigger print, the
prints before it and the rest of its second are excluded. It learns of the fast print at its block time,
sends a taker order over the network leg, waits the taker hold and meets the book a block lag later. No
parameter, threshold, zone, cap, latency, sizing or wallet-rule change is made for X1. Exactly:

```
P = add_causal_bucket(P); P = v2.strict_causal_bucket(P)          # order_col=None
tr, wf = v2.run(P, ends, causal=True, strict=True)
A = tr[(tr.month >= v2.E.EVAL_START) & tr.cond.isin(X1_window)]
A = A.join(v2.copier_reprice(A, uX1.set_index("cond"), lat))
m = v2.table1_metrics(v2.copier_book(A, "central"))               # PASS iff m["c_share_ci95"][0] > 0
```

`lat` comes from `results/decay/decay.json::latency_inputs` (file sha256
10cc6dfa3fae43c4e7007341b6dfb4253a02d6b53cfef3a42b3275885d4e4078): block lag median 1.976 s, p90 2.974 s
(n = 5,472), network leg 0.067 s. `uX1` is the X1 window rows prepared as in `src.tape.universe()`
(`universe()` itself drops the doubles and Davis Cup series, so it cannot be used for X1 conds).

File sha256 at 0d04048 (the runner checks that these files are unmodified before it runs and records them):

| File | sha256 |
|---|---|
| src/v2.py | 1c06b18ee52bf6513d20ff767c1f6fc5b646c704a84608629b5bf8ef55eafc21 |
| src/tiers.py | 46a79d75409fd416fdfc2e026c25f02d9ebb3a188a9de1a6ac353561f656363e |
| src/tape.py | 4627f5a8d13ec8d0f51acb0f77ecc0a0651d95cfe18eb10f7af0c8f1a9a3cb77 |
| src/polymarket.py | f42bb0d84b4d69aa3c16949d5a1093c6a32f5616b14d939fe9201a92e2a09ab3 |
| src/fasttier.py | ea78b353af95d7bd929a6b7220fa715ef4b4ccd14674b3086330a0dbc969162d |
| research/v2/sizing/engine.py | 1b512aeacb32d96b8682f093421c002e91797b7a4321a4a844e83ef347d9395c |
| results/decay/decay.json | 10cc6dfa3fae43c4e7007341b6dfb4253a02d6b53cfef3a42b3275885d4e4078 |
| research/v2/external/x1_test.py | bee9664031d9ef1d3cd1f79864f1803677b99900b8f1186dc671a9e922864ff8 |

## Universe X1 (provenance only; no series choice, no return information)

Every catalogue row with: (1) cond not among the 28,075 files in `data/raw/trades/` before the X1 fetch
(sorted-list sha256 4b12de915631b8ed4aa4b5b96fd8e4f3e8c3df3f72479bf74f3f5d6d67274ada); (2) cond not in
`results/universe_conds.txt.gz` (U1) and not in `data/expand_universe.parquet` (U2); (3) volume >= 5,000
(`src/tape.py` MIN_VOL); (4) start_time present, parsed with
`pd.to_datetime(start_time, utc=True, format="ISO8601")`. Every list hash in this file is the sha256 of
`"\n".join(sorted(ids))` with no trailing newline.

X1 history: 767 markets, first start 2025-09-19 06:00 UTC, last start 2026-10-02 09:00 UTC, 378.125 days.
Test window: the latest 20% of X1 history by time, start >= 2026-07-18 18:00 UTC: 108 markets
(51 atp-doubles, 39 wta-doubles, 18 daviscup-games), 43 start days, all 1 s delay / 5% fee.
Sorted window cond-list sha256: 2eceed5ee9f9d6826022928059f2b1b155456826ac277ba777a76c3bdd2f021e.
The 659 earlier X1 markets are not fetched and not used.

Window choice, fixed here on availability only: the window start is set by the full X1 history, whose
earliest rows are the unlabelled 2025 markets that the frozen copier cannot trade (it makes no trades
before 2026-01). Without them the window would be 57 markets from 2026-09-04 04:12 UTC. The rule above
(all 767, no series or period choice) is the one fixed in the feasibility plan before any fetch; it gives
the larger window, and that is disclosed. It will not be revisited after the evaluation.

Domain: 90 of the 108 window markets are doubles. The copier's declared domain is ATP/WTA singles
(`HYPOTHESIS_V2.md`), and U2 excluded doubles by rule. The 18 Davis Cup markets are singles. X1 therefore
tests a transfer of the policy to doubles as much as a new sample.

## Data build (once)

Fetch the 108 window tapes with `src.polymarket.fetch_many_trades(conds, workers=4)` (public read-only
data-api, at most 4 concurrent requests; the U1/U2 fetcher, including its 10,500-fill offset cap), with
`src.polymarket.RAW` pointed at `data/external_x1/raw`, so the pinned snapshot directory `data/raw/trades`
is unchanged. Build prints with `src.tiers.match_prints(row)`, rows prepared as in `src.tape.universe()`:
end = finished.fillna(closed_time); fee_rate.fillna(0); delay = seconds_delay.fillna(1). The build writes the
per-print markout columns that `match_prints` always produces, as in U1/U2; no summary or strategy statistic
is computed or viewed before the single run. res0 is read only in the build, after this commit. Markets whose
fetch fails, whose tape is empty or has < 20 in-play prints, or whose resolution is not in {0, 0.5, 1} are
dropped by these rules and counted. The sha256 of every tape and of the prints file is recorded; tapes with
>= 10,000 rows are counted as possibly truncated by the offset cap.

## Test (one script, one run, output logged)

P = concat(`data/is_prints.parquet`, `data/locked/oos_prints.parquet`, X1 prints); ends = U1 ends
(`src.tape.universe()`) and X1 ends by cond. Reading `data/locked/oos_prints.parquet` is a read of the U1
OOS period (already evaluated, non-blind); it is logged in `results/oos_peeks.log` as input to X1 wallet
qualification only. The same run regenerates U1 trades; they are not inspected, stored or reported. In each
month m, wallets are qualified only from prints of months < m. Only trades in X1 window markets, months >=
2026-02, are evaluated.

Primary: the X1 central copier book's net per-share P&L held to resolution (`c_share` with `c_share_ci95`;
share-weighted; match-clustered bootstrap, 1,000 draws, seed 0, as in `engine.metrics`); capital is 3 x the
X1 central book's own peak locked capital, with the 4 h ex-ante lock. PASS only if the 95% CI lower bound
> 0; otherwise FAIL, including when the central book has no trades.

Underpowered: fewer than 30 X1 matches with central copier trades, or fewer than 20 trade days. This label
is reported alongside the verdict and never changes it. 108 is an upper bound on the sample; the strict
labels and the drop rules will reduce it, and the result may well carry this label.

Secondary (reported, not tested): $ net P&L and CI, trades, matches with trades, trade days, daily Sharpe
(calendar days between the first and last trade day zero-filled, x sqrt(365)), max drawdown in $ and %,
worst day; the central book with +0.5c and +1c per share entry slippage; doubles vs Davis Cup split; the
harsh rule (p90 block lag); the optimistic rule, labelled an upper bound; the strict book at the fast
wallets' own fills, labelled an observational event study; for each copier rule `n_attempted_trades`,
`n_unsupported_fills`, `share_beyond_tape_end` and `share_same_side_print`.

Provenance (not a return): the share of X1 in-play prints, and of copier trigger prints, whose wallet
appears in P in a month before that market's month.

## Rules

Evaluated once; the runner refuses to overwrite `results/external_validation/results.json`. A rerun is
logged as a reproduction only and written to a separate file. Any deviation (data problem, bug, changed
definition) is written to `research/v2/external/DEVIATIONS.md` before any rerun. Any policy change made after
X1 output is seen makes X1 in-sample for the changed policy, and that result is exploratory. The result is
reported whatever it is, next to the U2 blind results (E15 v2, E18 v2-safe: FAIL, run before the timing
correction) and the corrected copier's non-blind OOS result.

The causal camera policy is not tested on X1. Its simulator uses synthetic point times, a coin-flip point
winner and the frozen classifier's measured call statistics, so its edge is an input: new tapes can test
costs, liquidity and outcome noise, not whether the signal exists on new matches. It also codes every
non-atp/challenger series as women's tennis, which would mis-assign all 108 window markets, and doubles
scoring differs from singles; correcting either would be a post-hoc policy change.

## Caveat (to be reproduced verbatim with any X1 number)

X1 is a prospective, predeclared out-of-universe check of a policy designed after exploratory analysis. Its
markets were never fetched before this test, but they trade in the same weeks (2026-07-18 to 10-02) as U1
data used for design (to 2026-08-25) or inspected as OOS (from 2026-08-25), and probably involve the same
wallets. 90 of its 108 markets are doubles, outside the copier's declared singles domain. X1 is not the
organizer's latest-20%-by-time out-of-sample test of the declared universe. It does not change the status
of any past exploratory, adaptive or OOS result, does not overturn the earlier U2 failure, and does not
imply any organizer waiver. The camera policy is not tested on X1, because its simulated edge is an input
rather than something new tapes can measure.
