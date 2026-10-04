# COURTSIDE: Pricing the Value of Speed in In-Play Tennis Prediction Markets

Ojasva Mishra, Yoan Exposito, Rafael Penhas, Ian Hoang · University of Florida · Gator Quant Hacks 2026 · Systematic Trading Track · October 4, 2026

**The paper is [`docs/NOTE.pdf`](NOTE.pdf).** This page is a short companion built from the same numbers
(`results/paper/numbers.json`, which names the source file of every value). If the two ever differ, the PDF wins.

**How to read the labels.** The computer-vision (CV) results are simulated: assumed feed latency (licensed feed not purchased); parameters measured. Their trades are past points
where the price later moved at least 4¢, so they are selected on outcomes, not ex ante. We show the pre-registered
stamp-lag reading first and the post hoc estimate (3.14 s, 95% CI 2.23–3.22 s) second. v2 is our
copy of the fast tier's trades at their own prices: it measures what their speed is worth, not what we could earn.
"OOS" for v2 and the CV simulation is a burned hold-out (we had looked at it), not a blind one. No real money was used
and no order was ever sent.

## Abstract

After each point, a Polymarket tennis price (a win probability) is set by whoever learns the point first. In public
data on 13,084 matches, wallets that repeatedly trade within 3 s of a point (the fast tier, picked on past
months) earn after fees in all
11 months, in and out of sample, while everyone else loses; copying them has no factor exposure and an
out-of-sample Sharpe ratio of 6.7 (14.5 in sample) that doubled fees erase. About half the edge
is gone within 1–2 s (+1.18¢ to +0.59¢ a share in sample), and the first second of
video delay costs a simulated computer-vision (CV) trader $42–74 a day; our pipeline needs
54 ms. With an assumed feed delay (no feed purchased), that trader makes +$15,
+$4 and −$13 a day out of sample at 0.5, 1 and 3 s pre-registered
(+$81, +$57, −$11 post hoc). Every blind test of a book we
could trade failed, and so did a replay on real order books.

## Table 1 of the PDF: our copy of the fast tier's trades (v2)

Sharpe uses daily P&L on every calendar day × √365; 95% CIs from a stationary block bootstrap; the deflated Sharpe
corrects for 3,386 trials.

| | IS | OOS (burned) |
|---|---|---|
| Net ¢ a share [95% CI] | +1.38 [1.17, 1.59] | +0.60 [0.09, 1.13] |
| Sharpe [95% CI] | 14.5 [11.9, 17.4] | 6.7 [1.9, 12.3] |
| Deflated Sharpe | 0.997 | 0.075 |
| Annual return / volatility | 253% / 17.5% | 148% / 22.2% |
| Max drawdown / worst month | −2.0% / +$2,543 | −2.1% / −$434 |
| Turnover (× a year) / skew | 93 / +0.53 | 129 / +0.33 |
| Net ¢, fees ×2 / all costs ×2 | +0.77 / +0.27 | −0.34 / −0.84 |

## Table 2 of the PDF: the CV strategy at three assumed feed delays

Simulated (assumed feed latency (licensed feed not purchased); parameters measured; 20 seeds a cell). Pre-registered stamp lag 2.0 s (break-even feed
delay 1.09 s IS, 1.01 s OOS):

| Feed delay V | IS $/day | IS Sharpe | IS ¢/share [95% CI] | OOS $/day | OOS Sharpe | OOS ¢/share [95% CI] |
|---|---|---|---|---|---|---|
| 0.5 s, best case | +$28 | 4.0 | +0.61 [0.08, 1.14] | +$15 | 2.1 | −0.02 [−1.22, 1.09] |
| 1 s, base case | +$15 | 2.1 | +0.40 [−0.32, 1.08] | +$4 | 0.3 | −0.38 [−2.08, 1.21] |
| 3 s, requirement | −$13 | −2.6 | −1.35 [−3.15, 0.37] | −$13 | −2.6 | −1.69 [−4.85, 1.32] |

Post hoc estimate 3.14 s (assumes humans at the court; break-even 2.23 s IS,
2.14 s OOS):

| Feed delay V | IS $/day | IS Sharpe | IS ¢/share [95% CI] | OOS $/day | OOS Sharpe | OOS ¢/share [95% CI] |
|---|---|---|---|---|---|---|
| 0.5 s, best case | +$133 | 15.5 | +1.21 [1.00, 1.42] | +$81 | 12.2 | +0.82 [0.39, 1.25] |
| 1 s, base case | +$94 | 11.9 | +1.11 [0.85, 1.38] | +$57 | 8.8 | +0.66 [0.10, 1.19] |
| 3 s, requirement | −$6 | −1.4 | −0.79 [−2.26, 0.60] | −$11 | −2.4 | −1.47 [−4.45, 1.34] |

Read per point, the post hoc inference loses (−$17 a day at 1 s). A replay of 9
matches recorded live against their real order books calls every point ex ante and loses in 36 of
36 settings (−0.94¢ a share at 1 s).

## Speed, capacity and what failed

- **Pipeline (paper; order built, not sent).** On our own footage a video frame becomes a built order in
  54 ms. With a simulated 1 s feed, 65 ms of network and the 1 s venue hold, the order can
  execute 2,119 ms after the point ends, inside the organizers' 3,000 ms bar.
- **CV on real held-out table-tennis footage.** The live causal engine called 4 of 41
  balls that went out early (median lead 162 ms), none wrongly, at 119.9 fps on one L4 GPU.
  On a freely licensed real tennis rally (Pexels), our tennis tracker found the ball in 89% of
  300 frames (48/48 random spot-checks on the ball in play) and fitted the court lines in
  every frame (0.36 px median); we make no in/out calls on single-camera tennis footage, and tennis
  trading is simulated.
- **Nearby settings also work.** All 55 sizing rules have a per-share 95% CI above zero in sample
  (Sharpe 4.1–16.8); the v2-safe grid's probability of backtest overfitting is 9–24% across
  block choices; the CV profit falls across all 14 feed delays from 0 to
  60 s, never rising by more than $0.09 a day.
- **Rally gate (risk).** Replayed on the engine's held-out call log (`scripts/rally_gate_eval.py`), the gate in our
  strategy code (a miss call trades only within 2.0 s of a bounce call, set before the test) removes
  5 of the 7 calls on balls outside labelled flights
  (4 of 5 between rallies) but keeps only 3 of
  5 correct calls (2 at 0.5–0.8 s); about
  8 phantom calls an hour remain, so it is not yet safe to trade.
- **Capacity.** v2's OOS edge holds up to 1× size ($22,754 of capital); 5× loses. The CV book has no
  capacity at the pre-registered lag; post hoc its Sharpe halves at $40,000 (OOS) to $73,000
  (IS) of capital. At 1 s it could pay at most $1,644 a month for data post hoc and
  $55 pre-registered, against reported feed prices of $1,250–$10,000.
  COURTSIDE prices speed; it is not yet a business.
- **What failed.** Doubled fees out of sample (−0.34¢); v2 on 11,307 never-examined markets
  (blind); v2-safe's blind test; the CV rule v3 (blind); the maker book (blind); table-tennis markets (untestable); v2
  after a central data licence (−$75 a day); the live-book replay. Blind forward test:
  pre-registered but not run within the hackathon window (HYPOTHESIS_V2.md A5). We tried 4,219 variants and logged 77 reads of held-out data (Appendix D of the
  PDF). Every test is in Appendix B; every formula with a worked example is in Appendix A.

Reproduce: `bash reproduce.sh` (rebuilds the result files, every figure and this paper).
