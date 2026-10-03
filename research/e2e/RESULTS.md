# End-to-end timing proof: a frame becomes an executable order in 2.1 s with a 1 s feed

**Label (applies to every number here): paper; order not sent; CV call on our own streamed footage mapped to a
live tennis market for timing (different sport); feed baseline 1 s is simulated (licensed feed not purchased).**

Organiser feedback: "since you need < 3 s latency data, prove you can make trades that soon." This run does the
whole path once per call and stamps every stage on one clock. Our own held-out clip is streamed over WebRTC
into the CV engine. Each MISS call drives the strategy on a live Polymarket tennis book, an unsigned order is
built, and the measured network leg and the market's own order delay are added. The order is then paper-filled
against the live book at the instant it would have become executable. Nothing was signed or sent.

Run `20261003T224404Z`, 2026-10-03 22:44-23:05 UTC, MacBook Air (Apple M4) shared with other jobs (load average 3-18).
Command: `scripts/e2e_proof.sh`. Outputs: `results/e2e/trace.jsonl` (every call, every stamp), `summary.json`,
`fig_waterfall.png`, `e2e_timeline.mp4`.

## The sentence

**Paper:** "On our own held-out clip streamed over WebRTC, each of 24 MISS calls became an unsigned, order-ready
Polymarket payload 54 ms after the frame was captured (p50; p99 72 ms). With the measured network leg (RTT/2,
65 ms p50) and the venue's 1 s order delay added, it was executable on two live tennis books 1.12 s after
capture (p99 1.22 s). With a simulated 1 s licensed feed in front, that is 2.12 s after the point (p99 2.22 s,
worst 2.24 s), inside the 3 s requirement in 24 of 24 calls, but 0.6-1.1 s after the book's typical reprice
(paper; order not sent; different sport; feed simulated)."

**Deck:** "Frame to order-ready: 54 ms. Point to executable order with a 1 s feed: 2.1 s, 24 of 24 under 3 s.
Our pipeline is under 3% of that; the 1 s feed and the venue's 1 s order delay are the other 94%."
Footnote: paper, order not sent; our own table-tennis footage mapped to a live tennis book for timing; the 1 s
feed is simulated.

## What ran

```
data/vision/test_2_copyts.mp4 (OpenTTGames test_2 frames 2000-2999, held out; our own footage, not a match feed)
 -> engine.webrtc.sender: paced virtual camera, frame code under the picture, x264 zerolatency, WHIP
 -> MediaMTX on 127.0.0.1 (engine/webrtc/mediamtx.yml, ports moved to 8899/8199/8564 for this run)
 -> engine.webrtc.whep_reader.WhepFrameSource: aiortc WHEP, marker-bit frame completion, decode, code read back
 -> engine.vision.stream (unchanged): BlurBall on CoreML GPU, tracker, frozen call model -> CallEvent
 -> engine.strategy rule on the LIVE book (fair-value jump, edge after half spread, tick and fee)
 -> engine.risk RiskManager.approve -> unsigned order payload (CLOB order fields, signature null) = order_ready
 -> + RTT/2 of a keep-alive GET https://clob.polymarket.com/time issued at order_ready = network_arrival
 -> + the market's Gamma secondsDelay (1 s) = executable
 -> engine.execution.paper: walk the live book as of its last update stamped <= executable, taker fee
```

- **Stream.** Every source frame was sent, at 10 frames/s of wall time (slow motion, as in `research/webrtc`).
  This laptop's engine sustains about 9-18 fps, so a real-time 120 fps stream backs up without bound. At
  10 fps nothing queues, so each stage time is processing time. The production reference for the CV stage is
  the NVIDIA L4 at a real 120 fps, below.
- **Passes.** The clip was repeated 12 times, alternating between the two markets. That gave 132 CallEvents:
  24 MISS (2 per pass, flights 2760 and 2819) and 108 BOUNCE (no trade by design). No frame was lost in any
  pass; the engine ran at 9.3 fps sustained with 0 frames skipped.
- **One clock.** Every stamp is on `time.monotonic()` (mach_absolute_time). The imported modules (sender,
  receiver, engine, feed) write `time.time()`. Those stamps are mapped onto the monotonic clock with the
  wall-minus-monotonic offset, sampled at 10 Hz (12,641 samples). The offset moved 3.75 ms over the 21 min run
  (NTP slew); each stamp uses the nearest sample, 100 ms away at most.
- **Market rule, fixed before the run.** Gamma tennis events; singles moneylines of ATP, WTA or Challenger
  that accept orders (no doubles, because the fair-value model is the singles Markov model). In-play markets
  rank first, then markets starting within 24 h; within each group, by Gamma `liquidityClob`. The first ones
  with a two-sided book on the public websocket are taken.
  - At 22:44 UTC, 35 markets were eligible and none was in play, so the rule took the two most liquid
    upcoming books:
    - `atp-munar-jacquet-2026-10-03` (start 02:00 UTC, liquidityClob $134,628, book 0.57/0.58)
    - `atp-hurkacz-khachan-2026-10-03` (start 05:00 UTC, $98,097, book 0.41/0.42)
  - Both have `secondsDelay` 1. Each got 12 MISS calls.
- **Network leg.** A dedicated keep-alive connection fires `GET /time` the moment the order is ready (the
  probe started a median 0.09 ms after `order_ready`). One-way = RTT/2. A background series on a second
  connection, once a second, gives the run's distribution.

## Stage times (24 MISS calls; ms, p50 / p90 / p99)

| stage | from -> to | p50 | p90 | p99 |
|---|---|---|---|---|
| sender: frame into the encoder | capture -> frame_sent | 2.2 | 4.5 | 15.2 |
| x264 encode + WHIP + MediaMTX + RTP in | frame_sent -> frame_received | 6.4 | 10.3 | 13.8 |
| H.264 decode + handoff | frame_received -> decoded frame in our code | 1.1 | 2.1 | 3.7 |
| frame prep + queue + detector (CoreML GPU) | -> detected | 39.9 | 45.1 | 47.5 |
| tracker + features + classifier + call rule | detected -> call_emitted | 2.4 | 4.7 | 5.2 |
| strategy rule on the live book | call_emitted -> decision | 0.09 | 0.17 | 0.27 |
| risk check | decision -> risk_checked | 0.03 | 0.09 | 0.13 |
| unsigned order payload built | risk_checked -> order_ready | 0.015 | 0.03 | 0.06 |
| **our pipeline, capture -> order ready** | | **54.1** | **66.8** | **71.7** (max 72.8) |
| network one-way, RTT/2 measured at order ready | order_ready -> network_arrival | 64.5 | 68.9 | 158.2 (max 181.5) |
| venue order delay (`secondsDelay`) | network_arrival -> executable | 1,000 | 1,000 | 1,000 |
| **capture -> executable** | | **1,118.6** | **1,136.2** | **1,218.5** (max 1,240.6) |

Other spans:
- **Capture -> call:** 54.0 / 66.6 / 71.5 over the 24 MISS calls; 51.8 / 69.7 / 85.9 over all 132 calls.
- **Video leg (capture -> decoded frame in our process):** 9.4 / 18.4 / 24.8.
- **Call -> order ready:** 0.145 / 0.29 / 0.38. The trading half of the path is under half a millisecond.
- **Engine detail at the call frames:** CoreML detector 33.4 ms p50, normalise 2.2, queue wait 3.1,
  classifier 1.7, features 0.7.
- **Effect of load.** Passes 0-5 ran at load 3-5 and gave capture -> order ready of 44.3 ms p50. Passes 6-11 ran
  at load 9-18, because other jobs started, and gave 61.0 ms p50. The detector carries about half of the difference
  (decoded -> call 37.4 vs 45.7 ms).
- **RTT to clob.polymarket.com (Gainesville -> Cloudflare MIA -> venue).** Background series: 129.5 / 138.1 /
  207.9 ms (n = 1,147). Probes at order ready: 129.0 / 137.7 / 316.5. The measured one-way of 64.5 ms matches
  the 67 ms `FLORIDA_MS` constant the backtests use (`src/paper.py`).

## The budget against "< 3 s" (p50 over the 24 calls, per-call totals for the tails)

| | feed (simulated) | ours | network | venue | **total after the point** |
|---|---|---|---|---|---|
| laptop CV, measured | 1,000 | 54.1 | 64.5 | 1,000 | **2,119 ms** (p90 2,136, p99 2,218, max 2,241) |
| L4 CV (production reference) | 1,000 | 16.4 | 64.5 | 1,000 | **2,081 ms** |

- **Requirement.** 24 of 24 calls are under 3 s. The margin is 881 ms at p50 and 759 ms for the worst call.
- **Reprice.** The book typically reprices 1.0-1.5 s after the point. That band rests on two things:
  - Measured: the book moves a median 1.16 s before the official point stamp (482 live WTA points,
    `research/v2/latency`).
  - Not measured: the stamp's own lag after the physical point. It is 2.0 s assumed in tier-0 and 3.14 s
    inferred, and the calibrated stamp reading puts the reprice 1.35 s after the bounce (an inference).

  With a 1 s feed, the order becomes executable 0.6-1.1 s **after** that reprice, so on a typical point the
  stale depth is gone by then. Without the feed delay (a camera at the court) the order is executable 1.12 s
  after the point, inside the band.
- **Where the time goes.** Our own pipeline is 54 ms of the 2,119 ms (2.6%). The network is 65 ms. The feed
  and the venue's order delay are the other 2,000 ms (94%). Neither of those two is ours to cut: the venue
  holds every marketable order for `secondsDelay`.
- **L4 row.** It is the measured video leg (9.4 ms) plus the L4's emitted-call latency at a real 120 fps
  (6.92 ms p50, 169 calls) plus the measured call -> order ready (0.15 ms). The L4 numbers come from
  `results/engine/online_vs_offline.json`: whole held-out test set, 0 frames dropped, frame -> decision p50 4.62 /
  p90 6.94 / p99 12.19 ms. `results/engine/vision_bench_gpu.json` gives the demo clip at 120 fps: frame ->
  decision 5.46 / 7.84 / 15.64 ms, emitted calls 7.08 ms p50. Swapping the laptop for the L4 saves 38 ms
  of 2,119.
- **Tier-0 context (stored cells, quoted, not re-run).** These come from `results/tier0/latency_sweep.json`, a
  counterfactual on assumed data: the licensed feed and video were not purchased, and burned OOS is not blind.
  - The `video_own120` cells at V = 1.0 s (a 1 s video feed):
    - With the 2.0 s stamp lag: IS $14.8/day, 0.40c/share, 13.8% of calls before the reprice; burned OOS
      $4.4/day, -0.38c/share.
    - With the calibrated 3.14 s lag: IS $94.4/day, 1.11c/share; burned OOS $56.6/day.
  - That sweep assumes 20 ms inference and its region-aware order path. Our measured equivalents from this
    laptop are 54 ms and a 65 ms one-way. `research/webrtc` costs the extra CV time on the 1 s row:
    IS $14.8 -> $10.1/day.

## The orders and fills

- **Every one of the 24 MISS calls was a timing probe; the rule itself sent nothing.** The rule said SKIP
  `edge_below_cost` on all 24.
  - On a pre-match book at 0-0 the point swing is about 3c, so E[move] is 1.35c.
  - The cost is half the spread (0.5c) plus the tick (1c) plus the fee (1.2c), which gives an edge of -1.33c
    to -1.36c.
  - The risk check said `edge_below_fee` on 22 calls. On 2 calls (pass 4) it said `kill:latency`: the feed
    delay was 460-536 ms, above its own p95 baseline.

  The probe payload is the order the rule would have built: BUY of the called winner's token, limit = stale
  ask + 1 tick, v2 risk-parity size capped by the depth inside the limit and the 100-share net cap (100 shares
  every time). It is labelled `timing_probe` in the trace, with the rule's and the risk check's verdicts.
- **Fills.** All 24 probes filled 100 shares at the ask seen at order ready (0.0c slippage, $29.23 of fees in
  total). Both books were quiet pre-match: the last update before the executable instant was a median 16 s
  earlier, and no venue message arrived in the second after any order. Every fill was therefore priced by the
  quiet-book timer, which fills once local time passes t_exec + the feed's p95 delay. **A quiet pre-match book
  cannot show the race against a reprice.** That race needs an in-play book at a real point, and the tier-0
  and match-replay studies measure it on recorded in-play books.
- **Feed.** The public market channel delivered 2,884 messages; 2 of 26 venue snapshots disagreed with our
  rebuilt book. Feed delay (local receive minus venue stamp) was p50 67 ms but p95 394 ms and p99 657 ms over
  the run. In the call windows, price_change delays were p50 67 / p90 88 ms. The feed shared one Python process
  with the CV engine and the WebRTC receiver on a loaded laptop, so in production the book belongs in its own
  process (the GIL lesson in `engine/README.md`). That tail is also what tripped the latency kill switch twice.

## What this does and does not show

- **Shows.** The whole path runs end to end on one clock: a captured frame becomes an order ready to send in
  54 ms on a laptop (about 16 ms with the L4 CV), against real live books. The network leg is measured at the
  moment of each order. With the venue's own delay and a 1 s feed in front, the order is executable 2.1 s after
  the point, under 3 s on every call, with 0.76-0.90 s to spare.
- **Does not show.**
  - **An edge.** The rule declined every call, and the call is a table-tennis call mapped onto a tennis
    match's book for timing only.
  - **A real feed or camera.** The 1 s feed is simulated. Capture is the paced sender's frame time, so camera
    exposure, a relay off this laptop and a licensed feed's own delivery are not in the measured part.
  - **The venue's matching time.** RTT/2 of `GET /time` stands in for the order path. A signed POST would
    add the venue's validation and matching time, which we do not measure because we never send.
  - **In-play behaviour.** No eligible singles match was in play at run time.
  - **A real 120 fps stream on the laptop.** The laptop engine only keeps up with the slowed stream; the L4
    numbers are the real-time reference.

## Reproduce

```bash
scripts/e2e_proof.sh                                  # ~25 min: 12 passes, then the figure and the video
PASSES=1 MAX_PASSES=1 MIN_CALLS=0 scripts/e2e_proof.sh   # one pass
RENDER_ONLY=1 scripts/e2e_proof.sh                    # redraw from results/e2e/trace.jsonl
.venv/bin/python -m engine.e2e.e2e_run --summarize-only   # recompute summary.json from the trace
.venv/bin/python -m pytest tests/test_e2e_paper_only.py -q
```

Needs MediaMTX (Homebrew v1.21.1), ffmpeg with WHIP (8.1), `data/vision/test_2_copyts.mp4`,
`models/vision/frozen_call_model.pkl` and access to the public Polymarket endpoints (Gamma, the `market`
websocket and `GET /time`). No key or credential is read anywhere. `tests/test_e2e_paper_only.py` checks:
- `engine/e2e` has no order endpoint and no signing library;
- the only request to the venue's REST host is `GET /time`;
- the payload is unsigned and marked not sent.
