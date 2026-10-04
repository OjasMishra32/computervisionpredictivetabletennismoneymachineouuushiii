# COURTSIDE: Calling the Point Before It Lands
## Predictive Ball Tracking and the Value of Speed in In-Play Tennis Markets

Ojasva Mishra, Yoan Exposito, Rafael Penhas, Ian Hoang · University of Florida · Gator Quant Hacks 2026 · Systematic Trading Track · October 4, 2026

**The paper is [`docs/NOTE.pdf`](NOTE.pdf).** This page is a short companion built from the same numbers
(`results/paper/numbers.json`, which names the source file of every value). If the two ever differ, the PDF wins.

**How to read the labels.** Executable results (what we could run at our latency, net of costs) come first: the
copier, timed after the second the score move was detected, and the causal camera policy, which trades every point
from the classifier's measured call statistics (simulated fills, an upper bound). Two benchmarks follow and are not
returns we could earn: v2, our copy of the fast tier's trades at their own prices, and the computer-vision (CV)
trader, simulated (assumed feed latency (licensed feed not purchased); parameters measured), whose trades are past points where the price later moved at least 4¢ (selected on the
outcome). We show the pre-registered stamp-lag reading first and the post hoc estimate
(3.14 s, 95% CI 2.23–3.22 s) second. v2 and the CV simulation were designed after we had read
the hold-out, so their OOS results are non-blind. No real money was used and no order was ever sent.

## Abstract

We built a predictive ball-tracking engine that calls a point (ball out, or into the net) before the ball lands. On
held-out real table-tennis video our live causal engine made its calls a median 162 ms before the ball
reached the table end, none wrong but few (4 of 41 misses), in real time at
119.9 fps; a frame becomes a ready order in 54 ms. On real broadcast tennis (one TV camera,
held-out games) its out calls were right 5 of 5 at the bounce and 3 of 3 when 33 ms ahead. In real
Polymarket data on 13,084 ATP and WTA matches (1,310 at Grand Slams), wallets trading within
3 s of a point earn after fees in all 11 months, as our pre-registered hypothesis predicted out of
sample. What we could trade loses after costs. A copier of their trades that acts only after the second the move was
detected, the venue's hold and the block lag makes −1.42¢ a share in sample (−$31 a day)
and −1.02¢ [−3.00, 0.84] out of sample (−$28 a day). A camera policy that trades
every point from our classifier's measured call statistics, at an assumed licensed 0.5 s feed, makes
−$92 and −$146 a day (simulated fills, an upper bound), and less at 1 s and 3 s; only
a post hoc stamp lag turns 0.5 s positive (+$174, +$65). Two labelled
benchmarks price the speed we lack: the fast tier's own fills (v2; Sharpe 14.5 in sample,
6.7 out of sample; doubled fees erase the out-of-sample gain) and a CV trader on points the market later repriced
(+$15 a day out of sample pre-registered, +$81 post hoc, at 0.5 s). Our one
test with rules fixed in advance holds the last 20% of matches, 10.7% of the calendar; no untouched test
meets the organizers' by-time rule.

## The real data behind every result

Simulated: only when our CV would see each point (an assumed feed latency) and the spin-aware Hawk-Eye-class model.

| Source | What is real | Matches | Period | Used for |
|---|---|---|---|---|
| Polymarket books and trades | prices, fills, fees, taker delays | 13,084 (8,554 ATP, 4,530 WTA); 1,310 at Grand Slams (Australian Open 415, Roland Garros 412, US Open 483) | Oct 2025 – Oct 2026 | fast tier; v2 (traded in 7,639 IS, 2,003 OOS); CV trader (7,755 matches at a 1 s hold, about 681 IS and 246 OOS traded per seed) |
| Polymarket, held back | same | 11,307 (10,855 ITF) | same | blind test |
| Match Charting Project (Sackmann) | 901,233 charted points | 5,889 (3,337 men, 2,552 women) | 2020–26 | how points end (out 36–41%, net 25–26%, winner 29–35%) |
| TrackNet broadcast set (Huang et al. 2019) | 19,835 labelled frames | 10 (95 clips) | | court, landing and out-call models (tuned on games 1–7, tested once on 8–10) |
| OpenTTGames; Pexels rally | 120 fps match video; phone video | 41 held-out misses; one rally | | early-call engine; tracker end to end |

Wimbledon is listed under a separate Polymarket series and is outside our universe.

## Executable: a copier, the causal camera policy and a live-book replay (Table 1 of the PDF, first rows)

| | IS | OOS (non-blind) |
|---|---|---|
| Copier after the detection second, the hold and the 1.98 s block lag: $ a day | −$31 | −$28 |
| Copier: net ¢ a share [95% CI] / Sharpe | −1.42 [−2.31, −0.50] / −3.9 | −1.02 [−3.00, 0.84] / −3.2 |
| Copier: total net P&L | −$6,351 [−$10,285, −$2,259] | −$1,104 [−$3,221, +$900] |
| Camera policy, every point, pre-registered 2.0 s lag, 0.5 / 1 / 3 s feed: $ a day | −$92 / −$124 / −$187 | −$146 / −$185 / −$230 |
| Same, fully pre-registered per-point timing | −$136 / −$155 / −$188 | −$190 / −$205 / −$217 |
| Same, post hoc 3.14 s lag | +$174 / +$67 / −$174 | +$65 / −$45 / −$227 |

The camera policy assumes the frozen classifier's measured table-tennis call statistics, because no footage of the
Polymarket matches exists (it has made no real calls on them); its fills are priced off the post-point price and the
measured live book (20-seed means). With fees doubled every camera-policy cell loses; the stated
$1,000 daily stop is simulated and never fired; the false-call halt is not simulated (a proposed
control).

A replay of 9 matches recorded live (one day), calling every point at the pre-registered 2 s stamp lag,
makes −0.66¢ a share [−0.96, −0.41] at a 0.5 s feed and −0.94¢ [−1.28, −0.58] at 1 s.

## Benchmark: v2, the fast tier's own fills (not attainable by a copier)

Sharpe uses daily P&L on every calendar day × √365; 95% CIs from a stationary block bootstrap; the deflated Sharpe
corrects for 3,386 trials. 97.7% of v2's in-sample profit (99.2% OOS) is in
prints stamped in the second the score move was detected; on later prints only, the same book at the fast tier's fills
makes +0.33¢ [−0.55, 1.21] IS and +0.76¢ [−1.19, 2.65] OOS.

| | IS | OOS (non-blind) |
|---|---|---|
| Net ¢ a share [95% CI] | +1.38 [1.17, 1.59] | +0.60 [0.09, 1.13] |
| Sharpe [95% CI] | 14.5 [11.9, 17.4] | 6.7 [1.9, 12.3] |
| Deflated Sharpe | 0.997 | 0.075 |
| Annual return / volatility | 253% / 17.5% | 148% / 22.2% |
| Max drawdown / worst month | −2.0% / +$2,543 | −2.1% / −$434 |
| Turnover (× a year) / skew | 93 / +0.53 | 129 / +0.33 |
| Fees paid, bps of notional | 120 | 179 |
| PSR / MinTRL / haircut tests passed (of 6) | 6 | 3 |
| Net ¢, fees ×2 / all costs ×2 | +0.77 / +0.27 | −0.34 / −0.84 |

## Benchmark: the CV trader on points that later moved, at three assumed feed delays (Table 1, lower rows)

Simulated (assumed feed latency (licensed feed not purchased); parameters measured; 20 seeds a cell); trades only past points the price later moved at least 4¢ on,
so every cell is an upper bound. Pre-registered stamp lag 2.0 s (break-even feed delay
1.09 s IS, 1.01 s OOS):

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

Return, volatility, max drawdown, turnover and the fees-doubled result of every cell are in Table 1 of the PDF
(`results/tier0/cost_turnover.json`); fees run 163–226 bps of notional, and with fees doubled every
out-of-sample cell loses (best −$13 a day). Read per point, the post hoc inference loses
(−$17 a day at 1 s). A replay of 9
matches recorded live against their real order books calls every point ex ante and loses in 36 of
36 settings (−0.94¢ a share at 1 s).

## If we were a quant firm with a licensed 0.5 s feed (counterfactual)

Real Polymarket prices, fills, fees and the venue's 1 s hold; simulated camera calls at an assumed feed delay; no feed
bought, no order placed. Choosing trades causally it would make −$92 / −$146 a day
(IS / OOS) at the pre-registered lag and +$174 / +$65 at the post hoc lag. The
upper envelope, on points selected by their later move: +$28 / +$133 a day in
sample and +$15 / +$81 OOS (pre-registered / post hoc). On the same selection, a fresh holdout,
pre-registered at `dc95717` before its data were fetched (16 newer matches,
2 UTC days), returned −$20.5 / +$50.8 a day (CIs
[−$96, +$57], [−$38, +$141]): anecdotal, evidence neither for nor against an edge. The most a
firm could pay a month for the feed is $384 / $2,397 OOS, against
quotes of $1,250–$10,000. Fig. 3 of the PDF; `results/fresh_holdout/`, `results/scenario/`.

## Speed, capacity and what failed

- **Pipeline (paper; order built, not sent).** On our own footage a video frame becomes a built order in
  54 ms. With a simulated 1 s feed, 65 ms of network and the 1 s venue hold, the order can
  execute 2,119 ms after the point ends, inside the organizers' 3,000 ms bar.
- **Vision on real video.** On the TrackNet broadcast set (tuned on games 1–7, tested once on games 8–10,
  132 bounces), one TV camera and the pretrained detector's own track put the landing point
  17 cm off at the bounce and 0.7–1.2 m off 33–300 ms ahead (median); out calls were right
  5 of 5 at the bounce, 3 of 3 at 33 ms and 3 of 4 at 67 ms ahead, and fail from 100 ms
  (2 of 5). Only the bounce-time call met our 95% precision rule on the training games, and the detector
  weights (not ours) saw frames of all ten games, so these are in-distribution numbers. On held-out table tennis the
  live causal engine called 4 of 41 misses early (median lead 162 ms), none
  wrongly, at 119.9 fps on one L4 GPU. On a Pexels rally our tennis tracker found the ball in
  89% of 300 frames. Tennis trading is simulated.
- **Nearby settings also work.** All 55 sizing rules have a per-share 95% CI above zero in sample
  (Sharpe 4.1–16.8); the v2-safe grid's probability of backtest overfitting is 9–24% across
  block choices; the CV profit falls across all 14 feed delays from 0 to
  60 s, never rising by more than $0.09 a day.
- **Per-match loss and a per-wallet cap (risk).** The 100-share net cap limits the open position, not the loss:
  the worst match lost −$206 in sample and −$154 out of sample. A per-wallet cap
  ($1,000 a day plus retirement), chosen in sample and pre-registered, ran once on the OOS (non-blind):
  +0.91¢ [0.20, 1.66], Sharpe 7.6; the top five wallets still carry 129%.
- **Rally gate (risk).** Replayed on the engine's held-out call log (`scripts/rally_gate_eval.py`), the gate in our
  strategy code (a miss call trades only within 2.0 s of a bounce call, set before the test) removes
  5 of the 7 calls on balls outside labelled flights
  (4 of 5 between rallies) but keeps only 3 of
  5 correct calls (2 at 0.5–0.8 s); about
  8 phantom calls an hour remain, so it is not yet safe to trade.
- **Capacity.** v2's OOS edge holds up to 1× size ($22,754 of capital); 5× loses. The CV benchmark has no
  capacity at the pre-registered lag; post hoc its Sharpe halves at $40,000 (OOS) to $73,000
  (IS) of capital. At 1 s it could pay at most $1,644 a month for data post hoc and
  $55 pre-registered, against reported feed prices of $1,250–$10,000.
  COURTSIDE prices speed; it is not yet a business.
- **What failed.** Doubled fees out of sample (−0.34¢); v2 on 11,307 never-examined markets
  (blind); v2-safe's blind test; the corrected copier on 108 never-fetched markets outside our universe
  (+8.80¢ [−34.41, 50.33], 21 trades: fail, underpowered); the CV rule v3 (post-freeze); the maker book
  (blind); table-tennis markets (untestable); v2
  after a central data licence (−$75 a day); the live-book replay. Blind forward test:
  pre-registered but not run within the hackathon window (HYPOTHESIS_V2.md A5). We tried 4,219 variants; the choices made after an OOS look are listed in Appendix D of the
  PDF from `results/provenance/experiments.json`. Every test is in Appendix B; every formula with a worked example is
  in Appendix A.
- **Risk controls.** Table 2 of the PDF separates the controls that operated in the backtests (order, net and price
  caps; the $3,000 gross cap a match for v2; the $1,000 daily stop in the causal camera
  policy, which never fired) from those proposed for deployment (the false-call halt, the trailing-edge and drawdown
  stops) or present only in the paper-trading engine (stale-feed and stale-vision stops).
- **The out-of-sample rule.** Our one evaluation with rules fixed in advance (frozen in `9d61d1b`, run
  once on Oct 3 at 10:42 UTC) used the pre-registered last 20% of matches: 2,617 matches over
  38.7 days, 10.7% of the 360-day history. It confirmed H6 as an
  observational fact (the fast tier stayed positive out of sample at its own fills). The organizers' rule takes the
  latest 20% by time, the 72.0 days from Jul 23; we had read all of it before the
  corrected policies were frozen, and a window of new matches alone would need 90 days. Our
  verdict: no untouched test that meets the by-time rule exists for any policy here; every later OOS result is
  non-blind and exploratory.

Reproduce: `bash reproduce.sh` (rebuilds the result files, every figure and this paper).
