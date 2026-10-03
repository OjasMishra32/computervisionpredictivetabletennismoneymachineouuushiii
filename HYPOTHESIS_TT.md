# COURTSIDE table tennis (TT1–TT5): pre-registration

Written 2026-10-03 ~18:30 UTC on top of `c29734b`. It was committed **before any table tennis trade
tape was fetched, loaded or summarised.** The commit time is the timestamp that counts.

**State of the data at writing (checked):**
- `data/raw/trades/` holds no tape for any table tennis `cond` (0 of 26,764).
- The live recordings in `data/live/` subscribe to no table tennis token.
- No table tennis print, markout, P&L or price statistic has been computed.

**What was read:** only catalogue metadata. That is series, start, close time, listed volume, `res0`,
fee schedule, `secondsDelay` and tick. All of it comes from
`data/raw/events_table-tennis_2025-07-01_2026-10-03.parquet` (sha256 `daa48f2c41716309fd643fb02995fcaed3e1dffaf23bfee5abc732c53e9533f8`), built by
`src.polymarket.enumerate_events("table-tennis", …)`. The gamma tag `table-tennis` is tag 103767.

**Completeness checks (gamma metadata only).** Three one-day spot checks against gamma matched the
catalogue event for event: 8/8 WTT on 2026-04-10, 354/354 Setka on 2026-09-10, and 0/0 on
2026-06-01. The child tag slugs ttcup, ttchallenger, ttbl, ttcl, tteuropecup, ttworldcup, ttworlds,
ttolympics, wttmen and wttwom return no closed events. ttelite returns the single match that is
already in the catalogue. Setka events also carry `table_tennis_match_totals` and
`table_tennis_game_handicap` markets; only the moneyline is studied.

Any change after this commit goes in `research/tt/DEVIATIONS.md` with its reason, before a re-run.

## Why
Every COURTSIDE rule was built on tennis. Table tennis is a different sport with a faster point
cycle, different leagues and different liquidity. It is also the sport our CV actually tracks: real
OpenTTGames footage, 11/11 calls correct at a 50 ms lead on held-out games, median call lead 25 ms
(`results/tracking/`). So it asks two questions the tennis work cannot:
- Does the tennis structure (calibrated prices, a persistent fast tier, the frozen v2 edge) exist
  in a market nobody here has looked at?
- How much edge is left at the latency a camera, a CV model and a network hop would actually have?

## Universe UTT and data window
UTT is every catalogue row with all of the following:
- moneyline with two outcomes (the catalogue only holds these);
- `volume > 0`, because a market with no fills has no tape;
- `res0` in {0, 0.5, 1} (all rows qualify).

Rows are prepared exactly as `src.tape.universe()` does:
- `start = to_datetime(start_time, utc)`;
- `end = to_datetime(finished.fillna(closed_time), utc, format="mixed")`;
- `fee_rate = fee_rate.fillna(0)`;
- `delay = seconds_delay.fillna(1)`.

League is `WTT` if `series` starts with "wtt", `Setka` if it starts with "setka", and `other`
otherwise.

**Data window:** match starts from 2026-02-15 06:10 UTC to 2026-10-03 01:30 UTC. The catalogue is not
refreshed. Markets listed later are not part of this study.

**Split** (the track rule, same code as tennis): sort UTT by `start` (stable) and set
`cut = start.iloc[int(0.8·N)]`. IS is `start < cut`; OOS is `start >= cut`.
**cut = 2026-09-16 05:30:00 UTC**, and the 3 matches that start exactly at the cut are OOS.

**Expected counts, from the catalogue:**

| | count |
|---|---|
| UTT | 3,588 markets in 3,588 distinct events, with no duplicate title+start |
| by series | setkameua 1,763 · setkamecz 512 · setkamemd 331 · setkawoua 100 · wtt-mens 471 · wtt-womens 410 · ttelite 1 |
| by league | Setka 2,706 · WTT 881 · other 1 |
| IS / OOS | 2,870 (Setka 1,988, WTT 881, other 1) / 718 (all Setka) |
| res0 = 1 / 0 / 0.5 | 1,752 / 1,819 / 17 (all 17 at 0.5 are WTT) |
| fee rate | Setka 5% (2,706) · WTT 3% (709, from 2026-03-30) · WTT none → 0 (172, 2026-02-15 to 03-29) · other 5% |
| fee exponent | 1 wherever a schedule exists, so the fee is `rate·p(1−p)` per share as in tennis |
| order delay | 1 s: Setka 2,706, WTT 302, other 1 · 3 s: WTT 579 (until 2026-05-10) |
| listed volume | Setka: median $19, total $359k · WTT: median $190, total $657k · other: $8 |
| listed volume bins <$10 / $10–100 / $100–1k / $1–5k / ≥$5k | Setka 871 / 1,354 / 447 / 29 / 5 · WTT 43 / 179 / 526 / 112 / 21 |
| `end <= start` | 17. These rows give no in-play prints and drop out at the print build. |

The catalogue drops 23,176 rows with zero volume, including 202 of the 219 rows at 0.5.

### Exclusions
- **Zero-volume markets** are out of UTT.
- **Voided or 50-50 markets (`res0 = 0.5`, 17 WTT markets)** stay in for TT2–TT5. The frozen v2
  settles them at 0.5, as it did in tennis, and nobody can know in advance that a match will be
  voided. They are excluded from TT1, because `calibration()` keeps only `res` in {0, 1}.
- **Matches with fewer than 20 in-play prints** are dropped by `tiers.match_prints`, as in tennis.
  Most Setka matches are expected to fall here.
- **Matches whose tape fetch fails** are dropped and listed by `cond`.

Final evaluable counts are reported; they do not change any rule.

## Fixed pipeline (shared by TT1–TT5; tennis code unchanged)
- **Tapes.** `src.polymarket.fetch_trades` parsing and cache (compact parquet in
  `data/raw/trades/`).
  - At most 4 concurrent data-api requests, with exponential back-off on 429/5xx. A
    back-off-only wrapper is allowed; the parsing is unchanged.
  - The data-api offset cap (about 10,500 fills per market) applies, as it did for U1 and U2.
  - Public endpoints only.
- **Prints.** `src.tiers.match_prints(row)` for every UTT row, with at most 3 processes. Output:
  - `data/tt/prints.parquet`;
  - `data/tt/universe.parquet`, with the oos flag and league.

  The build step computes no statistic.
- **Timestamps.** data-api timestamps are integer-second **block times**, about 2 s after the
  real trade. Differences between prints in the same market keep their order but are only
  resolved to whole seconds, and prints in one block share a timestamp.
- **Jump detector.** `tiers.jump_onsets` and `add_causal_bucket` are used unchanged.
  - **Rule:** J = 0.04 in probability units, short window 10 s, long window 60 s, refractory 60 s.
    J is defined on VWAP probability, not ticks, so it stays 0.04 at the 0.01 and 0.001 ticks that
    tennis also had. It would change only for a market whose tick exceeds 0.01, to J = 4 × tick.
    No UTT market has such a tick.
  - The catalogue `tick` is the tick when the catalogue was built. 87% of UTT rows show 0.001;
    tennis U1 shows 0.001 on 97%. Polymarket narrows the tick near 0 and 1, so a resolved market
    usually shows 0.001.
  - The windows are **not** shortened for table tennis's faster points, so one detection can span
    several points. This is a known handicap, and it is accepted on purpose.
- **"After a detected jump"** means the causal bucket: seconds since the latest jump *detection*
  (`bucket_c`, `since_det`), the A1 definition in `HYPOTHESIS_V2.md`.
- **Markouts.** For a taker print, `dir` is +1 if the taker bought outcome 0.
  `mo30 = dir·(mid at t+30 s − p)`, where the mid is the `tiers._mid_series` proxy.
  `net30 = mo30 − fee_rate·p(1−p)`.
- **In-play window (known difference from tennis).** No table tennis market has
  `finishedTimestamp`, so `end` is the market's close time. Median end − start is 145 min for Setka
  and 347 min for WTT; a Setka match takes well under an hour. The in-play window therefore also
  contains post-match prints near 0 or 1. The code is not changed. The consequences are handled
  where they matter (TT1) and reported.
- **Fees and delays.** Each market's own fee rate and `secondsDelay`, as listed above.

## TT1: calibration (the tennis calibration test)
This is the tennis test, `run_all.calibration()`, unchanged. In `HYPOTHESIS.md` the calibration claim
is H2; `DEVIATIONS.md` D4 reports it.

**In-play test**
- Data: TT prints with `res` in {0, 1}.
- Observations: the first print in each (match, minute).
- `fav = max(p, 1−p)` and `won` is whether the favourite won.
- Bins: [0.5, .6, .7, .8, .85, .9, .93, .95, .97, .98, .99, 1.0).
- Win rate per bin, with a match-clustered bootstrap CI (500 draws, seed 0).

**Closing test**
- One observation per UTT match with `res` in {0, 1}: the last tape print in [start − 24 h, start).
  It is read from the raw tape, not the in-play prints.
- Same bins. The CI is a bootstrap over matches (500 draws, seed 0).

**Verdict rule.** A test reads "calibrated" if, for every bin with ≥ 30 matches, the 95% CI of the
win rate contains the bin's mean favourite price. This is the criterion applied to tennis.
- The bin [0.99, 1.0] is reported but excluded from the in-play verdict. Without a finish time it
  is dominated by post-match prints, which would fail trivially (price about 0.995, won 100%).
- **TT1 holds if both the in-play and the closing tests read "calibrated".** Bins with < 30
  matches are reported and not judged.

**Secondaries (reported, not tested)**
- Pooled mean of (won − fav) over all in-play observations in [0.5, 0.99), with a match-clustered
  CI (2,000 draws, seed 0).
- Per-bin CIs at the Bonferroni level, 1 − 0.05/k, where k is the number of judged bins.
- In-play test truncated at the first in-play print with fav ≥ 0.99. This is causal, and it removes
  the post-match tail.
- Every bin split by league.

With about 10 judged bins, one bin failing by chance is plausible. That is why the pooled and
Bonferroni versions are reported next to the verdict; they do not replace it.

## TT2: the fast tier exists in table tennis
**Code:** `fasttier.walk_forward(P_TT, start_month=2, bucket="bucket_c")` on table tennis prints
only. No tennis prints and no tennis-qualified wallets are used.

**Thresholds** (the H6 rule, unchanged):
- A wallet qualifies for month m with ≥ 30 prints in the causal 0–3 s bucket, over ≥ 10 matches,
  before m.
- It also needs t > 3 on mean `mo30`, with t = mean / (sd / √matches).
- Evaluated months are the third month of TT prints onward; expected from 2026-04.

**Statistics**
- **Fast:** print-weighted mean `net30` of qualified wallets' 0–3 s prints in their evaluated
  month.
- **Others:** the same for every other wallet's 0–3 s prints in evaluated months.
- **Gap:** fast minus others.
- Each comes with a match-clustered bootstrap (2,000 draws, seed 0), as in Primary A of
  `scripts/forward_test.py`.

**TT2 passes only if all four hold:**
- (a) fast net30 > 0, with the 95% CI excluding 0;
- (b) others' net30 < 0, with the 95% CI excluding 0;
- (c) fast net30 > 0 in at least two-thirds of the evaluated months that have fast-tier prints
  (the H6 consistency rule);
- (d) fast net30 > 0 (point estimate) in both IS and OOS, with period assigned by match start.

**Fail cases and reporting**
- If no wallet qualifies in any month, TT2 fails as "no fast tier detected".
- If fewer than 30 matches have fast-tier prints, the result is also labelled "underpowered". The
  label never turns a fail into a pass.
- Also reported: the monthly `wf` table, the gap with its CI, and the "others" statistic restricted
  to months with ≥ 1 qualified wallet.

## TT3: blind out-of-sport test of the FROZEN v2 rule (1 variant)
**Rule.** `tr, wf = src.v2.run(P_TT, ends_TT, causal=True)`.
- This is `G_50pct_net100` as frozen in `HYPOTHESIS_V2.md` with A1, through
  `research/v2/sizing/engine.py`, unchanged.
- No parameter, threshold, zone, cap, sizing, lock or fee change.
- Wallet qualification, the wallet filter (shrunk past markout > each match's own fee rate ×
  q(1−q)) and the deployment scale k are all walk-forward on **table tennis months only**, as the
  rule specifies.
- `ends_TT` is UTT `end` indexed by `cond`. With `causal=True` the capital lock is the ex-ante 4 h
  per position. That overstates capital for short table tennis matches; it is frozen and reported
  as is.
- No other variant is run. v2-safe is not evaluated here.

**Empty-training months.** In the first month that has fast-tier (shadow) rows, there is no earlier
shadow row to fit the deployment scale on. The engine then drives k to about 1e-8, so those trades
hold about 0 shares and $0.
- They are kept in every share- or dollar-weighted metric, where they weigh nothing.
- They are excluded from count-based metrics: trade count, trade win rate and per-print means.
- This is a reporting convention. It is not a rule change.

**Periods.** A trade's period is its match's start: IS is before the cut, OOS from the cut. The
walk-forward runs continuously over all months. IS and OOS are both blind, because nothing has been
tuned on table tennis.

**Primary (pass/fail).**
- Metric: per-share net P&L held to resolution, share-weighted (`per_share_c` with `per_share_ci_c`
  from `v2.E.metrics`). The CI is a match-clustered bootstrap with 1,000 draws, seed 0.
- **TT3 PASSES only if the 95% CI lower bound is > 0 in IS AND in OOS.**
- A period with no trades fails as "no trades".
- A period with fewer than 30 matches with v2 trades is also labelled "underpowered". The label
  never turns a fail into a pass.

**Secondaries** (reported, not tested; for IS, OOS and both combined)
- $ P&L with its match-clustered CI, number of trades and number of matches.
- Sharpe (`sharpe_ann`: daily P&L on zero-filled calendar days, ×√365).
- Max drawdown in $ and as % of capital, and worst day.
- Profitable days: share of zero-filled calendar days with P&L > 0, and share of active days.
  P&L is booked on the trade's UTC date, as in `E.metrics`.
- Trade win rate: share of trades with `pnl_ps > 0`, with a match-clustered CI (2,000 draws,
  seed 0).
- Return on capital, where capital is 3 × the subset's peak locked dollars (`E.metrics`). The CI
  comes from an i.i.d. bootstrap of zero-filled calendar days (2,000 draws, seed 0), holding
  capital fixed.
- By league (WTT, Setka, other): `E.by_group` plus per-league per-share with a clustered CI.
- Costs doubled, holding the book fixed, as in `scripts/v2_cost_stress.py`:
  - `fee_x2`: `pnl_ps − fee`;
  - `costs_x2`: `pnl_ps − fee − 0.005`.

**Known from metadata before any tape:** OOS is entirely Setka, with a median listed volume of $10
per match, so OOS may well be underpowered or have no trades. That does not change the rule. v2 is
not changed in response to TT3. Any table-tennis-specific filter, cap or threshold would be a new
hypothesis, with its own pre-registration and a fresh forward window.

## TT4: liquidity and capacity (descriptive)
Per league, and also by IS/OOS:
- **Volume per match.**
  - Listed volume from the catalogue.
  - Tape volume (Σ size·price).
  - Split pre-start / in-play window (`start`→`end`; this includes post-match prints before close).
  - Mean, median and p90 of each.
- **Fast-tier volume.** USD of walk-forward fast-tier prints in the causal 0–3 s bucket (the
  opportunity set before v2 sizing), per match, per active day and per month.
- **Depth proxies** (the tape has no book):
  - median and p90 print size in USD in-play;
  - in-play prints per minute;
  - USD printed in the causal 0–3 s bucket per detected jump;
  - median `_mid_series` spread proxy in-play.
  - Optional and labelled as a snapshot, not history: one pass of public `clob /book` snapshots of
    open table tennis moneylines, measuring depth within ±1¢ and ±2¢ of mid.
- **What v2 could deploy** (from the TT3 run):
  - `usd_in` per match, per active day and per calendar day (from the first to the last v2 trade
    day, as in `E.daily_series`);
  - peak locked dollars and mean ticket;
  - $ P&L per calendar day.
  - Context, not compared: tennis v2 over the same calendar months, from
    `data/v2_trades_is_oos.parquet`.
- **Capacity rule, fixed now:** if v2's deployed dollars average **< $1,000 per calendar day** over
  its table tennis trading window, the report states plainly "capacity is negligible". It does so
  whatever the per-share result is.

## TT5: signal decay vs latency
**Curve.**
- Prints: every in-play taker print with `since_det >= 0`.
- Statistic: net30 as a function of `since_det`, print-weighted, with a match-clustered 95% CI
  (`fasttier.cluster_ci`, 2,000 draws, seed 0).
- Bins, left-closed: [0, 0.25), [0.25, 0.5), [0.5, 1), [1, 2), [2, 3), [3, 5), [5, 10), [10, 30) s.
- Baseline row: prints before the first detection or ≥ 30 s after the latest one.

**Curves computed**
1. all taker prints;
2. with-jump prints (`with_jump_det > 0`), which trade in the direction of the detected move;
3. against-jump prints.

Each is computed for table tennis (all UTT, also by league) and for tennis, separately. The tennis
prints are U1 IS + burned OOS (`data/is_prints.parquet`, `data/locked/oos_prints.parquet`). The
tennis curve is non-blind, because that data has been studied.

**Decay test (one per sport).**
- Statistic: with-jump net30 in [1, 2) minus with-jump net30 in [10, 30).
- CI: a paired match-clustered bootstrap (resample matches; 2,000 draws, seed 0).
- "Decays" if the CI is above 0.

**Timestamp resolution, stated before any data.** `since_det` is a whole number of block seconds.
- [0, 0.25) holds only `since_det = 0`: prints in the detection print's own block. Some of them may
  have executed before the detection print.
- [0.25, 0.5) and [0.5, 1) are **empty by construction**. They are reported as "not resolvable on
  block-time tapes", never interpolated.

**Latency stacks.** Pre-venue latency ℓ = camera + CV model + network:
- camera: 8.3 ms, one frame at 120 fps (OpenTTGames);
- CV model: 20 ms (`T_INF` in `src/tier0.py`, an assumption) or 50 ms (pessimistic);
- network one-way: 67 ms (Florida, measured median) or 2 ms (London co-located, inferred).

| stack | ℓ |
|---|---|
| FL-20 | 95.3 ms |
| FL-50 | 125.3 ms |
| LDN-20 | 30.3 ms |
| LDN-50 | 60.3 ms |

The H3 call lead (median 25 ms before the reference frame) is **not** credited.
δ_m is each market's `secondsDelay` (1 s, or 3 s for early WTT).

**Read-off rule.** The expected edge for a stack is the with-jump net30 (¢/share, match-clustered
CI) of prints whose `since_det` falls in the bin containing x, using each print's own market δ_m.
- **Reading A (primary, conservative):** x = ℓ + δ_m. This is the task's stack.
  - δ = 1 s → [1, 2);
  - δ = 3 s → [3, 5).
- **Reading B (upper bound):** x = ℓ. Every print on the tape has already passed the same venue
  delay, so δ cancels on the tape clock.
  - x → [0, 0.25), the same-block bin.
  - It is labelled an upper bound because it includes prints in the detection block.
- **Assumption, stated:** the physical point is placed at the detection time. Detection lags the
  move's onset by up to 10 s, so this is not the true event time.

At whole-second resolution, all four stacks fall in the **same bin** for a given δ. **The tape
cannot tell London from Florida (a 65 ms difference) or a 20 ms from a 50 ms model.** The report
will say so, and will not present the difference as zero. Measuring it would need millisecond-stamped
order-book data for table tennis, which this study does not have.

## Variants, multiplicity, reporting
- **Variants:**
  - TT1: 2 verdicts (in-play, closing).
  - TT2: 1 rule.
  - **TT3: 1 rule** (frozen v2 causal; nothing else run).
  - TT4: descriptive.
  - TT5: 1 curve definition per sport and 1 decay test per sport. The 4 stacks × 2 readings are
    read-offs, not selectable variants.
- Nothing is chosen among alternatives after seeing table tennis data. The tennis variant counts
  (`docs/NOTE.md`) are unchanged by this study.
- **Scripts:**
  - `research/tt/build_tt.py`: fetch and prints only; no statistic.
  - `research/tt/tt_test.py`: TT1–TT5 in a single run. Each run is appended to
    `results/tt/peeks.log` with the UTC time and git hash.
  - Outputs go to `results/tt/`.
- **Results will be reported whatever they are:** passes, fails, "no trades", "underpowered" and
  "capacity is negligible" alike. Every number comes from code in the repo run on real public data.
