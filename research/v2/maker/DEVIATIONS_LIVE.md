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
  each level. Nothing fills if the asks have moved above the limit. (Since 20:48 UTC the book used is the venue
  book at t_exec, waiting for the socket's clock under lag: L12.)
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
  challenger}, with "doubles" not in the title. (Until 20:48 UTC only the first 100 open tennis events were read:
  L11.) Only the moneyline and the six quoted side types are subscribed.
- **Websocket subscription.** At most 400 tokens per socket, with the two tokens of a market kept together. A PING
  goes out every 10 s; a socket silent for 45 s is replaced. L is updated from PING→PONG as PREREG 3.3 says.
- **Starting capital.** $10,000 per book, for the dashboard's equity line only. Position sizes come from the frozen
  $250 / $2,000 rule.

---

# Deviations during the session (timed)

Everything below was written **after** the session in PREREG 3 had started (19:58:42 UTC). Each entry is a
deviation, with its time. No constant of maker v1 changed: b_T, λ, 4c, the 600 s / 120 s / 30 s windows, 20%,
$250, $2,000, the price band, the rebate and hold-to-resolution are as frozen.

**Why.** An audit of `scripts/live_paper.py` (2026-10-03, about 20:30 UTC) found the three bugs below. Two of them
change how paper fills are counted, so the running session was stopped and restarted on the fixed code (L14).
**State when stopped:** no quote had been placed, no fill or taker order had happened in any book, and no
universe match had been in play since the start. Nothing in the old session's results is replaced.

## L11. Discovery read only the first 100 open tennis events (fix committed 20:47:54 UTC, 2c63112)
**The bug.**
- `gamma_universe()` asked Gamma for `limit=200` and stopped on a page shorter than 200.
- Gamma caps `/events` pages at 100 rows, so every discovery poll read one page: 100 of about 455 open tennis
  events, in Gamma's id order.
- At about 20:50 UTC, with the [now − 8 h, now + 16 h] window, the old code found 15 universe events and the fixed code
  finds 33. The 18 it missed include Zverev–Djokovic and Medvedev–Cerundolo (China Open), Lehecka (Japan Open),
  Charaeva–Kartal, 12 Wuning 3 Challenger matches, Bari and Porto 2. (The audit, at 20:30, found 16 of 34.)
- This broke PREREG 3.2: the session universe would have depended on Gamma's id ordering. The "14 matches between
  02:00 and 11:00" in SESSION.md came from the truncated page.

**The fix.**
- Request `limit=100` and advance the offset by the rows actually returned.
- Stop only on an empty page, or on a page with no new event id. Event ids are de-duplicated.
- A page that fails after its retries raises, so discovery never updates from a partial list. The poll is logged
  as `discovery_error` and retried in 120 s.
- Each `discovery` event now logs `gamma_pages` and `gamma_events`. The first poll of the restarted session read 5
  pages and 453 events.
- Unit test: `test_gamma_universe_pages_past_a_100_row_cap` mocks the 100-row cap, a server that ignores offset,
  and a failed page.

## L12. CTRL-taker timer priced orders on a stale local book under feed lag (fix committed 20:47:54 UTC, 2c63112)
This changes the fill model of the control book. CTRL-taker is not pre-registered (L6).

**The bug.**
- A taker order executes at the first message for its market stamped after t_exec, or else on a timer at
  t_exec + 2 s.
- The timer used whatever book the engine held at that moment. When the feed lagged by more than 2 s, venue
  changes stamped before t_exec had not arrived yet, so the order met an out-of-date book.
- Hour-13 replay of `data/live_v2`: a recorder lag episode ran from 13:18:10 to 13:20:09, with rt − ts up to 48.8 s.
  - oid 2892 filled at a VWAP of 0.7852 against a stale book. The venue book at t_exec gives 0.7223.
  - oid 3029 filled at 0.7534 against a stale book. The venue book at t_exec gives 0.6355.

**The fix.**
- On the timer, the order executes only once the socket that carries its market has delivered a venue timestamp
  ≥ t_exec + 1 s. Delivery is in order per socket, so every book change stamped ≤ t_exec has then been applied.
  The 1 s margin covers small cross-market disorder on a socket.
- Until then the timer re-arms every 500 ms. The engine counts each re-arm as `texec_rearm`.
- A message on the order's own market stamped after t_exec still executes the order before that message is
  applied, as before.
- If no such timestamp arrives within 600 s, the order is voided and logged as `taker_void`.
- **Recorder files.** They carry no socket id and mix several sockets with very different lags: during that
  episode the minimum lag stayed at 62 ms while other sockets reached 48 s. There the clock is the market's own:
  its own next change or trade. If the market stays quiet for 600 s, the order executes on its unchanged book,
  logged with `how = "timer: market quiet 600 s"`.
- Every fill and miss now records `how`, which is book, timer, gap, or quiet.

**Result on the hour-13 replay** (`replay_20261003T204340Z`):
- oids 2892 and 3029 now fill at 0.7223 and 0.6355, which matches the audit's independent rebuild of the venue
  book.
- The other 42 CTRL-taker outcomes are unchanged. CTRL-taker P&L for the hour moves from −$358.02 to −$304.10.
- The four maker books are identical.

**Tests:** `test_taker_timer_waits_for_venue_clock_under_feed_lag` and
`test_taker_timer_live_socket_dead_voids_and_recorder_quiet_executes`.
`test_taker_control_pays_latency_and_delay` now advances the market's clock past t_exec.

## L13. Socket gaps and feed lag were not accounted for (fix committed 20:47:54 UTC, 2c63112)
This changes the maker fill model: quotes are pulled during a gap.

**The bug.**
- After a socket dropped and reconnected, resting paper orders on its markets stayed active with their old queue
  position. Trades during the gap were never seen, so any fills in the gap were lost without a record.
- A pending taker order could execute on the stale pre-gap book once the reconnect snapshot arrived.
- Feed lag (rt − e) was not recorded at all.

**The fix (all paper; nothing is sent anywhere).**
- **Gap input.** A socket error is now an engine input (`gap`, raw-logged, so a replay reproduces it). It is
  posted once per gap.
- **Maker quotes.** Every live maker quote on that socket's markets is treated as pulled at the last venue
  timestamp seen on the socket + 1 ms. Each one is logged as `cancel` with `why = "feed gap"` and counted in
  `gap_cancels`. No fill is counted from a queue we could not observe.
- **Pending taker orders.** One whose t_exec the socket clock already covers (+1 s) executes. The others are
  voided (`taker_void`, "feed gap before t_exec").
- **While the socket is down.** No new quote or taker order is placed on its markets
  (`place_skipped_gap`, `taker_skipped_gap`).
- **When data returns.** The first message on the socket closes the gap (`feed_gap_end`). The strategy re-quotes
  from the fresh book at the back of the queue. As before, the in-play prints for the gap are back-filled from
  data-api for the signal only (L4).
- **Lag record.** Feed lag rt − e on price changes and trades is logged per socket:
  - per-minute quantiles (`lag`: n, p50, p90, p99, max);
  - episodes (`lag_episode_start` and `lag_episode_end`, from lag > 2 s until it is back under 0.5 s), each with
    the paper orders live on that socket's markets at its start.

  `summary.json` carries `feed_gaps` and `feed_lag`. Under lag, with no gap, orders stay live and fills are still
  computed in venue-time order. Our own decisions (placements and cancels) happen at seen time, so they are
  correctly late.
- **Test:** `test_feed_gap_pulls_quotes_and_voids_takers`.

## L14. Stop and restart of the session (20:48 UTC)
**Old session.**
- PID 65274, run `20261003T193534Z`. SIGTERM at **2026-10-03 20:48:00.72 UTC**, and the process exited at
  20:48:02 UTC.
- From the 19:58:42 start to the stop it placed 0 quotes, 0 fills and 0 taker orders in every book.
- Kept unchanged:
  - `results/live/session_20261003T193534Z.jsonl` and `results/live/session_20261003T193534Z_summary.json`;
  - `data/live_maker/raw_20261003T193534Z.jsonl.gz`;
  - its stdout log, moved from `session.log` to `results/live/session_20261003T193534Z.log`.
- Its exit marker `results/live/FINAL` was renamed to `results/live/STOPPED_20261003T193534Z`. A dashboard
  therefore does not read a stopped session as finished.

**Code.** The fixes were committed as `2c63112` before the restart. `scripts/live_paper.py` sha256 is
`73953c8e8f669af6b5f5bd8aacd6c335274dd639da6c65e664424600562f18ff`. The 20 unit tests pass.

**New session.**
- Restarted with the same command at **2026-10-03 20:48:12 UTC**: PID 2001, run `20261003T204812Z`.
  `caffeinate -i -w 2001` runs as PID 2114.
- The warm-up runs again from scratch, as PREREG 3.1 requires. `session_start` is written to
  `results/oos_peeks.log` when the warm-up passes.
- At the restart no universe event started within the 3 h discovery window. The first matches, at 02:00 UTC on
  2026-10-04, enter it at 23:00 UTC, so warm-up trades start then.
- Quoting still stops at 2026-10-04 11:30 UTC.

**Replays.** B2 replays of the new raw log use the fixed engine. The old session placed no order, so it has nothing
to re-price.
