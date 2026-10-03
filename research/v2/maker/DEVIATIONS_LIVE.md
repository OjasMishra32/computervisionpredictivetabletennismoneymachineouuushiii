# maker v1 (B), live paper session: pre-session implementation decisions

Written 2026-10-03, about 19:10 UTC, before the session in PREREG.md section 3 started, and before
`scripts/live_paper.py` placed any paper quote on live data. (A)'s decisions are in `DEVIATIONS.md`, which another
workflow owns; this file covers only (B). No constant of maker v1 is changed here: b_T, λ, 4c, the
600 s / 120 s / 30 s windows, 20%, $250, $2,000, the price band, the rebate and hold-to-resolution are as frozen.

What was looked at before writing this:
- Public docs and the live Gamma/CLOB API (`VENUE_RULES.md`).
- Recorded websocket data in `data/live_v2` (hours 13 and 17 UTC), read only for message ordering. This read is logged in
  `results/oos_peeks.log` at 18:47 UTC.
- One 1-hour engine replay of `data/live_v2` (12:00–13:00 UTC, with 11:23–12:00 as history). It checked that the
  code runs and is logged in the peeks log. It changed nothing below. Its fills were a handful, and no rule or
  parameter was tuned on them.
- Two short live TEST runs, 19:03–19:19 and 19:19–19:35 UTC. Each is logged in the peeks log and labelled TEST.
  - Only two Challenger matches were in play. Their side markets had no in-play print in the last 600 s, so no
    signal turned on: no quote was placed and nothing filled.
  - The tests exercised discovery, the socket, one real disconnect and reconnect, the warm-up check, the bootstrap,
    the start, the stop and the exit.
  - The trade-side check matched 35/35 and 24/24 trades. The median data-api lag was 2.3 s, and only 17 of 35 fell
    inside a raw ±2 s window (see L1).
  - Two bugs were found and fixed, neither a rule change. The raw-log flush call crashed. The bootstrap cutoff used
    the book snapshot's timestamp (see L4).

## L1. Trade-side check (PREREG 3.1): matching window
data-api `/trades` timestamps are block times, in whole seconds. They run about 2–3 s after the websocket's
server timestamp: in the first comparison, a trade stamped 09.061 on the websocket was stamped 12 by data-api.
The repo's blocklag study found a median lag of 1.98 s. A plain ±2 s window would therefore miss many true matches.
- Candidates must have the same market, size and outcome-0 price, with a data-api time 5 s before to 15 s after the
  websocket time. Each websocket trade keeps its closest candidate.
- The offset is the median lag over these pairs. The ±2 s window is then applied **after removing the offset**.
- The count inside the raw ±2 s window is logged too (`raw_2s`).
- The 50-trade and 95% thresholds are unchanged.

## L2. "Trades before book updates in the same millisecond" (PREREG 3.5)
On the venue, the `price_change` that removes a trade's volume from the book arrives **before** the
`last_trade_price` message, not in the same millisecond.

| hour checked | median lead | trades with the book update ≤ 250 ms earlier | ≤ 500 ms earlier |
|---|---|---|---|
| 13 | 27 ms | 98.4% | 98.9% |
| 17 | 28 ms | 98.2% | 98.9% |

Taken literally, the rule would count each trade twice: once when the book update shrinks the queue ahead, and again
when the trade message subtracts its volume. That overstates our fills. The rule's stated intent, "no trade is
counted twice", is implemented like this:
- A shrink in displayed size at our price is first recorded as **provisional**.
- It becomes a settled cancel ahead of us only after 500 ms with no trade at that price.
- A trade at our price computes the queue ahead *without* provisional shrinks, then uses up provisional shrinks for its
  own volume.

This is the conservative reading: the queue ahead is never smaller than under the literal rule. Unit tests:
`tests/test_live_paper.py::test_queue_ahead_and_trade_before_book` and `::test_cancels_ahead_shrink_queue`.

## L3. Strict information cut at millisecond resolution
§1.4 uses prints with ts **strictly** before t − d. With millisecond timestamps, a print at e therefore takes effect at
max(e + d + 1 ms, s(e) + L). PREREG 3.3 writes this as max(e + d, s(e) + L).

## L4. In-match history from data-api (PREREG 3.1)
- Bootstrapped prints are moved onto websocket time by subtracting the L1 offset.
- A market keeps only bootstrapped prints older than the moment we first received a websocket message for it, which
  is its subscription time. The book snapshot's own timestamp is not used, because it is the book's last change and
  can be hours old. This keeps prints from being double counted.
  A print is also dropped if a print within ±3 s already has the same size and price.
- Events whose markets were all subscribed before the scheduled start are not bootstrapped, because the socket has
  their whole in-play history.
- After a socket reconnect with a gap longer than 3 s, the gap is back-filled the same way.
- Every bootstrap and back-fill payload is written to the raw log as an engine input, so a replay reproduces it.

## L5. End of the in-play window, live
- Live, the end time comes from Gamma `finishedTimestamp` / `closedTime`, which discovery checks every 120 s, or from
  the moneyline's `market_resolved` message on the socket, whichever comes first.
- Once the end is known, later prints are dropped from the state. Fills that happened before we knew the end still count.
- Until then, the window is start + 6 h (§1.1).

## L6. Control book CTRL-taker (not pre-registered; descriptive only)
This book was added before the session as a control, at the workflow's request. It shares no state with the maker
books and is not part of any PREREG comparison. It shows what the same signal earns when traded as a taker at our
real latency.
- **Trigger.** It uses the real-time signal (B1-rt's view). It fires when the state turns on or flips for a side
  market.
- **Order.** A marketable buy of the favoured outcome is decided at seen time s:
  - limit = the implied fair price of that outcome, floored to 1c;
  - size = min($250, remaining match budget) / limit, in shares, and at least `orderMinSize`.
- **Execution.** The order reaches the venue at s + L. The venue holds it for d (`secondsDelay`, 1 s). It then walks
  the ask levels of the live book as they stand at that moment, up to the limit, and pays C × fee_rate × p(1 − p) at
  each level. Nothing fills if the asks have moved above the limit.
- **Cap.** $2,000 per match. Hold to resolution.
- **Reported.** The ask seen at decision time, the execution VWAP, slippage, and misses.

## L7. Replays of recorder files
The `data/live_v2` and `data/live` recorders did not store the Gamma venue fields. Replays of their files therefore use
the values Gamma showed on all 2,059 open tennis markets on 2026-10-03 (`VENUE_RULES.md`): secondsDelay 1, fee rate
0.05, rebateRate 0.15, orderMinSize 5. Replays of the session's own raw log (B2) use the logged Gamma values.

## L8. Session end
- Quoting stops at `--until`, 2026-10-04 11:30 UTC.
- The process then waits up to 4.5 h for resolutions (to 16:00 UTC, PREREG 3.1). It polls Gamma every 120 s and
  listens for `market_resolved`.
- Whatever is still unresolved is marked to the token mid, or the last trade if the book is one-sided, and labelled.

## L9. Raw log
`data/live_maker/raw_<run>.jsonl.gz` holds:
- every websocket frame, with its socket receive time `rt`, the engine drain time `w` and the latency `L` in force;
- every other engine input (Gamma meta, data-api prints, Gamma resolutions, latency updates, start and stop), in
  the order the engine took them.

`--replay data/live_maker/raw_<run>.jsonl.gz` re-runs the session item for item. With `--clock server`, seen time is
e + L (B2 in PREREG 3.6).

## L10. Details the PREREG leaves open (no rule changed)
- **Our order is not in the displayed book.** If every other order at our price leaves, the displayed best bid drops
  and we re-peg down to it. Staying alone above the displayed best would be improving, which §3.4 rules out.
- **Rounding.** Order sizes are in 0.01-share steps; fills are floored to 1e-6 shares.
- **Discovery window.** Events with Gamma `startTime` in [now − 8 h, now + 3 h] and `seriesSlug` in {atp, wta,
  challenger}, with "doubles" not in the title. Only the moneyline and the six quoted side types are subscribed.
- **Websocket subscription.** At most 400 tokens per socket, with the two tokens of a market kept together. A PING
  goes out every 10 s; a socket silent for 45 s is replaced. L is updated from PING→PONG as PREREG 3.3 says.
- **Starting capital.** $10,000 per book, for the dashboard's equity line only. Position sizes come from the frozen
  $250 / $2,000 rule.
