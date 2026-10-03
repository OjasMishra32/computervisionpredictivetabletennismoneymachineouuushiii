# COURTSIDE — pre-registered hypotheses

Written 2026-10-03 ~10:15 UTC, **before any backtest, event study or tracking result was computed.**
Only facts known at this point: Polymarket tennis moneylines exist with trade-level tapes; sports
markets carry `secondsDelay: 1` and a taker fee of `0.05 × p × (1−p)` per share (makers pay 0,
15% rebate); Polymarket table-tennis (Setka Cup) moneylines average ~$2 of volume per match.
Any change after this timestamp goes in `DEVIATIONS.md` with the reason.

## The economic story: who is on the other side?

A tennis point is resolved in tiers of knowledge:

| tier | who | knows the point is over at |
|---|---|---|
| 0 | ball tracking (Hawk-Eye class: 10+ cameras, ~340 fps) | while the ball is still in the air, from its trajectory |
| 1 | people in the stadium, chair umpire | the bounce / line call |
| 2 | official data feed (umpire tablet → data provider → market makers) | ~1–3 s later |
| 3 | TV | ~3–8 s later |
| 4 | streams, apps, the Polymarket score widget | ~10–40 s later |

Every tier trades against the tiers below it. In-play match-win probability is a known function of
the score (a Markov chain over points), so each point moves "fair value" by a computable amount:
the point's **leverage**. Slower tiers keep trading at prices that were right a few seconds ago.
The edge is the tier gap times the point's leverage. It exists because a stream delay is physical
and won't go away. Polymarket's 1-second taker delay shows the venue knows this.

## H1 — staircase repricing (tape test, historical, resolved matches)
After a large price move in the moneyline tape (a score event), the price **keeps drifting the
same way** over the next 10–120 s as slower tiers arrive.
- Signal: VWAP(p) over the last 10 s minus VWAP over the prior 60 s, |Δ| ≥ J. Primary J = 0.04.
- Trade: enter in the direction of the move at the first print ≥ 2 s after the signal (1 s venue
  delay + 1 s for us). Exit at the first print ≥ H s later. Primary H = 30 s.
- Costs: taker fee on both legs, plus half the median live spread (measured by the live recorder)
  on both legs.
- **Fails if** mean net P&L per trade ≤ 0 in sample, or the effect does not depend on |Δ|, or the
  sign flips (overreaction). If it flips, that is reported as the finding; we don't re-fit to it.

## H2 — late-match calibration (tape test, historical)
Live prices are mis-calibrated at the extremes. Retail "comeback" buyers overpay for the trailing
player (favorite–longshot bias), and capital lock-up keeps near-certain favorites below fair value.
- Test: reliability of in-play prints (first print in each 60 s bucket during the match) against
  the realized winner, clustered by match.
- Trade: buy the favorite when its price is in [0.85, 0.97] during play; hold to resolution. The fee
  is `0.05·p(1−p)`, tiny at these prices.
- **Fails if** realized win rate − price ≤ fee + spread in sample, or the edge comes from one
  tournament or one month.

## H3 — physics lead time (ball tracking, OpenTTGames 120 fps table tennis)
From the ball's tracked trajectory, whether the next contact is a **table bounce or a miss**
(out / net) can be called with ≥95% precision at least **50 ms** before the ball reaches the table
plane, and the lead grows with ball speed and with how far out the ball lands.
- **Fails if** precision at a 50 ms lead is < 95% on the held-out test videos (test_1…test_7).
- Tennis version: Monte Carlo of a ball with drag + Magnus lift and Hawk-Eye-class measurement
  noise (≈3 mm, 340 fps): the lead at which an "out" call beats 95% precision, as a function of how
  far out the ball lands.

## H4 — venue latency (live recording, 2026-10-03 onward)
The Polymarket order book reprices **before** Polymarket's own public sports score feed updates,
i.e. market makers sit in tier 2 and the score widget sits in tier 4.
- Measure: for each game-score change on `sports-api` ws, the time of the first mid move ≥ 1 tick
  in the direction implied by the score change, relative to the score message.
- **Fails if** the median book lead ≤ 0 s.

## Out-of-sample rule (track brief)
Most recent 20% of matches by start time, or the last 2 years, whichever is shorter → **the last
20% of matches**. Split is computed once in `src/split.py`. OOS is evaluated once by
`run_all.py --oos`; every OOS run is appended to `results/oos_peeks.log`.
The live recording (collected after this file was written) is a second, forward sample.

## Variant budget
H1: J ∈ {0.02, 0.03, 0.04, 0.06, 0.08} × H ∈ {10, 30, 60, 120} = 20 variants, all reported.
H2: price band lower edge ∈ {0.80, 0.85, 0.90}, upper ∈ {0.95, 0.97} = 6 variants, all reported.
Primary variants are fixed above; the plateau is reported in full.
