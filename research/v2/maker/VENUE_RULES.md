# Venue rules for the leaning maker (Polymarket tennis side markets)

Researched 2026-10-03, about 18:00–18:35 UTC. Sources are Polymarket's official docs, the help center, the changelog, and
the public keyless API. Nothing here places, signs or simulates an order. All market numbers are real reads of the live
venue. Docs quotes are kept short; the URLs hold the full text.

Reproduce:
- `.venv/bin/python research/v2/maker/venue_snapshot.py --repeat 2 --gap 90` (live REST snapshot; public GETs, 3 workers)
- `.venv/bin/python research/v2/maker/recorded_books.py` (today's `data/live_v2` websocket recording; local files only)

Outputs: `out/venue_snapshot_20261003T1826Z.json`, `out/books_20261003T1826Z.csv`, `out/recorded_books_20261003_1123.json`.
Reading the forward recording is logged in `results/oos_peeks.log`. It was descriptive only: no strategy, no P&L and no
parameter came out of it.

## Summary

| # | Question | Answer | Confidence |
|---|---|---|---|
| 1 | Does the sports order delay apply to makers and cancels? | **No.** `secondsDelay` applies only to *marketable* orders. A non-marketable (or post-only) order rests at once. Cancels are not delayed; the one exception is that a *marketable* order cannot be cancelled while it waits out its own delay. Every open tennis market has `secondsDelay = 1`. | High for the documented rule. It was not tested with live orders, which this project does not place. |
| 2 | Maker fee and rebate now | Maker fee **0** (`feeSchedule.takerOnly = true`). Takers pay `C × 0.05 × p(1−p)`. Makers get **15%** of the taker fees collected in the market, paid daily in pUSD. The pool is split per market by each maker's fee-equivalent on filled maker orders, `C × 0.05 × p(1−p)`. To qualify, an order must add liquidity and get filled. Payout needs ≥ $1 accrued. These terms took effect 2026-07-10 00:00 UTC; before that the rate was 0.03 with a 25% rebate. | High |
| 3 | Tick and minimum size | Tick **0.01**. It switches to 0.001 when the price nears 0 or 1: in today's recording, 92% of 1,708 switches came with best bid ≥ 0.96 or best ask ≤ 0.04, and none went back. Minimum order size is **5 shares**. All 2,059 open tennis markets in the window (in play, or starting within 24 h) have these values. | High |
| 4 | Post-only? | **Yes.** `postOnly: true` on a GTC or GTD order. An order that would cross is rejected, not executed. Live since 2026-01-06. | High |
| 5 | Live side-market spread and depth | **Right now** (Saturday 18:26 UTC; only Challenger, ITF and doubles in play): 181 in-play side markets across 13 matches, sampled twice. 54% of books were empty and 44% one-sided. Only 9 of 362 reads were two-sided: median spread 3c, top of book 3,430 bid / 63 ask shares. **Today 11:23–18:28 UTC, recorded in play** (741 side markets, 71.5k market-minutes): two-sided 15% of minutes. When two-sided with mid in 5–95c: median spread **13c** [IQR 2–95c], top of book **250 / 200 shares** (~$75 / $107). At tour level (China Open, plus 2 Japan Open markets; 107 markets): two-sided 29% of minutes, median spread **13c** [6–22c], top **234 / 200 shares**. For comparison, tour moneylines in play: 1c and ~4,000–7,000 shares. | High for the dates measured. Spreads depend on tier and time of day (see 5). |

## 1. Order delay (`secondsDelay`): marketable orders only

Docs:
- Market Details, field table: `secondsDelay` is the *"Delay, in seconds, before a newly placed marketable order can match."*
  https://docs.polymarket.com/market-data/market-details#market-timing
- Order Lifecycle, under "Match or Rest": if the order is marketable, some markets add a delay first. For sports, the
  *"Sports/game delay"* is turned on for configured sports markets around live play, and the order waits out the delay
  before matching. The non-marketable branch has no delay: *"If the order is not marketable, it rests on the book"*.
  https://docs.polymarket.com/concepts/order-lifecycle
- Order statuses: `delayed` = *"Marketable order accepted into an asynchronous delay window"*. `unmatched` = a marketable
  order that was placed on the book after its delay ran out with no match. Resting orders get `live`.
  (same page; also https://docs.polymarket.com/trading/place-orders)
- Cancels: you can cancel any time before a match, *"except while a marketable order is in a pending delay window"*.
  The order in its delay window is the only one that cannot be cancelled; resting orders can be.
  https://docs.polymarket.com/concepts/order-lifecycle#cancellation
- Help center ("Limit Orders", dated 2026-04-20): *"sports markets include a 3-second delay on the placement of
  marketable orders"*. The same article says a 1-second taker delay was being tested on NBA and MLB.
  https://help.polymarket.com/en/articles/13364444-limit-orders

The live API shows `secondsDelay = 1` on all 2,059 open tennis markets in the window (moneyline and side, in play and
starting within 24 h).
The CLOB agrees: `GET https://clob.polymarket.com/markets/<condition_id>` returns `seconds_delay: 1`, and `/clob-markets/<id>`
returns `sd: 1`. The help center's "3-second" figure is stale for tennis. The repo already uses 3 s up to about mid-2026 and
1 s after (DEVIATIONS.md). The separate 250 ms "taker delay" (`itode`) is limited to some crypto and finance up/down markets.
The tennis markets sampled do not have `itode`.

What this means for the leaning maker:
- A post-only quote is never marketable, so it rests at once with no delay. Cancelling or replacing a resting quote is also
  not delayed (rate limits below). RESULTS.md 5b says "makers can cancel instantly (no order delay)", and the docs back this.
- The delay works in the maker's favour. Any taker order on these markets waits 1 s before it can match, and a maker can
  cancel during that second. A maker who sees a moneyline jump has about 1 s plus their own latency to pull a stale side
  quote before an informed taker's order can execute against it.
- An aggressive order (taker exit, crossing limit) is held 1 s, cannot be cancelled during that time, and is then
  re-checked. The strategy holds to resolution, so this matters only for optional exits.

Not verified: we did not observe this with real orders, because the project places none. The rule rests on three docs pages,
the API field definition and the status table, which all agree.

## 2. Maker fee and maker rebate (sports, in force now)

Docs:
- Fees: *"Makers are never charged fees."* The sports taker rate is 0.05 and the maker rate 0. Formula:
  `fee = C × feeRate × p × (1 − p)`. Fees round to 5 decimals, with a minimum of 0.00001.
  https://docs.polymarket.com/trading/fees
- Maker Rebates Program: the sports rebate is 15%, "fee-curve weighted". For each filled maker order,
  `fee_equivalent = C × feeRate × p × (1 − p)`, and each day `rebate = (your_fee_equivalent / total_fee_equivalent) × rebate_pool`.
  Totals are per market, so makers compete only within their own market. To qualify: *"Place orders that add liquidity
  to the book and get filled"*. Paid daily in pUSD, with a $1 minimum accrued balance. Polymarket sets the percentage
  at its sole discretion and may change it.
  https://docs.polymarket.com/programs/maker-rebates
- Changelog, 2026-07-10: the sports taker rate went from 0.03 to 0.05 at midnight UTC, and *"The sports maker rebate
  decreases from 25% to 15% of collected taker fees."* Earlier: Fee Structure V2 (2026-03-30) brought fees to all sports,
  and from 2026-03-31 fees are computed from each market's `feeSchedule`.
  https://docs.polymarket.com/changelog/predictions
- Market Details: `feeSchedule.takerOnly` (when true, makers pay no fee) and `feeSchedule.rebateRate` (the share of
  taker fees rebated to the resting maker). https://docs.polymarket.com/market-data/market-details#trading-fees

Live API: all 2,059 open tennis markets in the window have `feesEnabled: true`, `feeType: "sports_fees_v3"`,
`feeSchedule = {rate: 0.05, exponent: 1, takerOnly: true, rebateRate: 0.15}`. The CLOB also returns `fd: {r: 0.05, e: 1, to: true}`.
A June tennis market still shows the old terms (`sports_fees_v2`, rate 0.03, rebate 0.25).

How the rebate works out per fill. Each match has one taker order and its maker fills, all at the same prices. That makes a
market's total maker fee-equivalent equal to the taker fees it collected. Each maker therefore receives about
**15% × 0.05 × p(1−p)** per filled share, at most 0.19c/share at p = 0.5. The repo's `REBATE = 0.15 × taker_fee(own rate)` matches this exactly
when the rate is 0.05. When it is 0.03 (2026-03-30 to 07-09), the true rebate was 25%, so the repo understates the rebate by
(0.25 − 0.15) × 0.03 × p(1−p), at most 0.08c/share (conservative). Fee-free matches get no rebate, both in the repo and on the venue.

Two caveats:
- The CLOB also returns legacy fields `maker_base_fee` / `taker_base_fee` = 1000 (bps), and `/fee-rate` returns `base_fee: 1000`.
  Docs say fees are set by the protocol at match time and are not part of the order, and should be computed from
  `feeSchedule` (changelog 2026-03-31). We treat the 1000 bps fields as legacy. They are not the rate charged.
- Liquidity rewards are a separate program. Tennis markets carry `rewardsMinSize 50` / `rewardsMaxSpread 4.5`, but every
  sampled market returned `rewards.rates: null`, meaning no reward pool. No liquidity-reward income is assumed.

## 3. Tick size and minimum order size

Docs:
- Every market has a tick (price increment) and a minimum order size. Orders below the minimum are rejected. The
  0.0025 tick is only for World Cup markets. https://docs.polymarket.com/market-data/market-details#trading-constraints
- `min_order_size` in `/book` is *"the minimum number of shares the CLOB accepts for an order"*.
  https://docs.polymarket.com/trading/place-orders (Note: the Gamma field table on market-details calls `orderMinSize`
  "USDC". The CLOB guide and the reject message (`Size ({size}) lower than the minimum`) treat it as shares, as do order
  sizes generally. We read it as **5 shares**.)
- The tick can change. The market websocket sends `tick_size_change`, described as *"Market tick size update when price
  approaches limits"*. Orders that don't fit the current tick are rejected.
  https://docs.polymarket.com/api-reference/wss/market and https://docs.polymarket.com/trading/place-orders

Live API: `orderPriceMinTickSize` is 0.01 on 1,994 of 2,059 open tennis markets. The other 65 are in-play markets whose
price is near 0 or 1, and they show 0.001. Every market has `orderMinSize = 5`, and `/book` agrees (`tick_size "0.01"`,
`min_order_size "5"`). The recorded websocket (11:23–18:28 UTC) has 1,708 `tick_size_change` events, all 0.01 → 0.001. In
92% of them the best bid was ≥ 0.96 or the best ask ≤ 0.04; most of the rest came with a one-sided book. None went back.
At the prices where the strategy trades (mid 5–95c), the tick is 1c.

## 4. Post-only orders

- Order Lifecycle: a post-only order only rests on the book. If it would cross the spread, it is rejected rather than
  executed, so the sender is always the maker. https://docs.polymarket.com/concepts/order-lifecycle
- Place Orders: a post-only order *"is rejected instead of taking"* if it would match immediately. It is set with
  `postOnly: true` on a GTC or GTD request. https://docs.polymarket.com/trading/place-orders#post-only-orders
- API reference, `postOnly`: *"Only supported for GTC and GTD orders."*
  https://docs.polymarket.com/api-reference/trade/post-a-new-order
- Reject message: `invalid post-only order: order crosses book`. https://docs.polymarket.com/resources/error-codes
- Launched 2026-01-06 ("Post Only Orders"). https://docs.polymarket.com/changelog/predictions
- After a matching-engine restart there are two minutes of post-only mode, when only post-only orders and cancels are
  accepted. https://docs.polymarket.com/trading/matching-engine

## 5. Live side-market spreads and top-of-book depth

Method. Side market = any tennis market other than the moneyline (first/set winner, set and game handicap, match, set and
first-set totals, completed match). Books are read for outcome 0. The outcome-1 book is an exact mirror (bid₁ = 1 − ask₀,
same sizes): 12 of 12 pairs fetched together matched, and we hand-checked 7 more on tour-level moneyline and side markets.
Spread = best ask − best bid. Depth = shares resting at the best price. Tier: "tour" = China Open and Japan Open
(ATP/WTA 500+); "challenger/other" = the rest of the atp/wta series; "itf"; "doubles". "In play" = scheduled start
passed and market not resolved (snapshot: up to 5 h after start; ITF start times are approximate).

### 5a. Right now: REST snapshot, 2026-10-03 18:26 and 18:28 UTC

181 in-play side markets in 13 matches (31 challenger, 30 doubles, 120 ITF; no tour matches in play at this hour), read twice:

| | reads | empty book | one-sided | two-sided | median spread (two-sided) | median top of book (bid / ask, shares) |
|---|---|---|---|---|---|---|
| in-play side, all | 362 | 54% | 44% | 9 (2.5%) | 3c (IQR 3–91c) | 3,430 / 63 |
| in-play ITF | 240 | 43% | 57% | 0 | — | — |
| in-play doubles | 60 | 85% | 15% | 0 | — | — |
| in-play challenger | 62 | 65% | 21% | 9 | 3c | 3,430 / 63 |

The 9 two-sided reads come from two Challenger matches. Columbus match totals were quoted at 3c by one ~3,400-share maker.
Curitiba side markets showed a 1c/99c stub. Pre-match books for comparison (tomorrow's slate):

| pre-match side | markets | two-sided | median spread | IQR | median top (bid / ask, shares) |
|---|---|---|---|---|---|
| tour (China Open, Japan Open) | 257 | 92% | **4c** | 2–44c | 105 / 100 |
| challenger/other | 28 | 100% | 21c | 3–88c | 16 / 12 |
| ITF (random sample) | 254 | 99% | 95c | 94–97c | 20 / 25 |
| doubles | 18 | 100% | 95c | 89–97c | 10 / 30 |

### 5b. Today in play: recorded websocket, 2026-10-03 11:23–18:28 UTC (`data/live_v2`, public market channel)

One sample per minute of the server's best bid and ask, with the size at the best price from the rebuilt book
(size is known for 96% of samples; it is used only where the rebuilt best price equals the server's).

| in-play side markets | markets | market-min | two-sided | no bid & no ask | median spread (two-sided, mid 5–95c) | IQR | ≤ 1c | median top (bid / ask, shares) | (~$) |
|---|---|---|---|---|---|---|---|---|---|
| all | 741 | 71,513 | 15% | 35% | **13c** | 2–95c | 18% | 250 / 200 | 75 / 107 |
| tour (China Open; Japan Open) | 107 | 8,814 | 29% | 28% | **13c** | 6–22c | 3% | 234 / 200 | 72 / 102 |
| challenger/other | 174 | 19,525 | 31% | 39% | 3c | 1–59c | 30% | 1,424 / 866 | 687 / 433 |
| ITF | 373 | 36,839 | 4% | 30% | 98c (stubs) | — | 0% | 56 / 56 | — |
| doubles | 87 | 6,335 | 6% | 58% | 98c (stubs) | — | 0% | 63 / 63 | — |
| *moneyline, tour (comparison)* | 9 | 833 | 65% | 1% | 1c | 1–1c | 90% | 4,058 / 7,069 | 2,569 / 3,962 |

Tour-level in-play side markets by type (two-sided minutes, mid 5–95c): first-set winner 7c [4–10] with 400/400 shares
(two-sided 52% of minutes); set winner 10c [7–21], 337/390; set handicap 16c [9–20], 400/400; match totals 11c [3–27],
116/150; set totals 19c [15–21], 200/200; first-set totals 28c, 100/179; set-games totals never two-sided. The
challenger median is driven by one or two deep quoters (Porto: 1c spread, two-sided 82% of minutes). Most other
challenger and nearly all ITF and doubles side books are empty or hold 1c/99c placeholder quotes in play.

What this means for the leaning maker:
- Side books in play are thin. At tour level the typical gap is about 13c and the book is two-sided only about 30% of the
  time. A lean quote placed a few cents inside the gap would usually be the best price on its side, so queue position is
  rarely the binding constraint. Fills depend on contrary takers arriving.
- The backtest fills us at historical print prices (we "joined that level"). In books this wide, our own quote could
  change where those prints happen. That is a modelling question for the backtest, not a venue rule. Still, the in-sample
  edge (+2.73c/share) is small next to a 13c gap, which means queue position or adverse selection inside the gap
  could change the result.
- Every open tennis market has `clearBookOnStart: true` (CLOB: `cbos: true`). The help center says outstanding limit orders
  *"are automatically cancelled once the game begins"*; the Markets & Events concept page says the same and warns that
  start times can move. Quotes must be placed after the start. In one example from today, Gamma's `gameStartTime` was
  18:15 and the CLOB's `gst` was 18:25.
  https://help.polymarket.com/en/articles/13364444-limit-orders, https://docs.polymarket.com/concepts/markets-events

## Other operating rules that matter for a maker (cited, not asked)

- Heartbeats: after the first one, a missing heartbeat for 10 s cancels all of that key's open orders (checked every 5 s).
  This is a dead-man's switch for a quoting process. https://docs.polymarket.com/trading/manage-orders#order-heartbeats
- Rate limits, standard tier: 40 orders/s (burst 60) and 80 cancels/s (burst 120), per signer.
  https://docs.polymarket.com/api-reference/trading-rate-limits
- Orders cannot be amended. A re-quote is a cancel followed by a new order. https://docs.polymarket.com/trading/market-making
- Cancels still work in cancel-only and post-only modes. https://docs.polymarket.com/trading/matching-engine

## Checking the assumptions in RESULTS.md 5b

| Assumption in 5b / `analyze.py` | Venue fact | Status |
|---|---|---|
| Makers pay no fee | `takerOnly: true`, maker rate 0 | holds |
| 15% maker rebate on fills | 15% of the market's taker fees, split pro rata by fee-equivalent ≈ 15% × fee on own fills; 25% before 2026-07-10 | holds (conservative in-sample) |
| Makers can cancel instantly | the delay applies only to marketable orders; cancels of resting orders are not delayed | holds (from docs) |
| Taker delay 3 s, then 1 s | `secondsDelay = 1` on every tennis market now | holds |
| Quote at the print price, ≤ $250/fill | tick 1c in the 5–95c range; minimum resting order 5 shares | holds |
| Rest during play | the book is wiped at the scheduled start; quote after it | needs handling in a live runner |
| Filled at print price | in-play side gap ~13c at tour level, books often empty | fill model needs a live check (forward paper fills) |
