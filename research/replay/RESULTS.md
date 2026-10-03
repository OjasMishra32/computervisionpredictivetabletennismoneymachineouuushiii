# Match replay: the 1 s video trader on real matches recorded live on 2026-10-03

> **BACKTEST REPLAY on a real match recorded live on 2026-10-03 — assumed 1 s licensed video feed (not purchased); bounce time = official point stamp - assumed stamp lag; fills priced against the real recorded order book; paper only.**
>
> We did not receive, buy or watch any video of these matches. The feed, its 1 s delay, the camera call and its lead are assumed. Real: the official WTA point stamps and winners, the Polymarket order books and trades recorded live today, the venue's 1 s taker delay, the fee and the match results. No order was sent. Protocol, committed before any P&L: `PROTOCOL.md`. **One day, 9 matches, a small sample: this is an illustration and a consistency check against the latency sweep (`research/v2/tier0/LATENCY_SWEEP.md`), not new evidence.**

## Bottom line

* **At the headline 1 s feed delay the replayed trader loses money:** 151 fills over the 9 matches, **-0.92c per share** marked at the +30 s mid (match-clustered 95 % CI [-1.29, -0.57]), −$229 marked and −$387 held to the result. Its order executes before the book reprices on only 35 of 467 calls (7%).
* **It still loses at V = 0.5 s and at V = 0** (a camera at the venue): -0.65c and -0.61c per share marked, −$174 and −$181. Faster helps in the right direction: the share of calls that beat the book goes 30% → 19% → 7% from V = 0 to 1 s, and correct-call fills before the reprice go 57 → 40 → 9.
* **Why:** the only fills that make money are correct calls that execute before the reprice (gross edge 1.1-1.3c per share against the +30 s mid at V ≤ 0.5 s, about half the live fast tier's 2.24c; see §2). They are outnumbered by correct calls that land just after a ≤ 1c reprice (the 1c limit lets them through at a roughly fair price, so they pay the fee) and by the simulated wrong calls, which always fill because the loser's price is falling. Because every point is called, the 100-share net cap blocks 218 of 482 calls at 1 s, including 5 of the 6 that beat the book in the selected match.
* **Selected match** (Xinran Sun v Cristina Bucsa, 125 matched points; chosen by the pre-committed rule): at V = 1.0 s the order beats the book on **6 of 121** calls and fills on **0** of them; at V = 0.5 s 19 (6 filled); at V = 0, 26 (9 filled).
* **Consistency with the latency sweep:** same mechanism and same direction (the edge needs the order to beat the reprice, and it shrinks with V). The level is lower than the sweep's in-sample curve, because this replay calls every point (the sweep trades only ≥ 4c jumps), lets ≤ 1c post-reprice fills through, and binds the net cap. It is closer to the sweep's burned-OOS reading (+0.58c at V = 0 with a CI that includes zero, -0.38c at 1 s) than to its in-sample curve, but still below it at V = 0. Every one of the 36 sensitivity cells is negative marked; the best is stamp lag 3.0 s at V = 0 (§5).

![selected match](../../results/replay/fig_selected_match.png)

`results/replay/fig_selected_match.png`: the recorded mid of the selected match, every official point, and the replayed V = 1.0 s trader's fills (blue: correct call; orange: simulated wrong call; grey x: missed because the book had already moved past the limit). Bottom: cumulative marked P&L at V = 0, 0.5 and 1.0 s.

## 1. Headline: 9 matches, stamp lag 2.0 s, model lead, Florida 67 ms, seed 0

| | V = 0 s (venue-camera bound) | V = 0.5 s | **V = 1.0 s (headline)** |
|---|---|---|---|
| replayable official points | 500 | 500 | 500 |
| calls (quoted, inside 5-95c) | 482 | 482 | 482 |
| of which simulated wrong calls | 34 | 34 | 34 |
| calls whose order executes before the book reprices | 141 of 467 (30%) | 91 of 467 (19%) | 35 of 467 (7%) |
| blocked by the 100-share net cap | 228 | 214 | 218 |
| orders sent | 254 | 268 | 264 |
| missed: book already moved past the limit | 80 | 99 | 113 |
| fills (correct / wrong call) | 174 (150 / 24) | 169 (146 / 23) | 151 (130 / 21) |
| fill rate (fills / orders) | 69% | 63% | 57% |
| correct-call fills executed before the reprice | 57 | 40 | 9 |
| shares / $ deployed | 29,961 / $14,924 | 26,617 / $13,201 | 24,798 / $12,469 |
| **net per share, marked at +30 s mid [95 % CI]** | **-0.61c** [-0.90, -0.37] | **-0.65c** [-0.96, -0.39] | **-0.92c** [-1.29, -0.57] |
| **net per share, held to the match result [95 % CI]** | **-0.71c** [-2.07, -0.10] | **-0.85c** [-2.51, -0.03] | **-1.56c** [-3.18, -0.58] |
| **$ P&L, marked / held** | **−$181 / −$213** | **−$174 / −$226** | **−$229 / −$387** |
| win rate of fills, marked / held | 29% / 51% | 30% / 51% | 23% / 49% |
| median (execution - reprice), s | +0.30 | +0.80 | +1.30 |


Per-share net = Σ P&L / Σ shares over fills. CI: 10,000 bootstrap resamples of the matches with at least one fill (8 / 8 / 8 matches at V = 0 / 0.5 / 1.0 s). Win rate counts fills with P&L > 0. Held-to-result P&L is mostly the match result on a ≤ 100-share net position, so it is far noisier than the marked P&L; read the marked figure for the edge.

**20 seeds** (lead draws and wrong calls re-drawn; same books and points): mean ± SD over seeds.

| | V = 0 s | V = 0.5 s | V = 1.0 s |
|---|---|---|---|
| fills | 183.6 ± 7.4 | 178.7 ± 8.4 | 154.8 ± 8.0 |
| wrong-call fills | 13.6 ± 4.6 | 13.4 ± 4.4 | 12.7 ± 4.7 |
| calls beating the book | 144.4 ± 1.8 | 90.5 ± 0.8 | 37.4 ± 1.5 |
| net c/share, marked | -0.53 ± 0.11 | -0.69 ± 0.10 | -0.96 ± 0.09 |
| net c/share, held | -0.76 ± 0.20 | -0.85 ± 0.21 | -1.44 ± 0.25 |
| $ marked | -163 ± 35 | -194 ± 32 | -242 ± 30 |
| $ held | -238 ± 70 | -240 ± 68 | -367 ± 80 |

Seed 0 (the replay shown everywhere) drew 34 wrong calls out of 482 (7 %, against 5 % expected), so it sits on the unlucky side of the seed spread; the sign does not change in any of the 20 seeds at any V (marked $ range: V = 0: -229 to -113, V = 0.5: -250 to -136, V = 1: -314 to -200).

## 2. Where the P&L comes from (accounting split of the same fills)

Gross = +30 s mid - fill price; net = gross - fee. Classes: whether the call was correct, and whether the order executed before the book's half-move reprice (`t_book`); "not before a reprice" includes the few fills on points with no matched reprice. This split uses `t_book`, which a trader would not know at the time; it explains the result and is not a trading rule.

| V | fill class | fills | shares | gross c/share | fee c/share | net c/share (marked) | $ marked | $ held |
|---|---|---|---|---|---|---|---|---|
| 0 s | correct, before the reprice | 57 | 9,883 | +1.14 | 0.86 | +0.28 | +$28 | +$301 |
| 0 s | correct, not before a reprice | 93 | 15,883 | +0.22 | 0.90 | -0.68 | −$107 | +$226 |
| 0 s | wrong call | 24 | 4,195 | -1.42 | 1.01 | -2.43 | −$102 | −$741 |
| 0.5 s | correct, before the reprice | 40 | 6,454 | +1.27 | 0.83 | +0.43 | +$28 | +$98 |
| 0.5 s | correct, not before a reprice | 106 | 16,333 | +0.12 | 0.87 | -0.75 | −$123 | +$387 |
| 0.5 s | wrong call | 23 | 3,830 | -1.09 | 0.98 | -2.07 | −$79 | −$710 |
| 1 s | correct, before the reprice | 9 | 1,498 | +0.11 | 0.89 | -0.79 | −$12 | +$21 |
| 1 s | correct, not before a reprice | 121 | 19,604 | +0.08 | 0.85 | -0.76 | −$150 | +$345 |
| 1 s | wrong call | 21 | 3,695 | -0.83 | 1.00 | -1.83 | −$68 | −$752 |

The correct fills that beat the book earn a gross 1.1-1.3c per share at V ≤ 0.5 s, about half of the live fast tier's 2.24c (`research/v2/tier0/RESULTS.md` §1), and keep a few tenths of a cent after the fee. At V = 1 s the few that remain earn nothing. There are too few of them: most correct calls either arrive after the reprice or are blocked by the net cap.

![P&L by V](../../results/replay/fig_pnl_by_v.png)

`results/replay/fig_pnl_by_v.png`: left, net per share with match-clustered 95 % CI at V = 0, 0.5, 1.0 s (marked and held), next to the latency sweep's headline-reading curve (in sample and burned OOS; a different trade set). Right, marked $ by fill class.

![race](../../results/replay/fig_race.png)

`results/replay/fig_race.png`: for every call with a matched reprice, our execution time minus the book's reprice time. Left of zero, the stale price is still there when our order executes.

## 3. The selected match, point by point: Xinran Sun v Cristina Bucsa

Selection rule (`PROTOCOL.md` §3): most points with a matched book reprice, ties by earliest start. `wta-su-bucsa-2026-10-02`: 128 official points, 125 matched, first stamp 2026-10-03T10:19:20.000Z, last 2026-10-03T11:50:12.000Z; winner Xinran Sun. Every point is in `results/replay/points.csv` (`selected_match = True`) with its bounce, call, execution and reprice times, the reference and execution prices, the status and the P&L.

| | V = 0 s | V = 0.5 s | V = 1.0 s |
|---|---|---|---|
| calls | 124 | 124 | 124 |
| calls with a matched reprice | 121 | 121 | 121 |
| **calls whose order beats the reprice** | 26 | 19 | 6 |
| blocked by net cap | 60 | 56 | 60 |
| missed (book already moved) | 25 | 27 | 32 |
| fills | 39 | 41 | 32 |
| of which correct calls | 31 | 33 | 26 |
| of which wrong calls | 8 | 8 | 6 |
| **fills that beat the reprice** | 9 | 6 | 0 |
| shares | 6,025 | 4,998 | 3,953 |
| $ marked / held | −$30 / +$17 | −$27 / +$32 | −$8 / +$26 |
| median execution - reprice, s | +0.67 | +1.17 | +1.67 |

**The 6 calls that beat the book at V = 1.0 s:**

| point | score after | point winner | called | execution - reprice (s) | ask at bounce → at execution | status |
|---|---|---|---|---|---|---|
| 4 | 30-30 | Cristina Bucsa | Cristina Bucsa | -17.92 | 0.69 → - | blocked (net cap) |
| 14 | 30-0 | Xinran Sun | Xinran Sun | -0.80 | 0.51 → - | blocked (net cap) |
| 77 | 40-15 | Xinran Sun | Xinran Sun | -2.28 | 0.44 → - | blocked (net cap) |
| 99 | 0-15 | Cristina Bucsa | Cristina Bucsa | -0.96 | 0.33 → - | blocked (net cap) |
| 100 | 15-15 | Xinran Sun | Xinran Sun | -1.31 | 0.63 → 0.67 | missed (book already moved) |
| 101 | 15-30 | Cristina Bucsa | Cristina Bucsa | -8.15 | 0.34 → - | blocked (net cap) |

The large leads (8-18 s) are points where the book's matched reprice comes long after the stamp; the latency write-up flags those as probable mismatches (`research/v2/tier0/LATENCY_SWEEP.md` §3). Without those, the 1 s trader beats the book on 4 points of the whole match.

![single points](../../results/replay/fig_point_race.png)

`results/replay/fig_point_race.png`: two points of the selected match with the assumed bounce, the official stamp, the book's reprice and the execution instant at V = 0, 0.5 and 1.0 s, and the result of each order. Left, point 126: the match's largest matched book move among quoted points (9.5c; a rule on the market move). Right, point 90: the largest matched move among points where the V = 0 order filled before the reprice (4.5c; chosen on the replay's own outcome, to show what a won race looks like, so it is not representative).

## 4. Per match (headline V = 1.0 s, and V = 0 for reference)

| match | points | replayable | calls | beat the book | fills (wrong) | c/share marked | $ marked | $ held | V = 0: fills, $ marked |
|---|---|---|---|---|---|---|---|---|---|
| Xinran Sun v Cristina Bucsa (selected) | 128 | 128 | 124 | 6 of 121 | 32 (6) | -0.19 | −$8 | +$26 | 39, −$30 |
| Iva Jovic v Harriet Dart | 191 | 114 | 113 | 3 of 109 | 34 (1) | -0.68 | −$42 | −$74 | 40, −$11 |
| Marie Bouzkova v Kimberly Birrell | 74 | 74 | 73 | 6 of 72 | 25 (6) | -1.55 | −$63 | −$17 | 29, −$49 |
| Sonay Kartal v Xinyu Wang | 60 | 60 | 60 | 7 of 59 | 14 (1) | -1.34 | −$36 | −$66 | 16, −$28 |
| Qinwen Zheng v Anna Kalinskaya | 170 | 52 | 49 | 5 of 47 | 14 (0) | -1.21 | −$29 | −$75 | 18, −$13 |
| Erika Andreeva v Lois Boisson | 42 | 42 | 42 | 8 of 41 | 23 (6) | -0.99 | −$40 | −$72 | 24, −$33 |
| Kamilla Rakhimova v Leylah Fernandez | 181 | 18 | 17 | 0 of 16 | 5 (1) | -0.06 | −$0 | −$8 | 4, −$7 |
| Belinda Bencic v Anastasia Zakharova | 144 | 8 | 0 | 0 of 0 | 0 (0) | - | +$0 | +$0 | 0, +$0 |
| Elena Rybakina v Alina Charaeva | 4 | 4 | 4 | 0 of 2 | 4 (0) | -1.53 | −$11 | −$101 | 4, −$10 |

Recorder coverage starts at 09:46 UTC, so the three early matches (Rakhimova-Fernandez, Bencic-Zakharova, Zheng-Kalinskaya) are mostly unreplayable; Rybakina-Charaeva has only 4 points in the frozen 12:45 UTC snapshot.

## 5. Sensitivity: all 36 cells (seed 0, pooled over the 9 matches)

| V | stamp lag | lead | network | fills | calls beating the book | correct fills before reprice | c/share marked [95 % CI] | $ marked | c/share held | $ held |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 s | 1 s | model | florida | 199 | 35 | 11 | -1.06 [-1.33, -0.79] | −$373 | -1.40 | −$493 |
| 0 s | 1 s | model | london | 213 | 45 | 15 | -0.98 [-1.24, -0.75] | −$371 | -1.34 | −$512 |
| 0 s | 1 s | zero | florida | 199 | 35 | 11 | -1.06 [-1.33, -0.79] | −$373 | -1.40 | −$494 |
| 0 s | 1 s | zero | london | 210 | 41 | 13 | -1.01 [-1.25, -0.79] | −$384 | -1.33 | −$508 |
| 0 s | 2 s | model | florida | 174 | 141 | 57 | -0.61 [-0.90, -0.37] | −$181 | -0.71 | −$213 |
| 0 s | 2 s | model | london | 182 | 166 | 65 | -0.52 [-0.85, -0.27] | −$165 | -0.70 | −$222 |
| 0 s | 2 s | zero | florida | 174 | 140 | 56 | -0.62 [-0.90, -0.39] | −$188 | -0.70 | −$210 |
| 0 s | 2 s | zero | london | 181 | 162 | 61 | -0.55 [-0.88, -0.25] | −$174 | -0.71 | −$226 |
| 0 s | 3 s | model | florida | 228 | 319 | 162 | -0.07 [-0.38, +0.27] | −$24 | +0.02 | +$6 |
| 0 s | 3 s | model | london | 232 | 341 | 165 | -0.10 [-0.40, +0.23] | −$36 | -0.03 | −$12 |
| 0 s | 3 s | zero | florida | 224 | 314 | 158 | -0.09 [-0.39, +0.25] | −$32 | -0.05 | −$17 |
| 0 s | 3 s | zero | london | 227 | 331 | 160 | -0.12 [-0.40, +0.22] | −$42 | -0.07 | −$27 |
| 0.5 s | 1 s | model | florida | 207 | 27 | 7 | -1.02 [-1.28, -0.78] | −$379 | -1.47 | −$548 |
| 0.5 s | 1 s | model | london | 207 | 28 | 7 | -1.02 [-1.28, -0.77] | −$378 | -1.46 | −$547 |
| 0.5 s | 1 s | zero | florida | 209 | 27 | 7 | -1.04 [-1.28, -0.81] | −$392 | -1.41 | −$533 |
| 0.5 s | 1 s | zero | london | 209 | 27 | 7 | -1.04 [-1.29, -0.81] | −$391 | -1.41 | −$532 |
| 0.5 s | 2 s | model | florida | 169 | 91 | 40 | -0.65 [-0.96, -0.39] | −$174 | -0.85 | −$226 |
| 0.5 s | 2 s | model | london | 166 | 94 | 40 | -0.66 [-0.96, -0.42] | −$176 | -0.84 | −$222 |
| 0.5 s | 2 s | zero | florida | 174 | 90 | 40 | -0.60 [-0.93, -0.30] | −$167 | -0.82 | −$225 |
| 0.5 s | 2 s | zero | london | 172 | 94 | 40 | -0.61 [-0.93, -0.32] | −$168 | -0.80 | −$221 |
| 0.5 s | 3 s | model | florida | 211 | 268 | 124 | -0.32 [-0.64, +0.01] | −$107 | -0.30 | −$100 |
| 0.5 s | 3 s | model | london | 213 | 277 | 133 | -0.26 [-0.60, +0.11] | −$88 | -0.27 | −$91 |
| 0.5 s | 3 s | zero | florida | 211 | 266 | 124 | -0.32 [-0.64, +0.01] | −$107 | -0.30 | −$100 |
| 0.5 s | 3 s | zero | london | 213 | 274 | 133 | -0.27 [-0.62, +0.11] | −$91 | -0.28 | −$94 |
| 1 s | 1 s | model | florida | 199 | 19 | 6 | -1.08 [-1.33, -0.83] | −$389 | -1.46 | −$531 |
| 1 s | 1 s | model | london | 200 | 21 | 7 | -1.06 [-1.34, -0.80] | −$384 | -1.46 | −$531 |
| 1 s | 1 s | zero | florida | 200 | 19 | 6 | -1.10 [-1.34, -0.88] | −$402 | -1.39 | −$513 |
| 1 s | 1 s | zero | london | 202 | 21 | 7 | -1.09 [-1.35, -0.86] | −$400 | -1.41 | −$517 |
| **1 s** | 2 s | model | florida | 151 | 35 | 9 | **-0.92** [-1.29, -0.57] | −$229 | -1.56 | −$387 |
| 1 s | 2 s | model | london | 154 | 45 | 15 | -0.94 [-1.33, -0.61] | −$239 | -1.50 | −$381 |
| 1 s | 2 s | zero | florida | 156 | 35 | 9 | -0.86 [-1.25, -0.43] | −$223 | -1.50 | −$388 |
| 1 s | 2 s | zero | london | 155 | 41 | 13 | -0.88 [-1.29, -0.45] | −$228 | -1.48 | −$386 |
| 1 s | 3 s | model | florida | 160 | 142 | 60 | -0.65 [-0.96, -0.34] | −$173 | -0.66 | −$174 |
| 1 s | 3 s | model | london | 165 | 167 | 68 | -0.58 [-0.94, -0.27] | −$166 | -0.65 | −$186 |
| 1 s | 3 s | zero | florida | 160 | 141 | 60 | -0.66 [-0.96, -0.37] | −$175 | -0.66 | −$176 |
| 1 s | 3 s | zero | london | 161 | 163 | 65 | -0.62 [-0.96, -0.30] | −$174 | -0.67 | −$189 |

The stamp lag matters most, as in the sweep: at 1.0 s the book has usually repriced before the assumed bounce, so almost no call beats it; at 3.0 s about two thirds of calls beat it at V = 0 and the result is near zero. The camera lead (0-100 ms) and London co-location (65 ms faster) change little.

## 6. Consistency check against the latency sweep

| | V = 0 | V = 0.5 s | V = 1.0 s |
|---|---|---|---|
| sweep, in sample, net c/share (headline reading) | +1.10 | +0.61 | +0.40 |
| sweep, burned OOS, net c/share | +0.58 | -0.02 | -0.38 |
| replay, net c/share marked [CI] | -0.61 [-0.90, -0.37] | -0.65 [-0.96, -0.39] | -0.92 [-1.29, -0.57] |
| sweep, in sample: calls before the reprice | 44 % | 19 % | 14 % |
| replay: calls that beat the reprice | 30% | 19% | 7% |

**Consistent:** in both, money is made only by correct calls that execute before the reprice; the share of such calls falls with V; the stamp lag dominates. **Different on purpose:** the sweep trades the historical ≥ 4c jumps and lets a correct call fill only before the reprice (a limit at the stale price), so its trades have bigger moves and no post-reprice fills; this replay calls every official point with a 1c-wider limit and the same net cap, which makes the cap bind on about half the calls. The replay's negative level is therefore not a contradiction of the sweep's in-sample curve; it is closer to the sweep's burned-OOS reading (CI including zero at V = 0), though still below it at V = 0.

## 7. What this does not show

* **No video.** No feed was bought, received or watched. V, the CV call, its lead and its 95 % precision are assumptions from the tier-0 model.
* **The bounce time is not observed.** It is the official stamp minus an assumed 1-3 s lag. Every number moves with that assumption (§5).
* **One day, 9 WTA matches, mostly WTA 1000 Beijing**, about 500 replayable points. The CIs are over 9 matches and are wide; a different day can differ.
* **Our orders do not move the book.** The real fast tier is already in the recording; we take what it left. We do not model being seen by makers.
* **Costs not deducted:** a feed licence, colocation, data.
* **Same data as the sweep's inputs.** The reprice times and books that parameterise the sweep come from this day, so agreement is a consistency check, not an independent test.

## 8. How to describe this in the paper

Accurate: *"We replay the trader on 9 WTA matches recorded live on 2026-10-03. For every official point we take the umpire's timestamp, assume the ball landed 2 s earlier, and assume a licensed video feed delivers it 1 s later (0 and 0.5 s as bounds). The simulated order is priced against the real Polymarket order book recorded at the instant it would have executed, after the venue's 1 s taker delay. We did not buy or receive match video."* Not accurate, and not to be written: that we received Polymarket or match footage over WebRTC (or any other way), that the replay used live video, or that the trader made money. A faster licensed feed is the stated limitation: the replay shows what a faster feed would have to beat (the reprice), not that one exists at a price that pays.

## Deviations from the protocol

None in the trading rule, the cells, the seeds or the statistics. Additions after P&L was seen, all descriptive: the accounting split of §2 (uses `t_book`, which is hindsight), the figures (the example points in `fig_point_race.png` are chosen by stated display rules, one of them on the replay's outcome), and the per-match V = 0 column in §4.

## Reproduce

```bash
.venv/bin/python scripts/match_replay.py          # ~2-3 min: parses the recording, replays 93 cells, writes everything
.venv/bin/python scripts/match_replay.py --figures-only   # redraw figures + this file
```

Recording lines scanned: 5,637,459. Receive latency (local receive - server timestamp) median 66 ms (p10-p90 63-109 ms); token 1's best ask equals 1 - token 0's best bid at 99.98% of captured instants (the two books mirror each other).

Outputs in `results/replay/`: `replay.json` (label, model, matches, every cell overall and per match, seed summary, selected-match story), `points.csv` (every official point of the 9 matches at V = 0, 0.5, 1.0 s, headline settings, seed 0), `seed_robustness.csv`, `selected_match_book.csv` (top of book every 250 ms), `fig_selected_match.png`, `fig_point_race.png`, `fig_race.png`, `fig_pnl_by_v.png`.
