# Match replay: protocol (written and committed before any P&L was computed)

> **BACKTEST REPLAY on a real match recorded live on 2026-10-03 — assumed 1 s licensed video feed (not
> purchased); bounce time = official point stamp - assumed stamp lag; fills priced against the real recorded
> order book; paper only.**
>
> We did not receive, buy or watch any video of these matches. The video feed, its delay V, the camera-based
> call and its lead are all assumed. What is real: the official WTA point stamps and point winners, the
> Polymarket order books and trades recorded live on 2026-10-03, the venue's 1 s taker delay, the fee
> formula and the match results. No order was sent anywhere.

## 1. What this is for

The tier-0 latency sweep (`research/v2/tier0/LATENCY_SWEEP.md`, `results/tier0/latency_sweep.*`) is a Monte
Carlo over historical tapes. It needs one day of live data for reprice timing and book depth, and it says
the edge is gone after about 1 s of feed delay. This replay walks the same trader through **every official
point of real matches recorded live today**, one point at a time, and prices each order against the actual
recorded book at the instant it would have executed. It is an illustration of the mechanism and a
consistency check against the sweep. It is **not new evidence**: one day, 9 matches, a few hundred points,
and the same live data that already parameterises the sweep.

## 2. Inputs (frozen)

| input | what | used for |
|---|---|---|
| `research/v2/latency/out/m1_points.csv` | 994 official WTA points, 9 matches, snapshot of the 12:45 UTC analysis run. `T_ms` = official umpire stamp (1 s resolution), `winner` = point winner oriented to outcome 0, `t_book` = half-move book reprice on the local receive clock (482 points) | point list, point winners, stamps, reprice times |
| `data/live/market_20261003_0946.jsonl.gz`, `data/live/market_20261003_1003.jsonl.gz` | raw Polymarket CLOB market websocket recorded live by `src/live_recorder.py` (book snapshots, per-level `price_change`, `last_trade_price`, `market_resolved`), each with the server `timestamp` and the local receive time `rt`. The 0946 file is truncated at its end (gzip EOF); it is read to the last complete line | the order book at every instant; prints; match results |
| `data/live/market_20261003_1501.jsonl` | the same recorder, later hours | match results only (`market_resolved`) if a match resolved after 15:01 UTC |
| `research/v2/latency/load.py` `events_table(load_meta())` | token ids and outcome order for the 9 moneylines | orientation identical to `m1_points.winner` |
| `src/tier0.py` `cv_systems()["own120"]`, `point_mix()` | the tier-0 own-camera CV model and the WTA point-ending mix | CV call lead distribution |

Nothing is re-fetched. `m1_points.csv` is not regenerated.

## 3. Match-selection rule (for the highlighted match)

**The match with the most points that have a matched book reprice** (`t_book` not null in
`m1_points.csv`); **ties broken by the earliest first official point stamp**. The rule uses no P&L and no
fill outcome. Applied to the frozen file it selects `wta-su-bucsa-2026-10-02` (Xinran Sun v Cristina Bucsa,
125 matched points of 128). All 9 matches are replayed and reported; the selected match is only the one the
write-up walks through point by point.

## 4. Per-point procedure

All times are UTC milliseconds. Polymarket's server `timestamp` is taken as UTC. The recorder's clock was
within 0.0 ± 11 ms of NTP (`research/v2/latency/RESULTS.md` §1).

**Book replay.** For each of the 9 markets, both outcome tokens' L2 books are rebuilt from the recording in
server-time order: `price_change` levels at their server `timestamp`; `book` snapshots (sent on subscribe or
reconnect, whose `timestamp` field can be the time of the book's last change) at `rt - L_recv`, where
`L_recv` is the median of `rt - timestamp` over the recorded `price_change` messages of these 9 markets
(≈ 67 ms, Florida). Events with equal effective time keep recording order. The book "at time t" is the state
after every event with effective time ≤ t. Each token's own book is used for that token; Polymarket
publishes each order in both tokens' books (a BUY of one outcome at p appears as a SELL of the other at
1 - p), so the token's own asks are the complete set of offers a buyer of that token can hit.

**Points replayed.** Points are processed per match in official order. A point is replayable if the market
has a book snapshot before the point's reference instant (below) and at least one recorded message for the
market in the 60 s before the execution instant. Other points get status `no book recorded` (the recorder
started at 09:46 UTC; the latency analysis counts 502 of the 994 points outside its book coverage) and are
excluded from every total.

For each replayable point, with stamp lag `Lag`, video delay `V`, one-way network `N`:

1. **Bounce.** `bounce = T - Lag`. `Lag` = 2.0 s primary (tier-0 primary); 1.0 s and 3.0 s sensitivity. It
   is not measured; it is the tier-0 assumption.
2. **CV call lead.** Drawn from the tier-0 own-camera model (`own120`), as `src/tier0.simulate` does it: the
   point ends with an out ball with probability 0.4125 (Match Charting Project, women, 2020s); an out ball is
   called early at lead L = the longest lead whose monotone recall covers the draw, L ∈ {100, 50, 25, 0} ms
   (probabilities 0.146 / 0.122 / 0.195 / 0.122; leads of 150-200 ms fail the model's 0.95 precision rule
   and are not used); out balls not called early and every other ending are called at the bounce (lead 0).
   So lead ∈ {0, 25, 50, 100} ms and is > 0 on about 19 % of points. Variant: lead = 0 on every point.
3. **Call.** `frame = bounce - lead` (the instant shown in the frame the call is made on);
   `call = frame + V + 0.020 s` (20 ms inference). `V` ∈ {0, 0.5, 1.0} s; **1.0 s is the headline**
   (assumed licensed feed, glass-to-glass).
4. **Direction.** Buy the token of the official point winner. A wrong call (buy the point loser's token)
   happens when a seeded uniform is ≥ 0.95 (call precision 0.95, as specified; the tier-0 per-lead blend is
   0.948 on WTA points). Wrong calls are traded and shown like any other call.
5. **Reference ("stale") price.** The called token's best ask in the book at
   `t_ref = min(frame, call - N)`, i.e. the price on the screen when the ball landed, as the trader could
   have seen it by the time of the call (no look-ahead). The call is **skipped** if at `t_ref` the token has
   no bid or no ask, its spread is > 5c, or its best ask is outside [0.05, 0.95] (the tier-0 trading zone).
6. **Order.** A fill-and-kill marketable BUY of the called token, `limit = reference ask + 0.01` (we never
   chase a book that has moved by more than 1c), size = min(the per-match net cap allowance, $1,000 / limit).
   Net cap: |net outcome-0 shares| ≤ 100 per match; a call that reduces exposure may trade up to
   `100 - d·net` shares (the tier-0 `_net_cap` rule). A call with allowance 0 is `blocked (net cap)` and no
   order is sent.
7. **Timing.** The order reaches Polymarket at `arrive = call + N`; `N` = 67 ms (Florida, measured median
   one-way, headline) or 2 ms (London co-location, sensitivity). It executes at `exec = arrive + 1.000 s`
   (the venue's taker delay on these markets).
8. **Fill.** Walk the called token's asks in the real recorded book at `exec`, cheapest first, taking levels
   priced ≤ limit until the size is filled. Status `filled` (or `partial`), else `missed (book already
   moved)` when the best ask at `exec` is above the limit (or the ask side is empty). The rest of the order
   is cancelled. Our fills do not change the recorded book (we take at most a few hundred shares).
9. **Fee.** 0.05 × q × (1 - q) per share at each level's price q.
10. **P&L.** *Hold*: each filled share pays 1 if its player won the match (from `market_resolved`), else 0;
    P&L = payout - price - fee. *Mark*: the called token's mid (best bid + best ask)/2 in the book at
    `exec + 30 s`; P&L = mid - price - fee.
11. **Did we beat the book?** For points with a matched reprice, `t_book_srv = t_book - L_recv` (m1's
    `t_book` is on the local receive clock). A call "beats the book" if `exec < t_book_srv`.

Recorded per point: bounce, frame, call, arrive, exec, t_book_srv (UTC ISO), lead, called side, correct or
wrong call, reference ask, limit, best ask at exec, status, shares, VWAP, fee, payout, hold P&L, +30 s mid,
mark P&L, net position after the call.

## 5. Cells and seeds

* **Headline cell:** V = 1.0 s, Lag = 2.0 s, model lead, Florida 67 ms, seed 0.
* **Reported cells:** V ∈ {0, 0.5, 1.0} × Lag ∈ {1.0, 2.0, 3.0} × lead ∈ {model, 0} × network ∈ {Florida
  67 ms, London 2 ms} = 36 cells, all at seed 0. Every cell is reported; none is selected.
* **Random numbers.** `numpy.random.default_rng(seed)` draws three uniforms per point (ending, lead, call
  correctness) for all 994 points in (match key, point number) order, so the draws do not depend on coverage
  or on the cell, and every cell uses the same draws (paired comparisons). Seed 0 is the shown replay.
* **Seed robustness (supplement):** seeds 0-19 for V ∈ {0, 0.5, 1.0} at Lag 2.0, model lead, Florida;
  mean ± SD over seeds of the pooled totals.

## 6. Statistics

Per match and pooled over the 9 matches, per cell: official points, replayable points, calls (not skipped),
orders (not blocked), fills, fill rate = fills / orders, correct-call and wrong-call fills, calls that beat
the book (and the share of calls with a matched reprice), shares, $ deployed, **per-share net P&L in cents
(hold and +30 s mark) with a match-clustered bootstrap 95 % CI** (10,000 resamples of the matches that have
at least one fill, seed 0; per-share = Σ P&L / Σ shares within each resample), **$ P&L** (hold and mark), and
**win rate** = share of fills with P&L > 0 (hold and mark).

Consistency check: compare the direction and rough size of the V = 0 / 0.5 / 1.0 results with the latency
sweep's headline reading (IS +1.10 / +0.61 / +0.40c per share; burned OOS +0.58 / -0.02 / -0.38c; fill rate
about 25 / 11 / 8 %). The trade sets differ (the sweep trades historical ≥ 4c jumps; this replay calls
every official point), so only the mechanism (fills only when the order beats the reprice, decline with V)
is compared, not the levels.

## 7. Rules for the write-up

* Every output carries the label at the top of this file. Never say we received or watched match video.
* No parameter is chosen from these results; every value above comes from the tier-0 model or the task.
  Any change made after P&L is seen is listed in `RESULTS.md` under "Deviations from the protocol".
* State plainly: one day, 9 matches, small sample; illustration plus consistency check, not new evidence.
* The live recordings of 2026-10-03 are forward data; their use here is logged in `results/oos_peeks.log`.

Code: `scripts/match_replay.py`. Outputs: `results/replay/replay.json`, `results/replay/points.csv`,
`research/replay/RESULTS.md`.
