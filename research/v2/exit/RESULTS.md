# Lens "exit": taker in, maker out

**Question.** The fast tier's edge shows up within seconds, but the shadow book held to resolution
and so carried the binary outcome. That noise is what made the OOS dollars negative. Can an exit
by resting order keep the edge and drop the noise in today's venue regime (1 s order delay, 5% fee)?

**Answer (in-sample, walk-forward only; no OOS data touched).**

| Sizing: ≤500 shares/trade, net of fees | all IS, per share [95% CI] | all IS $ | 1 s / 5%, per share [95% CI] | 1 s / 5% $ | 1 s / 5% daily Sharpe | worst day |
|---|---|---|---|---|---|---|
| Hold to resolution (old shadow book) | +1.16c [0.81, 1.53] | $164k | +0.71c [0.01, 1.42] | $46.4k | 5.7 | −$8.8k |
| Taker out after H (H walk-forward) | +0.19c [0.14, 0.23] | $31k | **−0.35c** [−0.45, −0.27] | −$12.3k | −12.2 | |
| 30 s mid markout (benchmark, not tradable) | +0.92c [0.88, 0.96] | $112k | +0.65c [0.59, 0.72] | $24.5k | 28.7 | |
| **Maker out, 1 tick inside the touch (recommended)** | **+0.80c [0.75, 0.85]** | **$92k** | **+0.53c [0.42, 0.64]** | **$15.4k** | **10.3** | **−$1.2k** |
| Maker out at the touch (pre-declared base model) | +0.89c [0.84, 0.94] | $99k | +0.63c [0.52, 0.73] | $17.9k | 12.0 | −$1.1k |
| Maker out at the touch, 50% of fills dropped | +0.64c [0.57, 0.71] | $84k | +0.22c [0.08, 0.36] | $11.0k | 6.7 | |
| Maker out, pegged, always back of queue | −0.07c [−0.12, −0.01] | $24k | **−0.51c** [−0.62, −0.40] | −$10.7k | −7.0 | |
| Maker out, fixed level, must trade through | −0.12c [−0.17, −0.07] | $10k | −0.56c [−0.64, −0.48] | −$17.1k | −13.8 | |

All rows use the same 137,144 entries (8,514 matches, Dec 2025 to Aug 2026), sized at
min(print shares, 500) with at most $3k committed per match. Every maker row uses fallback B (exit as
taker after the timeout) and no rebate. (H, T) is chosen walk-forward each month. "Per share" is the
trade-weighted mean, as in `src/backtest.stats`. CIs come from a bootstrap clustered by match.

1. **The exit decides the sign.** Leaving as a taker pays the 5% fee twice and loses money
   (−0.35c). Leaving as a maker earns back the spread and avoids the second fee.
2. **The maker exit does not create edge. It turns the 30 s mid markout into tradable P&L and
   removes the binary noise.** In 1 s/5% the CI narrows from ±0.70c to ±0.11c per share. The
   worst day goes from −$8.8k to −$1.2k and the daily Sharpe from 5.7 to 10.3. Over all IS the max
   drawdown falls from −$18.1k to −$1.2k, and all 9 of 9 walk-forward months are positive (8 of 9
   for hold-to-resolution). Holding to resolution earned more IS dollars ($164k vs $92k). That gap is
   share-weighted big-ticket outcome risk: the same risk that turned OOS dollars negative. The
   trade-weighted per-share edges overlap.
3. **Placebo passes.** The same exit applied to non-fast-tier 0-3 s prints loses −0.9 to −1.1c,
   matching their 30 s markout (−0.94c). The fill model hands out no free spread.
4. **The queue assumption decides the size, and in 1 s/5% even the sign.** We have no historical
   depth. If our order always sits at the back of the queue and a level must clear before we fill,
   the exit loses −0.51c in 1 s/5%. The recommended fix is to **quote one tick (0.1c) inside the
   touch**. We are then alone at the best price, so any historical taker who paid the touch would
   have filled us first. That needs spread ≥ 2 ticks at the fill, which the tape spread proxy shows
   at all but 2.3-3.3% of fills. It costs 0.1c/share against the touch model (identical fills, 1
   tick worse each). It still assumes no other maker reacts by pennying us; see caveats.

## What was simulated (`sim_exit.py`)

- **Entries.** Every walk-forward-selected fast-tier 0-3 s print in
  `data/derived/shadow_is_uncapped.parquet` (138,691 prints, all IS; months < m qualify the wallets
  for month m). All of them matched exactly to their row in the match's trade tape.
- **Sizing.** Taken in **shares from the tape**. The shadow file's `usd/price` overstates shares on
  SELL prints (about 7% of entries in a 30-match check, up to 7x), because `usd` there is size × price of the token sold.
  `sh500` = min(print shares, 500). `usd1k` = min(print shares, $1,000 / price paid). Per match,
  cumulative entry dollars are capped at $3,000 in time order (D6). The cap binds on 1.1% (sh500) and
  5.2% (usd1k) of entries.
- **Exit order.** Posted at ts + H_min, lives T seconds (T counts from posting, so no grid cell is
  empty). Long outcome 0 (dir = +1) rests a sell at outcome 0's ask and fills on later prints with
  `at_ask=True`. Long outcome 1 (dir = −1) rests a sell of outcome 1, i.e. a bid on outcome 0, and
  fills on `at_ask=False` prints. P&L per share = dir × (exit p0 − entry p) − entry taker fee
  (+ optional 15% rebate of the counterparty's fee at the exit price).
- **Fill models (queue realism):**
  - `touch` (pre-declared base): the first exit-side print in the window whose *remaining* size ≥
    our shares fills us at its p0. This is a pegged order. Prints are consumed by our own earlier
    orders (FIFO). The fast-tier entry prints themselves never fill our exits.
  - `touch50`: the touch fills with half of them dropped at random (one seeded uniform draw per
    entry). Dropped fills go to the fallback.
  - `through`: the first exit-side print in the window sets our level L. We fill at L only when a
    later print trades ≥ 1 tick beyond L with enough size. The order does not re-peg.
  - `pegthrough`: pegged, but always at the back of the queue. We fill at level L = p0 of exit-side
    print k only when the next exit-side print trades ≥ 1 tick beyond L. Under price-time priority
    that cannot happen without filling us.
  - `improve1` (recommended): the touch fills at 1 tick worse. We quote 1 tick inside the spread,
    so we are alone at the best price.
  - `improve1g`: improve1 restricted to prints whose tape spread proxy is ≥ 2 ticks.
    **Rejected, see "What did not survive".**
- **Fallbacks when not filled by ts + H + T.** A: hold to resolution. B: exit as taker at the
  first opposite-side print at or after ts + H + T + venue delay + 1 s of our latency, paying the
  taker fee. If no such print exists before the match ends, the position resolves.
- **Grid.** H_min ∈ {2, 5, 10, 20, 30} s × T ∈ {30, 60, 120, 300} s = 20 cells per family.
  Extension T ∈ {600, 1800} s for the sh500/fallback-B touch, pegthrough and improve1g families.
- **Walk-forward rule (pre-declared).** For month m, pick the cell with the largest summed net P&L
  over months < m. Because the entry set is identical across cells, that is the best share-weighted
  net per share. If months < m hold < 1,000 entries, use the default (H = 5 s, T = 60 s); this
  applies to Dec 2025 and Jan 2026. The reported series concatenates each month's chosen cell,
  evaluated on that month only.
- **Pre-declared primary before any P&L was computed:** sh500 / touch / fallback B / no rebate.

## Walk-forward by month: recommended (sh500 / improve1 / fallback B / no rebate)

| month | regime(s) | entries | matches | chosen (H, T) | per share | share-wtd | P&L $ | maker fill | median hold | hold-to-res per share | hold-to-res $ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2025-12 | 3s/0% | 71 | 14 | 5, 60 (default) | +2.30c | +2.35c | 225 | 45% | 72 s | +2.08c | −417 |
| 2026-01 | 3s/0% | 4,464 | 606 | 5, 60 (default) | +2.63c | +1.69c | 5,562 | 50% | 64 s | +1.16c | 689 |
| 2026-02 | 3s/0% | 8,805 | 932 | 5, 30 | +1.08c | +0.92c | 8,036 | 40% | 44 s | +2.05c | 22,924 |
| 2026-03 | 3s/0%, 3s/3% | 3,361 | 403 | 5, 300 | +2.01c | +1.93c | 7,693 | 87% | 44 s | +0.43c | 2,559 |
| 2026-04 | 3s/3% | 14,509 | 1,359 | 5, 300 | +1.30c | +1.25c | 17,069 | 92% | 32 s | +1.98c | 23,864 |
| 2026-05 | 3s/3%, 1s/3% | 35,712 | 1,408 | 5, 300 | +0.63c | +1.01c | 17,035 | 96% | 24 s | +1.06c | 30,327 |
| 2026-06 | 1s/3% | 23,628 | 1,248 | 30, 300 | +0.63c | +1.20c | 18,353 | 92% | 55 s | +1.23c | 27,332 |
| 2026-07 | 1s/3%, 1s/5% | 28,250 | 1,399 | 30, 300 | +0.47c | +0.36c | 8,009 | 91% | 59 s | +1.01c | 38,162 |
| 2026-08 (to 08-25) | 1s/5% | 18,344 | 1,154 | 30, 300 | +0.67c | +0.54c | 9,975 | 90% | 61 s | +0.56c | 18,980 |
| **all** | | 137,144 | 8,514 | | **+0.80c** | +0.90c | **91,958** | 88% | 46 s | +1.16c | 164,420 |

Positive in 9/9 months on both per-share and dollars. Hold-to-resolution was negative in dollars in
Dec 2025. Walk-forward daily Sharpe is 14.1 (hold-to-resolution 6.2) and max drawdown −$1.19k
(−$18.1k). Capital is 3 × peak dollars locked (D6 convention): $10.7k for the maker book, since
positions last a median 46 s with p90 225 s, against $79.5k for hold-to-resolution.

**By regime (same walk-forward series):** 3s/0% +1.69c (16,064 entries); 3s/3% +0.91c (32,509);
1s/3% +0.65c (49,134); **1s/5% +0.53c [0.42, 0.64]** (39,437 entries, 2,224 matches, 46 days,
$15.4k, both months positive). The 5% fee averages 1.01c/share on 1s/5% entries.

**Where the 1s/5% P&L comes from** (`tables/decomp_sh500_improve1_fbB_norebate.csv`): 90.7% of
entries exit as makers at +0.78c/share (+$30.5k, median 54 s). 8.1% time out and exit as takers at
−2.39c (−$15.4k, about 360 s): price ran away from us and we pay the fee plus spread. 1.2% resolve
(+$0.2k). The taker fallback is the main remaining drag.

**Grid plateau (descriptive, all IS months pooled, NOT used for selection), improve1 / fallback B,
per share:** all 20 cells are positive, 0.54 to 0.83c over all IS and 0.12 to 0.54c in 1s/5%. H
hardly matters; longer T helps (fill rate 52-57% at T = 30 s, 91-92% at T = 300 s). The extension
grid adds little: touch with T up to 1800 s gives +0.66c in 1s/5% against +0.63c. **Frozen rule for
a future single OOS run:** the cell chosen on all IS months, H = 10 s, T = 300 s, improve1, fallback B.

## Other comparisons (all walk-forward; full table in `tables/comparison_all_variants.csv`)

- **Shares vs dollars.** Per share is similar (touch/fallback B: 0.89c sh500 vs 0.85c usd1k), but
  dollar sizing loads thousands of shares onto cheap longshots. The 1s/5% Sharpe falls from 12.0 to
  3.1 and the all-IS max DD rises from −$1.1k to −$7.1k. Under the 50% haircut, usd1k 1s/5% dollars turn
  negative (−$2.8k) while sh500 stays positive (+$11.0k). **Size in shares.**
- **Fallback A (hold unfilled to resolution) vs B (taker out).** A has the higher mean (touch:
  0.77c vs 0.63c in 1s/5%), because unfilled positions lose less held (−0.8c) than dumped as takers
  (−2.4c). But A brings back the binary noise: 1s/5% Sharpe 7.8 vs 12.0, all-IS DD −$5.6k vs −$1.1k.
  B is the low-variance choice. A is reported throughout.
- **Maker rebate (15% of the counterparty's fee, approximated on our own fills).** Adds about
  +0.1c/share in 1s/5% (improve1: 0.53c → 0.67c; touch: 0.63c → 0.76c). The pool is pro-rata
  across makers and its exact share is unknown, so the headline excludes it.
- **Taker out after H, the no-maker baseline.** Positive only in the zero-fee 3 s era. In 1s/5% it
  is −0.35c even at the walk-forward-preferred H = 30 s.

## Placebo (`placebo_exit.py`, `tables/placebo_nonfast_0_3s.csv`)

Entries are 0-3 s post-jump prints by wallets NOT in the walk-forward fast tier. Same months, a
seeded sample of 1,500 shadow matches, ≤ 16 random prints per match: 20,171 entries. Same simulator
and sizing.

| exit | all IS per share [CI] | 1 s / 5% per share [CI] |
|---|---|---|
| hold to resolution | −0.57c [−1.26, 0.03] | −1.58c [−2.79, −0.29] |
| 30 s mid markout (benchmark) | −0.94c [−1.07, −0.82] | −1.13c [−1.30, −0.95] |
| maker, touch, H = 30 s / T = 300 s | −0.91c [−1.09, −0.73] | −1.12c [−1.34, −0.87] |
| maker, 1 tick inside, H = 30 s / T = 300 s | −1.00c [−1.19, −0.82] | −1.21c [−1.43, −0.97] |
| maker, back of queue, H = 30 s / T = 300 s | −2.86c [−3.08, −2.68] | −3.09c [−3.38, −2.82] |

The maker exit reproduces each group's 30 s mid markout: −0.91c vs −0.94c for slow takers and
+0.89c vs +0.92c for the fast tier. The exit is a way to realise the entry's information, not a
source of edge. The money still comes from being in the 0-3 s fast tier.

## What did not survive (reported, not used)

- **Fixed-level trade-through** (`through`) fails for a design reason, not a queue reason. The order
  never re-pegs, so when price runs away it is stranded, and the timed-out taker exits lose about
  −8c/share at T = 300 s. Its numbers are in the table, but it is a poor policy rather than a
  queue bound. `pegthrough` is the real conservative queue bound.
- **improve1g** (1 tick inside, but only on prints whose tape spread proxy ≥ 2 ticks) scored
  *higher* than touch (0.93c vs 0.89c) although it pays a tick on every fill. `diag_spread.py` shows
  why. The gate drops "crossed" proxies: an ask-side print below a stale bid-side print, i.e. a
  falling market. Those are 9.6-13.5% of fills and lose −2.1 to −2.8c each. The gate also drops
  "unknown" proxies (24-27%), which are profitable. The gate is a hidden direction filter built from
  stale-quote artifacts, so it was rejected. The recommended `improve1` is ungated: it keeps every
  touch fill and pays the tick on all of them.

## Variants tried: 902

- `analyze_exit.py`: 894 unique evaluated configurations.
  - Baselines: hold-to-resolution and 30 s markout × 2 sizings = 4.
  - Taker out after H: 5 H × 2 sizings = 10.
  - Maker families: 5 fill models (touch, touch50, through, pegthrough, improve1g) × 2 fallbacks ×
    2 rebate settings × 2 sizings × 20 cells = 800.
  - improve1 (sh500, fallback B, ± rebate): 40.
  - Extension cells T ∈ {600, 1800} for 4 sh500 fallback-B families (touch, pegthrough,
    improve1g ± rebate): 40.
- `placebo_exit.py`: 8.
- Each family's walk-forward picks among its 20 (or 30) cells using past months only. Fill model,
  sizing, fallback and rebate are *not* selected on P&L. They are reported side by side.

**Chronology (honest record of what was added after seeing results):**

1. First run: touch / touch50 / through. The primary (touch) was declared before it.
2. through's failure led to adding pegthrough.
3. The walk-forward kept picking T = 300 s, the grid edge, which led to the T ∈ {600, 1800}
   extension.
4. pegthrough's failure showed the queue assumption is decisive, which led to improve1 and
   improve1g.
5. improve1g's implausible gain led to `diag_spread.py` and its rejection.
6. The placebo was added last as a check on the fill model.

improve1 is recommended on realism grounds. Fill-for-fill it is exactly the touch model minus one
tick, so it cannot be a P&L-search artifact relative to the pre-declared primary.

## Caveats

- **Entry feasibility (inherited from H6).** The shadow book assumes we get the fast tier's 0-3 s
  fills. That requires being in that tier: courtside or tracking-speed information plus sub-second
  execution. Copying them 3 s later loses (H6). This lens fixes the exit, not the entry. It is not
  remote-executable at today's speed.
- **Queue position is unobservable in the tape.** touch is optimistic and pegthrough pessimistic;
  the 1s/5% sign flips between them (+0.63c vs −0.51c). improve1 assumes (a) spread ≥ 2 ticks
  (true at about 97% of fills with a usable proxy) and (b) no other maker pennies our inside quote.
  Real makers can cancel and re-quote instantly, so a penny war is plausible and would push our
  fills toward pegthrough. The live book data that could calibrate this lies in the forward/OOS
  window and was not used (rule 1).
- **Print semantics.** A print is a taker fill record from data-api. "Size ≥ ours" is
  all-or-nothing (partial fills ignored, which is conservative), and our own resting orders consume
  print size. The taker-fallback price is the first opposite-side print: no depth walk, no impact.
- **Small current-regime sample.** 1s/5% is 46 days (2026-07-11 to 2026-08-25), 2 calendar months
  and 39k entries. The per-share CI is tight because the trades are many and short, but regime-level
  inference rests on 2 months.
- **Daily Sharpe** is computed on calendar-day P&L with zero-trade days included. With hundreds of
  sub-minute trades a day it is naturally high. The per-share CIs and the placebo carry the evidence.
- **Rebate** is approximated as 15% of the fee on our own fills; the real pool is pro-rata.
- **Capacity** is bounded by the fast tier's own print sizes, since we copy ≤ 500 shares of each
  print, and by taker flow at the far touch. In 1s/5% that is $1.9M of entry notional over 46 days:
  about $1.26M a month, ~$10k/month net (~$12k with rebate), on about $10.7k of capital
  (3 × peak locked). Scaling up needs depth data we do not have IS.
- `tables/comparison_all_variants.csv` lists every family. Only walk-forward series are reported
  as results. Pooled-grid numbers are descriptive and labelled as such.

## Reproduce (from the repo root; IS data only; ~15 min on 2 cores)

```bash
.venv/bin/python research/v2/exit/run_exit.py          # everything below in order
# or step by step:
.venv/bin/python research/v2/exit/sim_exit.py          # ~7 min -> data/v2_exit/{entries,maker,fallback}.parquet
.venv/bin/python research/v2/exit/analyze_exit.py      # ~1 min -> results_full.json, tables/wf_*, tables/baseline_*
.venv/bin/python research/v2/exit/placebo_exit.py      # ~3 min -> placebo.json, tables/placebo_nonfast_0_3s.csv
.venv/bin/python research/v2/exit/diag_spread.py       # ~1.5 min -> tables/diag_spread_at_fill.csv
.venv/bin/python research/v2/exit/report_exit.py       # results.json, tables/comparison_all_variants.csv, figures/
```

Inputs: `data/derived/shadow_is_uncapped.parquet`, `data/derived/universe_is.parquet`,
`data/derived/prints_0_3s_is.parquet` (placebo), and `data/raw/trades/<cond>.parquet` for IS matches
only (start < 2026-08-25 14:15 UTC). Nothing in `data/locked/`, no OOS tapes, and no network.

Figures: `figures/exit_equity_wf.png` (walk-forward cumulative P&L, four exits) and
`figures/exit_fillmodel_1s5.png` (1s/5% per share with CI, by exit and fill model).
