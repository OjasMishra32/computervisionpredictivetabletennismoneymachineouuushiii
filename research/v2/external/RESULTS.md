# X1 result: frozen corrected v2 copier on never-fetched markets outside the declared universe

Pre-registration `research/v2/external/PREREG_EXTERNAL.md` (163195b, 10:26:04 UTC), deviation D1
(`DEVIATIONS.md`, 5286181), single evaluation 10:27:33-10:30:15 UTC on 2026-10-04 at 5286181.
Output: `results/external_validation/results.json`; console output: `RUN_OUTPUT.txt`.

**Verdict: FAIL (the 95% CI includes zero), underpowered** (11 matches with copier trades < 30; 9 trade days < 20).

| Central copier (pre-registered primary) | Value |
|---|---|
| Net P&L per share, held to resolution | +8.80c, 95% CI [-34.41, +50.33] (match-clustered bootstrap, 1,000 draws, seed 0) |
| Trades / matches / trade days | 21 / 11 / 9 |
| Net P&L | +$49.92, 95% CI [-$178.26, +$287.94], on $196 traded; capital $343 (3 x peak locked $114) |
| Rejected fills beyond the tape | 0 of 21 attempted |

Sample: 108 window markets fetched; 20 had an empty tape or < 20 in-play prints and 5 raised in the print
build (dropped as in the U1/U2 builders); 83 kept (resolutions 35 at 0, 8 at 0.5, 40 at 1); 10,200 in-play
prints. The copier traded in 11 of them (10 doubles, 1 Davis Cup).

Secondary (not tested): harsh rule +8.98c [-34.26, +50.68]; optimistic upper bound +12.04c [-29.16, +53.85];
central +0.5c slippage +8.30c, +1c slippage +7.80c; doubles 20 trades +9.20c [-35.43, +52.43], Davis Cup
1 trade -6.18c; strict book at the fast wallets' own fills (observational) +12.32c [-28.47, +54.15]. Daily
Sharpe 1.54 and max drawdown -$22.72 (-6.6% of capital) are reported in the JSON; with 9 trade days they carry
no weight. Provenance: 78.5% of X1 in-play prints and all 21 copier trigger prints come from wallets already
seen in the prints of earlier months.

Read next to: the U2 blind results (E15 v2, E18 v2-safe: FAIL, run before the timing correction) and the
corrected copier's non-blind OOS result (results/v2/strict_causal.json, central -1.02c [-3.00, +0.84]).

## Caveat (verbatim from the pre-registration)

X1 is a prospective, predeclared out-of-universe check of a policy designed after exploratory analysis. Its
markets were never fetched before this test, but they trade in the same weeks (2026-07-18 to 10-02) as U1
data used for design (to 2026-08-25) or inspected as OOS (from 2026-08-25), and probably involve the same
wallets. 90 of its 108 markets are doubles, outside the copier's declared singles domain. X1 is not the
organizer's latest-20%-by-time out-of-sample test of the declared universe. It does not change the status
of any past exploratory, adaptive or OOS result, does not overturn the earlier U2 failure, and does not
imply any organizer waiver. The camera policy is not tested on X1, because its simulated edge is an input
rather than something new tapes can measure.
