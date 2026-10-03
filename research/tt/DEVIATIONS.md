# Table tennis study: deviations and pre-run decisions

Written 2026-10-03, after the dataset commit `a7105a6` and **before** the first TT1–TT4 run. Before
writing this file, the only table tennis data read beyond `research/tt/DATA.md` was the schema of
`data/tt/prints.parquet` and its count of matches per calendar month (2026-02: 2, 03: 1, 04: 4,
05: 1, 07: 10, 09: 9). No price, markout, calibration, fast-tier or P&L figure had been computed on
table tennis.

Nothing below changes a rule, threshold, parameter, bin or bootstrap setting in `HYPOTHESIS_TT.md`.
Items marked **deviation** change the procedure; items marked **clarification** fix a reading of the
pre-registration where it leaves a choice open.

## TT-D1 (deviation). Script name and scope of this run
- The pre-registration names `research/tt/tt_test.py` and "TT1–TT5 in a single run". This run uses
  `scripts/tt_analyze.py` and evaluates **TT1–TT4 only**, as the task for this step specifies.
- TT5 (signal decay vs latency) is not computed here. When it runs, it is its own single run with its
  own log line. No TT1–TT4 output feeds any TT5 setting: every TT5 bin, statistic and read-off is
  already fixed in `HYPOTHESIS_TT.md`.
- Every run is logged twice before any result is printed: in `results/tt/peeks.log` (UTC time and git
  hash, as pre-registered) and in the track log `results/oos_peeks.log`.
- The script refuses a second run unless it is given `--rerun`, which is logged as a re-run.

## TT-D2 (clarification). A TT1 test with no judged bin
TT1 judges only bins with ≥ 30 matches (and never the in-play [0.99, 1.0) bin). If a test has
**no** bin to judge, it reads "not judged (no bin with ≥ 30 matches)". It does not read
"calibrated", so TT1 does not hold. It is reported as FAIL (not judgeable).

## TT-D3 (clarification). TT1 secondaries
- **Bonferroni CIs** use the same 500 bootstrap draws (seed 0) as each bin's primary CI. They take the
  percentiles 100·0.025/k and 100·(1 − 0.025/k), with k the number of judged bins in that test. If
  k = 0, no Bonferroni CI is reported. The script checks that its draws reproduce
  `run_all.calibration()`'s 95% CIs exactly.
- **Pooled mean of (won − fav)**: over the in-play observations (first print per match-minute) with fav
  in [0.5, 0.99). Observation-weighted. CI: resample matches, 2,000 draws, seed 0
  (`fasttier.cluster_ci`).
- **Truncated in-play test**: per match, only prints strictly before the match's first in-play print
  with max(p, 1 − p) ≥ 0.99. Then `run_all.calibration()` runs unchanged on those prints.
- **By league**: `run_all.calibration()` on each league's prints (and tape observations for the
  closing test).
- **Closing test**: the last fill by `timestamp` on the raw tape (`src.tape.load_tape`; ties keep
  tape order, which is `fetch_trades`' stable sort) in [start − 86,400 s, start). Its `p0` is the
  price. Those one-per-match rows go through `run_all.calibration()` unchanged. With one observation
  per match, its per-bin bootstrap is a bootstrap over matches, as pre-registered. Matches with no
  fill in that window have no closing observation; their count is reported.

## TT-D4 (clarification). TT2 "others", gap and NaN markouts
- The walk-forward is `fasttier.walk_forward(P, start_month=2, bucket="bucket_c")` on
  `tiers.add_causal_bucket(P)`.
- That function returns the fast-tier prints (its shadow) but not the per-print "others". So the
  script rebuilds the labelled 0–3 s prints with `fasttier.qualify` month by month, the same loop
  `walk_forward` runs. It asserts that its fast set and monthly means equal `walk_forward`'s output.
- Prints with no mid 30 s later have `net30 = NaN`. They are dropped before every mean and CI. That is
  what `walk_forward`'s pandas means already do, and what Primary A of `scripts/forward_test.py`
  does.
- The gap CI uses Primary A's code: resample matches among all matches with 0–3 s prints in evaluated
  months; 2,000 draws, seed 0.
- (c) counts only evaluated months with ≥ 1 fast-tier print that has a `net30`. (d) splits fast-tier
  prints by their match's `oos` flag. A period with no fast-tier print fails (d).
- "Underpowered" means fewer than 30 distinct matches with a fast-tier print (with `net30`).

## TT-D5 (deviation, code path only). TT3 when the fast tier is empty
`src.v2.run` cannot build features from an empty shadow: `build_features` sorts by columns that an
empty frame does not have. So the script first calls the same
`fasttier.walk_forward(add_causal_bucket(P), bucket="bucket_c")` that `v2.run` calls.
- If that shadow is empty, TT3 is recorded as **"no trades" (FAIL)** in both periods, as the
  pre-registration's rule says. `v2.run` is not called.
- If the shadow is non-empty, `v2.run(P, ends, causal=True)` runs unchanged.
- If v2 returns zero trades in a period, that period fails as "no trades".

No file in `src/` or `research/v2/` is edited.

## TT-D6 (clarification). TT3 empty-training month and count metrics
- The empty-training month is the first month that has shadow rows. Its trades are identified by
  `month == first shadow month`.
- They stay in every share- or dollar-weighted number: `E.metrics` on the full period, by-league $ and
  per-share figures, and the cost stress.
- They are left out of every count: trade count, matches with v2 trades (used for the
  "underpowered" label), trade win rate, per-print means, and active and profitable days. A day
  holding only such trades would otherwise show a P&L of about 1e-6 $ and count as an "active" or
  "profitable" day.
- **Return-on-capital CI**: zero-filled calendar days from `E.daily_series` on the full period,
  i.i.d. bootstrap of days, 2,000 draws, seed 0. Capital is held at `E.metrics`' `capital_usd`.

## TT-D7 (clarification). TT4 sources
- **Volume per match** (listed, tape, pre-start and in-play) is computed for every UTT market from
  the cached tapes, using the committed `scripts/tt_build._market_volume`.
- **Listed volume is in shares, not dollars.** `research/tt/DATA.md` found that gamma's `volume`
  equals the sum of fill sizes. It is reported under that label.
- **Depth proxies.** In-play print size, in-play prints per minute and the `_mid_series` spread proxy
  are computed on the raw in-play tape of **every** UTT market, not only the 27 with ≥ 20 in-play
  prints.
  - Prints per minute = in-play fills ÷ the in-play window (start → end) in minutes, per market with
    end > start.
  - The spread proxy is `tiers._mid_series`' ask − bid where both sides are fresh. It is reported as
    the median over fills and as the median of per-market medians.
- **Bucket-based figures** (USD in the causal 0–3 s bucket per detected jump, fast-tier volume) need
  `bucket_c`, which exists only for the 27 matches in `data/tt/prints.parquet`.
  - Detections are counted with `tiers.jump_onsets` on each match's print table, the call
    `add_causal_bucket` makes.
- **Book snapshot** (optional item): taken once in this run from public gamma `/events`
  (`tag_id=103767`, `closed=false`) and clob `/book`.
  - At most 300 open moneylines, nearest start to now first, one outcome-0 book each, requests in
    sequence.
  - Depth = USD (size × price) resting within ±1¢ and ±2¢ of the book mid.
  - Labelled a snapshot, not history. A failure there does not stop the run.
- **Tennis context.** v2 `usd_in` and $ P&L per calendar day, from `data/v2_trades_is_oos.parquet`,
  over the calendar months in which table tennis v2 traded. If table tennis v2 has no trades, the
  months used are the TT2 walk-forward evaluated months instead.
- **Capacity rule** (unchanged): v2 deployed USD per calendar day < $1,000 over its table tennis
  trading window → "capacity is negligible". No trades counts as $0 per day.

## TT-D8 (decision on the open item in DATA.md). The 96 zero-listed markets that traded
- UTT and every verdict stay exactly as pre-registered.
- One labelled **sensitivity** reruns TT1, TT2 and TT3 on UTT plus the 96 markets in
  `data/tt/universe_unlisted.parquet` / `prints_unlisted.parquet`. The period is assigned by the
  pre-registered cut (all 96 are IS). The UTT split is not recomputed.
- The sensitivity never changes a PASS or FAIL. It is the only extra variant in this run.

## TT5-D1 / TT5-D2 (TT5 only; written 19:17 UTC before the TT5 run)
TT5 runs on its own as `scripts/signal_decay.py` (outputs `results/decay/`, write-up
`research/decay/RESULTS.md`), logged in `results/tt/peeks.log`. The TT5 definition is unchanged. The
non-pre-registered secondaries (net-to-resolution, fast-tier curves, period splits, stream/feed/measured-CV
stacks, unlisted-markets sensitivity) are listed in `research/decay/PRERUN.md`.
TT5-D3 (19:21 UTC, before the TT5 run): tape stamps step in 2 s blocks, so the pre-registered [1, 2) bin is
(nearly) empty; TT5 reports the pre-registered test as written plus a block-resolution version that merges
[1, 2) and [2, 3) into [1, 3). Details in `research/decay/PRERUN.md`.
