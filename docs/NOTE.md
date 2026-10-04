# COURTSIDE: Pricing the Value of Speed in In-Play Tennis Prediction Markets

[Author names: team to fill] · University of Florida · Gator Quant Hacks 2026 · Systematic Trading Track · October 4, 2026

**The paper is [`docs/NOTE.pdf`](NOTE.pdf)** (LaTeX, built by `python scripts/build_paper.py`; every number below and in the
PDF is read from `results/paper/numbers.json`, which records the source file and key of each). This file is a short
readable companion; where the two differ, the PDF wins.

**Labels.** CV-strategy results: assumed feed latency (licensed feed not purchased); parameters measured; simulated at a 1 s licensed-feed baseline; the trade set is the historical
points the market later repriced ≥ 4¢ (selected on outcomes, not ex ante). The pre-registered stamp-lag reading comes
first; the post hoc estimate (95% CI 2.23–3.22 s) second. v2 results are measured at the fast tier's own
fills: the opportunity at their speed, not our execution. "OOS" for v2 and the CV simulation is a burned (non-blind)
hold-out. Real money: none.

## Abstract

In-play tennis prediction markets are priced by whoever learns the point first. We measure who that is, what they
earn and what each second is worth, from public trade tapes of 13,084 Polymarket tennis matches
($2.84B traded). A walk-forward fast tier of wallets trading within 3 s of a score move earns +0.93¢
per share after fees in sample and +0.75¢ in its single out-of-sample run (9/9 and
3/3 months positive); other takers lose, and copying the same trades 3 s later loses. At the fast
tier's own fills a frozen book (v2) earns +0.60¢ per share on a burned (non-blind) hold-out (Sharpe
6.7) but turns negative when fees double (−0.34¢). Simulated at a 1 s licensed-feed
baseline (assumed feed latency (licensed feed not purchased); parameters measured), the computer-vision trader earns +$4/day on that hold-out at the
pre-registered stamp lag (break-even 1.0–1.1 s of feed delay; each second of delay costs it
$42–74 a day) and +$57/day at a post hoc estimate, on trades selected on
outcomes. A replay on the real books of 9 matches recorded on 2026-10-03 loses in 36 of
36 settings, and an ex-ante swing filter loses in 9 of 9 cells.

## Main result: the CV strategy at the 1 s baseline (Table 2 of the PDF)

| Reading at V = 1 s | IS $/day [seed CI] | IS Sharpe | OOS $/day [seed CI] | OOS Sharpe | OOS ¢/share [CI] | Break-even V (IS / OOS) |
|---|---|---|---|---|---|---|
| Pre-registered stamp lag 2.0 s | +$15 [−9, 43] | 2.1 | +$4 [−36, 62] | 0.3 | −0.38 [−2.08, 1.21] | 1.09 / 1.01 s |
| Post hoc estimate 3.14 s [2.23–3.22] | +$94 [51, 125] | 11.9 | +$57 [1, 130] | 8.8 | +0.66 [0.10, 1.19] | 2.23 / 2.14 s |

The post hoc estimate assumes the first informed prints are courtside humans reacting in 0.25 s; at its
interval's low end the 1 s cell is about +$19 / +$8 a day, and the same inference
read per point loses (−$17 / −$17; break-even 0.34 / 0.29 s).
With the live causal engine's own calls (4 of 41 misses called, no false call) the cells
are +$17 / +$4 (pre-registered) and +$98 /
+$57 (post hoc); the offline evaluation with a look-ahead feature called 11 of
11 at 50 ms. At stamp lag 1.0 s the trader loses (−$6 IS, −$11 OOS
per day). Go/no-go: a measured stamp lag L ≥ 3.0 s pays for the cheapest data stack.

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

## Capacity and the business case (Section 7 of the PDF)

At the post hoc estimate the CV book's Sharpe halves at $41,000 of capital OOS and $74,000 IS
(10 matches a day); at the pre-registered lag it has no capacity (Sharpe 2.7 / 0.9
at the smallest size). The 10-match book can pay at most $1,644 (post hoc) or $55
(pre-registered) a month for data, against an assumed licence of $1,250–$10,000.

## What failed or is pending

Fees ×2 out of sample (−0.34¢); v2 on 11,307 never-examined markets (blind, FAIL);
the CV simulation's frozen v3 rule (blind, FAIL); maker v1 (blind, FAILURE, −$379); table
tennis (untestable, median spread 94¢); v2 out of sample after a central feed licence
(−$75/day); the live-book replay (−0.94¢ at 1 s) and its ex-ante filter
(−0.95¢). Forward test: pending (runs once, Oct 4). Live paper session: pending (paper; 0 fills so far). Variants tried:
4,219. Logged reads of held-out data: 76 (full list in Table A8 of the PDF). Rules changed after a
look: 2 for v2, 13 for the CV simulation (T1–T3, V1–V10).

Reproduce: `bash reproduce.sh` (regenerates the result files, every figure and this paper).
