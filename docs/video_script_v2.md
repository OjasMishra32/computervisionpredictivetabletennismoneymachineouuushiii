# COURTSIDE video v2: narration script (voice: Liam)

Rendered by `scripts/make_video_v2.py` into `results/viz/courtside_video_v2.mp4` (1920x1080, 30 fps, H.264 + AAC),
with burned-in captions and a sidecar `results/viz/courtside_video_v2.srt`. Every number on screen or in the
narration is read from a results file at render time. The renderer writes the mapping (number -> file + key + value)
to `results/viz/v2_assets/manifest.json`. Target runtime: 2:50 to 3:15.

## How the renderer reads this file

- `## Snn key | title` starts a scene. The parser regex is the v1 one: `## (S\d\d) (\w+) \| (.+)`.
- `window:` is the target time slot. It is a guide only; scene length = narration + 0.6 s, plus `hold:` seconds where a
  scene lists one.
- `when: name` skips the whole scene (no visual, no TTS) while `name` is pending.
- `visual:` says what is on screen. `label:` lines are mandatory honesty chips, drawn on screen for the whole scene.
- `> text` is one caption and one TTS clip. `> [if name] text` is spoken only when `name` is not pending.
  `> [else name] text` is spoken only when `name` is pending. A line whose guard (see the numbers table) fails is
  replaced by its `[else]` line, or dropped.
- `{name}` is filled from the numbers table in the same scene. A missing input renders as "pending" on screen. A
  narration line that needs a pending number is never spoken with "pending" in it: it falls back to its `[else]`
  line or is skipped.
- `...` is a spoken pause (ElevenLabs reads it as a beat). Captions show it as written.
- Spoken forms reuse `make_video.spoken()`: `-` before a digit -> "minus", `%` -> "percent", `¢` -> "cents".
- Number display: 1 decimal place unless the table says otherwise; a trailing ".0" is dropped (11.95 -> "12").
  Thousands get a comma.

## Voice

- ElevenLabs voice **"Liam"**, via `scripts/tts_elevenlabs.synth(text, out, voice="Liam", previous_text=..., next_text=...)`.
  `previous_text`/`next_text` are the neighbouring narration lines of the same scene (prosody only). The key comes
  from the gitignored `.env` inside that module. It is never printed, logged, copied or committed. A failed call is
  reported as its HTTP status only.
- Clips are cached by text, voice, model, settings and neighbours in `data/tts_cache/` (gitignored). Changing one line
  also re-renders its neighbours.
- Budget: under ~6,000 characters per full render. This script is about 2,700 characters with S05 skipped (S05 adds
  about 170).
- Read: conversational and fast, like a quant walking a friend through his favourite trade. Short sentences. Lean on
  the questions and the `...` pauses.

## Honesty rules (hard)

1. Every number comes from the file and key in its scene table, read at render time. No number is typed into this
   script.
2. Missing input -> "pending" on screen, and the narration line is skipped or swapped for its generic `[else]` line.
3. The CV-strategy numbers (S06) always carry **"Simulated at a 1 s licensed-feed baseline (feed not purchased)"**.
4. The tennis spin tracker (S04) always carries **"Simulated physics"**.
5. Real footage always carries **"Real match footage (OpenTTGames, CC BY-NC-SA 4.0)"**.
6. The replay (S07) always carries **"Backtest replay of a real match recorded 2026-10-03, assumed 1 s feed"**.
7. Never say or show that we received match video, bought a licensed feed, used live ATP/WTA data, or traded real money.
8. End card: **"Voice: AI (ElevenLabs). Paper trading only."**

---

## S01 hook | The point is over before it lands
window: 0:00-0:15
visual: CV showcase reel on real held-out table-tennis footage, game test_2, flight 2819 (`results/viz/cv_showcase.mp4` and `results/viz/stills/` when present; fallback `results/tracking/demo/01_miss_test_2_f2819_lead408ms.mp4`). The ball leaves a comet trail, the predicted arc locks in, and a spin chip reads "fitted spin {hook_top_rpm} rpm topspin (separate spin fit, no ground truth)". Then the stamp "MISS CALLED {tt_lead_ms} ms BEFORE CONTACT" (frozen call model). Footnote: "Longest early call on held-out games. Median {lead_med_ms} ms; {lead_n_called} of {lead_n_miss} test misses called early." The COURTSIDE title fades in over the last line.
label: Real match footage (OpenTTGames, CC BY-NC-SA 4.0)

> Watch this rally. Real footage, from a game our model never trained on.
> Right... there. It calls the miss {tt_lead_ms} milliseconds early.
> This model knew the point was over... before the ball landed.
> So what's that worth on a prediction market?

numbers:
| name | now | display | source (file :: key) | guard / note |
|---|---|---|---|---|
| tt_lead_ms | 408.3 | integer | `results/tracking/demo/manifest.json :: clips[0].call_lead_ms` (or the CV showcase manifest's entry for test_2 f_net 2819, if present) | must be flight test_2 / 2819, label MISS, call MISS; otherwise use the showcase's own hero clip and its own number |
| hook_is_longest | true | - | same file: `clips[0].call_lead_ms == max(call_lead_ms of MISS clips)` | false: drop the word "Longest" from the footnote |
| lead_med_ms | 25 | integer | `results/tracking/summary.json :: early_call.miss_first_call_lead_test_ms.median` | on screen only |
| lead_n_called | 8 | integer | `results/tracking/summary.json :: early_call.miss_first_call_lead_test_ms.n_called` | on screen only |
| lead_n_miss | 41 | integer | `results/tracking/summary.json :: early_call.miss_first_call_lead_test_ms.n_miss` | on screen only |
| hook_top_rpm | 3,736 | integer, comma | `results/spin/tt/test/showcase/index.json :: flights[f_net=2819].top_rpm_t_ref` | on screen only, always with "no ground truth" |

## S02 game | Whoever knows first takes the stale price
window: 0:15-0:40
visual: Information-tier ladder, built top to bottom: ball lands (t = 0) -> our CV call (before contact) -> Polymarket book reprices ({t0_preB} to {t0_calB} s after the bounce, both estimates) -> umpire's point stamp (the book moves a median {book_vs_stamp_s} s relative to it) -> ESPN live score ({espn_s} s behind the book) -> public streams. Side panel: a recorded book whose stale-depth bar drains from ${stale_pre_usd} to ${stale_post_usd} at the reprice, and a {venue_delay_s} s clock on every taker order.
label: Measured on one live day (2026-10-03): public Polymarket book + WTA public point-by-point log, {stale_n} points
label: Reprice time after the bounce is an estimate, not a measurement

> Here's the game: live tennis on Polymarket reprices point by point.
> [if t0_calB] When a point ends, the book moves about a second later... we estimate {t0_preB} to {t0_calB} seconds after the ball lands.
> [else t0_calB] When a point ends, the book reprices within seconds.
> Right before that, a median {stale_pre_usd} dollars sits at the old price. Half a second later? {stale_post_usd}.
> And taker orders wait {venue_delay_s} second at the venue... so you have to know the point's over as the ball lands.

numbers:
| name | now | display | source (file :: key) | guard / note |
|---|---|---|---|---|
| t0_preB | 0.68 | 1 dp | `results/tier0/results.json :: timing.pre_registered_primary_median_t_reprice_minus_t_bounce_s` | |
| t0_calB | 1.349 | 1 dp | `results/tier0/results.json :: timing["calibrated_t_reprice_minus_t_bounce_s (inference)"]` | line 2 needs t0_preB and t0_calB; otherwise its `[else]` line is spoken |
| stale_pre_usd | 222.2 | integer | `research/v2/latency/results.json :: summary.stale_depth.pre.median_usd` | |
| stale_post_usd | 0.0 | integer | `research/v2/latency/results.json :: summary.stale_depth.post.median_usd` | spoken "zero" when 0 |
| stale_n | 482 | integer | `research/v2/latency/results.json :: summary.stale_depth.pre.n` | on screen only |
| venue_delay_s | 1.0 | integer | `results/engine/demo_run.json :: latency_budget[stage="venue marketable-order delay"].ms / 1000` | |
| book_vs_stamp_s | -1.32 | 2 dp, signed | `results/tier0/results.json :: timing.median_t_reprice_minus_t_stamp_s` | on screen only ("moves 1.32 s before the stamp") |
| espn_s | 28.2 | 1 dp | `results/decay/decay.json :: latency_inputs.espn_behind_book_s` | on screen only |

## S03 alpha | The edge is real, and it's speed
window: 0:40-1:00
visual: Monthly bars, Dec 2025 to Oct 2026 (in sample solid, out of sample pale), cents per share after fees: fast tier, everyone else, and "copy them 3 s later". Then the decay chart: fast-tier markout by seconds since the jump, in sample and out of sample (`results/alpha/fig_alpha_decay.png` style). Corner card: four-factor alpha t = {fac_t}; largest factor |t| = {fac_maxt}; R² = {fac_r2}%.
label: Fast tier = walk-forward-qualified Polymarket wallets; net 30 s markout after taker fee. Oct 2026 = 3 days. Tape time resolution: whole seconds
label: Factor test: v2 at the fast tier's own fills (the opportunity at their speed, not our execution); Fama-French 3 + momentum, Newey-West

> Is the edge real? Wallets that trade in the first three seconds after a point are up, after fees, in {ft_pos} of {ft_n} months.
> Copy them three seconds late? You lose in {fol_neg} of {ft_n}.
> [if d1_is] Their edge halves in a second... and out of sample, it's gone by two.
> And it's not market beta: four-factor alpha, t-stat {fac_t}.

numbers:
| name | now | display | source (file :: key) | guard / note |
|---|---|---|---|---|
| ft_n | 11 | integer | `results/alpha/alpha.json :: A_source.IS.months[].month ∪ A_source.OOS.months[].month` (distinct calendar months) | Aug 2026 has an IS and an OOS row |
| ft_pos | 11 | integer | same rows: months where every row has `fast_net30_c > 0` | |
| fol_neg | 11 | integer | same rows: months where every row has `copy_3s_later_net_to_resolution_c < 0` | |
| oth_neg | 11 | integer | same rows: months where every row has `others_net30_c < 0` | on screen only |
| d0_is | 1.18 | 2 dp ¢ | `results/alpha/alpha.json :: E_decay.within_a_point.IS.rows[0].fast.net30_c` (bin "0 s") | on screen |
| d1_is | 0.59 | 2 dp ¢ | `... IS.rows[bin="1 s"].fast.net30_c` | guard: `d1_is / d0_is <= 0.55`, else skip the line |
| d2_oos | -0.02 | 2 dp ¢ | `... OOS.rows[bin="2 s"].fast.net30_c` | guard: `d2_oos <= 0.05`, else skip the line |
| fac_t | 8.5 | 1 dp | `results/alpha/alpha.json :: headline.factor_alpha_t_committed_file_incl_oos_weekdays` | on screen add "IS-only spec t = {C_factor_neutral.IS_committed_spec.alpha_t}" |
| fac_maxt | 1.33 | 2 dp | `results/alpha/alpha.json :: C_factor_neutral.committed.max_abs_factor_t` | on screen only; guard for "it's not market beta": `fac_maxt < 2`, else drop that clause and keep the t-stat |
| fac_r2 | 3.3 | 1 dp % | `results/alpha/alpha.json :: C_factor_neutral.committed.r2 × 100` | on screen only |

## S04 vision | Calling it before contact
window: 1:00-1:35
visual: Split screen. Left: held-out real footage with detections and the call (`results/viz/stills/` or `results/tracking/demo/supercut.mp4`); a panel shows ball-detection recall {det_recall}% (within 5 px: {det_w5}%, {det_n} frames), and at 50 ms before contact {n50} calls / {tp50} correct, Wilson 95% lower bound {wil50}%, recall {recall50}%. Middle: tennis Hawk-Eye-style replay with the spin-aware tracker (`results/spin/tennis/fig_error_vs_lead.png`, `fig_spin_readout.png`): landing error vs lead, old predictor vs new trackers, with the ratio band marked at 300-400 ms and the spin error at 200 ms. Right: table-tennis spin result card, spin model {tt_spin_tp50}/{tt_spin_n50} vs frozen model {tt_frozen_tp50}/{tt_frozen_n50} correct at 50 ms, fitted topspin median {tt_spin_med_rpm} rpm (no ground truth). Then the engine clip (`results/engine/engine_live_demo.mp4`) with a latency card: {l4_ms} ms frame to call, {l4_fps} fps sustained, NVIDIA L4.
label: Real match footage (OpenTTGames, CC BY-NC-SA 4.0): held-out test games
label: Tennis tracker: simulated physics (no licensed tennis footage)
label: Engine demo: table-tennis calls mapped onto a recorded WTA order book; an illustration, not a backtest; paper only

> Can vision get there first? On held-out real footage it finds the ball in {det_recall} percent of frames.
> Fifty milliseconds before contact, it {calls50_phrase}. The 95 percent floor on precision: {wil50} percent.
> For tennis, a spin-aware tracker on simulated physics: {spin_x_lo} to {spin_x_hi} times less landing error than our old predictor, and spin within about {spin_rpm} rpm.
> [if tt_spin_tp50] On real table tennis, spin didn't beat our frozen model, so the frozen one stays.
> And it runs end to end: {l4_ms} milliseconds frame to call, on a cloud GPU.

numbers:
| name | now | display | source (file :: key) | guard / note |
|---|---|---|---|---|
| det_recall | 96.71 | 1 dp % | `results/tracking/summary.json :: detection_accuracy_pooled[split=test, source=tracked].recall × 100` | |
| det_w5 | 93.97 | 1 dp % | same row `.within5 × 100` | on screen only |
| det_n | 6,833 | integer | same row `.n_visible` | on screen only |
| tp50 | 11 | integer | `results/tracking/summary.json :: early_call.precision_recall_test_snapshot["50ms"].tp` | |
| fp50 | 0 | integer | `... ["50ms"].fp` | |
| n50 | 11 | integer | tp50 + fp50 | |
| calls50_phrase | "made 11 miss calls and got all 11 right" | derived | fp50 = 0: "made {n50} miss calls and got all {n50} right"; else "made {n50} miss calls, {tp50} of them right" | |
| wil50 | 74.12 | integer % | `... ["50ms"].precision_wilson95[0] × 100` | |
| recall50 | 26.83 | integer % | `... ["50ms"].recall × 100` | on screen only |
| spin_x_lo | 5.08 | floor | `results/spin/tennis/key_numbers.json`: min over m ∈ {bls, ukf}, L ∈ {300, 400} of `baseline.sd_cm[L] / m.sd_cm[L]` | |
| spin_x_hi | 7.90 | round | same set, max | guard: spin_x_lo ≥ 2, otherwise drop the ratio clause |
| spin_rpm | 6.8 | integer | `results/spin/tennis/key_numbers.json :: bls.rpm_err_med_abs["200"]` | median abs error of the Magnus-active spin |
| tt_spin_tp50 / tt_spin_n50 | 10 / 12 | integer | `results/spin/tt/test/report_numbers.json :: snapshot_spin["50ms"].tp / .calls` | guard for the "didn't beat" line: spin precision < frozen precision at 50 ms (`report_numbers.json :: snapshot_*["50ms"].precision`); otherwise drop the line |
| tt_frozen_tp50 / tt_frozen_n50 | 11 / 11 | integer | `results/spin/tt/test/report_numbers.json :: snapshot_frozen["50ms"].tp / .calls` | on screen only |
| tt_spin_med_rpm | 3,060 | integer | median of `results/spin/tt/test/test_spin_readout.csv :: top_rpm` | on screen only, "no ground truth" |
| l4_ms | 6.92 | 1 dp | `results/engine/demo_run_L4.json :: vision.timing.emitted_call_latency_ms.p50` | p50; on screen also p90 |
| l4_fps | 119.88 | 1 dp | `results/engine/demo_run_L4.json :: vision.timing.fps_sustained` | on screen only |

## S05 pipeline | WebRTC in, order out
window: 1:35-1:50
when: webrtc_ms
visual: Pipeline diagram lit stage by stage: our WebRTC stream of held-out OpenTTGames footage -> decode -> CV call -> strategy -> paper order; each box shows its measured median ms from `results/webrtc/latency.json`. Inset: `results/webrtc/webrtc_demo.mp4` if present.
label: Our own WebRTC stream of OpenTTGames footage, not a match feed; paper only

> Then we made it live-shaped: video in over WebRTC, vision in the middle, a paper order out the other end.
> On our own stream, frame in to decision out takes {webrtc_ms} milliseconds.

numbers:
| name | now | display | source (file :: key) | guard / note |
|---|---|---|---|---|
| webrtc_ms | pending | integer | `results/webrtc/latency.json :: capture_to_decision_ms.p50` (confirm the key against the file when it lands) | pending: the whole scene is skipped. Say "under a second" only if this measured value is < 1000; the line above states the number itself |

## S06 baseline | The one-second baseline
window: 1:50-2:25
hold: 1.5
visual: Paper returns ($/day) against feed delay V (log x), in sample and held out (`results/tier0/fig_pnl_vs_feed_latency.png` style): calibrated reading (stamp lag {lc_lag} s) and pre-registered reading (2.0 s) as solid curves, the stamp-noise reading dashed. Source bands along the x axis: venue camera {band_cam} s (not feasible), betting video {band_vid} s (vendor claims), official feed {band_feed} s, TV {band_tv} s, public streams {band_stream} s. A dotted vertical line at V = 1 s. Break-even ticks: {be_t_is} s (pre-registered) and {be_lc_is} s (calibrated). Two pairs of counters run up at 1 s: cumulative paper P&L, calibrated ${lc_is_pnl} over {lc_is_days} days in sample and ${lc_oos_pnl} over {lc_oos_days} days held out; pre-registered ${t_is_pnl} and ${t_oos_pnl}. Counters only: no per-day series exists for these cells, so no equity path is drawn.
label: Simulated at a 1 s licensed-feed baseline (feed not purchased)
label: Calibrated reading = stamp lag inferred from the data, post hoc. Held out = burned OOS (held-out matches, not blind)
label: Video latency figures are vendor claims, unverified, not stated for tennis

> So what's it worth? Fast match video is sold to bookmakers; vendors claim as little as {vid_lo_s} seconds. We didn't buy it... so we simulate a one-second licensed feed.
> Faster wins, and from {all_lose_s} seconds on, every reading loses.
> At one second? Calibrated from the data: Sharpe {lc_is_sh} in sample, {lc_oos_sh} held out... about {lc_is_day} and {lc_oos_day} dollars a day.
> Pre-registered and conservative: {t_is_sh} and {t_oos_sh}. Stricter readings lose.
> It all hinges on one number we haven't measured: how fast the umpire logs the point.

numbers:
| name | now | display | source (file :: key) | guard / note |
|---|---|---|---|---|
| vid_lo_s | 0.5 | 1 dp | `results/tier0/latency_sweep.json :: sources[key=betting_video].band_s[0]` | |
| band_cam, band_vid, band_feed, band_tv, band_stream | 0-0.05, 0.5-8, 1-3, 0.9-20, 10-60 | as given | `results/tier0/latency_sweep.json :: sources[key=venue_camera\|betting_video\|official_feed\|tv\|stream].band_s` | on screen only |
| all_lose_s | 3 | integer | `results/tier0/latency_sweep.json :: video_own120`: smallest grid V with `usd_per_day < 0` for every reading × {IS, burned_OOS} at V and at every larger V | |
| lc_is_sh | 11.95 | 1 dp | `results/tier0/latency_sweep.json :: video_own120.tournament_lagcal["1"].IS.sharpe_ann` | |
| lc_oos_sh | 8.85 | 1 dp | `... tournament_lagcal["1"].burned_OOS.sharpe_ann` | |
| lc_is_day | 94.35 | integer $ | `... tournament_lagcal["1"].IS.usd_per_day` | |
| lc_oos_day | 56.59 | integer $ | `... tournament_lagcal["1"].burned_OOS.usd_per_day` | |
| t_is_sh | 2.15 | 1 dp | `... video_own120.tournament["1"].IS.sharpe_ann` | |
| t_oos_sh | 0.34 | 1 dp | `... video_own120.tournament["1"].burned_OOS.sharpe_ann` | |
| stricter_lose | true | - | `... video_own120.stamp["1"]` and `tournament_lag1["1"]`: `usd_per_day < 0` in IS and burned_OOS | false: drop "Stricter readings lose." |
| lc_lag | 3.14 | 2 dp | `results/tier0/results.json :: timing["calibrated_stamp_lag_s (inference)"]` | on screen only |
| be_t_is | 1.09 | 1 dp | `results/tier0/latency_sweep.json :: breakeven_video_delay.tournament.IS.breakeven_V_s_seed_mean_curve` | on screen only (OOS value beside it) |
| be_lc_is | 2.23 | 1 dp | `... breakeven_video_delay.tournament_lagcal.IS.breakeven_V_s_seed_mean_curve` | on screen only |
| lc_is_pnl, lc_is_days | 9,718 / 103 | integer $ | `results/tier0/latency_sweep.csv` row source=video, cv=own120, reading=tournament_lagcal, x_s=1.0, period=IS: `pnl_usd`, `days` | on screen only |
| lc_oos_pnl, lc_oos_days | 2,264 / 40 | integer $ | same, period=burned_OOS | on screen only |
| t_is_pnl / t_oos_pnl | 1,522 / 174 | integer $ | same, reading=tournament, x_s=1.0, period=IS / burned_OOS | on screen only |

## S07 replay | A real match, raced against the real book
window: 2:25-2:45
visual: `results/replay/replay_match.mp4` if present; fallback `results/replay/fig_selected_match.png` and `fig_race.png` animated: the recorded mid of {rep_match}, every official point, and each order racing the real book (green: executes before the reprice; grey: book already moved). Counter: calls that beat the book at V = 1 s, {rep_sel_beat} of {rep_sel_calls}; all {rep_n} matches: {rep_v1_c}¢ per share marked at +30 s (95% CI {rep_v1_ci}), {rep_beat_share}% of calls beat the book.
label: Backtest replay of a real match recorded 2026-10-03, assumed 1 s feed
label: Point times from the WTA public point-by-point log; no match video was received; paper only

> [if rep_v1_c] A real match from {rep_when}: {rep_match}. Real recorded book, assumed one-second feed, every order racing it.
> [if rep_v1_c] Our order gets there first on {rep_sel_beat} of {rep_sel_calls} calls.
> [if rep_v1_c] Across all {rep_n} matches we recorded, trading every point, not just big swings, it {rep_verb} {rep_v1_c_abs} cents a share. One second is right on the edge.
> [else rep_v1_c] Next: the same trader, raced against real order books we recorded live.

numbers:
| name | now | display | source (file :: key) | guard / note |
|---|---|---|---|---|
| rep_match | Xinran Sun versus Cristina Bucsa | text | `results/replay/replay.json :: matches[selected=true].n0 + " versus " + .n1` | |
| rep_when | today | text | `results/replay/replay.json :: matches[selected=true].first_T` (UTC date) | "today" only if the render's UTC date equals it; otherwise the date spoken, e.g. "October 3rd" |
| rep_sel_beat | 6 | integer | `results/replay/replay.json :: selected_story.V1.beat_book` | |
| rep_sel_calls | 121 | integer | `results/replay/replay.json :: selected_story.V1.calls_with_reprice` | |
| rep_n | 9 | integer | `results/replay/replay.json :: len(matches)` | |
| rep_v1_c | -0.92 | 2 dp ¢, signed | `results/replay/replay.json :: headline_by_V.V1.all.per_share_mark_c` | headline cell: stamp lag 2.0 s, V = 1 s, model lead, Florida |
| rep_v1_c_abs, rep_verb | 0.92, "loses" | 2 dp | abs(rep_v1_c); verb "loses" if rep_v1_c < 0, else "makes" | |
| rep_v1_ci | [-1.29, -0.57] | 2 dp | `... headline_by_V.V1.all.per_share_mark_ci95_c` | on screen only |
| rep_beat_share | 7.5 | integer % | `... headline_by_V.V1.all.share_calls_beat_book × 100` | on screen only |

## S08 fund | Built like a fund
window: 2:45-3:05
hold: 1.5
visual: Scoreboard: pre-registrations (`HYPOTHESIS*.md`, `research/**/PREREG.md`, `research/replay/PROTOCOL.md`); blind tests with PASS / FAIL / PENDING chips (forward test: {fwd_state}); deflated Sharpe at N = {n_trials}: in sample {dsr_is}, held out {dsr_oos}; out-of-sample looks logged: {peeks}; stress rows: fees ×2 {fee2_is}¢ / {fee2_oos}¢, all costs ×2 {cost2_is}¢ / {cost2_oos}¢, latency break-even {be_t_is}-{be_lc_is} s, 5× size {x5_oos_day} $/day held out; kill-switch table (code vs policy) from `docs/RISK.md`; capacity ${cap_lo}k-${cap_hi}k; live paper session state: {sess_state}.
label: Paper trading only. Stress, capacity and deflated-Sharpe rows: v2 at the fast tier's own fills

> And we built it like a fund. Pre-registered hypotheses. Blind tests, scored even when they failed.
> A deflated Sharpe counting all {n_trials} configurations we tried.
> We stress-tested costs, fees, latency and size, and every break point is on the scoreboard.
> Risk limits, kill switches, and a capacity ceiling around {cap_lo} to {cap_hi} thousand dollars.

numbers:
| name | now | display | source (file :: key) | guard / note |
|---|---|---|---|---|
| n_trials | 3,410 | integer, comma | `results/rigor/rigor.json :: psr_dsr.N.all_plus_v2safe_grid` | |
| dsr_is | 0.997 | 3 dp | `results/rigor/rigor.json :: psr_dsr.rows[series=v2_is]`: min over `dsr["N3410/*"].dsr` | on screen only |
| dsr_oos | 0.075 | 3 dp | same, series=v2_oos | on screen only, with "40 days cannot rule out luck" |
| peeks | 65 | integer | `results/oos_peeks.log :: count(non-empty lines)` at render time | on screen only |
| fee2_is / fee2_oos | 0.77 / -0.34 | 2 dp ¢ | `results/v2/cost_stress.json :: is_eval/fee_x2.per_share_c`, `burned_oos/fee_x2.per_share_c` | on screen only |
| cost2_is / cost2_oos | 0.27 / -0.84 | 2 dp ¢ | `results/v2/cost_stress.json :: is_eval/costs_x2.per_share_c`, `burned_oos/costs_x2.per_share_c` | on screen only |
| x5_oos_day | -24.5 | 1 dp $ | `results/alpha/alpha.json :: H_capacity.rows[size="5x"].OOS.pnl_usd_per_day` | on screen only |
| cap_lo / cap_hi | 22,754 / 33,875 | integer $k | `results/alpha/alpha.json :: headline.oos_capital_capacity_usd[0] / [1]`, ÷ 1000 | |
| kills | 4 rows | text | `docs/RISK.md :: "## Daily kill-switch rules (summary)"` table: Trigger, Action, Implemented in | on screen only |
| fwd_state | pending | text | `results/v2/forward.json :: verdict` (absent: "pending, runs once ~2026-10-04 11:30 UTC" from `HYPOTHESIS_V2.md`) | on screen only |
| sess_state | warming up | text | `results/live/summary.json :: status` (+ STOPPED marker / file age, as in `make_video.live_state`) | on screen only |

## S09 close | License the feed
window: 3:05-3:15
hold: 3.0
visual: Repo URL ({repo_url}) and the command `bash run.sh replay` (~15 s, recorded public books, no network). End card, held 3 s: "Voice: AI (ElevenLabs). Paper trading only." Under it: "No match video was received. No licensed feed was purchased. No live ATP/WTA data was used. No real money was traded. CV-strategy figures are simulated at a 1 s licensed-feed baseline (feed not purchased). Footage: OpenTTGames (OSAI), adapted, CC BY-NC-SA 4.0. Every number: results/viz/v2_assets/manifest.json."
label: Voice: AI (ElevenLabs). Paper trading only.

> That's Courtside: a real edge, fast vision, and speed is the whole trade.
> License a feed, measure that one number, and this goes live.
> It's all in the repo... and one command replays the paper engine on recorded books.

numbers:
| name | now | display | source (file :: key) | guard / note |
|---|---|---|---|---|
| repo_url | github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii | text | `git remote get-url origin` at render time | on screen only |
| replay_cmd | bash run.sh replay | text | `run.sh` usage block | on screen only |

---

## Values at the time of writing (2026-10-03, for checking a render; the render reads the files)

| scene | spoken with today's files |
|---|---|
| S01 | 408 ms (longest; median 25 ms, 8 of 41 misses called early) |
| S02 | 0.7 to 1.3 s; $222 before the reprice, $0 half a second after; 1 s venue delay |
| S03 | 11 of 11 months up; copying 3 s late loses in 11 of 11; markout 1.18¢ -> 0.59¢ at 1 s (IS), -0.02¢ at 2 s (OOS); alpha t = 8.5 |
| S04 | 96.7% of frames; 11 calls, all 11 right; Wilson floor 74%; 5 to 8 times smaller landing error; spin within ~7 rpm; 6.9 ms frame to call (L4) |
| S05 | skipped (results/webrtc/latency.json not written yet) |
| S06 | 0.5 s vendor claim; every reading loses from 3 s; calibrated Sharpe 12 / 8.8, $94 / $57 a day; pre-registered 2.2 / 0.3 |
| S07 | "today" (on 2026-10-03 UTC), Xinran Sun versus Cristina Bucsa; 6 of 121 calls beat the book; 9 matches, loses 0.92¢ a share |
| S08 | 3,410 configurations; capacity 23 to 34 thousand dollars |
| S09 | no numbers spoken |

Why S07 says the replay loses: `research/replay/RESULTS.md` (protocol committed before any P&L) finds the replayed
trader negative at every feed delay and stamp lag it tried, marked at +30 s. It trades every point with a 100-share net
cap; the latency sweep trades only the larger jumps. The script states the loss and that difference, in one line each.
