# COURTSIDE: Pricing the Value of Speed in In-Play Tennis Prediction Markets

Ojasva Mishra, Yoan Exposito, Rafael Penhas, Ian Hoang · University of Florida · Gator Quant Hacks 2026 · Systematic Trading Track · October 4, 2026

**The paper is [`docs/NOTE.pdf`](NOTE.pdf)** (LaTeX, built by `python scripts/build_paper.py`; every number below and in
the PDF is read from `results/paper/numbers.json`, which records the source file and key of each). This file is a short
readable companion; where the two differ, the PDF wins.

**Labels.** CV-strategy results are simulated: assumed feed latency (licensed feed not purchased); parameters measured. Their trade set is the historical points the market later
repriced by at least 4¢ (selected on outcomes, not ex ante). The pre-registered stamp-lag reading comes first; the post
hoc estimate (3.14 s, 95% CI 2.23–3.22 s) second. v2 is measured at the fast tier's own fills:
the opportunity at their speed, not our execution. "OOS" for v2 and the CV simulation is a burned (non-blind) hold-out.
Real money: none; no order was ever sent.

## Abstract

We study who profits from speed in Polymarket's in-play tennis moneylines (13,084 matches, public tapes). A
walk-forward fast tier of wallets trading within 3 s of a score move earns after fees in every in-sample and held-out
month; other takers lose, and copying the same trades 3 s later loses. At the fast tier's own fills a frozen book (v2)
has a Sharpe ratio of 14.5 in sample and 6.7 on a burned hold-out, but turns negative when fees
double. We then price the speed a computer-vision (CV) trader needs (simulated; assumed feed latency (licensed feed not purchased); parameters measured). Pre-registered, it breaks
even at a 1.0–1.1 s feed delay and earns +$15, +$4 and
−$13 a day held out at 0.5, 1 and 3 s; a post hoc stamp-lag inference gives +$57 at
1 s. A replay on real books loses. Real money: none.

## Headline metrics (Table 1 of the PDF)

**A. v2 at the fast tier's own fills** (Sharpe: daily P&L on zero-filled calendar days × √365; 95% CI from a stationary
bootstrap; deflated Sharpe at 3,386 trials, 3,410 for v2-safe)

| | v2 IS | v2 OOS | v2-safe IS | v2-safe OOS |
|---|---|---|---|---|
| Sharpe [95% CI] | 14.5 [11.9, 17.4] | 6.7 [1.9, 12.3] | 15.7 [13.1, 18.6] | 9.3 [4.5, 15.6] |
| Deflated Sharpe | 0.997 | 0.075 | 1.000 | 0.290 |
| Net ¢ per share | +1.38 [1.17, 1.59] | +0.60 [0.09, 1.13] | +1.33 [1.16, 1.52] | +0.69 [0.24, 1.15] |
| Return / volatility, a year | 253% / 17.5% | 148% / 22.2% | 239% / 15.2% | 170% / 18.4% |
| Max drawdown / worst month | −2.0% / +$2,543 | −2.1% / −$434 | −1.6% / +$1,499 | −1.9% / −$187 |
| Turnover (× a year) / skew | 93 / +0.53 | 129 / +0.33 | 90 / +0.61 | 129 / +0.17 |

v2-safe (net cap 50) was fixed after v2's OOS losses were seen, and failed its blind unseen-market test
(+1.21¢ [−0.02, 2.43]).

**B. The CV strategy at three assumed feed latencies** (simulated; assumed feed latency (licensed feed not purchased); parameters measured; 20 seeds a cell)

Pre-registered stamp lag 2.0 s (break-even feed delay 1.09 s IS, 1.01 s OOS):

| Feed latency V | IS $/day | IS Sharpe | IS ¢/share [95% CI] | OOS $/day | OOS Sharpe | OOS ¢/share [95% CI] |
|---|---|---|---|---|---|---|
| 0.5 s, best case | +$28 | 4.0 | +0.61 [0.08, 1.14] | +$15 | 2.1 | −0.02 [−1.22, 1.09] |
| 1 s, base case | +$15 | 2.1 | +0.40 [−0.32, 1.08] | +$4 | 0.3 | −0.38 [−2.08, 1.21] |
| 3 s, requirement | −$13 | −2.6 | −1.35 [−3.15, 0.37] | −$13 | −2.6 | −1.69 [−4.85, 1.32] |

Post hoc stamp-lag estimate 3.14 s (assumes courtside humans; break-even 2.23 s IS,
2.14 s OOS):

| Feed latency V | IS $/day | IS Sharpe | IS ¢/share [95% CI] | OOS $/day | OOS Sharpe | OOS ¢/share [95% CI] |
|---|---|---|---|---|---|---|
| 0.5 s, best case | +$133 | 15.5 | +1.21 [1.00, 1.42] | +$81 | 12.2 | +0.82 [0.39, 1.25] |
| 1 s, base case | +$94 | 11.9 | +1.11 [0.85, 1.38] | +$57 | 8.8 | +0.66 [0.10, 1.19] |
| 3 s, requirement | −$6 | −1.4 | −0.79 [−2.26, 0.60] | −$11 | −2.4 | −1.47 [−4.45, 1.34] |

At 1 s the same post hoc inference read point by point loses (−$17 / −$17 a day); with
no early CV calls the pre-registered cell is +$8 / −$13; with the live causal engine's
own call table it is +$17 / +$4 (pre-registered) and +$98 /
+$57 (post hoc). A replay calling every point on 9 matches' real books loses in
36 of 36 settings (−0.94¢ at 1 s).

## Components, pipeline and capacity

- **CV, table tennis (real held-out footage):** the live causal engine calls 4 of 41
  misses before contact (median lead 162 ms), none wrongly;
  an offline evaluation with a look-ahead feature called 11 of 11 at 50 ms.
  **Tennis:** simulated physics only; a spin-aware
  tracker cuts landing error from 5.76 to 0.57 cm at 200 ms. **GPU engine:** L4,
  119.9 fps, call-ready in 4.6 ms p50, 0 of 102,120 frames dropped.
- **Pipeline (paper; order built, not sent):** frame to unsigned order 54 ms p50 on our own footage over
  WebRTC (video leg 4–8 ms); with a simulated 1 s feed, 65 ms network and the 1 s venue hold the
  order is executable at 2,119 ms, under the organiser's 3,000 ms bar.
- **Capacity:** v2's OOS edge holds up to 1× size ($22,754); 5× loses. The CV book has no capacity at the
  pre-registered lag (Sharpe 2.7 / 0.8 at its smallest size); post hoc its Sharpe
  halves at $40,000 (OOS) to $73,000 (IS) of capital; it trades 0.22% of
  in-play volume but 9% of the fast tier's 0–3 s volume. At 1 s it can pay at most
  $1,644 a month for data post hoc and $55 pre-registered, against quotes of
  $1,250–$10,000. COURTSIDE prices speed; it is not yet a business.

## What failed

Fees ×2 out of sample (−0.34¢); v2 on 11,307 never-examined markets (blind, FAIL);
v2-safe's blind test (FAIL); the CV simulation's frozen v3 rule (blind, FAIL); maker v1 (blind,
FAILURE, −$379); table tennis markets (untestable, median spread 94¢); v2 out of sample
after a central feed licence (−$75/day); the live-book replay and its ex-ante filter. Blind
forward test (v2; tier-0 v3 secondary): runs 2026-10-04 11:30 UTC (pre-registered) (`HYPOTHESIS_V2.md` A4). The live paper session was stopped and is
not used. Variants tried: 4,219. Logged reads of
held-out data: 77 (Table A9 of the PDF). Everything we tested, with its best result, is Table A1 of the PDF;
every formula with a worked example is the appendix "Calculations".

Reproduce: `bash reproduce.sh` (regenerates the result files, every figure and this paper).
