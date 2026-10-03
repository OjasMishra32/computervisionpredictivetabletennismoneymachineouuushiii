# COURTSIDE: allocation review by a systematic-trading PM

Written 2026-10-03, about 19:10 UTC, against `main` at `b694498` plus the untracked work in the tree. The
review is adversarial on purpose: it lists what a PM at a systematic fund, or a hackathon judge, would raise
before putting money or points on this. Paper only: nothing here places an order or reads a key.

**Update, about 19:45 UTC.** Every [COMPUTE-NOW] item has now been run (section "Compute-now results" below;
`scripts/pm_compute.py` → `results/financials/pm_compute.json`). `scripts/financials.py` was re-run and now
carries the 1 s / 5% rows, break-even fees, ex-ante capital, the corrected tier-0 headline and the table-tennis
verdicts. `docs/RISK.md` was brought up to date. Edits needed in files this review does not own (NOTE, README,
Devpost, compliance) are listed line by line in `research/financials/CORRECTIONS.md`. The verdict is unchanged.

**Read:** `docs/NOTE.md` (source of `docs/NOTE.pdf`), `README.md`, `docs/COMPLIANCE.md`, `docs/RISK.md`,
`research/financials/FINANCIALS.md`, `research/rigor/RESULTS.md` (including "Verifier corrections"),
`research/v2/{expand,lowloss,maker,crossmarket,latency,livefill,tier0,sizing}/` results and deviations,
`HYPOTHESIS_V2.md`, `DEVIATIONS.md`, and the results files `results/v2/*.json`, `results/expand/results.json`,
`results/lowloss/results.json`, `results/maker/oos.json`, `results/tier0/results.json`,
`results/financials/financials.json`, `results/risk/risk_stats.json`, `results/summary.json`,
`results/oos_peeks.log`, `results/live/summary.json`.

**Where the numbers come from.** Every number below is quoted from a file in this repo, which is named next
to it. Derived figures show their arithmetic and inputs. A few figures are new. They come from
`research/financials/pm_checks.py`, which writes `results/financials/pm_checks.json`. That script reads
**in-sample trades only** and first reproduces `results/v2/causal.json` (IS P&L $40,425.72, Sharpe 14.483)
before it computes anything. It reads no burned-OOS, U2 or forward data, so it adds no line to
`results/oos_peeks.log`. External costs are the cited ESTIMATES and labelled ASSUMPTIONS in `FINANCIALS.md` §1.
No new external price was looked up.

## Verdict: no allocation today

1. **The book with the good numbers is not one we can run.** v2 is priced at the fast tier's own fills
   (NOTE §3). Our executable copy of the same trades, entered after the delay, loses −0.89¢/share
   [−1.10, −0.68] IS and −1.89¢ [−2.41, −1.36] on the burned OOS (`docs/RISK.md` stress table).
2. **No strategy has passed a blind out-of-sample test.** v1 lost $36k (blind). v2 and v2-safe failed the
   pre-registered U2 test. Maker v1 failed its blind OOS. The v2 forward test is pending. The corrected tier-0
   counterfactual landed at 19:20 UTC (`results/tier0/results.json` `headline`, `VERIFIED` marker present):
   $88.8/day IS and $46.4/day burned OOS, against $1,151/day of fixed costs even at the low assumption.
3. **The economics are break-even at best.** In today's fee and delay regime (1 s, 5%), in-sample v2 makes
   $179/day (`pm_checks.json`) against $167/day of central fixed costs (`FINANCIALS.md`): about +$12/day,
   or $65.5k a year against $60.9k a year. On the burned OOS it makes $92/day, which is −$75/day after
   costs. The maker makes −$12/day after costs on its blind OOS.

**What would change the call:** forward primary A passes, the corrected tier-0 clears its fixed costs, the
feed licence is quoted below the opportunity, and there is a legal route to a venue. The table under
"Pending tests" sets out what each outcome would mean.

## Tags and severity

- **[COMPUTE-NOW]**: can be computed from data already in the repo in under 30 minutes. The item says how.
- **[PENDING]**: waits on a test that is running: the v2 forward test, the maker live paper session, the
  table-tennis study, or the tier-0 revision.
- **[WRITE]**: documentation only, because the number already exists.
- **[OUT-OF-SCOPE]**: needs data or money we do not have.
- **S1** changes the allocation decision or risks the criterion-5 cap. **S2** is material to a headline
  number or a rubric criterion. **S3** is an inconsistency or missing analysis a careful reader will find.
  **S4** is hygiene.

## Compute-now results (about 19:45 UTC)

Run with `.venv/bin/python scripts/pm_compute.py quick` (about 7 s) and `... sens` (about 5 min, one process,
IS prints only). Output: `results/financials/pm_compute.json`. No rule changed and nothing was selected; every
IS rebuild first reproduces `results/v2/causal.json` (P&L $40,425.72, Sharpe 14.483) or stops. Only P07 reads
burned-OOS rows; P17 re-ran committed scripts on a clone. Both are logged in `results/oos_peeks.log`.

| item | result | where it now lives |
|---|---|---|
| **P07** wallet-clustered CI | IS +1.38¢ [0.57, 2.30] (80 wallets); burned OOS +0.60¢ **[−0.45, 2.38]** (86 wallets; top wallet 48.4%, top 5 142.1% of P&L). The note's [−0.60, 2.11] does not reproduce: across 4 seeds and 1,000–10,000 draws the bounds stay within [−0.53, −0.45] and [2.28, 2.41]. Logged OOS read | `pm_compute` `p07_wallet_clustered_ci`; RISK R2; CORRECTIONS N1 |
| **P14** volume bands, IS | By **pre-start** volume (known at the start): < $1k +1.88¢ [1.14, 2.63]; $1–5k +1.41 [1.03, 1.80]; $5–20k +1.18 [0.79, 1.57]; $20–100k +1.39 [0.92, 1.84]; ≥ $100k +1.43 [0.34, 2.50]. Matches under $5k pre-start carry 43% of shares and 47% of P&L. The lifetime-volume bands reproduce `risk_stats` exactly | `pm_compute` `p14_volume_bands_is`; RISK R9 |
| **P14** point-in-time universe | Pre-start ≥ $5k (a subset of the lifetime ≥ $5k universe), rebuilt walk-forward on IS prints: 4,731 of 9,581 IS matches, 25,092 trades, +1.29¢ [0.98, 1.59], $18,988, Sharpe 10.0. **1 s / 5% slice: +0.44¢ [−0.14, 1.01].** The frozen book's own trades in those matches (no refit): +1.28¢ [0.99, 1.56], $21,321. At ≥ $20k pre-start: +1.35¢ [0.81, 1.86], $7,615, Sharpe 6.5; 1 s / 5% +0.17¢ [−0.73, 1.06] | `pm_compute` `p15_sensitivity_is.runs`; RISK R9; CORRECTIONS N14 |
| **P15** threshold surface, IS | 19 one-step runs (detector 3/6¢, short window 5/20 s, long window 30/120 s, entry window 2/4/6 s, ≥ 20/40 prints, ≥ 5/15 matches, t > 2/4, n₀ 100/400, zone 0–1 / 0.1–0.9): +1.21 to +1.46¢/share, every CI above 0; Sharpe 9.0–17.6; P&L $21.8k–48.0k (base +1.38¢, 14.5, $40.4k). 1 s / 5% slice: +0.66 to +1.39¢, every CI above 0. The print and match counts never bind; the 6¢ detector halves P&L ($21.8k) | `pm_compute` `p15_sensitivity_is`; RISK R10; CORRECTIONS N15 |
| **P17** clean clone | Clone of `56a9c8f` in scratch, `data/` linked read-only by file, `.venv` linked. (1) `reproduce.sh` fails at once when `PY` is a path with spaces (unquoted `$PY`; CORRECTIONS O7). (2) `run_all.py --oos` with 1 worker (the ≤ 2-process budget) printed nothing in 18 min (its first stage, the H1/H2/H5 grids); stopped, as this item allows. (3) `v2_causal.py`, `v2_cost_stress.py`, `note_metrics.py`, `factor_regression.py`, `v2_figures.py` ran clean (6 min) and reproduced `results/v2/{causal,burned_oos,cost_stress,note_metrics,factor_regression}.json` with **0 differences** (tolerance 1e-9) and left `results/figures/` byte-identical. The v2 steps need none of the untracked files (P05) | this table; CORRECTIONS O7, O8, C2 |
| **P24** factor regression, IS only | Every calendar day (factors and RF 0 off trading days), excess return, ×365: alpha +0.675%/day (t = 9.5), 246% a year; market beta 0.18 (t = 1.54), largest factor t 1.54, R² 2.3%, 206 days. Weekdays only (×252): alpha t 8.1, largest t 1.37, R² 2.7%, 142 days. Same conclusion as the committed file, which included Aug 25–31 burned-OOS days | `pm_compute` `p24_factor_regression_is`; RISK R14; CORRECTIONS N5, O2 |
| **P25** kill rules on IS | Trailing 30-day edge rule (causal: trades entered in the last 30 days and already resolved): edge min +0.74¢, median +1.47¢, so 206/206 days at full size; the rule never fires. 5% drawdown stop: never (worst −2.01%). $1,000 daily stop: never (worst −$551). Per-book stop at v2's 3.86 σ: v2 $1,000, v2-safe $545, maker $599 (the $1,000 stop is 36% of the maker's $2,779 capital; the scaled stop would fire on 1 IS day). v2 vs maker IS daily correlation −0.04 | `pm_compute` `p25_kill_rules_is`; RISK kill table and R14; CORRECTIONS O4 |
| **P26** gross edge split, IS | Of +1.99¢ gross: fill vs mid 30 s later (the stale quote) **+1.56¢ [1.50, 1.62]** (79%); 30 s to resolution +0.43¢ [0.21, 0.64]. Finer: fill vs 5 s mid +1.13¢, 5 s→30 s +0.43¢. Fees −0.61¢, net +1.38¢. In the 1 s / 5% slice: stale quote +1.58¢ [1.48, 1.69], drift +0.38¢ [−0.04, 0.81] (CI includes 0) | `pm_compute` `p26_gross_edge_split_is`; CORRECTIONS N16 |
| **P10** tier-0 bound | Corrected headline (20-seed means): IS +1.10¢ [0.82, 1.38], $88.8/day, Sharpe 11.4; burned OOS +0.58¢ [−0.08, 1.21], $46.4/day, Sharpe 7.3. To cover the low fixed-cost case ($1,151/day) it would need 13.0× (IS) or 24.8× (OOS) its trading P&L. Decision table: **stop** | `FINANCIALS.md` headline and §4 |

## Findings, most severe first

### S1: critical

**P01 [WRITE] The headline v2 numbers measure an opportunity. They are not a strategy we can trade.**
- The note's own headline does say this. But Sharpe 14.5 and 253% a year lead the README table and the
  Devpost text (`docs/DEVPOST.md` line 24), and nothing next to them shows what we can actually execute.
- v2 takes the copied print in full in 84% of trades (`docs/RISK.md` R3). Getting those fills means
  displacing the wallets we copy.
- The executable variants all lose:
  - late entry: −0.89¢ IS / −1.89¢ OOS;
  - worst-quartile fills: −0.31¢ OOS;
  - +½ tick: +0.10¢ [−0.41, 0.63] OOS (`results/v2/causal.json`).
- **Fix:** put an "executable today" row first in the README table and the NOTE summary: late entry
  −1.89¢ OOS, and maker v1 blind OOS −$379. Present v2 as "the prize for tier-0 speed".

**P02 [PENDING] Nothing has passed a clean out-of-sample test.**
- The record so far:
  - v1: −$36k, blind (NOTE §4);
  - v2 on U2: +1.22¢ [−0.19, 2.65], FAIL (`results/expand/results.json`);
  - v2-safe on U2: [−0.02, 2.43], FAIL (`research/v2/lowloss/RESULTS.md`);
  - maker v1: +1.87¢ [−0.14, 3.86] per fill and −$379, FAIL (`results/maker/oos.json`).
- The only positive held-out evidence for v2 is the **burned** 40-day window:
  - DSR 0.075 at N = 3,386 (`research/rigor/RESULTS.md`);
  - minimum track record against the best of 3,386 trials: infinite at the OOS Sharpe.
- **Waiting on:** `results/v2/forward.json` (one run, about 11:30 UTC Oct 4) and the tier-0 revision.

**P03 [WRITE] After fixed costs nothing makes money out of sample. The note never mentions fixed costs.**
- `FINANCIALS.md` headline, at central costs:
  - v2: −$75/day burned OOS and −$114/day U2-OOS;
  - v2-safe: −$104/day;
  - maker: −$12/day.
- Today's regime, IS: $179.3/day (`pm_checks.json` `current_regime_1s_5pct_is`) against $166.9/day central
  (`financials.json`), so +$12/day.
- Fees are the binding variable. On the burned OOS, where every trade paid 5%, taker fees are $5,773 of
  $9,461 gross, or 61.0%. In sample they are 30.5% ($17,748 of $58,174; `financials.json` waterfall).
- Derived break-even taker fee on the burned OOS, with the book held fixed and fee linear in the rate:
  - before fixed costs: 5% × 9,460.7 / 5,773.2 = **8.2%**;
  - after central fixed costs: 5% × (9,460.7 − 40 × 166.9) / 5,773.2 = **2.4%**, against 5% today.
- `grep -n licen docs/NOTE.md` finds no dollar figure.
- **Fix:** add one sentence and the break-even fee to NOTE §6 and the README. The note's owner makes the
  edit; this review does not touch the note.

**P04 [WRITE] The note's capacity claim contradicts the causal size curve.**
- NOTE §6 says "roughly $100k before Sharpe falls to ~6" and "$102k trades $1.65M at 6.0". Those rows come
  from the sizing lens (`research/v2/sizing/RESULTS.md` §6), which has three problems here:
  - it used onset-window labels, the hindsight bug fixed in D9;
  - it is in-sample only;
  - the $102k row is the copy-everything **Baseline** and the $79k row is policy `F12`. Neither is v2
    scaled up.
- The causal re-runs in `FINANCIALS.md` §2d tell a different story on the burned OOS:

  | size | capital | $/day | Sharpe |
  |---|---|---|---|
  | 2× | $33,875 | $82.5 | 3.2 |
  | 5× | $53,816 | −$24.5 | −0.5 |
  | all prints | | −$1,281.5 | |

  In sample, 5× ($80,253) still gives Sharpe 10.4.
- **Fix:** replace the §6 capacity sentence with the causal curve, in sample and burned OOS. On this
  evidence, out-of-sample capacity is about $23–34k of capital.

**P05 [WRITE] Code the docs cite is not in git.**
- `git status` at 19:03 UTC shows these untracked:
  - `engine/` (cited in NOTE §5, the README layout and throughout `docs/RISK.md`);
  - `src/tier0.py`, `scripts/tier0_backtest.py`, `research/v2/tier0/`, `results/tier0/` (the peek log
    counts 7 tier-0 reads);
  - `scripts/live_paper.py`, `tests/test_engine_*.py`, `tests/test_live_paper.py`, `research/tt/`.
- `main` equals `origin/main` (`b694498`), so none of this is pushed. A judge spot-checking the code would
  find the paths missing. That is the "code mismatch" route to the criterion-5 cap.
- **Fix:** the owning workstreams commit and push before 11:00 EDT Oct 4.

### S2: high

**P06 [WRITE] The note understates wallet concentration.**
- NOTE §5 quotes only the U2 figure: the top 5 wallets carry 98% of that profit.
- `docs/RISK.md` R2 goes further:
  - on the burned OOS the top 5 carry **142.1%**;
  - without them v2 makes **−0.34¢ [−1.24, 0.55] (−$1,552)**;
  - the top wallet alone carries 41.7% of IS P&L.
- New, IS: the wallet-clustered 95% CI is **[+0.57, +2.30]¢** across 80 wallets, against
  [+1.17, +1.59] clustered by match (`pm_checks.json` `wallet_clustered_is`). The sample that matters is
  80 wallets, not 7,639 matches.
- **Fix:** add the burned-OOS ex-top-5 line to NOTE §5, and show the wallet-clustered CIs next to the
  headline.

**P07 [COMPUTE-NOW, done] The OOS wallet-clustered CI in Table 2 has no source file.**
- `[−0.60, 2.11]` (NOTE Table 2 footnote) appears in no results file and no script. The only other place
  it appears is `research/compliance/JUDGE.md`. Spot-checkers will look for it.
- **How:** copy the wallet bootstrap in `research/financials/pm_checks.py` §2 into `scripts/v2_causal.py`
  or `scripts/note_metrics.py` for both periods, and write it to JSON. The OOS read must append a line to
  `results/oos_peeks.log`. About 5 minutes.

**P08 [WRITE] The headline in-sample row blends fee and delay regimes that no longer exist.**
- In sample covers 3 s/0%, 3 s/3%, 1 s/3% and 1 s/5%. Only the last one is live today.
- New, from `pm_checks.json`, the 1 s/5% slice (Jul 11 – Aug 25, 46 days):

  | trades | ¢/share | $/day | Sharpe | capital | max drawdown | months positive |
  |---|---|---|---|---|---|---|
  | 15,120 | +1.02 [0.60, 1.45]* | $179 | 11.2 | $28.0k | −2.0% | 2/2 |

  \* 2,000 match draws (`pm_checks.json`). The engine's default 1,000 draws, used for every other CI in Table 2
  and in `FINANCIALS.md`, gives [0.59, 1.45]; quote that one in the note.

  The point estimate matches `docs/RISK.md` R11.
- **Fix:** add this row to NOTE Table 2 and the `FINANCIALS.md` headline as the forecast-relevant in-sample
  figure.

**P09 [WRITE + OUT-OF-SCOPE] The computer-vision evidence is thin, and it is table tennis.**
- NOTE §6 says 11 of 11 misses were called correctly 50 ms early. The Wilson 95% CI on that is
  [0.74, 1.00].
- After the post-hoc label audit the result is 8/8 with recall 0.38 (`DEVIATIONS.md` H3-D10).
- The deployable **online** rule made 3 calls, 3/3, recall 0.07 (`docs/RISK.md` R7).
- The test-split ball detector fires on 53% of frames where the ball is absent (`fp_rate_absent` 0.53 in
  `results/tracking/summary.json`).
- Real 25 fps tennis broadcast is "useless" (NOTE §6). The tennis numbers come from simulated physics at an
  assumed 340 fps.
- A 0.95 lower bound on precision needs 73 correct calls in a row (R7). CV reaches P&L only through the
  pending tier-0 counterfactual.
- **Fix:** report the audited and online results next to 11/11. Measuring tennis at high frame rates needs
  footage we do not have [OUT-OF-SCOPE].

**P10 [DONE: the corrected headline landed; it does not clear its fixed costs] Tier-0 is unlikely to clear its fixed costs.**
- The pre-registered primary makes $307.9/day IS (`results/tier0/results.json`).
  `research/v2/tier0/DEVIATIONS.md` V1 shows that number **overstates** the fill edge.
- At the scenario's 10 covered matches a day, fixed costs are $1,151 / $4,149 / $7,215 per day (low /
  central / high; `FINANCIALS.md` §4).
- So the corrected headline would need to be at least 3.7× the overstated primary (1,150.5 / 307.9) just to
  cover the low-cost case, and 13.5× to cover central.
- As modelled, tier-0 is also prohibited wherever ticket terms match the Australian Open's (R16).
- **Fix:** when the revision lands, report corrected P&L per day next to these costs.

**P11 [WRITE] Maker v1, the only book we can run remotely, is weaker than its per-fill headline.**
- The pre-registered primary is the **per-fill** mean, which ignores size. In dollars the OOS lost $379.
  Share-weighted it is −0.75¢ [−4.92, 3.56].
- Even in sample, the share-weighted CI includes zero: +2.59¢ [−0.09, +5.20] (`FINANCIALS.md` §5c).
- All 3,116 OOS markets list `makerBaseFee` 1000. Charged that way, the book makes −0.21¢ and −$1,419
  (stress viii).
- Capacity estimates differ by 10–40×:
  - $1.3–2.1k per 30 days (`research/v2/crossmarket/RESULTS.md` §7);
  - $130 per 30 days in the verifier's step-ahead model, and $48 in its combined conservative model
    (`FINANCIALS.md` §5d).
- 20,191 of the 23,307 OOS side markets of the six frozen types were dropped by a **lifetime**-volume filter
  (< $250). That filter uses information a live trader would not have.
- The live paper session was in `warm-up` with 0 fills at 19:03 UTC (`results/live/summary.json`).
- **Fix:** make the dollar-weighted figure the maker headline; settle the maker fee from the venue docs;
  state the live session's stop rule and minimum sample before it runs.

**P12 [PENDING + WRITE] The forward test cannot validate dollar P&L.**
- Both primaries are 30 s markouts, not resolution P&L.
- Primary B is underpowered by design for a window under one day (`HYPOTHESIS_V2.md` A1.5).
- The window holds about 21.5 h of match starts (from 14:00 UTC Oct 3 to the run at about 11:30 UTC Oct 4).
- **Fix:** write down beforehand what each outcome changes (table below), and print the expected CI
  half-width next to the result.

**P13 [WRITE] Capital is defined differently for each period, so returns are not comparable.**
- Capital is 3 × the period's **own** peak locked: $28,302 IS, $22,754 OOS, $7,432 U2, $2,022–2,779 for the
  maker. A trader funds once, ex ante.
- On IS capital, burned-OOS return is 3,687.5 / 28,302.4 = 13.0% in 40 days, or **119% annualised**. The
  reported figure is 148%.
- Realised lock times need $34,818, not $28,302 (R13).
- The live maker paper session books $10,000 per book.
- The 3× multiplier is a convention, not a loss quantile.
- **Fix:** fix capital ex ante, at $34.8k realised-lock capital for v2, and use it for every period.

**P14 [COMPUTE-NOW, done] The edge sits in the thinnest markets, and the universe filter looks ahead.**
- In sample, ¢/share by final volume band (R9):

  | band | $5–20k | $20–100k | $0.1–1M | > $1M |
  |---|---|---|---|---|
  | ¢/share | +2.55 | +2.15 | +1.11 | +0.95 |

  The $5–20k band is −1.96¢ on the burned OOS. On U2, markets above $100k make −3.46¢ IS.
- These bands use **lifetime** volume. So does the $5k entry filter.
- **How:** take each match's pre-start volume, computed the same way `src/tier0.py` ranks coverage. Band IS
  v2 trades (`data/v2_trades_is_oos.parquet`, IS conds, months ≥ 2026-02) by it, with match-clustered CIs.
  Then rebuild the universe with a pre-start threshold. IS only, about 15 minutes.

**P15 [COMPUTE-NOW, done] No sensitivity surface for v2's signal thresholds.**
- The plateau evidence covers net cap and deployment (onset labels) and the v2-safe grid. It does not cover:
  - the detector (4¢ over 10 s against 60 s);
  - the 3 s window;
  - qualification (≥ 30 prints, ≥ 10 matches, t > 3);
  - shrinkage n₀ = 200;
  - the price zone.
- **How:** loop `src.v2.run` with each threshold one step up and one step down on `data/is_prints.parquet`
  only, and report per-share and Sharpe. Each run takes 10–20 s (`financials.py` ran four scaled books in
  55 s), so about 25 runs fit in 15 minutes on 1–2 processes. No OOS.

**P16 [WRITE, key renamed; ratio guard in CORRECTIONS O3] `results/summary.json` holds a stale v2 and some broken statistics.**
- Its `v2` key is a third version of the superseded onset-window book:

  | source | IS trades | IS Sharpe | OOS trades | OOS Sharpe | OOS capital |
  |---|---|---|---|---|---|
  | `results/summary.json` `v2` | 67,468 | 16.78 | 13,184 | 11.14 | $8,566 |
  | `causal.json` `onset/*` | 67,485 | 16.77 | 13,167 | 11.15 | |

- The current `run_all.py` does not write that key, so a fresh `reproduce.sh` would change the file.
- `best_month_share` blows up when the denominator is near zero: −4.4×10¹² in `summary.json`
  `oos.h1`, and 1.7×10¹¹ in `results/maker/oos.json`.
- **Fix:** delete the key or rename it `v2_onset_superseded`, and guard the ratio.

**P17 [COMPUTE-NOW, done in part] `reproduce.sh` has not been run end to end since the last scripts were added.**
- The last full run is `reproduce.log`, 09:47 local. That predates `v2_cost_stress.py`, `note_metrics.py`
  and the D9 causal pipeline. COMPLIANCE item 53 leaves the clean-clone diff to the team.
- **How:** clone into a scratch directory, link `data/` read-only, run `bash reproduce.sh`, and diff
  `results/*.json`. The step-1 peek line lands in the clone's log. Runtime is unknown. If it runs past
  30 minutes, run only the `v2_*`, `note_metrics` and `factor_regression` steps.

### S3: medium

**P18 [WRITE] The peek count differs by file.**
- NOTE §4 and `note_metrics.json` say 19.
- `docs/RISK.md` R10 and COMPLIANCE item 27 say 15. `JUDGE.md` says 14.
- The working log now has 20 lines. At 19:00 UTC a maker live-engine REPLAY line was added, and it is not
  committed yet.
- **Fix:** recount right before submission and update every file.

**P19 [WRITE] Fast-tier month counts.**
- NOTE Table 1 says IS "8/8 months". `summary.json` `is.h6_walkforward` lists 9 months (Dec 2025 – Aug
  2026), all positive.
- The README says "11/11 (8 IS + 3 OOS)". August is in both lists.
- The "3/3" OOS months include Aug 25–31 (7 days) and Oct 1–3 (3 days). The fast tier's October resolution net is −0.54¢.
- **Fix:** state 9 IS months plus 1 full and 2 partial OOS months.

**P20 [WRITE] v2-safe's in-sample Sharpe ignores a verifier correction.** `FINANCIALS.md` and `docs/RISK.md`
show 15.7. Rigor correction 4 says the honest figure is the stitched walk-forward one, **14.02**.

**P21 [WRITE] Maker figures disagree across files.** See the disagreement table below, items 7–12.

**P22 [WRITE] Latency figures disagree across files, and all come from one day.** See table items 13–14.
Everything comes from the Oct 3 recording: 2.98 h of moneyline books, 9 WTA matches, 482 points.

**P23 [WRITE] Cross-references point to the wrong note sections, and `docs/RISK.md` is out of date.**
- `FINANCIALS.md` cites:
  - NOTE "section 7" for the 2.5 s requirement and table-tennis liquidity (it is §6);
  - "section 6" for ticket terms (it is §5);
  - "section 5" for "not remotely executable" (it is §3 and §6).
- `docs/RISK.md` cites:
  - "NOTE §7" for depth (it is §6);
  - "NOTE §6" for the de-risking rules (it is §5).
- The rigor pack cites "NOTE.md §8", which does not exist.
- R12 asks for the note's "retirements" line to be corrected. NOTE §5 already says "mostly walkovers".
- `docs/RISK.md` still lists the maker OOS as pending. It returned FAILURE (`a4cce70`).

**P24 [COMPUTE-NOW, done] The factor regression needs cleaning up.**
- `results/v2/factor_regression.json` runs from 2026-02-02 to **2026-08-31**, so it includes burned-OOS
  days (Aug 25–31). The script filters `month ≥ 2026-02`, not on IS.
- Weekends are dropped by the inner join with trading days: 142 days instead of 206. Tennis trades every day.
- Alpha is annualised ×252 (199.6%). Everything else uses ×365.
- Returns are not net of the risk-free rate.
- **How:** restrict to IS conds; keep calendar days with weekend factors set to 0, or regress
  weekday-only and say so; annualise ×365. About 5 minutes.

**P25 [WRITE + COMPUTE-NOW, done] Kill switches are not calibrated per book, and most are untested.**
- The $1,000 daily stop never fires in the backtest (worst IS day −$551).
- On the maker's $2.0–2.8k capital, the same stop would be 36–50% of capital.
- The drawdown, trailing-edge, fee-change and dispute rules are policy only (RISK kill table).
- **How:** replay the trailing-30-day edge rule (halve below 0.3¢, stop at 0) on the IS daily series from
  `data/v2_trades_is_oos.parquet`. About 10 minutes. Then set a `RiskConfig` per book.

**P26 [COMPUTE-NOW, done] No split of the gross edge.**
- The question is whether v2's +1.99¢ gross IS comes from the fill price (stale quote against the new mid)
  or from drift after the point.
- **How:** in `data/v2_trades_is_oos.parquet`, IS rows only, split `gross_res` into the fill price against
  the mid 30 s later (`mo30`, `gross30`) and the move from 30 s to resolution. Report both share-weighted with
  match-clustered CIs. About 15 minutes.

**P27 [PENDING + OUT-OF-SCOPE] The latency and depth case rests on one recording day.**
- The live recorder is running. Add the Oct 3–4 sessions before submission.
- London co-location at 2 ms and the venue's matching location are assumed, not measured (R5). Measuring
  them needs hosting we have not paid for [OUT-OF-SCOPE].

### S4: low

- **P28 [WRITE]** Daily P&L is booked on the **entry** date (`research/v2/sizing/engine.py`
  `daily_series` groups by trade `date`), not on settlement. Say so. Matches resolve a median 1.25 h after entry (`FINANCIALS.md` §2b), and 11 markets closed more than
  7 days after the match finished (R12).
- **P29 [WRITE]** R10 says "3,386 (all v2 lenses)". In fact 3,386 = 44 (H1–H6) + 3,342 (lenses).
- **P30 [COMPUTE-NOW, done]** The 2,889 matches with no published fee are charged 0% in the backtest. If
  they were charged 3% instead, 7,487 IS trades (13.5%, all Feb–Mar) give +1.30¢ [1.08, 1.51] and $37,908,
  against +1.38¢ and $40,426 (`pm_checks.json`). Low impact. Add one line.
- **P31 [OUT-OF-SCOPE]** Several things cannot be settled from here:
  - The US, UK, France, Canada, Australia, Germany, Italy and others are close-only on polymarket.com (R16). Polymarket US is a separate
    venue we have not tested: its fees, delay and market list are unknown.
  - The feed licence has no public price (ASSUMPTION $1,250–10,000 a month).
  - After-tax return is unmeasured; the IRS has published no guidance (R17).
  - The hackathon terms forbid funded accounts (TERMS 5.3).

  Within those limits, live work stays paper.
- **P32 [OUT-OF-SCOPE]** Platform, oracle and stablecoin failure probabilities, and UMA dispute counts. Only
  a close-time proxy exists (R12, R15).
- **P33 [DONE]** Table-tennis out-of-sport test: first run 19:23 UTC, TT1, TT2 and TT3 all FAIL (no fast tier
  detected, no trades; 27 evaluable matches; `results/tt/results.json`). Before that run: Table
  tennis is untradable (89¢ spread, $23 at the touch), so the result cannot change the allocation either way.

## Numbers that disagree between files

| # | Quantity | File A | File B | Which to use |
|---|---|---|---|---|
| 1 | OOS peeks | NOTE §4, `note_metrics.json`: 19 | RISK R10, COMPLIANCE #27: 15; `JUDGE.md`: 14; live log: 20 | Recount at submission |
| 2 | v2-safe IS Sharpe | `FINANCIALS.md`, `lowloss/results.json`: 15.70 | Rigor correction 4: 14.02 (stitched walk-forward) | 14.02 |
| 3 | Superseded onset v2 | `summary.json` `v2`: 67,468 trades, 16.78; OOS 13,184, 11.14 | `causal.json` `onset/*`: 67,485, 16.77; 13,167, 11.15 | Neither. Headline is causal 14.48 / 6.67 |
| 4 | Capacity | NOTE §6: ~$100k at Sharpe ~6 (onset, IS, Baseline/F12) | `FINANCIALS.md` §2d causal OOS: 2× Sharpe 3.2, 5× −0.5 | `FINANCIALS.md` |
| 5 | OOS concentration | NOTE §5: top 5 carry 98% (U2) | RISK R2: 142.1% burned OOS; ex-top-5 −0.34¢ | Report both |
| 6 | Fast-tier months | NOTE: 8/8 IS; README: 11/11 (8+3) | `summary.json`: 9 IS + 3 OOS rows, August in both | 9 IS + 3 OOS (2 partial) |
| 7 | Maker IS per-fill CI | crossmarket 5b, RISK: [1.73, 3.70] | `FINANCIALS.md` §5: [1.70, 3.70] | Use one bootstrap for both |
| 8 | Maker OOS max DD | `maker/oos.json`, maker RESULTS: −46.7% | `FINANCIALS.md` §5c: −57.2% (same −$1,156) | Name the base: capital + peak equity vs capital |
| 9 | Maker IS max DD | crossmarket 5b: −44% | `FINANCIALS.md`: −59.2% | Explained in `FINANCIALS.md`; keep one base |
| 10 | Maker capacity / 30 d | crossmarket §7: $1.3–2.1k P&L | `FINANCIALS.md` §5d: $130 step-ahead; $48 conservative | Verifier models |
| 11 | Maker OOS status | RISK table and R14: "pending" | `maker/oos.json`: FAILURE | FAILURE |
| 12 | Maker IS reference | maker RESULTS: +3.06¢, n = 10,171 (fixed b_T) | crossmarket 5b: +2.73¢, 8,905 (walk-forward) | Label the book each time |
| 13 | Book reprice vs official stamp | latency RESULTS, RISK R5: −1.16 s (n = 482); NOTE −1.2 s | tier-0 V3: R median −1.32 s; tier-0 inputs: −1.418 s (49 points) | One canonical figure with its sample |
| 14 | Public feed lag | latency: ESPN +27.5 s after stamp, 28.2 s behind book | `summary.json` h4: median lead 44.5 s (n = 75); RISK: "17–62 s behind the book (p10–p90)"; README: "27–43 s behind" (behind the stamp) | Define against stamp or book |
| 15 | Factor regression window | IS ends 2026-08-25 | `factor_regression.json`: to 2026-08-31 | IS only |
| 16 | OOS return on capital | `causal.json`: 148% a year on $22,754 | Same P&L on IS capital $28,302: 119% (derived) | Ex-ante capital |
| 17 | Fast-tier monthly volume | NOTE §6: $0.3–3.1M "in the window" | RISK R3: $0.45–2.7M IS | NOTE's low end is the 3-day October |
| 18 | Live paper capital | `results/live/summary.json`: $10,000 per book | Maker convention: $2,022–2,779 | State it |
| 19 | CV precision headline | NOTE §6: 11/11 at 50 ms, recall 27% | `DEVIATIONS.md` H3-D10: audited 8/8, recall 0.38; online rule 3/3, recall 0.07 | Show all three |

Status at about 19:45 UTC. Fixed in files this review owns: row 2 (`FINANCIALS.md` caveat and reading line give
the stitched 14.02), row 3 (`results/summary.json` key renamed `v2_onset_superseded`), row 4 (`FINANCIALS.md` §2d
capacity sentence, `docs/RISK.md` R3), row 5 (RISK R2 adds the wallet-clustered CIs), rows 7–9 (`FINANCIALS.md`
maker caveats name the bootstrap and the drawdown base), row 10 (RISK R3 quotes the verifier's models), row 11
(RISK), row 15 (`pm_compute` P24), row 16 (`FINANCIALS.md` §2c rows on one ex-ante capital), row 18
(`FINANCIALS.md` live-session line). Rows 1, 6, 13, 14, 17 and 19 need edits in the note, README, Devpost or
compliance files: `research/financials/CORRECTIONS.md` lists each one. Row 12 (label the maker book each time) is
still open.

## Pending tests: what each outcome would mean for the allocation

| Test | Outcome | What it means |
|---|---|---|
| v2 forward, primary A (fast tier minus other takers) | pass | The mechanism holds in the current regime for one more day. That supports a tier-0 build, not v2 as we can run it (P01) |
| | fail | H6 persistence fails out of sample in the current regime. v2 and tier-0 lose their reason to exist |
| v2 forward, primary B (v2 book, 30 s net) | pass | Supporting evidence only: one day of 30 s markouts, not P&L |
| | fail | Expected even if the edge is real, because B is underpowered (A1.5). Uninformative unless A also fails |
| Tier-0 revision | corrected P&L < $1,151/day | Uneconomic at 10 matches a day in every cost case (P10). Stop. **This is the outcome: $88.8/day IS, $46.4/day OOS** |
| | ≥ $4,149/day | Worth a feed-licence quote and a legal review. Still a counterfactual |
| Maker live paper | any | Maker v1 already failed its blind OOS. A changed rule is maker v2, which needs its own pre-registration (PREREG §5). The live run only checks the plumbing |
| Table tennis | any | No allocation consequence: the books cannot be traded (P33) |

## Rubric map

| Criterion | Items |
|---|---|
| Economic Foundation | P02, P06, P19 |
| Innovation | P09, P10, P27 |
| Risk Management Plan | P06, P13, P25, P31, P32 |
| Liquidity & Capital Deployment | P03, P04, P11, P13, P14 |
| Performance & Analytical Evidence (and the cap) | P01, P05, P07, P08, P12, P15, P16, P17, P18, P20–P24, P26 |

## Appendix: PM spot checks (`results/financials/pm_checks.json`, IS only)

Run with `.venv/bin/python research/financials/pm_checks.py`, about 3 s on one process. The script first
reproduces `causal.json` exactly.

| Check | Result |
|---|---|
| v2 in the 1 s/5% regime, IS (Jul 11 – Aug 25, 46 days) | 15,120 trades; +1.02¢ [0.60, 1.45]; $179.3/day; Sharpe 11.2; capital $28.0k; max DD −2.0%; 2/2 months |
| Wallet-clustered CI, IS (80 wallets) | +1.38¢ [0.57, 2.30]; top 1 = 41.7%, top 5 = 81.4% of P&L |
| By entry price (¢/share [match-clustered CI]) | 0.05–0.2: +1.37 [−0.20, 2.92]; 0.2–0.4: +0.53 [−0.83, 1.88]; 0.4–0.6: +1.99 [1.12, 2.80]; 0.6–0.8: +1.39 [0.09, 2.77]; 0.8–0.95: +1.66 [0.41, 3.00]. No clean favourite or longshot tilt |
| Null-fee matches charged 3% | +1.30¢ [1.08, 1.51]; $37,908 (base +1.38¢, $40,426) |
