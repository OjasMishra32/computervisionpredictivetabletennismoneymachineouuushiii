# Out-of-universe test of frozen v2 (U2): pre-registration

Written 2026-10-03 ~17:15 UTC on top of 113ed22. This file is committed before any U2 trade tape is
fetched. Up to this commit nobody had loaded a U2 tape, built a U2 print, or computed any U2 P&L,
markout or strategy statistic. The only U2 facts used below are catalogue metadata: series, volume,
res0, start time, fee rate, delay and tick, all read from
`data/raw/events_tennis_2025-07-01_2026-10-03.parquet`.

## Why
COURTSIDE v2 (`src/v2.py`, `run(prints, ends, causal=True)`, rule in `HYPOTHESIS_V2.md` with A1) was
designed and evaluated only on U1 = `src.tape.universe()`: ATP/WTA/Challenger singles moneylines
with volume >= $5k, 13,084 matches. Results so far are IS Sharpe 14.5 at +1.38¢/share, and burned
OOS Sharpe 6.7 at +0.60¢/share. The OOS number is non-blind. No analysis in this repo has looked at
any other resolved Polymarket tennis moneyline, so those markets are a clean test set. This test
asks whether the frozen rule earns money on markets it was never designed on, in both periods.

## U2: the unseen universe
U2 is every row of the tennis event catalogue that satisfies all of the following:
- `series` in {atp, wta, challenger, itf}. The catalogue has no `challenger` label because
  Challengers are filed under `atp`, so in practice the series are atp, wta and itf.
- `series` does not contain "doubles". The doubles series are atp-doubles and wta-doubles. No
  title in atp/wta/itf contains " / ", so no doubles rows remain.
- `volume >= 1000`.
- `res0` in {0, 0.5, 1}, meaning the market resolved. The single 0.9995 row is excluded.
- `start < 2026-10-03 07:10 UTC`, which is the latest U1 match start. Start is parsed with
  `pd.to_datetime(start_time, utc=True, format="mixed")`. Rows with no start time are excluded,
  and none of them meet the other conditions.
- `cond` is not in U1.

Columns are prepared exactly as in `src.tape.universe()`:
- `start` is `start_time` in UTC.
- `end` is `to_datetime(finished.fillna(closed_time), utc=True, format="mixed")`.
- `fee_rate` is `fee_rate.fillna(0)`.
- `delay` is `seconds_delay.fillna(1)`.

The `oos` flag is `start >= 2026-08-25 14:15 UTC`, which is the U1 OOS cutoff.

**Expected count, from the catalogue: 11,307 markets in 11,307 distinct events.**

| | count |
|---|---|
| itf | 10,855 |
| atp | 292 (all with volume < $5k, otherwise they would be in U1) |
| wta | 160 (same) |
| IS period (start < 2026-08-25 14:15 UTC) | 7,743 |
| OOS period (start >= cutoff) | 3,564 |
| res0 = 1 / 0 / 0.5 | 5,818 / 5,309 / 180 |
| volume $1–2k / $2–5k / $5–10k / $10–100k / > $100k | 2,692 / 3,642 / 2,162 / 2,757 / 54 |
| fee rate 5% / 3% / 0% | 7,460 / 3,549 / 298 |
| order delay 1 s / 3 s | 10,952 / 355 |
| start range | 2025-10-11 to 2026-10-03 02:00 UTC |

Overlap checks against U1 (metadata only):
- No shared `cond` and no shared `event_id`.
- No shared title+start pair.
- No duplicate title+start inside U2.

The set of matches that can actually be evaluated will be smaller than 11,307, because of the
same rules that applied to U1:
- Matches whose tape fetch fails are dropped.
- Matches with fewer than 20 in-play prints are dropped (`match_prints` returns None).
- Matches before 2026-02 are used for training only.

The final count will be reported; it does not change the test.

## Data build (`research/v2/expand/build_u2.py`)
1. Fetch tapes with `src.polymarket.fetch_many_trades(U2.cond, workers<=6)`. This is the same
   fetcher used for U1, including the data-api's 10,500-fill offset cap, which also applied to U1.
2. Build prints for every U2 match with `src.tiers.match_prints(row)`, using the row prep above
   and at most 3 processes. Write `data/expand_prints.parquet` and `data/expand_universe.parquet`
   (U2 rows with start, end, res0, fee_rate, delay, series, volume and the oos flag).
3. The build step computes no P&L, markout summary or strategy statistic.

## The test (run once, by a script in this folder, output logged)
1. **Prints.** `P = concat(data/is_prints.parquet, data/locked/oos_prints.parquet,
   data/expand_prints.parquet)`, with no dedup. **Ends.** U1 `end` and U2 `end`, indexed by `cond`.
2. **Run.** `tr, wf = src.v2.run(P, ends, causal=True)`, frozen, with no parameter, threshold,
   zone, cap or sizing change. Every month m qualifies wallets, applies the wallet filter and
   normalises deployment using U1 ∪ U2 prints from months before m, as in the frozen rule. U1 and
   U2 both start in 2025-10, so the walk-forward month grid is unchanged.
3. **Period assignment.** A trade's period is its match's start: IS if start < 2026-08-25
   14:15 UTC, OOS otherwise. `E.metrics` keeps only months >= 2026-02, because Dec 2025 and Jan
   2026 are training-only in the frozen rule. In practice the IS period covers trades from
   2026-02 onwards.
4. **Books evaluated**, each through `v2.E.metrics`:
   - U2-IS and U2-OOS: trades in U2 matches. Capital is 3× the subset's own peak locked capital,
     using the metrics default with the 4 h ex-ante lock.
   - Combined-IS and Combined-OOS: all trades, U1 ∪ U2.
   - Context only, not tested: U1-IS and U1-OOS from the same joint run. These show how adding U2
     history changes U1's own trades.

### Primary (the pass/fail claim)
The primary metric is U2 per-share net P&L held to resolution: `per_share_c` with `per_share_ci_c`
from `E.metrics`. It is share-weighted, with a match-clustered bootstrap (1,000 draws, seed 0).

**PASS only if the lower bound of the 95% CI is > 0 in the IS period AND in the OOS period.**

### Secondary (reported, not tested), for U2-IS, U2-OOS, Combined-IS and Combined-OOS
- Daily Sharpe (`sharpe_ann`: daily P&L with zero-filled calendar days, × √365).
- Max drawdown in $ and as % of capital, worst day, and months positive out of months total.
- $ P&L and its CI, number of trades and number of matches.
- Resolution per share at +½ tick and +1 tick of entry slippage: `pnl_ps − 0.005` and
  `pnl_ps − 0.01`, the same as `scripts/v2_causal.py`, then `E.metrics`.
- U2 v2 book 30 s net markout, share-weighted:
  `m30_ps = gross30 − (gross_res − pnl_ps)`, with rows where gross30 is NaN dropped. The CI comes
  from `scripts/forward_test.cluster_ci` (match-clustered, 2,000 draws, seed 0).
- U2 fast-tier minus others, 30 s gap:
  - Prints: U2 prints in the causal 0–3 s bucket (`add_causal_bucket`, `bucket_c == "0-3s"`), in
    months >= 2026-02, split by period.
  - Fast: a print's wallet is `fasttier.qualify(prints of months < m, "bucket_c")` for that
    print's month m, using all U1 ∪ U2 prints.
  - `net30 = mo30 − fee_rate·p(1−p)`.
  - The statistic is the print-weighted mean of fast minus the print-weighted mean of others, with
    a match-clustered bootstrap (2,000 draws, seed 0), as in Primary A of `forward_test.py`.

### Fail conditions
- If the U2 primary CI includes 0 or is negative in either period, the result is reported as a
  **FAILURE** of out-of-universe generalisation for that period.
- If a period has fewer than 30 U2 matches with v2 trades, it is also labelled "underpowered".
  That label does not turn a fail into a pass.
- The verdict is reported whatever it is. Sharpe is not a pass criterion.

## Rules
- v2 is not changed in response to this test. Any rule tuned on U2 (for example an ITF-specific
  filter, a different volume floor or new caps) is a new hypothesis. It would need its own
  pre-registration and a fresh forward window, and U2 would count as in-sample for it.
- Any deviation from this file (data problems, a bug in the build, a changed definition) goes in
  `research/v2/expand/DEVIATIONS.md` with its reason, before the test is re-run.
