# Final video: team requirements (binding) - REVISED: 60 SECONDS MAX

**The team decided (2026-10-03 evening): the video is at most 60 s. It is NOT the presentation; the paper and deck carry
the full argument, the IC questions, the pipeline diagram and the latency analysis. The video only shows the model working,
the test, and the profit, in a really cool way.** Voice: ElevenLabs "Liam", energetic, few words (about 110-140 spoken words
total). Fast, punchy editing; music bed with hits on the calls.

Purpose: convince a SKEPTIC in about 60 s that the model actually works, with Liam explaining (ElevenLabs).

| time | content |
|---|---|
| 0:00-0:04 | Cold open: one real MISS call in slow motion, "Called 408 ms before contact", title COURTSIDE |
| 0:04-0:24 | **Proof it works, multiple games**: 2x2 split-screen / fast montage across several held-out real table-tennis games (OpenTTGames test_1..test_7, credited): ball comet trail, predicted arc, live P(miss) gauge, "MISS - n ms early" / "IN" stamps exactly when the model made them (results/engine/online_events_L4.jsonl, cv_showcase logs); live counters with the honest totals (frames tracked, detection accuracy, calls, precision; results/engine/online_vs_offline.json, results/tracking/summary.json) |
| 0:24-0:34 | **The pipeline**: animated boxes feed -> WebRTC -> GPU CV -> fair value -> risk -> order -> network -> Polymarket 1 s delay -> fill, each with measured ms (results/e2e, results/engine/vision_bench_gpu.json: 120 fps, 4.6 ms; results/webrtc) and the total vs the < 3 s requirement |
| 0:34-0:46 | **The latency graphs**: returns vs feed latency (log axis, dotted 1 s baseline, source bands, break-even), then the edge-decay panel (edge vs seconds after the move: fast tier vs everyone else) |
| 0:46-0:57 | **The test and the profit**: today's real Polymarket match replay (orders racing the book; "backtest replay, assumed 1 s licensed feed") then money counters at the simulated 1 s baseline (IS / OOS $/day and Sharpe, both readings compact) with the equity curve drawing in |
| 0:57-1:00 | End card: COURTSIDE, repo URL, "Paper trading only - simulated 1 s licensed-feed baseline - Voice: AI (ElevenLabs) - footage: OpenTTGames CC BY-NC-SA 4.0" |

The material below (presentation structure, IC framing) now applies to the DECK and PAPER, not the video.

---

Voice: ElevenLabs "Liam" (scripts/tts_elevenlabs.py). Length about 3:00-3:30. Structured like a team presentation video:

1. **Title** (COURTSIDE, team, Gator Quant Hacks 2026, Systematic Trading).
2. **The problem**: in-play tennis on Polymarket reprices about a second after each point; whoever learns the point first takes the stale price.
3. **Our idea**: computer vision that knows the point is over before the ball lands.
4. **CV demo, 25-30 s, the centrepiece**: real held-out match footage (OpenTTGames, CC BY-NC-SA 4.0, credited) with the full HUD drawn from logged model output:
   ball detections with a fading trail, the fitted 3D trajectory with spin readout, the predicted landing point and its
   uncertainty closing in, a live P(miss) gauge rising frame by frame until it crosses the threshold, then
   "MISS - called N ms before contact", then a 1/4-speed replay of the same moment. Use results/viz/cv_showcase.mp4,
   results/engine/engine_live_demo.mp4 (the engine making its own calls) and the logged per-frame scores; nothing invented.
5. **The alpha**: fast traders profit every month, the late ones lose; edge decays within ~1-2 s.
6. **Pipeline and speed** (organizer concern: prove we can trade inside the window): WebRTC frame -> CV call -> decision -> order-ready -> measured network -> 1 s venue delay -> fill against a live Polymarket book, stage timings in ms (results/e2e), GPU 120 fps / 4.6 ms (results/engine/vision_bench_gpu.json).
7. **Results at the simulated 1 s licensed-feed baseline**: returns-vs-latency curve with the dotted 1 s line and source bands; both readings (calibrated and pre-registered); money counters.
8. **A match from today**: the real Polymarket match recorded live on 2026-10-03 (results/replay): real book, real points, our orders at the assumed 1 s feed racing the reprice, P&L counter. Label: "backtest replay; we have no video of this match; assumed 1 s licensed feed".
9. **Risk and capacity** (organizer concern): capital capacity in $ (results/capacity), limits and kill switches, stress tests.
10. **How it goes live**: license a low-latency feed (Polymarket itself buys official data from Genius Sports); faster feed = further left on the curve.
11. **Close**: repo URL, one command, "Voice: AI (ElevenLabs). Paper trading only."

Hard rules: no footage of matches we do not have rights to (no YouTube/Setka captures); every number from a results file;
CV-strategy results labelled "simulated 1 s licensed-feed baseline"; tennis Hawk-Eye segments labelled "simulated physics".

## Addendum (team, 2026-10-03): pitch it like an investment committee

Frame the whole video (and the deck) as an investment-committee pitch. Every question an IC would ask about the strategy is
answered on screen, with a number and its source:

- **The latency graph, full and clear (must be in the video, ~15 s, held long enough to read):** returns ($/day and Sharpe)
  vs feed latency on a log axis (0.05-60 s), IS and OOS, both stamp-lag readings with seed bands, the dotted 1 s baseline,
  break-even markers, and shaded bands for every real source with its measured/stated latency (venue/official <= 0.15 s,
  licensed betting video 0.5-8 s vendor-stated, sportsbook apps 4-8 s, our measured public WebRTC stream 12.2 s, TV,
  public score feeds 28-44 s measured), plus the market-side decay panel (edge vs seconds after the move). Source:
  results/tier0/latency_sweep.json, research/v2/feed_latency/LATENCY_SWEEP.md, results/decay/*, research/v2/latency.
- **The pipeline diagram (~15 s):** camera/feed -> WebRTC -> GPU CV (detect, track, spin fit, P(miss)) -> fair value
  (Markov point leverage) -> risk checks -> order -> network -> Polymarket 1 s taker delay -> fill vs live book -> hold to
  resolution; each box annotated with its measured ms (results/e2e, results/engine, results/webrtc) and the total vs the
  < 3 s requirement.
- **"IC questions" segment (~25-30 s, fast cards, one per question, answer + number):**
  1. Where does the edge come from and who pays? (slow takers; fast tier wins 11/11 months; factor-neutral t = 8.5)
  2. Why does it persist? (speed costs money; sub-second video is sold only to bookmakers/desks)
  3. How fast do you need to be, and can you trade that fast? (break-even latency; our pipeline ms; < 3 s proof)
  4. How much capital can it run? (capacity in $, Sharpe vs size, ADV share; results/capacity)
  5. What does it cost to run? (feed licence, infra; after-cost break-even; results/financials)
  6. What kills it? (stamp lag unmeasured, queue position vs fast tier, fee changes, shrinking edge -0.17c/month, concentration)
  7. How do you know it is not overfit? (pre-registration, blind tests, deflated Sharpe, PBO, peeks logged)
  8. Is it legal / allowed? (licensed feed only, no courtsiding, paper only per event rules)
  9. What do you need to go live? (licensed low-latency feed, London gateway, one live calibration session for the stamp lag)
- Tone: confident and precise, like a PM presenting to an IC: lead with the answer, then the number.
