# Final video: team requirements (binding) - REVISED: 75-90 SECONDS, VISUAL SYNOPSIS

**The team decided (2026-10-03 evening): the video is at most 60 s. It is NOT the presentation; the paper and deck carry
the full argument, the IC questions, the pipeline diagram and the latency analysis. The video only shows the model working,
the test, and the profit, in a really cool way.** Voice: ElevenLabs "Liam", energetic, few words (about 110-140 spoken words
total). Fast, punchy editing; music bed with hits on the calls.

Purpose: explain the strategy in ONE sentence, then a very short, highly visual synopsis of the paper that convinces a
skeptic the model actually works. 75-90 s total, wall-to-wall visuals (entertaining, fast cuts, motion graphics), Liam
(ElevenLabs) narrating about 180-220 words. The paper carries the detail.

| time | content |
|---|---|
| 0:00-0:05 | Cold open: one real MISS call in slow motion, "Called 408 ms before contact", title COURTSIDE |
| 0:05-0:12 | **The strategy in one sentence** (Liam + kinetic type): "Our computer vision calls the point before the ball lands, so we trade the Polymarket match price before it reprices." |
| 0:12-0:20 | **The edge exists** (paper sec. 2): animated information-tier ladder + fast tier wins 11/11 months vs late traders losing (alpha chart) |
| 0:20-0:46 | **Two models, shown separately.** (a) TABLE TENNIS model, ~13 s: real held-out match footage (OpenTTGames test games, credited), 2x2 split / montage across several games: thin ball trail, small P(miss) bar, "MISS - n ms early" stamps exactly when the frozen model called them (11/11 correct at 50 ms; honest totals as counters). (b) TENNIS model, ~11 s: clean Apple-style 3D court replay of the spin-aware tracker (scripts/render_hawkeye_video.py style re-rendered minimal: white lines on black, the ball arc, a spin vector and rpm readout, the predicted landing ellipse shrinking onto the line, "OUT - called 200 ms before the bounce" with its margin), with stats from results/spin/tennis/key_numbers.json (landing error 5-8x lower, OUT precision >= 99%, spin error ~7 rpm); label "simulated physics: Hawk-Eye-class camera model". No real tennis broadcast footage (copyright). (c) REAL TENNIS FOOTAGE, ~4-5 s, placed right before (b): results/viz/v60_assets/tennis_real/tennis_tracked.mp4 (freely licensed real rally with OUR tennis tracker's ball trail; attribution from LICENSE.md shown small; no in/out call on it), then cut to (b) for the call. |
| 0:46-0:54 | **The pipeline**: animated boxes feed -> WebRTC -> GPU CV -> fair value -> risk -> order -> network -> Polymarket 1 s delay -> fill, each with measured ms; total vs < 3 s |
| 0:54-1:04 | **What speed is worth**: returns vs feed latency (log axis, dotted 1 s baseline, source bands, break-even), then the edge-decay panel |
| 1:04-1:16 | **The test, shown on a real match**: the showcase match from the multi-month backtest (results/viz/v60_assets/backtest_match/example_match.mp4 + match.json: real Polymarket price path from recent weeks, the model's calls and fills at the simulated 1 s baseline, running P&L; label "example match from the backtest (selected for illustration)" + share of matches profitable), then the full backtest equity curve drawing in (in-sample then out-of-sample, months positive) and rigor badges. Do NOT use the 2026-10-03 replay. |
| 1:16-1:26 | **The profit**: money counters at the simulated 1 s baseline (IS / OOS $/day, Sharpe; both readings compact), equity curve drawing in, capacity one-liner (results/capacity) |
| 1:26-1:30 | End card: COURTSIDE, repo URL, "Paper trading only - simulated 1 s licensed-feed baseline - Voice: AI (ElevenLabs) - footage: OpenTTGames CC BY-NC-SA 4.0" |

**DESIGN: Apple keynote / product-film style. Very clean. No AI slop.** (overrides earlier style notes)
- Canvas: pure black (#000) for most scenes, occasional pure white for data scenes; generous margins (>= 8% of width);
  a strict 12-column grid; one idea per frame.
- Type: Inter (OFL; download from Google Fonts' GitHub into results/viz/v60_assets/fonts/) - Display weights 600-700 for
  hero numbers (very large, tight tracking), 400-500 for labels; white on black, #1d1d1f on white; at most two sizes per
  frame plus the hero number. Do NOT use SF Pro (licence).
- Colour: monochrome + ONE accent (Courtside orange #FF6B1A) used only for our strategy, the call stamp and the dotted 1 s
  line; greys (#86868b) for everything else; red only for losses. No gradients except a subtle vignette on footage.
- Motion: slow, confident easing (cubic in-out, 400-700 ms), fades and gentle scale (0.96 -> 1.0), numbers counting up
  with tabular figures, charts drawing in left to right; match cuts on the ball; no spins, wipes, glitches, shakes.
- Data viz: thin 2 px lines, no gridlines or chart junk, direct labels at line ends, a single axis label line, the dotted
  1 s baseline as the only dashed element.
- Footage: full-bleed, clean overlays only (thin trail, small P(miss) bar, one call label) - no busy sci-fi HUD,
  no particle effects, no neon, no lens flares, no stock imagery, no emoji, no fake UI chrome, no AI-generated images.
- Sound: minimal, warm electronic bed; soft ticks on number reveals; one clean hit per call; Liam clear and upfront.
- Captions: small, clean, bottom-centre, two lines max, fade in/out.

**Stats everywhere (team request): it should read like a paper summary.** A persistent, clean STATS RAIL on the right
third of the frame (or lower band on full-bleed shots) that updates per segment with the key numbers, animated count-ups,
each from the manifest:
- Edge exists: fast tier months positive 11/11; late traders' net c/share; factor alpha t-stat 8.5; R^2 3%.
- Model works: frames tracked, detection within 5 px %, MISS precision (with n), first-call lead median, GPU 120 fps,
  frame->decision 4.6 ms p50; spin: landing error 5-8x lower, spin within ~7 rpm (simulated physics).
- Pipeline: each stage ms and the total vs < 3 s; WebRTC leg ms.
- Speed: Sharpe and $/day at 0 / 0.5 / 1 s; break-even latency.
- Backtest at the simulated 1 s baseline: IS and OOS side by side - $/day, total P&L, Sharpe, per-share net with CI,
  win rate, max drawdown, months positive, trades; both stamp-lag readings (calibrated and pre-registered) shown compactly.
- v2 (edge at fast-tier speed): Sharpe 14.5 IS / 6.7 OOS, +1.38c / +0.60c per share, deflated Sharpe, annualised return/vol.
- Rigor: variants tested, blind tests, OOS looks logged, deflated Sharpe, PBO.
- Capacity: capital at which Sharpe halves / P&L-max size, ADV share (results/capacity).
Big hero numbers (Sharpe, $/day) get a full-screen moment with a count-up and a sound hit. Every number labelled IS/OOS.

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
8. (deck/paper only) **A match from today** replay (results/replay): not in the video.
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
