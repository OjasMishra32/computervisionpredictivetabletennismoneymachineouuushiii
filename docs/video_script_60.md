# COURTSIDE, the 75-90 s cut: script and shot list

Spec: `research/compliance/VIDEO_REQUIREMENTS.md` (the 75-90 s table at the top, DESIGN, the stats rail and the
red-team addendum). The strategy in one sentence comes first. A short visual synopsis of the paper follows, told as
a skeptic's arc: think it's a gimmick? Watch it call misses on real games. Then the whole pipeline in
milliseconds, what speed is worth, and months of backtest and the profit.

Output: `results/viz/courtside_60.mp4` (1920x1080, 30 fps, H.264 + AAC, faststart, 89.0 s) and
`results/viz/courtside_60.srt`.
Build: `.venv/bin/python scripts/make_video_60.py final`. The script holds the narration lines and stops if this file
no longer carries them word for word. Every number on screen is read from a results file at render time and
listed in `results/viz/v60_assets/manifest.json` (`values`: file, key, value, shown form, segment; `final`: timeline,
audio, sound cues, decisions).

Voice: ElevenLabs "Liam" (`scripts/tts_elevenlabs.synth`, cached in `data/tts_cache`), 220 words. Pauses longer than
0.26 s are tightened and the narration is sped up 8 % (ffmpeg atempo, pitch kept). Under the voice runs the
ElevenLabs music bed, ducked under speech, with one soft hit per call and per hero number and soft ticks on number
reveals. Captions are small, bottom-centre and one line where possible.

## Narration (Liam), matched to the nine segments of the spec

| # | time | segment | Liam |
|---|---|---|---|
| 1 | 0:00-0:05 | cold open | That ball's going out. The model called it 325 milliseconds early. |
| 2 | 0:05-0:11 | the idea (one sentence) | Our computer vision calls the point before the ball lands, so we trade the Polymarket match price before it reprices. |
| 3 | 0:11-0:21 | the edge | Polymarket prices each match from zero to a dollar, a player's chance to win, and reprices about a second after each point. The fastest traders won eleven months of eleven. |
| 4a | 0:21-0:33 | the models: table tennis | Think it's a gimmick? Watch it call misses on real games it never saw. A miss call means it knows the ball is out before it lands. Not one was made on a ball labelled in. |
| 4b | 0:33-0:37 | the models: real tennis | Same tracker, real tennis. |
| 4c | 0:37-0:45 | the models: tennis, spin | Add spin: landing error drops five to eight times. Out, called 200 milliseconds before the bounce. |
| 5 | 0:45-0:55 | the pipeline | Here's the whole pipeline in milliseconds: our part, about fifty. Add a one-second feed and Polymarket's one-second delay: 2.1 seconds. Under three. |
| 6 | 0:55-1:03 | what speed is worth | Here's what speed is worth: every second costs money; by three seconds, every version loses. The edge halves within a second. |
| 7 | 1:03-1:12 | the test | Here's months of backtest, on one real match: every fill on the real price path. 59 percent of traded matches made money. |
| 8 | 1:12-1:25 | the profit | And the profit, at a simulated one-second feed, post-hoc estimate: 94 dollars a day, Sharpe 12: return per unit of risk, above two is very good. On data it never saw: 57 a day. |
| 9 | 1:25-1:29 | end card | Courtside. Paper trading only. |

Segment lengths come from the measured narration and the spec's minimums; the script caps the total at 89.6 s.

## What is on screen

The canvas is pure black, with white for the speed chart. Type is Inter (OFL, `results/viz/v60_assets/fonts/`). Every
frame has a small chapter title at top left and the honesty label at top right. A stats rail sits on the right third
(on full-bleed footage it becomes a lower band). Orange #FF6B1A marks only our model and strategy: the call stamps,
the predicted path, the tennis landing region and the dotted 1 s line. Red marks losses only.

| segment | picture | stats rail / band | label on screen |
|---|---|---|---|
| cold open | test_2, flight 2819: the engine's own MISS call at its exact frame, real time then ¼ speed. Shows a thin ball trail, the engine's predicted path, a small P(miss) bar, and the stamp "MISS · called 325 ms early". The outcome tick reads "passes the end line". Then the title COURTSIDE. | none | OpenTTGames held-out games (CC BY-NC-SA 4.0) · game test_2 · ¼ speed |
| the idea | the sentence in kinetic type ("before the ball lands", "before it reprices" in orange), then a timeline: model calls, ball lands, price catches up 1.0-1.5 s later | 1.0-1.5 s reprice band (inferred); $222 median stale depth 250 ms before the reprice | - |
| the edge | information ladder on a log time axis: venue camera, licensed betting video, official feed, TV, our measured public stream (12.2 s), public score feeds (ESPN 28 s, WTA 44 s), the reprice band and the dotted 1 s line. Then 11 months of fast-tier markout (white) against copying them 3 s later (red), with the held-out months shaded | −0.89¢ others; t = 8.5; R² 3.3 %; 11/11 up; 11/11 down | Polymarket public tapes · wallets' own fills, not our trades |
| table tennis | test_4 f5751 (92 ms) and test_4 f9837 (233 ms), full bleed, each MISS stamp at its own call frame (½ speed around the call). Then a 2x2 grid of IN calls on test_1, test_3, test_5 and test_6 → test_7, each stamp at its own frame. Every other call the engine made inside a clip window is shown at its own frame with what the labels say, including the wrong one (test_3, frame 3479) and the disputed one (test_2, frame 2766) | 7 games; 102,120 frames, 0 dropped; 12 MISS calls, 0 on a ball labelled in; 6.9 ms frame to call. Then 68/88 IN calls right; 4/41 labelled misses called early; 79 of 172 calls on unlabelled balls; 11/11 MISS calls right at 50 ms (offline test) | OpenTTGames held-out games (CC BY-NC-SA 4.0) |
| real tennis | `results/viz/v60_assets/tennis_real/tennis_tracked.mp4`, our tracker's trail on a licensed rally, no line calls | none | the Pexels credit from `tennis_real/LICENSE.md` |
| tennis, spin | minimal 3D court. One simulated shot (nominal world, shot 4243, lands 4.8 cm out) flies in slow motion while the camera pushes in. The spin-aware fit (bls) is shown at the evaluation's own decision points: its 95 % landing region in orange shrinks onto the line, with the spin axis, P(out), the estimated spin against the true spin, and the no-spin tracker's guess in grey. The stamp "OUT · called 200 ms before the bounce" sits at the first decision point with P(out) ≥ 0.95, then the ball lands | 5-8x less landing error; 100 % OUT precision at P(out) ≥ 0.95; 98.3 % of OUT balls called at 200 ms; ~7 rpm spin error | simulated physics: Hawk-Eye-class camera model · not real footage |
| the pipeline | nine stages with measured p50 ms (feed simulated, WebRTC 9.4, vision 43.3 on this laptop / 6.9 on an L4, fair value 0.09, risk 0.03, order 0.02, network 64.5, venue delay 1,000, paper fill), then a bar of 2,119 ms against the 3 s requirement | 54 ms ours; 2,119 ms total; 881 ms margin (24/24); 46 ms WebRTC frame → call | paper: order built, never signed or sent · 1 s feed simulated |
| speed | white canvas: paper $/day against feed delay (log axis). Both readings, in sample and held out, with the dotted 1 s line, the break-even dots (2.2 s post-hoc, 1.1 s pre-registered) and the source bands. Then the decay bars: fast-tier ¢/share by seconds after the point (1.18¢ at 0 s, 0.59¢ at 1 s) | $199 · $133 · $94 a day at 0 / 0.5 / 1 s; Sharpe 23 · 16 · 12; break-even 2.2 s (pre-registered 1.1 s); every reading loses by 3 s | simulated feed delays in the backtest (paper) · decay: fast-tier fills, not our trades |
| the test | `backtest_match/example_match.mp4` (Bondar v Zidansek, real Polymarket price path, modelled fills, +$82.22), then the 1 s equity curve drawing in: post-hoc in white with a p10-p90 band, pre-registered in grey, the held-out part shaded. Rigor pills: pre-registrations, blind tests (pass and fail counts), out-of-sample looks logged, variants counted, deflated Sharpe, PBO | +$82.22 this match; 58.9 % of 931 traded matches profitable, median +$11.27; months with a profit; 103 + 40 days | example match from the backtest (selected for illustration) · simulated 1 s licensed-feed baseline · real Polymarket price path · paper |
| the profit | hero numbers: $94 a day, Sharpe 12 (in sample, post-hoc estimate, stamp lag 3.14 s inferred after the fact, labelled on screen), then $57 a day, Sharpe 8.8 out of sample ("data the model never saw") | pre-registered $15 · $4 a day (Sharpe 2.2 · 0.3); +1.11¢ · +0.66¢ per share with 95 % CIs; $9,718 · $2,264 total; capacity $41k-$74k (post-hoc), $12k-$29k (pre-registered); v2 Sharpe 14.5 · 6.7 | simulated 1 s licensed-feed baseline · paper trading |
| end card | COURTSIDE, the team, the repo URL | none | Paper trading only · simulated 1 s licensed-feed baseline · Voice: AI (ElevenLabs) · footage: OpenTTGames CC BY-NC-SA 4.0, plus the tennis credit |

## Decisions and honesty notes

- **Cold open: 325 ms, not 408 ms.** The spec line "Called 408 ms before contact" is the offline evaluation's lead
  for test_2, flight 2819. The video shows the streaming engine's own call on that flight. That call came 325 ms
  before the labelled outcome, which is the ball passing the end line, not a contact. The stamp therefore says
  "called 325 ms early" and the outcome tick names the end line.
- **Calls appear only where the engine made them.** Every stamp sits at the engine's own call frame in the L4
  real-time log (`results/engine/online_events_L4.jsonl`). The predicted path is the engine's own fit at that frame,
  re-derived with its code: all 1,363 decision frames in the clip windows reproduce the logged score (max |Δp| 0).
  Clips were chosen by the rule in `results/viz/v60_assets/selection.json`, written before rendering: every MISS
  call made on a MISS-labelled flight before its outcome and not flagged by the audit, plus for each other game the
  IN call closest to the median lead. The counters give the totals over all 172 calls.
- **"11/11 at 50 ms"** appears only with the word "offline". The live counters come from the causal engine run.
- **Tennis is simulation.** Shot rule in `results/viz/v60_assets/tennis_sim/shot.json`: in the nominal world, the
  shot landing 2-10 cm out whose bls P(out) first reaches 0.95 at the 200 ms lead, closest to 5 cm. The fit was re-run
  with `src/spin/tennis_filter.bls_fit` (unchanged). At the evaluation's decision frames it reproduces the published
  parquet: d̂ within 0.1 mm, P(out) within 0.001. The picture uses those decision points only. A per-frame re-run
  would already pass 0.95 from about 252 ms; the stamp follows the evaluation grid (200 ms).
- **Profit**: the hero numbers use the post-hoc reading, with "post-hoc estimate" and the inferred stamp lag on
  screen. The pre-registered reading stays on the rail in the same frame. The narration says "post-hoc estimate".
  The video never says "calibrated from the data", "conservative" or "goes live".
- **Not used**: `results/replay` (team decision; the test segment uses the backtest showcase match) and the earlier
  plates `seg_*.mp4`, which were in the v2 style and are replaced by the keynote-style renderers in the script.
