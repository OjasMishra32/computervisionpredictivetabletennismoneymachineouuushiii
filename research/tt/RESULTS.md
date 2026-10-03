# Table tennis TT1–TT4: results of the single pre-registered run

| | |
|---|---|
| Pre-registration | `HYPOTHESIS_TT.md` (`0f01362`) |
| Dataset | `a7105a6` (`research/tt/DATA.md`) |
| Pre-run decisions | `research/tt/DEVIATIONS.md` TT-D1–D8, committed in `eb0e692` before the run |
| Run | `scripts/tt_analyze.py` at commit `eb0e692`, 2026-10-03 19:23:14 UTC |
| Logs | `results/oos_peeks.log` ("table tennis TT1-TT4 evaluated (first run)") and `results/tt/peeks.log`, both written before any result was printed |
| Where it ran | Locally on the laptop. HiPerGator was not used. |
| Corrections after verification | `research/tt/DEVIATIONS.md` TT-C1–TT-C4 (labels, one count, post-hoc wallet figures); `results/tt/corrections.json` (`research/tt/corrections.py`). TT1–TT4 were **not** re-run, and no verdict changed. |

All the numbers below come from `results/tt/results.json`. The exceptions are the post-hoc
section, which comes from `results/tt/posthoc.json` (`research/tt/posthoc.py`) and `results/tt/audit_tt3.json`,
and the corrected labels and counts, which come from `results/tt/corrections.json` and `results/tt/audit_checks.json`.

TT5 is not part of this run (TT-D1). It runs separately as `scripts/signal_decay.py`.

## Verdicts

| test | verdict | why |
|---|---|---|
| **TT1** calibration | **FAIL** | In-play: **not judged**. No bin reaches 30 matches; the largest has 19. Closing: **not calibrated**. 5 of 9 judged bins miss at 95%, and 3 still miss at the Bonferroni level. |
| **TT2** fast tier | **FAIL (no fast tier detected)**, underpowered; **structurally untestable on this sample** | 0 wallets qualify in any of the 4 evaluated months, so there are 0 fast-tier prints. A wallet needs ≥ 10 earlier matches; before 2026-04, -05, -07 and -09 there were 3, 7, 8 and 18 evaluable matches, so only 2026-09 could qualify anyone, and at most 9 matches could hold fast-tier prints against the 30-match bar (TT-C1). |
| **TT3** frozen v2, blind | **FAIL (no trades), underpowered** in IS and in OOS; **structurally untestable on this sample** | The fast-tier shadow is empty, so v2 has nothing to trade (TT-D5). 0 matches with trades in either period, against the 30-match bar; IS has 24 evaluable matches and OOS 3, so neither could reach it (TT-C1, TT-C2). |
| **TT4** capacity | **"capacity is negligible"** | v2 deployed $0 per calendar day, against the $1,000 bar. |

Plainly: **the tennis structure could not be found in table tennis, and nothing could be traded.**
- The tennis structure means calibrated prices, a persistent fast tier, and the v2 edge.
- The reason is not a negative edge. The market is too thin for any of these tests to have material:
  - 39 of 3,588 matches (1.09%) have the 20 in-play prints the pipeline needs, and 27 of them also have a
    detected jump;
  - those 27 matches hold 113 prints in the 0–3 s post-detection window, across all months;
  - the open books right now are 94¢ wide with nothing near the mid.
- **TT2 and TT3 say nothing about whether v2 carries over to another sport.** Their FAILs were close to
  certain from the match counts before the run (TT-C1). Wherever these results sit next to tennis (the note,
  the deck, the financials), they are not evidence against v2 generalising.

## Counts

- UTT: 3,588 markets, 2,870 IS and 718 OOS, cut 2026-09-16 05:30 UTC.
- **Evaluable matches** (≥ 20 in-play prints and a detected jump): **27**. That is Setka IS 16, Setka
  OOS 3 and WTT IS 8, with 1,002 print rows. 39 matches reach 20 in-play prints; 12 of them (10 WTT,
  2 Setka, all IS) were dropped because no jump was detected, the unchanged tennis behaviour
  (`results/tt/audit_checks.json` `ge20_inplay`).
- So OOS has 3 evaluable matches.

## TT1: calibration (`run_all.calibration()` unchanged)

### In-play
450 observations (the first print per match-minute) from 27 matches. **No bin has ≥ 30 matches,
so nothing is judged**, and per TT-D2 the test reads "not judged".

| fav bin | obs | matches | mean price | win rate | 95% CI |
|---|---|---|---|---|---|
| [0.5, 0.6) | 73 | 17 | 0.540 | 0.616 | 0.500–0.719 |
| [0.6, 0.7) | 66 | 19 | 0.644 | 0.697 | 0.504–0.831 |
| [0.7, 0.8) | 62 | 17 | 0.746 | 0.726 | 0.424–0.941 |
| [0.8, 0.85) | 32 | 14 | 0.817 | 0.875 | 0.667–1.000 |
| [0.85, 0.9) | 40 | 15 | 0.875 | 0.850 | 0.610–1.000 |
| [0.9, 0.93) | 23 | 10 | 0.910 | 0.739 | 0.493–1.000 |
| [0.93, 0.95) | 11 | 5 | 0.936 | 0.909 | 0.667–1.000 |
| [0.95, 0.97) | 27 | 11 | 0.956 | 0.963 | 0.857–1.000 |
| [0.97, 0.98) | 12 | 8 | 0.971 | 1.000 | 1.000–1.000 |
| [0.98, 0.99) | 34 | 10 | 0.983 | 0.971 | 0.887–1.000 |
| [0.99, 1.0) *(never judged)* | 70 | 14 | 0.995 | 1.000 | 1.000–1.000 |

### Closing
The closing price is the last tape fill in [start − 24 h, start).
- 3,571 matches have `res` in {0, 1}. **Only 780 have any fill in that window**; 2,791 have none.
- 9 bins are judged. **5 fail at 95%.**
- At the Bonferroni level (99.44%, k = 9), 3 still fail: [0.95, 0.97), [0.98, 0.99) and [0.99, 1.0).
- Every bin from 0.8 up has the favourite **winning less often than its price**.

| fav bin | matches | mean price | win rate | edge (¢) | 95% CI | Bonferroni CI | judged / verdict |
|---|---|---|---|---|---|---|---|
| [0.5, 0.6) | 258 | 0.523 | 0.492 | −3.1 | 0.426–0.550 | 0.399–0.578 | covers |
| [0.6, 0.7) | 119 | 0.648 | 0.580 | −6.8 | 0.483–0.664 | 0.444–0.686 | covers |
| [0.7, 0.8) | 81 | 0.741 | 0.704 | −3.7 | 0.605–0.797 | 0.548–0.852 | covers |
| [0.8, 0.85) | 37 | 0.821 | 0.676 | −14.5 | 0.514–0.811 | 0.460–0.865 | **misses** (Bonf. covers) |
| [0.85, 0.9) | 40 | 0.868 | 0.850 | −1.8 | 0.725–0.950 | 0.700–0.975 | covers |
| [0.9, 0.93) | 62 | 0.914 | 0.790 | −12.3 | 0.694–0.887 | 0.645–0.929 | **misses** (Bonf. covers) |
| [0.93, 0.95) | 18 | 0.938 | 0.833 | −10.5 | 0.638–1.000 | | not judged |
| [0.95, 0.97) | 42 | 0.958 | 0.810 | −14.9 | 0.690–0.905 | 0.667–0.952 | **misses** (Bonf. misses) |
| [0.97, 0.98) | 20 | 0.972 | 0.800 | −17.2 | 0.600–0.950 | | not judged |
| [0.98, 0.99) | 43 | 0.982 | 0.814 | −16.8 | 0.698–0.919 | 0.637–0.945 | **misses** (Bonf. misses) |
| [0.99, 1.0) | 60 | 0.992 | 0.800 | −19.2 | 0.700–0.900 | 0.667–0.927 | **misses** (Bonf. misses) |

### Secondaries (reported, not tested)
- **Pooled in-play (won − fav), fav in [0.5, 0.99):** +1.22¢, CI −9.97 to +9.86. That is 380
  observations from 27 matches.
- **In-play truncated at the first fav ≥ 0.99 print:** 332 observations from 27 matches. Still no bin
  has ≥ 30 matches, so it is not judged.
- **In-play by league:** neither league has a judged bin. Setka has 211 observations from 19 matches;
  WTT has 239 from 8.
- **Closing by league:**
  - **Setka** (461 matches) reads "calibrated" on its 3 judged bins:
    - [0.5, 0.6): 0.523 vs 0.464 (0.402–0.534);
    - [0.6, 0.7): 0.649 vs 0.571 (0.467–0.667);
    - [0.7, 0.8): 0.738 vs 0.667 (0.544–0.790).

    Its unjudged high bins are far off (fewer than 30 matches each):
    - [0.8, 0.85): 0.819 priced, 0.556 won (18 matches);
    - [0.9, 0.93): 0.905, 0.308 (13);
    - [0.98, 0.99): 0.983, 0.533 (15);
    - [0.99, 1.0): 0.990, 0.583 (24).
  - **WTT** (319 matches) reads "not calibrated". 1 of its 5 judged bins misses at 95%:
    [0.95, 0.97), priced 0.957, won 0.816 (0.684–0.921). None misses at the Bonferroni level
    (99%).

    Its other judged bins:
    - [0.5, 0.6): 0.525 vs 0.612 (0.490–0.755);
    - [0.85, 0.9): 0.870 vs 0.900 (0.800–1.000);
    - [0.9, 0.93): 0.916 vs 0.918 (0.837–0.980);
    - [0.99, 1.0): 0.992 vs 0.944 (0.861–1.000).

**What the closing failure is (post-hoc, see below).** The "closing price" here is usually one
tiny fill, not a market price.
- The median closing fill is $5.00, and 51% of them are under $5.
- In Setka favourites priced ≥ 0.80, the median closing fill is $1.99. In 90% of them the taker bought
  the favourite, and those favourites won 55.6% at an average price of 0.925.
- The live book snapshot (TT4) shows Setka books quoted about 3¢ / 97¢. On such a book any small
  buy prints near 97¢, whoever is the real favourite.

So the closing test fails because a print on a 94¢-wide book is not an estimate of probability.
Read it as a statement about the tape, not as a fadeable edge. Nobody could have sold those
favourites in size, because there was nothing to sell into.

## TT2: fast tier (`fasttier.walk_forward(P, start_month=2, bucket="bucket_c")`)
- The tape has prints in 2026-02, 03, 04, 05, 07 and 09, so the evaluated months are **2026-04,
  2026-05, 2026-07 and 2026-09**.
- **Qualified wallets: 0, 0, 0, 0.**
- The parity checks against `walk_forward`'s own table passed.

| month | evaluable matches before it (bar: 10) | qualified wallets | fast-tier prints | other takers' 0–3 s prints (matches) | others' net30, ¢/share (95% CI) |
|---|---|---|---|---|---|
| 2026-04 | 3 | 0 | 0 | 9 (4) | −0.93 (−10.63 to +0.90) |
| 2026-05 | 7 | 0 | 0 | 2 (1) | −12.59 (one match) |
| 2026-07 | 8 | 0 | 0 | 44 (10) | −3.34 (−7.21 to +0.39) |
| 2026-09 | 18 | 0 | 0 | 47 (9) | +3.50 (−0.18 to +7.00) |

The second column comes from `results/tt/corrections.json` (`structural`): only 2026-09 had enough earlier
matches for any wallet to reach the ≥ 10-match qualification bar.

**Statistics**
- Fast net30: none, because there are no prints.
- **Others' net30: −0.16¢ (CI −3.06 to +2.45)**, from 102 prints in 24 matches. 53% of those prints come
  from one wallet (`0xc07d…`; post-hoc, see below), so this figure is largely that wallet.
- Gap: none.
- Others in months with a qualified wallet: none.
- Fast-tier prints by period: 0 IS and 0 OOS.

**Criteria**
- (a) fast > 0 with CI excluding 0: no.
- (b) others < 0 with CI excluding 0: no.
- (c) fast > 0 in two-thirds of months: no (0 months have fast prints).
- (d) fast > 0 in IS and OOS: no.

**Verdict:** FAIL (no fast tier detected), labelled **underpowered** (0 matches with fast-tier prints,
against the bar of 30) and **structurally untestable on this sample**: even had a wallet qualified in 2026-09,
the only month where one could, that month has 9 matches, so the 30-match bar was out of reach (TT-C1).

**Others' net30 by causal bucket**, point estimates in the evaluated months:

| no jump | 0–3 s | 3–6 s | 6–10 s | 10–20 s | 20–40 s | 40–120 s | > 120 s |
|---|---|---|---|---|---|---|---|
| −1.86 | −0.16 | −0.08 | −1.29 | +1.16 | −2.50 | +1.18 | −1.56 |

The figure is `results/tt/fig_fasttier.png`.

## TT3: the frozen v2 rule, blind (`G_50pct_net100`, causal)
- The fast-tier shadow has **0 rows**, so v2 has no opportunity set (TT-D5). `v2.run` was not
  called.
- **IS: no trades. OOS: no trades. TT3 FAILS ("no trades"), labelled underpowered in both periods**
  (0 matches with v2 trades, against the bar of 30). The first run's `results.json` has `"labels": []` for
  both periods, because `tt3()`'s empty-shadow path never set the label. The label is applied here and in
  `results/tt/corrections.json`; the code path is fixed in `scripts/tt_analyze.py` for any logged re-run
  (TT-C2). The independent recompute (`results/tt/audit_tt3.json`) also marks both periods underpowered.
- **Structurally untestable on this sample** (TT-C1): IS has 24 evaluable matches and OOS 3, both under the
  30-match bar. v2 could only have traded in 2026-09, the one month where a fast tier could qualify, and that
  month would have been v2's empty-training month, where trades hold about 0 shares (TT-D6).
- Every TT3 secondary is undefined because there are no trades: $ P&L, Sharpe, drawdown, worst day,
  profitable days, win rate, return on capital, by league, and the doubled-cost stress.
- The figure `results/tt/fig_v2_equity.png` says so for each panel; it does not plot an empty line.

## TT4: liquidity and capacity (descriptive)

### Volume per match
Listed volume is in **shares**, not dollars (DATA.md). In each cell: total; mean / median / p90 per
match.

| group | markets | listed volume (shares) | tape USD | pre-start USD | in-play window USD |
|---|---|---|---|---|---|
| all | 3,588 | 1,016,076; 283 / 41 / 400 | $652,468; $181.85 / $21.04 / $274.41 | $161,205; $44.93 / $0 / $27.00 | $491,262; $136.92 / $13.97 / $224.21 |
| Setka | 2,706 | 358,608; 133 / 19 / 187 | $248,396; $91.79 / $9.90 / $99.00 | $16,610; $6.14 / $0 / $6.62 | $231,787; $85.66 / $7.95 / $88.27 |
| WTT | 881 | 657,461; 746 / 190 / 1,330 | $404,066; $458.64 / $162.94 / $830.12 | $144,596; $164.13 / $0 / $142.88 | $259,470; $294.52 / $126.35 / $579.73 |
| other | 1 | 8 | $5.98 | $0 | $5.98 |
| IS (all) | 2,870 | 943,496; 329 / 50 / 436 | $605,722; $211.05 / $34.19 / $290.87 | $152,254; $53.05 / $0 / $25.37 | $453,467; $158.00 / $23.22 / $247.72 |
| Setka IS | 1,988 | 286,027; 144 / 23 / 187 | $201,650; $101.43 / $12.93 / $97.80 | $7,658; $3.85 / $0 / $3.40 | $193,992; $97.58 / $9.90 / $93.28 |
| OOS (all Setka) | 718 | 72,581; 101 / 10 / 183 | $46,746; $65.11 / $5.83 / $105.10 | $8,951; $12.47 / $0 / $29.66 | $37,795; $52.64 / $3.90 / $73.78 |

WTT IS is identical to the WTT row: every WTT market is IS.

### Depth proxies
These come from the raw in-play tape of every UTT market (TT-D7).

| group | in-play fills | print USD (median / mean / p90) | in-play prints per minute (median / mean / p90) | fills with a two-sided spread proxy (markets) | spread proxy: pooled median / median of market medians |
|---|---|---|---|---|---|
| all | 10,645 | $7.66 / $46.15 / $98.94 | 0.0072 / 0.0155 / 0.0342 | 799 (266) | 1.0¢ / 0.0¢ |
| Setka | 6,633 | $6.16 / $34.94 / $36.60 | 0.0072 / 0.0162 / 0.0350 | 713 (226) | 1.0¢ / 0.0¢ |
| WTT | 4,008 | $10.72 / $64.74 / $122.42 | 0.0070 / 0.0133 / 0.0290 | 86 (40) | 0.80¢ / 0.80¢ |
| IS | 9,347 | $9.13 / $48.52 / $99.00 | 0.0073 / 0.0163 / 0.0357 | 635 (206) | 1.0¢ / 0.60¢ |
| OOS | 1,298 | $3.45 / $29.12 / $50.00 | 0.0072 / 0.0124 / 0.0259 | 164 (60) | 0.0¢ / 0.0¢ |

- A median 0.0072 prints per minute is **one print every 2.3 hours** of the start-to-close window.
- Only 7.5% of in-play fills (799 of 10,645) had a fresh print on the other side within 30 s, which
  the spread proxy needs. The proxy's 0–1¢ describes those few moments, not a standing book.

**Bucket figures** (the 27 matches with prints):

| | matches | detected jumps | USD in the causal 0–3 s bucket | USD per detection | spread proxy median |
|---|---|---|---|---|---|
| all | 27 | 90 | $8,063.59 | $89.60 | 2.90¢ |
| Setka | 19 | 76 | $6,785.13 | $89.28 | 2.95¢ |
| WTT | 8 | 14 | $1,278.46 | $91.32 | 2.54¢ |

### Fast-tier volume and what v2 could deploy
- **Fast-tier volume: $0.** There are 0 prints, in 0 matches, on 0 active days. Each evaluated month
  (2026-04, 05, 07, 09) has $0.
- **v2: 0 trades**, which means $0 deployed per calendar day, $0 peak locked and $0 P&L.
- **Capacity rule:** $0 < $1,000 per calendar day, so **"capacity is negligible."**
- **Context, not a comparison.** Tennis v2 over the same evaluated months (2026-04, 05, 07, 09;
  122 calendar days):
  - 37,517 trades in 5,491 matches;
  - **$8,400.75 deployed per calendar day**;
  - $198.25 P&L per calendar day.

  Source: `data/v2_trades_is_oos.parquet`.

### Book snapshot
This is one snapshot of public clob `/book`, taken 2026-10-03 19:24:32 UTC. It is not history.
- It covers the 300 open table tennis moneylines with start nearest to now, all Setka. All 300 books
  were read.
- 251 are two-sided, and all of them are pre-match:
  - median spread **94¢** (mean 89.7¢, p90 94¢);
  - **USD resting within ±1¢ and ±2¢ of the mid: $0 in all 251.**
- 49 markets had a start time already past. **None of them had a two-sided book.**

## Sensitivity: the 96 zero-listed markets added (TT-D8; no verdict changes)
- UTT plus the 96 markets is 3,684 markets: 2,966 IS and 718 OOS.
- There are 34 evaluable matches (Setka IS 16, Setka OOS 3, WTT IS 15) and 1,274 print rows.
- **TT1:** FAIL, with the same reasons. In-play is not judged; closing has 9 judged bins, with the same
  5 missing.
- **TT2:** FAIL (no fast tier detected), underpowered, with 0 qualified wallets in every month.
  - Others' net30 is unchanged at −0.16¢ (−3.06 to +2.45).
  - The 7 added evaluable WTT matches are all in March, which is a training-only month.
- **TT3:** FAIL (no trades); 0 matches with trades, so also underpowered.
- **TT4:** v2 deploys $0 per day.

## Post-hoc diagnostics
These are not pre-registered and change no verdict (`research/tt/posthoc.py`, logged).

**The closing observation**

| group | matches | mean fav | won | closing fill USD (median / p90) | share < $5 | taker bought the fav | minutes before start (median) |
|---|---|---|---|---|---|---|---|
| all | 780 | 0.733 | 0.653 | $5.00 / $31.01 | 51% | 67% | 113 |
| Setka, fav < 0.80 | 371 | 0.592 | 0.526 | $5.00 / $12.55 | 50% | 51% | 190 |
| Setka, fav ≥ 0.80 | 90 | 0.925 | 0.556 | $1.99 / $100.00 | 66% | 90% | 39 |
| WTT, fav < 0.80 | 87 | 0.604 | 0.667 | $3.70 / $17.65 | 59% | 71% | 65 |
| WTT, fav ≥ 0.80 | 232 | 0.934 | 0.888 | $8.14 / $103.63 | 46% | 83% | 68 |

The median match with a closing observation has 2 pre-start fills and $18.34 of pre-start USD.

**How far from the fast-tier thresholds** (≥ 30 causal 0–3 s prints over ≥ 10 matches before the
month, and t > 3):
- Across all months, the causal 0–3 s bucket holds 113 prints from 28 wallets in 27 matches.
- Before each evaluated month, the most active wallet had:

  | evaluated month | prints | matches |
  |---|---|---|
  | 2026-04 | 1 | 1 |
  | 2026-05 | 2 | 1 |
  | 2026-07 | 2 | 1 |
  | 2026-09 | 31 | 6 |

- The 31 prints in 6 matches before 2026-09 belong to one wallet (`0xc07d…`), and it is the same wallet that
  ends the window with 58 bucket prints in 14 matches. Only then could it pass the count thresholds, and no
  month is left to evaluate it on.
- **Its t-stat** (mean 30 s markout over its sd / √matches, the qualification statistic): **−0.001** on the 31
  prints before 2026-09, and **0.70** on all 58, against the bar of t > 3 (`results/tt/audit_tt3.json`
  `walk_forward`, `posthoc`). The one wallet active enough to measure shows no edge.
- **How concentrated the bucket is.** That wallet holds 51% of the 113 prints in the 0–3 s bucket, 53% of
  TT2's "others" prints, and 28% of all 1,002 print rows. TT2's "others' net30 −0.16¢ [−3.06, +2.45]" is
  therefore largely one wallet.
- **Copying every 0–3 s print to resolution** (an upper bound on v2's opportunity set: any wallet, net of each
  market's fee; `audit_tt3.json` `posthoc`): IS, 100 prints in 24 matches, −12.93¢ print-weighted
  [−21.20, −5.27] and +0.58¢ share-weighted [−10.39, +8.47]. OOS has 13 prints in 3 matches, so its CI is not
  interpretable.

## Liquidity verdict
**Polymarket table tennis cannot carry this strategy family today. On these numbers, it is not a
venue for any size-bearing taker strategy.**
- **Volume.** Over about 7.5 months (2026-02-15 to 2026-10-03) and 3,588 traded matches, the whole tape is $652k. The median match
  trades $21 (Setka $9.90, WTT $163). Half of all closing fills are under $5.
- **Print density.**
  - In-play prints arrive at a median of one every 2.3 hours of the market window.
  - 39 matches (1.09%) reach the 20 in-play prints the tennis pipeline needs; 27 of them also have a
    detected jump (12 dropped, the unchanged tennis behaviour). Keeping the 12 would not change TT1: the
    largest judgeable in-play bin rises from 19 to 23 matches, still under 30 (post-hoc,
    `audit_checks.json`).
  - The causal 0–3 s window after a detected jump, which is where the tennis edge lives, saw $8,064
    in total, or about $90 per detected jump.
- **Books.** The open books are a market-maker placeholder: a 94¢ spread and $0 within 2¢ of the
  mid. None of the markets past their start time had a two-sided book.
- **Where the volume went.** WTT, the only league with $100s per match, has no moneyline in the catalogue
  after 2026-07-06. Setka, which replaced it, runs at a median $5.83 per match in OOS.
- **Comparison with tennis.** Tennis v2 deployed $8,401 per calendar day over the same months. Table
  tennis v2 deployed $0, because no wallet traded often enough for the walk-forward to identify a
  fast tier.

**What this run does not say.**
- It does not say table tennis prices are miscalibrated in a tradeable way. The closing "edge" sits
  on $2–$5 prints against an empty book.
- It cannot say whether table tennis has a fast tier. The one wallet active enough to measure shows no
  edge (t = 0.70 over all months, against a bar of 3). Nobody else traded often enough to be measured.
- TT2 and TT3 are not evidence against v2 carrying over to another sport. On this sample they could not
  have passed (TT-C1).
- It does not say our table tennis CV has no value. That needs a liquid venue, and TT5 asks the
  latency question separately.

**What would change it:** a table tennis venue with standing two-sided depth near the mid, and
in-play prints counted per minute rather than per hour. By TT3's own rule, any table-tennis-specific
filter would be a new hypothesis with a fresh forward window.

## Files
- `scripts/tt_analyze.py`: the run.
- `research/tt/posthoc.py`: the diagnostics.
- `research/tt/DEVIATIONS.md`: the pre-run decisions.
- `results/tt/results.json` and `results/tt/posthoc.json`: the numbers.
- `results/tt/fig_fasttier.png` and `results/tt/fig_v2_equity.png`: the figures.
- `results/tt/peeks.log`: the run log.
- No v2 trade file was written, because there were no trades.
- `research/tt/corrections.py` and `results/tt/corrections.json`: the post-run label corrections (TT-C1–TT-C4).
  The script also redraws both figures with the corrected labels.
- `research/tt/audit_tt3.py`, `research/tt/audit_checks.py` and their JSON: the independent audit.
