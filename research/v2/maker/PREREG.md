# maker v1: frozen leaning maker, blind OOS test and live paper session (pre-registration)

Written 2026-10-03 ~18:30 UTC on top of 9cefefc. This file is committed before any of the tests below
exists as code or has been run. Everything here is paper: no order is signed or sent anywhere, and no
wallet key or API key is used. Market data comes only from public, keyless Polymarket endpoints
(gamma-api, data-api, clob REST and websocket).

## What has and has not been looked at
- **In-sample (matches starting before 2026-08-25 14:15 UTC).** Everything in
  `research/v2/crossmarket/RESULTS.md`. The leaning maker idea, its grid and its walk-forward picks all come
  from IS side-market tapes.
- **OOS side markets.** Nothing. No Gamma side-market catalogue for an OOS event, no side tape and no side
  print has been fetched or loaded. `data/v2_crossmarket/` holds IS markets only (asserted in `common.py`).
- **OOS moneyline.** The raw OOS moneyline tapes (`data/raw/trades/<cond>.parquet`, the source of
  `data/locked/oos_prints.parquet`) have already been used by other strategies (v2, v2-safe, tier0; see
  `results/oos_peeks.log`). The OOS is therefore *burned for the moneyline*. Test (A) uses those tapes
  **only as the signal input** (the moneyline mid proxy). Whatever is known about them, nothing is known
  about how OOS side-market takers traded against them.
- **OOS catalogue metadata.** Read for this file: the moneyline rows of `src.tape.universe()` with
  `oos == True`. That is 2,617 matches (1,776 ATP, 841 WTA), every one with a 5% fee rate and a 1 s order
  delay, starting from 2026-08-25 14:15 to 2026-10-03 07:10 UTC. No side-market field was read.
- **Live recordings.** The latency lens used the side-market books in `data/live_v2` from 11:08 to
  12:45 UTC on 2026-10-03 to measure reprice lags and spreads. Live median side spreads were 8–44c, against
  1c on the moneyline. No leaning-maker quote, queue position, fill or P&L has been computed on any live data.
  For this file, only the recorder's source code (`research/v2/latency/recorder.py`) was read, not its data.
- **Sibling job.** `research/v2/maker/venue_snapshot.py` is another job's read-only venue-parameter
  snapshot. It is not part of this pre-registration and is not committed with it.

## 1. The frozen rule: maker v1

**Provenance.**
- `research/v2/crossmarket/analyze.py: lean_maker`, cell `window="always", min_impl=0.04`.
- The walk-forward picked this cell for May, June, July and August 2026 (`analysis.json["lean_maker"]["choices"]`).
- Across the Feb–Aug cells it also has the largest dollar P&L: $5,326, against $5,110 for always/2c.
- Sensitivities are the walk-forward **2026-08 row** (fit on Nov 2025–Jul 2026 intervals), with the in-match
  shrinkage λ = 1.0 that the walk-forward model choice picked every month from March to August.
- Nothing is re-fit. In particular, the IS intervals of 2026-08 are not added to the fit.

**Code at freeze (sha256):**

| file | sha256 |
|---|---|
| `analyze.py` | 3138af84d0be171c54082956d15f0669754f018223cd04364d80bb6d08a11bb4 |
| `model.py` | e7b091a941fbb9daa3a6eac19057fdd5dc27808617e5fc0203a30e2bec872f59 |
| `common.py` | 20ca19acc8773cede70c8b63f2c68377de246476234c093e524d64fa2c8df115 |
| `build.py` | 151202928d84a1e3308f7c3f695eded3e37abfeff53e5610f557162e0cf2644d |
| `fetch_events.py` | 85881cfbb4fc83562b400ef6a68dd11a424864613dd14ed70ac05a687c366275 |
| `beta_walkforward.csv` | df9196cc3fe7c5cdf97e1078a2921fa79212f5e0e13c2be70dc85ce8dd8dd99d |
| `src/tiers.py` | 46a79d75409fd416fdfc2e026c25f02d9ebb3a188a9de1a6ac353561f656363e |
| `src/backtest.py` | dbf82b752942dcff7ba3e0d1fcde2603894d6066938ca1476e8b8f1467a98b46 |

All files are under `research/v2/crossmarket/` except the two `src/` files.

### 1.1 Markets
- **Events.** ATP, WTA and Challenger singles matches (Gamma `seriesSlug` in {atp, wta, challenger}).
- **Markets.** The two-outcome side markets of these six types. They are the only types with a frozen b.

  | type | how it is modelled |
  |---|---|
  | `tennis_first_set_winner`, `tennis_set_winner`, `tennis_set_handicap` | player market |
  | `tennis_match_totals`, `tennis_set_totals`, `tennis_first_set_totals` | totals market (outcome 0 = "Over") |

- **Never quoted.** `tennis_set_games_totals` and `tennis_game_handicap` (no b in the 2026-08 row), and
  `tennis_completed_match`.
- **Player markets.** `align0` is +1 if the side outcome 0 names moneyline player 0 and −1 if it names
  player 1. It is computed by `fetch_events.align` (name matching). As in the IS code, `implied_q0` treats
  a player market with `align0 = 0` as +1.
- **Totals markets.** A market whose outcome 0 is not labelled "Over…" is skipped and counted. In IS, all
  78,720 totals markets had "Over" as outcome 0.
- **In-play window.** From the event's scheduled start (Gamma `startTime`) to its end (finished or closed
  time). If the end is unknown, the window closes at start + 6 h. Only in-play prints enter any state below.

### 1.2 Inputs
- **Prints.** Public taker prints, put on the outcome-0 axis:
  - `q0` is outcome 0's price.
  - `at_ask` = True if the taker bought outcome 0 or sold outcome 1. That lifted outcome 0's ask.
  - The moneyline's p is defined the same way, for its outcome 0.
- **Moneyline mid proxy at a moneyline print** (`src.tiers._mid_series`, stale = 30 s): the mean of the
  latest ask-side and the latest bid-side in-play prints, each at most 30 s old, if ask ≥ bid. Otherwise it
  is the print's own price.
- **Side mid proxy at a side print:** the same, with stale = 120 s, over that side market's in-play prints.

### 1.3 Frozen sensitivities (b_T)

| type | b_T |
|---|---|
| tennis_first_set_winner | 1.527875991592811 |
| tennis_set_winner | 1.0781295500280448 |
| tennis_set_handicap | 0.8171462571666066 |
| tennis_match_totals | 1.8243248664803704 |
| tennis_set_totals | 2.721259317541827 |
| tennis_first_set_totals | 3.514143233195978 |

sha256 of `json.dumps({smt: repr(b)}, sort_keys=True, separators=(",", ":"))` over these six:
`f40c53f741d23fc911cfb42857af4b59d5c22cc54efa7fbfcc27d57fbd18466c`. Every script below asserts it.

### 1.4 Signal for side market m at venue time t
Notation: d is m's order delay (Gamma `secondsDelay`, falling back to the moneyline's). The information cut
is t* = t − d. Only prints with server timestamp **strictly before** t* are used. This is exactly the IS
information set, which was built as of t_send = print time − delay.

1. **Side reference.** r is m's last in-play print with ts < t*. There is no quote if no such print exists,
   or if t* − ts_r > 600 s.
2. **Reference prices.**
   - q_ref is the side mid proxy at r.
   - p_ref is the moneyline mid proxy at the last moneyline in-play print with ts ≤ ts_r.
   - p_now is the moneyline mid proxy at the last moneyline in-play print with ts < t*.
   - There is no quote if any of the three is missing.
3. **In-match sensitivity** (`model.shrunk_b`, λ = 1.0): b = (S_xy + 1.0·b_T) / (S_xx + 1.0).
   - The sums run over m's in-play intervals that end at or before ts_r. An interval is a pair of consecutive
     prints at most 300 s apart.
   - x and y are defined as in `model.xy`:
     - **Player markets:** x = logit p₂ − logit p₁ and y = logit m₂′ − logit m₁′. Here m′ is the side mid
       oriented to moneyline player 0 (1 − m if `align0` = −1).
     - **Totals markets:** x = c(p₂) − c(p₁), with c(p) = 4p(1−p), and y = logit m₂ − logit m₁.
   - logit is clipped to [0.005, 0.995].
   - An interval counts only if all four of m₁, m₂, p₁ and p₂ lie in (0.03, 0.97). Player markets with
     `align0` = 0 are left out of the sums.
4. **Implied move** (`model.implied_q0`):
   - **Player markets:** orient q_ref, set q′ = expit(logit q_ref′ + b·(logit p_now − logit p_ref)), then
     orient back.
   - **Totals markets:** q′ = expit(logit q_ref + b·(c(p_now) − c(p_ref))).
   - impl = q′ − q_ref.
5. **State.**
   - If impl ≥ +0.04, **bid outcome 0** (we would end up long outcome 0).
   - If impl ≤ −0.04, **bid outcome 1**, which is an offer on outcome 0.
   - Otherwise there is no quote.
   - The rule never quotes both sides, and never quotes the side the implied move goes against.

### 1.5 Fills, sizing and caps (the IS fill model, used in A and as B3)
- **Which prints fill us.** An in-play side print j fills us if its taker traded **against** the implied
  move: it sold outcome 0 while impl > 0, or bought outcome 0 while impl < 0. The state is evaluated at
  t = ts_j, so the information cut is ts_j − d.
- **Price.** We fill at the print's price on our token: px = q0_j if we are long 0, 1 − q0_j if long 1. The
  fill needs 0.02 < px < 0.98.
- **Size.** shares = min(**0.2** × print size, **$250** / px).
- **Per-match cap.** Candidate fills are taken in time order. Ties keep the stable order of the per-print
  table. A fill is kept while the match's cumulative gross (Σ shares × px over all side markets and both
  tokens, this fill included) is at most **$2,000**. The first fill that would cross the cap is dropped, and
  so is every later fill in that match.
- **No netting, no exit, no hedge, no stop.** Every fill is **held to resolution**. The jump detector is not
  used, because the window is always-on.

### 1.6 Fees, rebate and P&L
- **Makers pay no fee.** Gamma `feeSchedule.takerOnly` = true.
- **Rebate assumption: 15% of the taker fee paid by the print that filled us.** Per share:
  rebate = 0.15 × fee_rate × q0_j × (1 − q0_j).
  - fee_rate is the side market's `feeSchedule.rate`. If that is missing, the moneyline's rate is used,
    else 0.
  - The 0.15 is hard-coded as in IS. It matches Gamma `feeSchedule.rebateRate` = 0.15 on every IS 5%-fee
    market checked: all 27,179 side markets in the last 40 IS catalogue batches had
    {rate 0.05, rebateRate 0.15, takerOnly true}.
  - At a 5% fee the rebate is at most 0.19c/share. It averaged 0.16c on IS 1 s/5% fills.
  - Whether the venue pays it per fill or from a pool is not verified. Stress (iii) removes it.
- **P&L per share:** pnl_ps = payout − px + rebate.
  - payout is the resolved value of our token: 1, 0 or 0.5.
  - $ P&L = shares × pnl_ps, booked on the fill's UTC date, as in IS.

**IS reference for the OOS regime (1 s / 5%, Jul 11–Aug 25 2026, 46 days):**
- 4,159 fills in 1,017 matches.
- **+2.02c/share [0.53, 3.48]**, share-weighted +3.35c.
- $3,269 of P&L on $54k notional.
- Mean fill $13, median $2.94.

## 2. (A) Blind OOS test

### 2.1 Sample
- **Matches.** Every row of `src.tape.universe()` with `oos == True` and start in [2026-08-25 14:15 UTC,
  2026-10-03 14:00 UTC). From the cached catalogue that is the 2,617 matches above, starting 2026-08-25
  14:15 to 2026-10-03 07:10 UTC.
- **Matches not added.** Matches that start between 07:10 and 14:00 UTC on 2026-10-03 are not in the cached
  catalogue, and they are not added. Adding them would mean re-enumerating the catalogue that other
  workflows share.
- **Side markets.** Those of these events that meet three conditions, the same as IS:
  - their type is in §1.1;
  - their Gamma lifetime volume is at least $250 at fetch time;
  - their Gamma `outcomePrices` show a resolution, (1, 0), (0, 1) or (0.5, 0.5). Markets that are not
    resolved at fetch time are excluded and counted.

### 2.2 Data build (`research/v2/maker/oos_build.py`): computes no P&L
1. **Catalogue.** Gamma `/events` by id, 50 per request, sequential, with the same fields and parsing as
   `fetch_events.py`. Output: `data/v2_maker/oos/side_markets.parquet`.
   - Each row carries `align0`, `fee_rate`, `delay`, `res_s0`, plus `rebateRate` and `takerOnly`.
   - Asserts: every event is in the OOS window and none is in `universe_is`.
2. **Tapes.** data-api `/trades` per side market, as in `fetch_tapes.py`: at most 4 concurrent requests,
   exponential back-off on 429/5xx, the same 10,500-fill offset cap.
   - Cached to `data/v2_maker/oos/trades/`, a separate directory from the IS cache.
3. **Per-print and interval tables.** These use the logic of `build.py: process` (at most 2 processes).
   - The moneyline input is the raw OOS moneyline tape via `src.tape.load_tape`.
   - **The markout columns (`mo60`, `mo300`, `mo_res`) are not computed**, and no P&L or markout statistic
     is printed.
   - The jump columns are left NaN, because the window is always-on.
   - The build prints only counts: events, side markets by type, tapes, prints, intervals, excluded markets.

### 2.3 Parity check on IS, before any OOS P&L
The OOS code path (`research/v2/maker/oos_test.py`) must first reproduce the IS cell (always, 0.04) on the IS
per-print table:
- IS walk-forward b by month and the IS model choice by month;
- months ≥ 2026-02;
- target: the cell as reported in `analysis.json["lean_maker"]["cells"]`, n = 10,171 fills and $5,326.05 of
  P&L, with 1e-6 relative tolerance.

If parity fails, the OOS step does not run. The fix is recorded in `research/v2/maker/DEVIATIONS.md` and
parity is re-run.

### 2.4 The OOS book
- Maker v1 as in §1, with the frozen b_T table for every OOS row and λ = 1.0 local shrinkage.
- The fill model is the IS model of §1.5 and the P&L is §1.6.
- One run. The run appends a line to `results/oos_peeks.log` **before** it computes any P&L.

### 2.5 Primary (the pass/fail claim)
- **Statistic.** Per-share net, held to resolution: `mean_pnl_per_share_c` from `src.backtest.stats`. It is
  the fill-weighted mean of pnl_ps, the same statistic as the IS headline +2.73c.
- **CI.** The 95% CI from the same call: a match-clustered bootstrap with clusters = event_id, 2,000 draws,
  seed 0.
- **PASS only if the CI's lower bound is > 0.** Anything else is reported as a **FAILURE** of the OOS
  claim, including a positive point estimate whose CI contains 0.
- **Underpowered label.** A sample with fewer than 500 fills or fewer than 100 matches is labelled
  "underpowered". The label does not turn a fail into a pass.
- **Power.** The OOS spans about 39 days, against IS 1s/5% at 4,159 fills, 1,017 matches and SE ≈ 0.75c.
  - If OOS side flow matches IS, the expected sample is about 3,500 fills and 860 matches, with SE ≈ 0.8c.
  - P(pass) ≈ 0.7 if the true edge is +2.0c, and ≈ 0.25 if it is +1.0c.
  - Side-market volume has been shrinking relative to the moneyline (16% → 1.4% of in-play $), so n may come
    in lower.

### 2.6 Secondary (reported, not tested)
- **Headline statistics:**
  - $ P&L, notional, fills, matches, share-weighted net with a match-clustered CI, hit rate.
  - From `stats(book, capital=3 × peak locked)`, with daily P&L on fill dates and zero-filled calendar days:
    daily Sharpe ×√365, max drawdown (% of capital and $), worst day ($ and % of capital), worst month ($).
  - Months positive, in $ and per share. The months are calendar months: Aug 25–31, Sep, Oct 1–3. Aug and
    Oct are labelled partial.
- **By regime** (fee/delay of the side market), each with n, net c/share, CI, $. The OOS is expected to be
  entirely 1 s / 5%. The comparator is IS 1s/5% at +2.02c [0.53, 3.48].
- **By side-market type**, each with n, net c/share, match-clustered CI, $ and notional.
- **Consistency.** Whether the OOS point estimate lies inside the IS 1s/5% CI.

### 2.7 Cost stresses (same book construction, one change each)
| stress | change |
|---|---|
| (i) queue share 10% | shares = min(0.1 × print size, $250/px). Per-share P&L moves only through which fills the $2k cap keeps; $ roughly halves. |
| (ii) trade-through | Our resting level L_j is the price, on our token's axis, of m's latest in-play print on **our** side of the book (a taker sold our token) with ts < ts_j − d, at most 120 s old. There is no quote if no such print exists. The contrary print j fills us only if its price on our token is **strictly below** L_j. The fill is at L_j, with shares = min(0.2 × size_j, $250 / L_j), 0.02 < L_j < 0.98, and pnl_ps = payout − L_j + rebate(L_j). |
| (iii) rebate removed | pnl_ps = payout − px |
| (iv) all of (i)–(iii) | 10% share, trade-through, no rebate |

Each stress reports the §2.5 statistic, its CI and the §2.6 headline statistics.
- **Cost-robust OOS:** maker v1 is called this only if (iv) also has a CI lower bound > 0.
- **Cost-fragile:** it is called this if (iv)'s point estimate is ≤ 0.

### 2.8 Diagnostics (not tested, never chosen)
These are the two IS placebos, on the same fill model and min_impl 0.04:
- the **unconditional maker**: every print, both sides, no lean;
- the **anti-lean placebo**: filled by takers trading *with* the implied move.

IS values for 1s/5%: −0.12c [−1.26, 0.95] and −1.29c [−2.75, 0.12].

### 2.9 Variants evaluated on OOS: 7, all listed
1. maker v1 (primary)
2. stress (i) queue share 10%
3. stress (ii) trade-through
4. stress (iii) no rebate
5. stress (iv) all three
6. diagnostic: unconditional maker
7. diagnostic: anti-lean placebo

**Conditional 8th.** If the OOS catalogue shows a nonzero maker fee on any side market (Gamma
`takerOnly` false, or `makerBaseFee` > 0), a stress charging that fee is added and labelled. This is decided
from metadata before the run, never from P&L.

The lens's cumulative count is 68 IS variants plus these 7 or 8. Regime and type breakdowns are cuts of
book 1, not variants.

## 3. (B) Live paper session (forward, real live markets, paper fills)

### 3.1 Window and what runs
- **Script.** `scripts/live_paper.py` is built and committed after this file and before its session
  starts.
- **Start.** The session starts when the script writes its `session_start` line after warm-up. That moment
  is logged to `results/oos_peeks.log` together with the script's commit hash.
- **End.** Quoting stops at **2026-10-04 11:30:00 UTC**.
- **Open positions** are held to resolution. The final report is written no later than 2026-10-04
  16:00 UTC. Anything unresolved by then is marked to its last mid and labelled.
- **No changes.** Any change to `live_paper.py` after the start is a deviation, logged with its time.
- **Read-only.** It uses Gamma `/events` discovery every 120 s, the CLOB market websocket (book,
  price_change, best_bid_ask, last_trade_price, tick_size_change, market_resolved) and data-api `/trades`
  (at most 4 concurrent, with back-off).
- **Runtime.** One process, with no signing code and no keys. Anyone can run it the same way:
  `python scripts/live_paper.py --until 2026-10-04T11:30:00Z`.
- **Raw log.** Every websocket message is logged with its local receive time to
  `data/live_maker/raw_<run>.jsonl.gz`, so the session can be replayed exactly.
- **Warm-up check: trade-side convention.** Before the start, the script matches at least 50 websocket
  `last_trade_price` messages to data-api `/trades` records (same market, price and size, ±2 s). The side
  convention used must agree on ≥ 95% of them; data-api `side` is the taker side, as in IS. If neither
  convention reaches 95%, the session does not start.
- **Warm-up check: in-match history.** For markets already in play, the in-play print history is
  bootstrapped from data-api `/trades`. After that, websocket `last_trade_price` messages extend it.
  - Two messages on the two tokens of one market with the same server ms, the same size and prices summing
    to 1 (±1e-9) count as one print.

### 3.2 Markets
- §1.1, applied ex ante: open Gamma tennis events with `seriesSlug` in {atp, wta, challenger}, singles only,
  in play by §1.1's window.
- No volume floor can be applied live. A secondary cut reports the IS/OOS universe ex post: moneyline
  volume ≥ $5k and side lifetime volume ≥ $250.
- d, the tick, `orderMinSize`, the fee rate and `rebateRate` are read per market from Gamma.

### 3.3 Clock and latency
- **One-way latency.** L = max(67 ms, the running median of half the PING→PONG round trip on our market
  websocket over the previous 10 min). 67 ms is the FLORIDA preset in `src/paper.py`, the measured median
  from Gainesville. The script logs its measurements.
- **When a message is seen.** A message with server timestamp e is seen at s(e) = max(e + L, local receive
  time). The local clock is NTP-synced; `latency/RESULTS.md` measured it within 0.0 ± 11 ms of
  time.apple.com.
- **Venue rules applied.** Polymarket sports markets hold **marketable** orders for d (1 s). The takers'
  print times already contain that delay. Our orders are post-only limit orders, never marketable, and
  neither they nor our cancels wait d; they act at the venue L after our decision. A post-only order that
  would cross the opposite best on arrival is rejected, and the next decision retries.
  - If the venue clears a market's book (`clearBookOnStart`, or an empty book snapshot on both tokens), our
    resting orders there are cancelled.
- **Signal timing (primary).** Information is cut at t − d (§1.4). A signal change caused by a print at e
  takes effect at the venue at max(e + d, s(e) + L). Because d ≥ 2L this is normally exactly e + d, which
  reproduces the IS information timing.

### 3.4 Quote mechanics
- **Price.** While the state is "bid token k", we rest one post-only bid on token k at that token's
  **displayed best bid (join, never improve, never cross)**. No quote is placed if token k has no bid or the
  price is outside (0.02, 0.98).
- **Size.** R₀ = ⌊min($250, remaining match budget) / price⌋, in 0.01-share steps. There is no order if
  R₀ < `orderMinSize`.
  - Once an order is fully filled and the state is still on, a fresh R₀ order is placed at the back of the
    queue, visible at s(fill print) + L.
- **Re-peg.** When the seen best bid of token k differs from our price, we cancel and replace at the new
  best bid. It takes effect at s + L, and we lose our queue position.
- **Cancel.** When the state goes off or flips, the order is cancelled, effective as in §3.3. Fills that
  occur before a cancel takes effect count.
- **Budget.** $2,000 gross filled per match (event), across all side markets and both tokens, kept
  separately for each variant.

### 3.5 Queue-aware fill model (conservative)
- **Queue ahead (Q).** When our order becomes visible at time v, Q is the displayed size at our price on
  token k in the venue book as of v: all messages with server ts ≤ v. Q is 0 if the level is empty.
- **Eligible trades.** Only trades with server ts strictly after v, whose taker **sold token k** (hit
  token k's bids). Each trade has size V and price x on token k's axis.
  - **At our price (x = P).** We fill f = min(max(0, V − Q), 0.2 × V, R, budget/P). Then Q ← max(0, Q − V).
    Trades consume the queue ahead before they reach us.
  - **Through our price (x < P).** We fill f = min(0.2 × V, R, budget/P) at **our** price P.
- **Cancels ahead of us.** After each message, Q ← min(Q, displayed size at P). Orders that join later sit
  behind us, so we advance only when the displayed size proves that orders ahead of us left. Any other
  cancel is assumed to come from behind us.
- **Same-millisecond messages.** Trades are applied before book updates, so no trade is counted twice.
- **The 0.2 × V cap** is the frozen sizing (20% of each contrary print). It keeps the live model a subset of
  the IS model, print by print. Variant B1-full drops it.
- **Fill P&L:** resolved payout − P + 0.15 × fee_rate × P(1 − P). No fee.

### 3.6 Books run in the session (all descriptive): 7
| # | book | how |
|---|---|---|
| B1 | **primary**: §3.3–3.5 | live |
| B1-rt | as B1, but information is cut at seen time (real-time, no IS lag) | live |
| B1-full | as B1, without the 0.2 × V cap (a resting $250 order fills up to the queue allows) | live |
| B1-delay | as B1, but our placements also wait d before becoming visible (cancels not delayed) | live |
| B2 | offline replay of `live_paper.py`'s own raw log through the same engine, in server time + L | after |
| B2v | offline replay of the independent `data/live_v2` recorder's `clob_*` messages through the same engine, up to the recorder's end | after |
| B3 | IS fill model (§1.5) on data-api `/trades` tapes of the same markets and window | after |

B2v covers only part of the session. The live_v2 recorder (started 2026-10-03 11:23 UTC, `--hours 20`) stops
around 2026-10-04 07:23 UTC.

### 3.7 Reported for every book
- Fills, matches, $ filled, and fills per market type.
- **Per-share net at resolution**, fill-weighted and share-weighted, with a match-clustered 95% CI (2,000
  draws, seed 0).
- **$ P&L at resolution.**
- **$ P&L marked to mid at 11:30 UTC.** Resolved markets use the payout. Unresolved markets use the mid of
  token k's best bid and ask, or the last trade if one side of the book is empty.
- Each with the 15% rebate, with the market's own `rebateRate`, and with no rebate.
- Mid markouts at +5 s, +60 s and +300 s after each fill (adverse selection).
- Measured L, its distribution, and message gaps or reconnects.

**Comparison (the point of B):**
- B1 vs B2 must match fill for fill. Any difference is explained, and it can come only from receive-time
  vs server-time timing.
- B1 vs B2v measures sensitivity to message loss between two independent recordings.
- **B1 vs B3** measures how optimistic the IS fill model is on the same hours:
  - the ratio of $ filled (B1 / B3) and of fill counts;
  - the share of B3 fills, by print, that B1 also filled;
  - per-share net on the overlap vs on B3-only fills.

**Honest framing.** (B) is descriptive and has no pass/fail.
- At the IS 1s/5% rate (about 90 IS-model fills per day), a 12–16 h session gives roughly 45–60 B3 fills,
  so per-share CIs will be several cents wide.
- (B) can show that the implementation works on real live markets, and how much the IS fill model
  overstates fills. It cannot confirm the edge.
- **Pre-written red flags, reported as such:**
  - B1 $ filled < 25% of B3 $ filled means "IS dollar capacity overstated ≥ 4×".
  - A B1 per-share CI upper bound < 0 means "live loss, inconsistent with IS".
  - B1 ≠ B2 means "engine not deterministic; B1 numbers withdrawn until explained".

## 4. (C) Fill-model validation on live side-market books
- **Data.** `data/live_v2` (`clob_*` and `clobmeta_*`), with prints = websocket `last_trade_price`
  (de-duplicated as in §3.1), mapped to the outcome-0 axis.
- **Period.** The B session from its start to min(2026-10-04 11:30 UTC, end of the live_v2 recording).
  - An extension to the end of B, using `live_paper.py`'s own raw log, is reported separately and labelled.
- **Markets.** As in §3.2.
- **In-match history.** Signals use only prints in the recording. The recording starts 11:08 UTC, hours
  before B. Markets whose in-play history begins before the recording are flagged.
- **Candidates.** Every contrary print j that the IS fill model (§1.5) would fill, with the signal computed
  from recorded prints with ts < ts_j − d. Call its price level ℓ_j (on our token) and its size V_j.
- **Two queue measures at ℓ_j:**
  - **Q_back**: the displayed bid size at ℓ_j on our token just before the print. This is the worst case for
    an order that is at the level.
  - **Q_live**: the queue ahead under the B1 rules. The order joins at the touch when it becomes visible,
    trades at its level consume the queue, and the queue is capped by displayed size. If B1 would not be
    resting at ℓ_j at ts_j (for example, the print swept a better level first, or we were re-pegging), the
    candidate is marked "not at level".
- **Reported:**
  - **The share of candidates for which the assumed 20% is achievable**, meaning V_j − Q ≥ 0.2 × V_j. It is
    given by count and $-weighted, under Q_back and under Q_live.
  - The distribution of the achievable fraction clip((V_j − Q)/V_j, 0, 1), against the assumed 0.2.
  - The ratio of achievable fill $ to IS-model fill $: Σ min(0.2, fraction) × V × px over Σ 0.2 × V × px.
  - The share of candidates at the touch vs through it, and the share "not at level".
  - Breakdowns by type, by print size (<$10, $10–100, >$100) and by time since the signal turned on.
  - Websocket-vs-data-api print coverage for the same markets and hours.
- **Measures counted: 2** (Q_back and Q_live). (C) is descriptive.

## 5. Order of operations, logging, deviations
1. Commit this file. Nothing below has run.
2. Build `oos_build.py`, then pass the parity check (§2.3) on IS.
3. Build and commit `scripts/live_paper.py`, with unit tests of the fill engine on hand-written message
   sequences. Those are test fixtures, never presented as market data. Then start the B session.
4. Run (A) once: `oos_test.py` appends a peeks line, then writes `research/v2/maker/oos/` (books, tables,
   `results.json`).
5. After 2026-10-04 11:30 UTC: run B2, B2v, B3 and (C), resolve, and write `research/v2/maker/LIVE.md` plus
   `live_results.json`.

Every evaluation on OOS or forward data appends a line to `results/oos_peeks.log`: (A), B's start, B's
report and (C).

- **Fixed rules.** No constant of maker v1 is changed because of (A), (B) or (C). That covers b_T, λ,
  min_impl 4c, the 600 s / 120 s / 30 s windows, 20%, $250, $2,000, the price band, the rebate and
  hold-to-resolution. A changed rule is maker v2. It needs its own pre-registration and data that nobody
  has looked at, and (A), (B) and (C) count as in-sample for it.
- **Deviations.** Bugs, data problems and changed definitions go in `research/v2/maker/DEVIATIONS.md`, with
  their reason, before any re-run. First-run numbers are kept and reported next to any re-run.
- **Reporting.** Every result is reported whatever it shows, including a FAILURE of (A).
