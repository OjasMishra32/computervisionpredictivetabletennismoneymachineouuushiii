# COURTSIDE: Pricing the Value of Speed in In-Play Tennis Prediction Markets

[Author names: team to fill] · University of Florida · Gator Quant Hacks 2026 · Systematic Trading Track · October 4, 2026

**The paper is [`docs/NOTE.pdf`](NOTE.pdf)** (LaTeX, built by `python scripts/build_paper.py`; every number below and in the
PDF is read from `results/paper/numbers.json`, which records the source file and key of each). This file is a short
readable companion; where the two differ, the PDF wins.

**Labels.** CV-strategy results: assumed feed latency (licensed feed not purchased); parameters measured; simulated at a 1 s licensed-feed baseline. v2 results are measured at
the fast tier's own fills: the opportunity at their speed, not our execution. Real money: none.

## Abstract

We study who profits from speed in Polymarket's in-play tennis moneylines, using public trade tapes for
13,084 matches ($2.84B traded). A walk-forward fast tier of wallets trading within 3 s of a
score move earns +0.93¢ per share after fees in sample and +0.75¢ out of sample (positive in
9/9 and 3/3 months); every other taker loses, and copying the same trades 3 s later
loses. At the fast tier's own fills a frozen book (v2) earns +0.60¢ per share out of sample (Sharpe
6.7) but turns negative when fees double (−0.34¢). Simulated at a 1 s licensed-feed
baseline (assumed feed latency (licensed feed not purchased); parameters measured), the computer-vision trader earns +$57/day out of sample under a calibrated,
post hoc stamp lag and +$4/day under the pre-registered one, which breaks even at
1.0–1.1 s of feed delay.

## Main result: the CV strategy at the 1 s baseline (Table 2 of the PDF)

| Reading at V = 1 s | IS $/day [seed CI] | IS Sharpe | OOS $/day [seed CI] | OOS Sharpe | OOS ¢/share [CI] | Break-even V (IS / OOS) |
|---|---|---|---|---|---|---|
| Calibrated stamp lag 3.14 s (calibrated, post hoc) | +$94 [51, 125] | 11.9 | +$57 [1, 130] | 8.8 | +0.66 [0.10, 1.19] | 2.23 / 2.14 s |
| Pre-registered stamp lag 2.0 s | +$15 [−9, 43] | 2.1 | +$4 [−36, 62] | 0.3 | −0.38 [−2.08, 1.21] | 1.09 / 1.01 s |

At stamp lag 1.0 s the same trader loses (−$6 IS, −$11 OOS per day). A replay of
9 matches recorded live on 2026-10-03 against their real books loses in 36 of
36 settings (−0.94¢ per share at V = 1 s, stamp lag 2 s).

## v2 at the fast tier's own fills (Table 1 of the PDF)

| | In sample | Burned OOS (non-blind for v2) |
|---|---|---|
| Net ¢/share [95% CI] | +1.38 [1.17, 1.59] | +0.60 [0.09, 1.13] |
| Annualised return / volatility | 253% / 17.5% | 148% / 22.2% |
| Sharpe [bootstrap CI] | 14.5 [11.9, 17.4] | 6.7 [1.9, 12.3] |
| Max drawdown | −2.0% | −2.1% |
| Skew / worst month | +0.53 / +$2,543 | +0.33 / −$434 |
| Turnover (× capital per year) | 93 | 129 |
| Fees ×2, ¢/share [CI] | +0.77 [0.57, 0.98] | −0.34 [−0.86, 0.19] |
| All costs ×2, ¢/share [CI] | +0.27 [0.07, 0.48] | −0.84 [−1.36, −0.31] |

## What failed or is pending

Fees ×2 out of sample (−0.34¢); v2 on 11,307 never-examined markets (blind, FAIL);
tier-0 v3 frozen rule (blind, FAIL); maker v1 (blind, FAILURE, −$379); table tennis
(untestable, median spread 94¢); v2 out of sample after a central feed licence
(−$75/day); the live-book replay (−0.94¢ at 1 s). Forward test: pending (runs once, Oct 4).
Live paper session: pending (paper; 0 fills so far). Variants tried: 4,219. Logged reads of held-out data:
69 (full list in Table A6 of the PDF).

Reproduce: `bash reproduce.sh` (regenerates the result files, every figure and this paper).
