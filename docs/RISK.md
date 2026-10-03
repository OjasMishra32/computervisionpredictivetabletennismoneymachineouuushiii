# COURTSIDE risk register

Written 2026-10-03 (about 18:45 UTC); updated about 19:40 UTC with the PM review's compute items (`scripts/pm_compute.py` → `results/financials/pm_compute.json`, marked `pm_compute`) and the results that landed since (maker blind OOS, corrected tier-0 headline); audited about 20:00 UTC (every number traced to its source; stale engine-demo, vision and live-session figures refreshed; fixed-cost table aligned with `research/financials/FINANCIALS.md` §1). Paper only: this repo places no orders and holds no keys. No live ATP/WTA point feed was bought or used, and no courtside camera was operated: tier-0 is a counterfactual, and the "official stamps" below are the WTA's public point-by-point log, read after the fact.

Every number below comes from a file in this repo or from a public source with its URL. Numbers marked
`risk_stats` come from `scripts/risk_stats.py`, which writes `results/risk/risk_stats.json` (run:
`.venv/bin/python scripts/risk_stats.py`, about 20 s). That script reads existing results only. It reproduces
`results/v2/causal.json` and `results/v2/cost_stress.json` to the cent before computing anything, and it re-tunes
nothing. When something has not been measured, this file says "unmeasured".

**Conventions.** IS = Feb 1 to Aug 25 2026 (206 days). Burned OOS = U1 matches starting from 2026-08-25 14:15 UTC
(40 days). The burned OOS is non-blind (`results/oos_peeks.log`). Capital = 3 × peak locked dollars, with a 4 h
ex-ante lock per position (v2, v2-safe). The maker's lock runs from entry to the side market's resolution
(`research/v2/crossmarket/analyze.py` `capital_for`), and tier-0's capital is the 20-seed mean of 3 × its own peak. Each
period uses its own peak, which a trader cannot know in advance; on one capital fixed ex ante (v2's IS $28,302) the
burned-OOS return is 119% a year, not 148% (`FINANCIALS.md` §2c). Tier-0's IS covers only the 1 s-delay matches
(trades from 2026-05-15, 103 days), not the 206-day IS above. Per-share CIs are 95%, match-clustered. Sharpe = daily
mean / sd × √365 on zero-filled calendar days.

**What each strategy is, and whether it can trade live.**

| Book | What it is | Can it trade live today? | Evidence status |
|---|---|---|---|
| **v2** | Frozen fast-tier book (`HYPOTHESIS_V2.md`, `src/v2.py`), priced at the fast tier's own fills | **No.** It measures the opportunity at the fast tier's speed. Copying the fast tier from a remote seat loses money (late-entry stress below: −0.89¢/share IS) | IS +1.38¢ [1.17, 1.59]; burned OOS +0.60¢ [0.09, 1.13]; blind U2-OOS +1.22¢ [−0.19, 2.65], FAIL; forward test `results/v2/forward.json` **pending** (one run, about 11:30 UTC Oct 4) |
| **v2-safe** | v2 with the net cap at 50 shares (`research/v2/lowloss/`) | Same as v2 | Burned OOS +0.69¢ [0.24, 1.15]; blind U2-OOS FAIL |
| **tier-0** | Counterfactual: courtside camera + own CV + licensed point feed + London gateway. Not purchased, not built | **No.** Needs a data licence and organiser consent (see R16) | A verifier refuted the pre-registered fill pricing (`research/v2/tier0/DEVIATIONS.md` V1–V10). Corrected headline (`results/tier0/results.json` `headline`, 20-seed means; `results/tier0/VERIFIED` present): IS +1.10¢ [0.82, 1.38], $88.8/day, Sharpe 11.4 (IS = 1 s-delay matches only, 103 days); burned OOS +0.58¢, $46.4/day, Sharpe 7.3. Fixed costs at 10 covered matches a day are $1,153 / $4,149 / $7,215 per day (low / central / high, `research/financials/FINANCIALS.md` §4), so it is uneconomic in every cost case |
| **maker v1** | Leaning maker on side markets (`research/v2/crossmarket/RESULTS.md` 5b) | **Technically yes, remotely:** public moneyline feed plus post-only quotes. Live *paper* trading only: a US person cannot open positions on polymarket.com, and the hackathon forbids funded accounts (checklist 1–2) | IS +2.73¢ [1.73, 3.70] per fill (share-weighted +2.59¢ [−0.09, 5.20]). **Blind OOS: FAILURE**, +1.87¢ [−0.14, 3.86] per fill, −$379 (−0.75¢/share share-weighted) (`results/maker/oos.json`). Live paper session `20261003T193534Z` (`results/live/summary.json`) started 19:35 UTC, passed its trade-side warm-up and began paper quoting about 20:00 UTC; 0 fills at 20:03 UTC. It books $10,000 of paper capital per book, not the 3 × peak-locked convention ($2,022–2,779), and checks plumbing only |
| **table tennis** | Out-of-sport test (`HYPOTHESIS_TT.md`) | **No.** Polymarket TT books: 89¢ median spread, $23 at the touch (NOTE §6) | First run 19:23 UTC (`results/tt/results.json`): 27 evaluable matches; TT1 FAIL, TT2 FAIL (no fast tier detected), TT3 FAIL (no trades) |

---

## Pre-trade checklist (one page)

Go only if every line is YES. Any NO means no new risk; risk-reducing orders are still allowed.

| # | Check | Pass condition | Where checked |
|---|---|---|---|
| 1 | Operator jurisdiction | Not a resident of a close-only or blocked jurisdiction on the venue used. The US, UK, France, Canada (BC, ON, AB, QC), Australia and Germany are close-only on polymarket.com, including the API ([Polymarket geoblock](https://docs.polymarket.com/api-reference/geoblock)). A US person needs Polymarket US, which is a separate venue and untested here | policy only; legal sign-off |
| 2 | Competition rules | Hackathon TERMS 5.3: no funded exchange account is connected to any Event activity (`research/compliance/REQUIREMENTS.md` item 44). Paper only during the event | policy only |
| 3 | Data rights | v2 and maker use only public, keyless Polymarket data. Tier-0 needs a licensed point feed and organiser consent for any courtside capture. **Neither is held, so tier-0 cannot go live** | policy only (R16) |
| 4 | Venue parameters equal the backtest | Each market's `feeSchedule.rate` = 0.05, `secondsDelay` = 1, tick 0.01, minimum size 5 shares (`research/v2/maker/VENUE_RULES.md`). If anything differs: stop and re-run `scripts/v2_cost_stress.py` | policy only; values are read per market by `src/polymarket.py` |
| 5 | Capital funded | At least 3 × peak locked: v2 $28,302 (IS); v2-safe $17,681. Holding 3 × the *realised* peak ($34,818 IS) covers matches that run past the 4 h lock assumption (R13) | `risk_stats` `liquidity_capital` |
| 6 | Risk config loaded and tested | `RiskConfig()` defaults: $1k per order, net cap 100 shares per match, zone 0.05–0.95, daily stop $1k, feed-stale 2 s, vision-stale 1 s, latency above p95. `pytest tests/test_engine_risk.py` passes | `engine/risk/limits.py` |
| 7 | Feeds healthy | Feed delay near the measured baseline (p50 58 ms, p95 102 ms, p99 134 ms); no `gap` event in the last minute; Mission Control green | `engine/market/clob.py`, `docs/live/control.html` |
| 8 | Keys | No key on disk or in env on the research host. The paper executor refuses to start if a live flag or key variable is set | `engine/execution/paper.py` (`LiveTradingForbidden`) |
| 9 | Signal freshness | v2: wallet set re-qualified walk-forward this month and filtered at today's fee. Tier-0: CV precision on audited calls with a Wilson 95% lower bound ≥ 0.95 (that takes at least 73 correct calls in a row; see R7) | `src/fasttier.py`, `src/v2.py`; policy only for CV |
| 10 | Edge still alive | Trailing 30-day net edge ≥ 0.3¢/share (else half size); > 0 (else stop) | policy only (NOTE §5); replayed on IS it never fires (`pm_compute` P25: trailing edge min +0.74¢) |
| 11 | Settlement rules read | Retirement after the start resolves to the advancing player. Walkover, cancellation, tie, or no winner within 14 days resolves 50-50 ([market rules](https://polymarket.com/sports/wta/wta-bouzkov-birrell-2026-10-01)) | policy only |
| 12 | Kill switch tested today | `RiskManager.kill("manual")` blocks every order, risk-reducing ones included | `engine/risk/limits.py` |

## Daily kill-switch rules (summary)

| Trigger | Action | Implemented in |
|---|---|---|
| Day P&L (marked, since 00:00 UTC) below −$1,000. That is 3.86 σ of IS daily P&L; a 5 σ day is −$1,294 | Latch to the next UTC day; only risk-reducing orders pass | `engine/risk/limits.py` `daily_stop_usd` |
| No market data for > 2 s | Risk-reducing only until data returns | `limits.py` `feed_stale_ms` |
| No vision heartbeat for > 1 s (tier-0 only) | Risk-reducing only | `limits.py` `vision_stale_ms` |
| Recent feed delay (median of last 25) > rolling p95 (floor 150 ms), or > 2 s | Risk-reducing only | `limits.py` `latency_*` |
| Manual kill | Everything halts, including risk-reducing orders | `limits.py` `kill("manual")` |
| Any market's fee rate or order delay differs from the frozen backtest | No new risk until the cost stress is re-run at the new values | policy only |
| Drawdown from equity peak > 5% of capital (about 2.4 × the worst measured drawdown, −2.06% on the burned OOS) | Stop; review before restarting | policy only; never fires on IS (worst −2.01%, `pm_compute` P25) |
| Trailing 30-day net edge < 0.3¢/share; ≤ 0 | Half size; stop | policy only (NOTE §5). IS replay (`pm_compute` P25): the causal trailing edge never fell below +0.74¢ (median +1.47¢), so 206/206 days stay at full size and the rule changes nothing in sample. It is untested on a decline |
| Any UMA proposal on a market we hold is disputed | Add no risk to that market; earmark its capital for 4–6 days | policy only |
| Venue incident, matching-engine restart (2 min post-only mode), CLOB upgrade | No taker orders until resolved; makers: cancel and re-check | policy only (`VENUE_RULES.md`) |
| Tier-0: a false call is confirmed in the live audit | Halt tier-0 for the day; re-audit | policy only |

What is not automated yet: the trailing-edge rule, the drawdown stop, the fee/delay change stop and the dispute
freeze are written policy, not code.

**Per-book calibration (`pm_compute` P25).** The $1,000 daily stop never fires in the v2 backtest (worst IS day
−$551). It is 3.86 σ of v2's IS daily P&L (σ $259) and 3.5% of v2's capital. Applied unchanged to the other books it
means very different things:

| book | capital | IS daily σ | worst IS day | $1,000 stop in σ / % of capital | stop at v2's 3.86 σ | that stop, % of capital | IS days it would fire |
|---|---|---|---|---|---|---|---|
| v2 | $28,302 | $259 | −$551 | 3.86 σ / 3.5% | $1,000 | 3.5% | 0 |
| v2-safe | $17,681 | $141 | −$284 | 7.09 σ / 5.7% | $545 | 3.1% | 0 |
| maker v1 | $2,779 | $155 | −$669 | 6.45 σ / 36.0% | $599 | 21.5% | 1 |

Proposed `RiskConfig` per book (for the engine owner; `engine/` is not edited here): `daily_stop_usd` = 1,000 (v2),
545 (v2-safe), 599 (maker). The maker's capital convention (3 × peak locked = $2,779) is itself too small for its
variance (IS max drawdown −59% of capital), so a maker book should be funded well above it before any stop in % of
capital means anything. `engine/risk/limits.py` covers the per-order and per-match caps, the daily
stop and the feed, vision and latency kills. `scripts/live_paper.py` is being written in parallel by another
workstream; check at submission that it routes every order through `RiskManager.approve`.

---

## Register

Each item has four parts. **(a)** what the risk is for this strategy. **(b)** its measured size, or
"unmeasured". **(c)** the limit or mitigation and where it lives. **(d)** the trigger or kill rule.

### R1. Market risk and position limits
- **(a)** Every position is a binary held to resolution, so the loss on a position is its full cost if the
  player loses. Exposure is per match, per outcome. Polymarket cannot short; to short A you buy B.
- **(b)** Worst match: −$206 IS, −$154 burned OOS (v2); −$122 / −$77 (v2-safe). Worst day: −$551 IS (−1.95% of
  capital), −$469 OOS (−2.06%). Max drawdown: −2.01% IS, −2.06% OOS (`results/v2/causal.json`). Largest order in the
  book: $190 and 200 shares. Max |net| shares in any match: exactly 100. Gross per match: median $133, p99 $867,
  max $2,096 (`risk_stats` `liquidity_capital`).
- **(c)** Per order ≤ $1,000 / price. |Net outcome-0 shares| ≤ 100 per match, with in-flight orders counted.
  Price zone 0.05–0.95 for risk-increasing orders. No naked sells. Minimum 5 shares. All in
  `engine/risk/limits.py`; the same limits were applied in the backtest (`research/v2/sizing/engine.py`
  `apply_caps`). The backtest also has a $3k gross-per-match cap. It never binds (max $2,096), and `limits.py`
  does not implement it.
- **(d)** Net cap and order cap reject or clip the order (`Approval.reason`). Daily stop at −$1,000.

### R2. Concentration (wallets, matches, days, tournaments)
- **(a)** v2 copies a small set of walk-forward-qualified fast-tier wallets. If a few of them stop trading, or
  were lucky, the P&L goes with them.
- **(b)** Share of net P&L carried by the top 5 units (`risk_stats` `concentration`):

  | | top-5 wallets | top-5 matches | top-5 days | top-5 tournaments |
  |---|---|---|---|---|
  | IS ($40,426; 80 wallets, 7,639 matches, 199 days, 232 tournaments) | **81.4%** (top 1: 41.7%; top 10: 98.8%) | 2.2% | 11.7% | 16.3% |
  | Burned OOS ($3,688; 86 wallets, 2,003 matches, 40 days, 58 tournaments) | **142.1%** (top 1: 48.4%) | 19.6% | 74.0% | 51.0% |
  | U2-OOS blind ($2,117; 68 wallets) | **98.4%** (top 1: 63.4%) | | | |

  Without its top-5 wallets, v2 earns +0.61¢ [0.00, 1.27] IS and **−0.34¢ [−1.24, 0.55] on the burned OOS
  (−$1,552)**. Clustered by copied wallet instead of by match (`pm_compute` P07; 2,000 draws, seed 0), the 95% CI
  is [+0.57, +2.30] IS (80 wallets) and **[−0.45, +2.38] on the burned OOS** (86 wallets), against [1.17, 1.59] and
  [0.09, 1.13] by match. The effective sample is the wallets, not the matches. Out of sample the whole profit sits on the five most profitable copied wallets (ranked by P&L, not by speed). The U2 row confirms the NOTE's
  "98%". Match concentration is low in sample: without the top-5 matches, IS is still +1.35¢ [1.15, 1.57].
- **(c)** Per-match net cap (R1). No per-wallet cap exists, in the backtest or in `limits.py`. For a live tier-0
  trader the "wallet" is ourselves, so this risk becomes "are we one of the top-5 fastest" (R6).
- **(d)** Policy only: if one copied wallet carries > 50% of trailing-30-day P&L, or the book without its top-5
  wallets is negative over 30 days, treat the edge as unproven and halve size.

### R3. Liquidity and capacity
- **(a)** The edge is the stale quote left at each point. Its size is set by the depth resting at that moment
  and is shared with the existing fast tier.
- **(b)**
  - Stale depth per point: median $222–565 (mean $1.3–3.1k), from 2 s to 0.25 s before the reprice; about $0
    at 0.5 s after it (`research/v2/latency/RESULTS.md` §5).
  - Fast-tier 0–3 s volume: $0.45–2.7M a month IS (`results/fasttier_walkforward_is.csv`). v2's dollar volume
    was 8.8–18.1% of it by month (`risk_stats`).
  - v2's size equals the copied print in 84% of trades (median participation 100% of the print), and the net cap
    cut 31–35% of trades. So **the book assumes we take the fast tier's whole fill**, which live we would be
    competing for.
  - Moneyline depth: 1¢ median spread, $8.1k at the touch, $61k within 2¢ (NOTE §6).
  - Side markets (maker): in play at tour level, two-sided 29% of minutes, median spread 13¢, top of book about
    234/200 shares (`research/v2/maker/VENUE_RULES.md` §5b). Maker capacity is $1.3–2.1k P&L per 30 days in the
    lens's own fill model (crossmarket RESULTS §7), but $130 per 30 days in the realism verifier's step-ahead model
    and $48 in its combined conservative model (`research/financials/FINANCIALS.md` §5d). Use the verifier's.
  - v2 capacity out of sample: on the burned OOS, $/day peaks at 1x ($92.2/day, capital $22,754); 2x makes
    $82.5/day (Sharpe 3.2, capital $33,875) and 5x loses (−$24.5/day). So OOS capacity is about $23–34k of capital,
    not the ~$100k of the sizing lens, which used onset labels, was IS only, and whose $102k row is the Baseline,
    not v2 (`FINANCIALS.md` §2d).
  - Table tennis: not tradable (89¢ spread, $23 at the touch).
- **(c)** Never take more than the copied print (backtest). The engine caps size at the visible stale depth
  inside the limit (`engine/strategy.py` `cap_at_visible`) and does not re-take liquidity its own paper fills
  consumed in the last 10 s (`engine/execution/paper.py`).
- **(d)** Policy only: if live fills come in below 50% of the requested size over a day, halve size the next day.

### R4. Execution: order delay, queue position, partial fills, adverse selection
- **(a)** Every marketable order waits 1 s (3 s before 2026-05-15) and cannot be cancelled during the
  wait. Resting orders and cancels are not delayed. Makers wait in a queue. The fills a maker gets are the ones
  that hurt.
- **(b)**
  - Passive exit after a jump, 1 tick inside the ask: filled 27% within 30 s, 35% within 60 s, 56% within 300 s.
    Joining the queue (median 238 shares ahead): 14% / 21% / 37%. After a fill the price kept running +5.6¢;
    unfilled, it fell −5.7¢ (`research/v2/livefill/RESULTS.md`). That is adverse selection.
  - Chasing after the move (`results/engine/demo_run.json` `sensitivity`; an illustrative pairing of table-tennis
    calls with a recorded WTA book, not a tennis camera and not a backtest): with vision that keeps up and a 2.0 s
    stamp lag, 72 calls on 8 points sent 11 orders and filled 8. With a 1.0 s stamp lag, 7 orders went out; 4 calls
    were skipped because the book had already repriced and 2 because it moved against the call. With vision as it
    actually ran on the shared laptop, all 72 calls were stale and 0 orders went out.
  - Tier-0 fill rate: 31.9% IS / 31.8% OOS under the pre-registered model, whose pricing was refuted
    (`results/tier0/results.json` `prereg_record.primary`, 20-seed means). Corrected headline (20-seed means,
    `headline`): 25.1% IS / 20.3% OOS.
  - v2 worst-quartile fills (every fill at the 75th-percentile price within its 3 s burst; a +1.0¢ add-on for
    singletons): +0.49¢ [0.28, 0.71] IS, **−0.31¢ [−0.83, 0.21] OOS** (`risk_stats` `stress`).
- **(c)** Hold to resolution, so no exit fills are needed (HYPOTHESIS_V2 rule 6). Taker orders are FAK limits at
  the stale price + 1 tick and never chase (`engine/strategy.py`). Paper fills walk the real book after one-way
  latency + 1 s (`engine/execution/paper.py`). Makers quote post-only and send heartbeats; the venue cancels all
  orders after 10 s without a heartbeat (`VENUE_RULES.md`).
- **(d)** Kill on feed staleness or latency (R6). Policy only: if the live fill rate on correct calls is below
  half the modelled rate over 50 calls, stop.

### R5. Latency and signal decay
- **(a)** The fast tier's edge exists only for the first seconds after a point. Anyone later pays the spread to
  the fast tier.
- **(b)**
  - The book reprices a median 1.16 s **before** the official point stamp (n = 482 points, 9 WTA matches; the
    stamps are the WTA's public point-by-point log, read after the fact, not a licensed feed). Stale depth is gone 0.5 s
    after the reprice. With the 1 s delay, an order must leave ≥ 1.3 s before the reprice, about 2.5 s before the
    official stamp (latency RESULTS §3, §5).
  - Every public score feed is 18–63 s behind the book (p10–p90 across ESPN, Polymarket sports and the WTA API; latency
    RESULTS §3a); 0 of 295 observations led by more than 1.3 s.
  - Decay inside v2's own 0–3 s window, by seconds since detection (`risk_stats` `signal_decay_within_window`):

    | | 0 s | 1 s | 2 s |
    |---|---|---|---|
    | IS ¢/share [CI] (trades) | +1.59 [1.27, 1.91] (47,302) | +1.43 [−1.09, 3.84] (2,933) | −0.44 [−2.07, 1.16] (5,427) |
    | Burned OOS | +0.66 [0.03, 1.33] (9,314) | +2.66 [−1.91, 7.43] (619) | −3.13 [−8.27, 2.26] (479) |

  - Late entry (copy at +delay+3 s, `src/fasttier.py` follower): −0.89¢ [−1.10, −0.68] IS, −1.89¢ OOS.
  - Infrastructure: 67 ms one-way from Gainesville; London co-location assumed 2 ms (inferred, not measured).
    Vision processing takes 100 ms p50 (p90 153 ms) from frame to call on the loaded laptop when frames do not
    queue (`results/engine/demo_run.json` `latency_budget`). The laptop sustains only 54 fps unloaded
    (`results/engine/vision_bench.json`), so a 120 fps feed queues for seconds.
  - **Latency ×2 for v2: not computable.** v2 has no own-latency parameter (it fills at the fast tier's
    prices). The decay table and the late-entry row are the measured substitutes.
- **(c)** The decision path takes 0.06 ms p50 (p90 0.13 ms; `demo_run.json` `latency_budget`). Size the vision host for 120 fps with headroom (not done). Co-locate
  near London for a real deployment (not done).
- **(d)** Latency kill in `limits.py`. Policy only: drop any call whose frame-to-decision time exceeds 1 s
  (`engine/strategy.py` `max_call_latency_ms` = 1,000).

### R6. Crowding and competition for the same stale quote
- **(a)** The strategy pays whoever is first. New fast entrants shrink everyone's share.
- **(b)** Qualifying fast-tier wallets grew from 4 (Jan) to 101 (Aug) IS, and to 122 (Sep) and 131 (Oct)
  (`results/fasttier_walkforward_is.csv`; `results/summary.json` oos `h6_walkforward`). v2's per-share edge fell
  from +1.96¢ (3 s/0% regime) to +1.02¢ (1 s/5%) IS, then +0.60¢ OOS (R11). Today the margin for second place is
  under half a tick: +0.10¢ at +0.5¢ slippage on the burned OOS.
- **(c)** Fee-aware wallet filter at the current fee (`src/v2.py`). Being faster than the existing fast tier
  needs in-venue tracking plus co-location (not built).
- **(d)** Same trailing-edge rule as R2 (policy only).

### R7. Model risk: CV false calls, Markov fair value, wallet qualification
- **(a)** Tier-0 trades on a call that the ball is out before the umpire's stamp. A false call buys the wrong
  side, and wrong calls always fill (the market has not moved against them). The engine prices each call with a
  point-level Markov model calibrated to the book.
- **(b)** Early "miss" calls on real 120 fps table-tennis video (`results/tracking/summary.json`, test split,
  snapshot rule, 41 misses / 130 bounces; Wilson 95% CIs from `risk_stats` `cv_calls`):

  | lead before contact | precision [95% CI] | recall [95% CI] |
  |---|---|---|
  | 0 ms | 24/24 = 1.00 [0.86, 1.00] | 0.59 [0.43, 0.72] |
  | 50 ms (pre-registered test) | 11/11 = 1.00 [0.74, 1.00] | 0.27 [0.16, 0.42] |
  | 100 ms | 6/6 = 1.00 [0.61, 1.00] | 0.15 [0.07, 0.28] |
  | 50 ms, online rule | 3/3 = 1.00 [0.44, 1.00] | 0.07 [0.03, 0.19] |
  | 50 ms, train out-of-fold | 60/63 = 0.95 [0.87, 0.98] | 0.55 [0.45, 0.64] |
  | 50 ms, audited labels (20 relabelled) | 8/8 = 1.00 [0.68, 1.00] | 0.38 [0.21, 0.59] |

  Simulated tennis (Hawk-Eye-class physics world, not real footage; P(out) ≥ 0.95, 159 out of 300 shots,
  `results/spin/tennis/raw/nominal_s7_m300.parquet`; counts kept in `results/risk/spin_tennis_calls.json`): every method has 0 false calls and precision CI
  [0.97, 1.00]; recall is 0.96 [0.92, 0.98] at 0 ms falling to 0.87–0.92 at 300 ms. On the real video no
  false call has been seen, but the CI is wide: a Wilson lower bound of 0.95 needs **73 correct calls in a row**.
  Under the pre-registered tier-0 model, wrong calls were 8.9% IS / 8.8% OOS of trades and cost −$4,394 IS (that
  model's pricing was refuted; `prereg_record.primary`). In the corrected headline they are 12.6% IS / 19.1% OOS of
  trades and cost −$3,942 IS (`results/tier0/results.json` `headline`; both 20-seed means).

  Markov fair value: live prices are calibrated within about 1¢. 3 of 11 price bands have CIs excluding the
  price, with the largest gap 1.01¢ (DEVIATIONS D10; `results/calibration_is.csv`). The engine's limits:
  no format for a match tiebreak in place of a third set (ITF, doubles); calibration varies only the serve split;
  the sports feed has no point score, so the state is advanced by `apply_point` and re-synced at games
  (`engine/README.md`). v2 itself does not use the Markov model.
- **(c)** Trade only calls with confidence ≥ 0.95 (`engine/fair/value.py` default for MISS calls). The edge after
  fee must be > 0 using (c − p_w) × leverage (`engine/strategy.py`). The net cap bounds a wrong call to ≤ 100
  shares per match.
- **(d)** Policy only: halt tier-0 for the day on any confirmed false call; go live only after 73 consecutive
  audited correct calls.

### R8. Data risk
- **(a)** Wrong timestamps, missing prints or feed gaps make the backtest see things in the wrong order, or not
  at all.
- **(b)**
  - Tape timestamps are on-chain block times, a median **1.98 s** after the true match time (p10 1.95 s, p90
    2.97 s; n = 5,472 trades matched to the websocket by tx hash; `research/v2/blocklag/results.json`).
    Resolution is 1 s, and same-second order is unknown.
  - All 994 official WTA stamps end in 000 ms; if they are truncated, R is off by about 0.5 s (tier0 DEVIATIONS V9).
  - Book rebuilt from deltas vs the venue's snapshots: 6 of 25,753 mismatched (0.02%) (`engine/README.md`).
  - Feed outages seen on Oct 3: the `src/live_recorder.py` sports socket stayed alive but silent from 11:13 UTC.
    ESPN stalled 2–30 min on 15.6% of games (latency RESULTS §3c, §8).
  - Missing metadata: `finished` is missing for 4,260 of 13,084 markets (end falls back to `closed_time`);
    3,714 have no score string (`risk_stats` `settlement`).
  - Side markets with lifetime volume < $250 were not fetched (4.7% of side volume).
- **(c)** The causal window is measured from detection (D9), and the tier-0 limit order needs no exact clock.
  The replay feed emits `gap` events, and orders due inside a gap miss (`engine/market/clob.py`,
  `engine/execution/paper.py`). The latency recorder got an idle-reconnect watchdog.
- **(d)** Feed-stale kill > 2 s (`limits.py`). Policy only: any day with a book-snapshot mismatch rate > 0.1% is
  excluded from paper P&L and investigated.

### R9. Survivorship and point-in-time universe
- **(a)** The universe must be the markets a trader could have chosen at the time.
- **(b)** Winners and losers both come from the venue's own event list, and the OOS split is by match start
  (`src/tape.py`). But **the ≥ $5k volume filter uses each market's final lifetime volume, which is not known at
  match start.** Measured effect: IS P&L by final-volume band is $5–20k +2.55¢ ($1,196), $20–100k +2.15¢,
  $0.1–1M +1.11¢, > $1M +0.95¢. On the burned OOS the $5–20k band is −1.96¢ (−$187) (`risk_stats`
  `universe_volume_filter`). The blind U2 test covered markets below the filter (`research/v2/expand/RESULTS.md`, $1–2k and $2–5k bands: IS +4.15¢ and
  +3.95¢), so the filter does not flatter the result. Markets never marked closed by Oct 3 are not in the
  sample (unmeasured).
  - **Pre-start volume instead** (`pm_compute` P14; $ traded before the scheduled start, the ex-ante measure
    tier-0 uses). IS ¢/share by pre-start band: < $1k +1.88 [1.14, 2.63]; $1–5k +1.41 [1.03, 1.80]; $5–20k +1.18
    [0.79, 1.57]; $20–100k +1.39 [0.92, 1.84]; ≥ $100k +1.43 [0.34, 2.50]. Matches under $5k pre-start carry 43%
    of IS shares and 47% of IS P&L.
  - **Point-in-time universe** (pre-start ≥ $5k; every such market is inside the lifetime ≥ $5k universe, so
    nothing is missing). Rebuilt walk-forward from scratch on IS prints (wallets re-qualified on the smaller
    universe): 4,731 of 9,581 IS matches, +1.29¢ [0.98, 1.59], $18,988, Sharpe 10.0. **In today's 1 s/5% regime
    it is +0.44¢ [−0.14, 1.01]: the CI includes 0.** The frozen book's own trades in the same matches, without
    re-fitting: +1.28¢ [0.99, 1.56], $21,321.
- **(c)** A live filter should use pre-start volume; tier-0 already ranks coverage by pre-start volume (tier0
  DEVIATIONS T1).
- **(d)** Policy only: the live universe rule is written down before trading and never uses end-of-match fields.

### R10. Overfitting
- **(a)** Thousands of variants were tried. The best one can look good by luck.
- **(b)** (`research/rigor/RESULTS.md`, incl. "Verifier corrections"; `results/rigor/rigor.json`)
  - Trials: 3,386 = 44 (H1–H6) + 3,342 (the six v2 lenses); 3,410 adds the 24-variant v2-safe grid. The tier-0
    grid (432 × 2) comes on top of that.
  - IS: DSR 0.997 at N = 3,386 under the most conservative variance.
  - OOS headline: PSR vs 0 = 0.987 (0.995 with an AR(1) adjustment). DSR 0.951 / 0.880 / 0.825 at N = 2 / 4 / 6
    strategies looked at on the OOS. The stress case, N = 3,386 at T = 40, gives 0.075.
  - PBO: about 9–24% on the v2-safe grid; 39–42% for its selection rule; 0% for the sizing grid.
  - MinTRL: 6 days at the IS Sharpe, 22 days at the OOS Sharpe.
  - Threshold sensitivity (`pm_compute` P15; IS prints only; each threshold of the frozen rule moved one step and
    the whole walk-forward re-run; 19 runs; nothing selected): detector 3¢/6¢, 5 s/20 s short window, 30 s/120 s
    long window, 2/4/6 s entry window, ≥ 20/40 prints, ≥ 5/15 matches, t > 2/4, n₀ 100/400, zone 0–1/0.1–0.9.
    Every run stays at +1.21 to +1.46¢/share with the CI above 0 (base +1.38¢), Sharpe 9.0–17.6, P&L
    $21.8k–48.0k (base $40.4k). In the 1 s/5% regime the range is +0.66 to +1.39¢, every CI above 0. The
    print and match counts barely matter (at most 3 trades change); the detector threshold moves dollars most (6¢: $21.8k, Sharpe 9.0).
  - Peeks: `results/oos_peeks.log` had 28 lines at 19:41 UTC Oct 3 and 32 at 20:04 UTC (first 10:42 UTC). It grows
    while the other workstreams run (maker live session, table-tennis audits, this review's P07 and P17 lines, the
    financials audit's reproduction line); recount at submission and use one number everywhere (NOTE §4 says 19).
- **(c)** Pre-registration (`HYPOTHESIS*.md`), deviations logged, adversarial verifiers for every lens, a blind
  U2 test and a blind forward window.
- **(d)** If the forward primary (`results/v2/forward.json`) fails, v2 is not traded. Its CI-excludes-0 rule is
  fixed in HYPOTHESIS_V2 A1.

### R11. Regime risk (fees, delays, venue upgrades)
- **(a)** The venue changes the rules the edge depends on. In our universe (per-market `feeSchedule` and
  `secondsDelay`, `src/tape.py`), the tennis fee went from 0 to 0.03 in late March 2026 (first 0.03 match
  2026-01-18; all matches from April) and to 0.05 from 2026-07-11 (changelog: 2026-07-10). The order delay went
  from 3 s to 1 s on 2026-05-15. On 2026-04-28 the exchange moved to new contracts (CTF Exchange V2) and pUSD
  collateral; trading paused for about 1 h, order books were cleared, and v1 client libraries stopped working
  ([help center](https://help.polymarket.com/en/articles/14762452-polymarket-exchange-upgrade-april-28-2026)).
  Each change moves the edge or breaks the bot.
- **(b)** v2 by regime IS (`risk_stats` `regime`): 3 s/0% +1.96¢ [1.37, 2.54]; 3 s/3% +1.36¢ [0.86, 1.87];
  1 s/3% +1.45¢ [1.12, 1.78]; **1 s/5% +1.02¢ [0.59, 1.45]**. Burned OOS, all 1 s/5%: +0.60¢ [0.09, 1.13]. With
  fees doubled the OOS is −0.34¢ [−0.86, 0.19]; with fees doubled + 0.5¢ it is −0.84¢ [−1.36, −0.31]
  (`results/v2/cost_stress.json`). **A further fee rise or a longer delay would remove the OOS edge.**
- **(c)** The wallet filter re-prices at each market's published fee (`src/v2.py`). Fees are charged per match
  (`rate·q(1−q)`).
- **(d)** Fee/delay change stop (kill table, policy only).

### R12. Settlement and resolution
- **(a)** P&L is realised only when UMA settles the market. Disputes delay that. A retirement pays the advancing
  player, even one who was losing. Walkovers and cancellations pay 50-50.
- **(b)** Counted in the 13,084-match universe (`risk_stats` `settlement`):
  - 50-50 resolutions: 378 (2.89%). **302 of them had a "0-0" score (never started: walkover or cancellation)**,
    73 had no score, 2 a complete score, 1 a partial score. They are mostly walkovers, which is what NOTE §5 now
    says.
  - Retirements (score shows play started but no winner of the match): 283, of which 282 resolved to a player and
    1 to 50-50, which agrees with the current rule text.
  - v2 exposure: retirement matches 148 IS (760 trades, +$1,614, 4.0% of P&L) and 44 OOS (−$81); 50-50
    matches 3 trades IS (−$28) and 1 OOS (−$7).
  - Market close minus finish time: median 0.58 h, p99 19.1 h; 68 markets > 24 h, 31 > 72 h, 11 > 7 days.
    UMA dispute status is not in our cached data, so these long gaps are a **proxy**, not a dispute count. v2
    P&L in > 72 h markets: +$34 IS, −$126 OOS.
  - UMA: a 2 h challenge window and a $750 bond; a disputed market takes about 4–6 days in total
    ([Polymarket resolution docs](https://docs.polymarket.com/developers/resolution/UMA)).
- **(c)** Held to resolution with the real outcome, so 50-50 and retirement outcomes are already in every P&L
  number. `RiskManager.settle()` releases a match's exposure only when the market resolves.
- **(d)** Dispute freeze (kill table, policy only).

### R13. Capital lock-up and funding
- **(a)** Cash is locked from fill until resolution. The 4 h ex-ante lock is an assumption.
- **(b)** Realised lock (fill to market close): median 2.85 h, p90 5.16 h, p99 13.8 h IS; 24.9% of IS trades
  were locked > 4 h (5.9% OOS). Peak locked with realised times: $11,606 IS vs $9,434 under the 4 h rule, so
  capital at 3 × realised peak is **$34,818 vs $28,302**. OOS realised peak is lower ($5,462). Up to 4–6 more
  days if disputed; 14 days before a no-winner 50-50 (`risk_stats` `liquidity_capital`).
- **(c)** Fund 3 × the realised peak, not 3 × the 4 h peak. Collateral is pUSD, an ERC-20 on Polygon backed by
  USDC ([docs](https://docs.polymarket.com/concepts/pusd)); keep only working capital on the venue.
- **(d)** Policy only: if locked capital exceeds 50% of equity, accept only risk-reducing orders.

### R14. Correlation across matches and strategies
- **(a)** If outcomes in the book move together, the many-small-bets argument behind the high Sharpe fails.
- **(b)**
  - Same-day cross-match variance ratio: 1.07 IS (implied mean pairwise correlation 0.0013 across about 39
    matches a day); 0.92 OOS (`risk_stats` `correlation`).
  - Lag-1 autocorrelation of daily P&L: +0.15 IS, −0.15 OOS.
  - Factors (Fama–French market, size, value, momentum), IS only, every calendar day (factors 0 on weekends),
    returns net of the risk-free rate, alpha ×365 (`pm_compute` P24): R² 2.3%, no beta significant (largest
    t = 1.54, market beta 0.18), alpha t = 9.5. The committed `results/v2/factor_regression.json` (R² 3.3%, largest
    t = 1.33) also used burned-OOS days to Aug 31, dropped weekends and annualised ×252; the conclusion is the same.
  - v2 vs v2-safe daily correlation 0.955 IS (0.956 burned OOS): they trade the same opportunities, so running both does not
    diversify. U1 vs U2 OOS: 0.21.
  - v2 vs maker: daily correlation −0.04 IS (206 days, `pm_compute`); OOS not computed (the maker failed its
    blind OOS, so the pair is not a portfolio candidate).
  - Up to 61 matches were open at once (IS, 4 h lock).
- **(c)** Per-match net cap. Treat v2 and v2-safe as one book.
- **(d)** Policy only: if the trailing 30-day variance ratio exceeds 2, halve size.

### R15. Counterparty and platform
- **(a)** Polymarket's contracts, the UMA oracle, Polygon, and the USDC issuer behind pUSD can each fail, freeze
  or be exploited. Polymarket can change rules, fees or access at its own discretion.
- **(b)** Unmeasured (no incident in our data). Venue facts: 1 s delay, fee 0.05, rebate 15% at Polymarket's
  discretion; post-only mode for 2 minutes after a matching-engine restart (`VENUE_RULES.md`).
- **(c)** Keep only working capital on the venue (R13). No leverage. Positions are fully collateralised
  binaries, so there is no margin call.
- **(d)** Venue-incident rule (kill table). Policy only: a stablecoin depeg alert stops new risk.

### R16. Legal, regulatory and compliance
- **(a)** Jurisdiction, venue terms, data rights, and how courtside data may be collected.
- **(b)** What the sources say:
  - **Venue access.** polymarket.com puts the US, UK, France, Canada (BC, ON, AB, QC), Australia, Germany, Italy and others in
    close-only mode, on the API as well as the frontend ([geoblock](https://docs.polymarket.com/api-reference/geoblock)).
    The ToS page (https://polymarket.com/tos) shows US users a notice pointing to polymarket.us. Its full text
    could not be extracted from this environment, so read it before any deployment. Polymarket US runs under
    CFTC oversight through a registered intermediary ([Dec 2025 report](https://www.regulatoryoversight.com/2025/12/cftc-approval-allows-polymarket-to-reenter-the-u-s-market/)).
    It is a different venue; nothing here was tested on it.
  - **Venue conduct rules.** The [market integrity policy](https://integrity.polymarket.com/) bans trading on
    stolen confidential information in breach of a duty, on illegal tips, and with influence over the outcome,
    plus spoofing, wash trading and front-running. It does not mention courtsiding or latency.
  - **Courtsiding.** The Tennis Anti-Corruption Program 2026 defines "Courtsiding" (D.1.p) as transmitting
    contemporaneous results from on site for tennis betting without the consent of the governing body or event.
    It binds Covered Persons: players, related persons and tournament support personnel (B.9)
    ([TACP 2026](https://www.itia.tennis/media/3tihxdff/tennis-anti-corruption-program-2026.pdf)).
    Spectators are bound by ticket terms. Australian Open 2026, clause 24 "No Court-siding": no continual
    collection or transmission of scores or data for betting. Clause 19(d) bans devices that transmit scoring
    data for betting; breaches mean refused entry, removal or exclusion
    ([AO 2026 conditions](https://www.tennis.com.au/content/dam/tennisaustralia/events/australian-open/documents/pdf/ticket-conditions-of-sale-and-entry-ao-jan2026.pdf)).
    Ticket terms for other ATP/WTA/ITF events were **not checked** one by one.
  - **Data rights.** ATP Tour and Challenger betting data rights belong to Sportradar via Tennis Data
    Innovations ([iGB, Dec 2023](https://igamingbusiness.com/sports-betting/sportradar-tennis-data-streaming-deal-atp/)).
    On 2026-08-03 Polymarket announced an ATP deal with TDI that includes Sportradar's real-time data and
    integrity services ([PR Newswire](https://www.prnewswire.com/news-releases/polymarket-secures-exclusive-atp-tour-streaming-rights-for-prediction-markets-302841534.html)).
    So the venue's own integrity partner watches the matches tier-0 would trade. WTA and ITF data-rights holders
    were not checked.
  - **Plain statement.** Tier-0 as modelled (own courtside camera, no licence) is **prohibited** at any event
    whose ticket terms match the AO's. A licensed version needs a data licence and organiser consent. A US
    person cannot open positions on polymarket.com at all.
- **(c)** The repo reads only public, keyless data and places no orders (compliance AUDIT). Tier-0 stays a
  counterfactual.
- **(d)** Checklist items 1–3 are hard gates.

### R17. Tax
- **(a)** US tax treatment of prediction-market gains is unsettled. It could be capital gains, gambling income,
  or (arguably, for regulated venues) Section 1256. The international venue issues no 1099s.
- **(b)** As of June 2026 the IRS had published no formal guidance
  ([Pease Bell, Apr 2026, updated](https://www.peasebell.com/insights/will-the-irs-issue-prediction-market-guidance-before-april-15th/)).
  After-tax return: unmeasured.
- **(c)** Keep a per-fill ledger (`engine/execution/paper.py` `Ledger`; on-chain records). Get a tax adviser
  before any live trading.
- **(d)** n/a.

### R18. Operational
- **(a)** Key leaks, crashed processes, silent sockets, a vision host that falls behind, unattended runs.
- **(b)**
  - The silent sports socket on Oct 3 (R8).
  - Vision on the shared laptop queued for seconds: 17 fps sustained against 30 fps arrivals (`results/engine/demo_run.json`
    `vision.timing`).
  - Book-snapshot mismatch 0.02%.
  - Uptime and reconnect counts over a full session: unmeasured.
- **(c)**
  - Keys never on disk. `PaperExecutor` raises `LiveTradingForbidden` on `live=True`, on any credential-like
    argument, when a live or key variable is set, or when a signing library is loaded. A test asserts that the
    execution module has no HTTP/websocket client and no order endpoint (`engine/README.md`). `.env` and `data/` are git-ignored.
  - `LiveClobFeed` reconnects with backoff from 0.5 s to 30 s, re-subscribes, and marks books invalid until
    fresh snapshots arrive.
  - Mission Control (`scripts/status_daemon.py` → `docs/live/control.html`) refreshes every 5 s.
  - Makers rely on the venue heartbeat, which cancels everything after 10 s of silence.
- **(d)** Kill switches in `limits.py`; manual kill.

---

## Stress table (v2, frozen book; `risk_stats` `stress`; CIs match-clustered)

Max DD is in % of each period's own base capital ($28,302 IS / $22,754 OOS). On the IS capital fixed ex ante,
the OOS percentages are 0.80 × those shown (22,754 / 28,302).

| Scenario | IS ¢/share [CI] | IS $ | IS Sharpe | IS max DD | OOS ¢/share [CI] | OOS $ | OOS Sharpe | OOS max DD |
|---|---|---|---|---|---|---|---|---|
| Base | +1.38 [1.17, 1.59] | 40,426 | 14.5 | −2.0% | +0.60 [0.09, 1.13] | 3,688 | 6.7 | −2.1% |
| **Fees ×2** | +0.77 [0.57, 0.98] | 22,677 | 8.4 | −5.6% | **−0.34 [−0.86, 0.19]** | −2,086 | −3.8 | −8.7% |
| Costs ×2 (fee ×2 + 0.5¢) | +0.27 [0.07, 0.48] | 8,046 | 3.0 | −16.1% | −0.84 [−1.36, −0.31] | −5,165 | −9.0 | −21.3% |
| Slippage +½ tick | +0.88 [0.67, 1.09] | 25,794 | 9.8 | −3.7% | +0.10 [−0.41, 0.63] | 608 | 1.1 | −5.1% |
| Slippage +1 tick | +0.38 [0.17, 0.59] | 11,162 | 4.3 | −5.9% | −0.40 [−0.91, 0.13] | −2,471 | −4.4 | −10.3% |
| **Fills at worst quartile** | +0.49 [0.28, 0.71] | 14,473 | 5.6 | −5.6% | −0.31 [−0.83, 0.21] | −1,931 | −3.5 | −8.1% |
| **Latency: late entry (+delay+3 s)** | −0.89 [−1.10, −0.68] | −26,174 | −9.3 | −96.2% | −1.89 [−2.41, −1.36] | −11,637 | −18.7 | −48.3% |
| Fees ×2 + worst-quartile fills | −0.11 [−0.32, 0.10] | −3,276 | −1.2 | −32.5% | −1.25 [−1.77, −0.72] | −7,704 | −12.9 | −31.7% |

How the scenarios are built:
- **Worst-quartile fills.** A burst is all v2 trades in the same match and direction, at most 3 s apart. In a
  burst with 2+ trades, each fill is moved to the burst's 75th-percentile price. Singletons get the pooled p75
  gap, which is +1.0¢. The fee is re-charged at the worse price. Mean add-on: 0.85¢ IS, 0.90¢ OOS.
- **Late entry** is the repo's follower definition: the move to +5 s (1 s delay) or +15 s (3 s delay), plus half
  the spread. Mean cost 2.4¢ IS.

**A 5σ day.** Daily sd is $259 IS / $264 OOS, so a 5σ day loses $1,294 (4.6% of capital) / $1,321 (5.8%). The
worst day seen was −2.9σ IS and −2.1σ OOS; no day fell below mean − 3σ (`risk_stats` `tail_day`). The −$1,000
daily stop sits at 3.9σ. It blocks new risk but cannot cap losses on positions already open. The hard ceiling is
all open positions resolving against us at the same time: the peak locked amount, $9,434 IS. That is 33% of
capital by construction (capital = 3 × peak locked). Same-day correlation is about 0 (R14), so this is far in
the tail, but it is the true worst case.

**Tier-0 stresses (latency ×2, worst-quartile timing).** The pre-registered sensitivities ("all venues at
100 ms", "stamp lag 1.0 s") use the refuted fill pricing. The corrected stresses, one change at a time over 20
seeds, are in `research/v2/tier0/RESULTS.md` §3 (revised in commit `a5769c7`) and `results/tier0/results.json`
`stresses_corrected`. Every row stays far below the counterfactual's fixed costs ($1,153–7,215/day at 10 covered
matches a day): the headline is $89 ± 21/day IS and $46 ± 39/day burned OOS, and the best of the 27 stresses in either period is $203/day (IS, net cap 1,000 shares).

## Fixed costs a live tier-0 would carry (not in any backtest)

The full cost table, with every source URL and label, is `research/financials/FINANCIALS.md` §1 (generated by
`scripts/financials.py`, sources retrieved 2026-10-03). Summary:

| Item | Public price? | Value used (low / central / high) |
|---|---|---|
| Licensed live point feed (Sportradar/TDI for ATP, Stats Perform for WTA) | **None.** Negotiated contracts | **ASSUMPTION** $1,250 / $5,000 / $10,000 a month, anchored to reported figures (LSports: Sportradar API "from $1,250/month"; SharpAPI, a competitor's claim: starter contracts $5,000–10,000/month). At v2's caps the opportunity a licence unlocks is $33.6k/yr (burned-OOS rate) to $71.6k/yr (IS rate) (`risk_stats` `fixed_cost_breakeven`); the central $60k/yr sits inside that range, so v2 nets +$29/day IS and −$75/day burned OOS after central costs |
| London gateway VPS (co-location proxy) | Yes | **ESTIMATE** $34 / $77 / $98 a month, AWS EU (London) on-demand list prices (t3.medium / c7i.large / c6in.large) |
| Courtside camera operator | Yes | **ESTIMATE** $36.10/h, BLS 2025 median pay of film and video editors and camera operators; 3 / 4 / 5 h per covered match (ASSUMPTION) |
| Cloud GPU for CV inference | Yes | **ESTIMATE** $0.615 / $0.615 / $1.02 per hour, AWS EU (London) g4dn.xlarge / g6.xlarge |
| 120 fps camera kit, 24-month life | Components only | Low **ESTIMATE** $648 (GoPro HERO13 Black $399 + NVIDIA Jetson Orin Nano Super developer kit $249, launch list prices); central $1,000 and high $2,000 are an **ASSUMPTION** |
| Organiser consent / camera position | **None** | **ASSUMPTION** $0 / $250 / $500 per covered match; see R16 |
| **Total at 10 covered matches a day** | | **$1,153 / $4,149 / $7,215 per day**, against $89/day (IS, 1 s-delay matches) and $46/day (burned OOS) of tier-0 trading P&L |

## What is not measured (plain list)

- Our own live fill rate, queue position and slippage on real orders (we place none).
- t_stamp − t_bounce, the lag between a ball landing and the umpire's stamp. Tier-0 depends on it most.
- Live CV precision on real tennis footage. Our real-video numbers come from table tennis.
- UMA dispute counts (only a close-time proxy).
- v2 vs maker correlation out of sample; maker live results; the v2 forward test.
- Platform, stablecoin and smart-contract failure probabilities.
- After-tax returns.
- Session uptime and reconnect counts.
