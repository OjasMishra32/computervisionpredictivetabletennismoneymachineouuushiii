# Final video: team requirements (binding for the integration pass)

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
