# Final-prep review: video, deck, script, clean clone (2026-10-03, ~21:10 UTC)

Adversarial pass over what judges will see. The default was to flag anything doubtful.

| what | version reviewed |
|---|---|
| Video | `results/viz/courtside_video.mp4` + `.srt` + `video_manifest.json` at `63926df` (204.6 s, 1920x1080, 30 fps, H.264/AAC mono 48 kHz) |
| Script | `docs/video_script.md` at `63926df` |
| Deck | `docs/deck/courtside.pptx` at `9e750a1` (python-pptx text dump of all 30 slides). It was also rebuilt into the scratchpad from today's files, and the two manifests were diffed |
| GitHub | `597b0de` (fetched 21:00 UTC). It contains `9e750a1`, `63926df`, `8cd93a7` and `57a05c6`. Local `main` was ahead (at `4ca0dca`, other workflows) |

Method:

- Every value in `video_manifest.json` (166 on screen) was re-derived by re-running `make_video.build_values()` on today's files, then diffed against the render.
- 15 numbers were recomputed independently from lower-level files (table below).
- 12 end-of-scene frames and 14 extra frames/crops were extracted with ffmpeg.
- Caption timing was checked against `silencedetect` on the audio track.
- Two failing clean-clone steps were re-run on a fresh clone of the GitHub commit.

## Bottom line

The numbers are mostly sound: 13 of the 15 recomputations match the results files exactly, the counterfactual
label is present wherever a tier-0 P&L appears, the required failures are shown, and the captions are in sync.
Five things must change before anything is shown, though:

1. A new failure is missing from both deck and video: the frozen tier-0 v3 blind tests (FAIL).
2. The "no live ATP/WTA data was used" disclaimer is contradicted by our own latency study.
3. If the deck is rebuilt right now (as the deck README advises), slide 8 will say "as of 1970-01-01".
4. The deck and video disagree on several headline counts that judges will see side by side.
5. The hook shows a cherry-picked 408 ms call without saying so.

## Prioritized fix list

P0 = blocks presenting. P1 = fix before the talk. P2 = should fix. P3 = polish. "Both" = deck and video.

| # | P | where | issue (evidence) | fix |
|---|---|---|---|---|
| 1 | P0 | both | **A failure is not shown.** The frozen tier-0 v3 blind tests FAILED: U2-IS −0.22¢, U2-OOS −0.52¢, and burned OOS +0.68¢ but a FAIL on its CI (`results/tier0_v3/blind.json` `verdicts`; `research/v2/tier0_v3/TEST_RESULTS.md`; `oos_peeks.log` 20:28 UTC). Video S08/S09 and deck slides 6, 7 and 20 present tier-0 with no mention. Deck slide 7's notes still say the verification "is running separately". (These files are still untracked; another workflow owns them.) | Once that workflow commits `blind.json`, add a scoreboard row "Tier-0 v3, frozen, blind on unseen markets (counterfactual): FAIL" to deck slide 6 and video S08. Add one sentence to deck slide 7 and video S09: "A frozen version then failed its blind tests." Delete the stale slide 7 note. |
| 2 | P0 | both | **The "No live ATP or WTA data was used" disclaimer is inaccurate as worded** (video S12 narration and card; deck slide 10 "bought or used"). `research/v2/latency/RESULTS.md` recorded the WTA public JSON API (`matches?states=L` every 2 s) and the ESPN scoreboard live on 2026-10-03. That study is the source of "ESPN 28.2 s behind" and "public score 44.5 s" on S02 and slide 2. A judge who asks how 28.2 s was measured will find the contradiction. | Reword everywhere: "We bought no official ATP/WTA data feed, and no trading result uses one. Free public score pages (the WTA website, ESPN) were recorded only to time how far they lag the book." Keep the tier-0 label as it is. |
| 3 | P0 | deck s8, video S10 | **The live-session card breaks on rebuild.** Run `20261003T193534Z` was stopped (`results/live/STOPPED_20261003T193534Z`). The restarted run `20261003T204812Z` is in warm-up, and `summary.json` has `"now": "1970-01-01T00:00:00.000Z"`, `counters: {}`. A scratch rebuild of the deck today printed "as of 1970-01-01 00:00 UTC" and "0 book messages". The video's `done` regex (`make_video.py:398`) has no "stopped/error", so a stopped run still reads "running now". | In `build_deck.py` s08 and `make_video.py`: if `now` starts with 1970 or `counters` is empty, show "warming up since `started_process`". Add `stopped\|error\|killed` to the regex. Rebuild only after the session has quoted. |
| 4 | P1 | both | **The deck and video contradict each other.** (a) Peek log: deck 45, video 51, file now 60, still growing. (b) Fast-tier months: deck 11/11 (8 IS + 3/3 OOS, `results/summary.json`); video "9 of 9" (`results/fasttier_walkforward_is.csv`, in-sample only). (c) DSR in sample: deck 1.00, video 0.99 (`floor2` truncates 0.9969). (d) Ball detection: deck 97.7% within 5 px / 99.7% found (`engine/demo_run.json`); video recall 96.7% / precision 98.0% (`tracking/summary.json`). (e) CV latency: deck 100 ms median; video "~95 ms" (84.3 ms + camera + London, `decay.json`). (f) Tier ladder: deck 6 tiers (tier 2 = market makers); video 5 (tier 2 = official feed). | Rebuild both from the same files in one sitting. Use one source per quantity: summary.json for months, one detection metric, one latency, one ladder. Show DSR as 0.997. Say "every look is logged (N at build time)". |
| 5 | P1 | video S01 | **The hook is cherry-picked.** "Calls this shot a miss 408 ms before" is the single longest held-out call. The online rule called 8 of 41 test misses, median lead 25 ms, p90 210 ms (`tracking/summary.json` `miss_first_call_lead_test_ms`). The scored metric is the 50 ms snapshot. Also, in the slow-mo replay the overlay reads "MISS CALLED −408 ms" with P(miss) 0.99, then **0.00** at frames 2820–2826, then 1.00 (seen at 5.8–6.5 s). | Add on screen and in narration: "our longest call on held-out games; most come tens of ms early". Add a small note "the call latches at the first crossing; P(miss) is per frame", or mask the P(miss) row after the call (crop in `make_video.py`; `src/` stays read-only). |
| 6 | P1 | video S04 | "So we built our own fast tier" overclaims. There is no tennis camera and no live call, tier-0 is a counterfactual, and v3 failed blind. | "So we tested whether vision could get there: on held-out table-tennis games it calls misses before contact." |
| 7 | P1 | video S03 | The video shows only the in-sample months, where H6 was found (Dec–Aug), and labels them "in sample" only in the 11 px source line. The out-of-sample test months are missing. | Switch to the deck's data: 8 IS months plus 3/3 OOS, OOS bars pale. Narration: "…in every month, including 3 of 3 out of sample." |
| 8 | P1 | deck s1 notes, s2 | **Wrong number.** Slide 2 says "$4.2 total \|fair-value move\| … (161 points, 5.7% mean per point)", but 161.19 × 5.716% = $9.21. In `scripts/leverage_stats.py`, `mean_abs_leverage` is the swing between winning and losing the point; the realised mean move is 4.212 / 161.19 = **2.6¢**. Slide 1's notes repeat the error: "on average about 5.7% of a player's fair value per point". | Derive the value in `build_deck.py` (total ÷ points). Caption: "2.6¢ realised move per point on average (5.7¢ swing between winning and losing it)". Fix the slide 1 notes. |
| 9 | P1 | video S05, S10, S12 | **"The code and every result file are in the public repository" is false today.** `results/spin/tennis/metrics_v2.csv` (S05 spin panel), `results/live/summary.json` (S10, slide 8) and `results/tier0_v3/**` are untracked. Local `main` is ahead of GitHub. | Commit those files when their owners finish (or drop the S05 spin panel), push, then re-render. Never commit `data/` or `models/`. |
| 10 | P1 | video S12, deck s10 | **Reproduce claims outrun the clean-clone result.** "One command rebuilds the backtest tables" and "bash reproduce.sh … from cached public data" leave out three facts. (a) A clone has no cache: `bash run.sh data` (~1–2 h crawl) must run first, and the chain has not been run end to end on a clean clone (CLEAN_CLONE F5). (b) `run.sh money` still fails without it (F6, re-confirmed below). (c) The CV calls cannot be reproduced: `models/vision/frozen_call_model.pkl` (12 MB) is not distributed (F8d). The rubric caps Performance at 4 if the code does not reproduce. | Say: "`bash run.sh replay` reruns the paper engine in 7 s; `bash run.sh data` then `bash run.sh reproduce` rebuilds every table from public data (~1–2 h)." Offer the frozen model as a GitHub release asset or document the HiPerGator retrain (`hpg/engine_vision.sbatch`). Do not commit `models/`. |
| 11 | P1 | both | Time-relative words are baked into static media: "tonight", "running now", "running tomorrow", "runs once, tomorrow", "LIVE PAPER SESSION (TONIGHT)". These will be wrong when shown after the forward run. | Use dates ("forward test: 2026-10-04 from 11:30 UTC"). Re-render after `results/v2/forward.json` lands, since it currently renders "pending" correctly. |
| 12 | P2 | video S02 | **Overlap.** "44.5 s behind" is drawn over the tier-4 subtitle "…video streams 5–30 s (assumed)". | Shorten the subtitle or move the streams note onto its own line. |
| 13 | P2 | video S01 | **Overlap.** At 7.7–12 s the two-line caption box covers the right-aligned credit line (y≈924), dimming "real held-out test game · Footag". | Left-align the credit as S04 does, or raise it 30 px. |
| 14 | P2 | video, all scenes | **Pacing.** Every scene holds 0.3 s after the last word (scene = speech + 0.6 s). The closing card (repo URL, disclaimers) is visible for 0.3 s after the final word. The dense S06 (≈20 numbers), S08 (9-row table) and S11 cannot be read at this speed. Speech averages 191 wpm (`say -r 215`). | Hold the end card for 3 s and add 1.5 s to S06, S08 and S11 (≈+7.5 s total). Optionally `-r 200`. |
| 15 | P2 | video S07 | The PBO figure is cherry-picked: only 15% (selection by Sharpe) is shown. On the same 24-variant grid, PBO by our selection rule is **42.0%** (`rigor.json` `lowloss_24_selection_rule`). Deck backup Q7 shows both. | Show both numbers. |
| 16 | P2 | video S09, deck s7 | The pre-registered bounce-to-reprice estimate, 0.68 s, lies in the negative zone of the stamp curve (IS −2.48¢ at 0.6 s, −1.76¢ at 1.0 s, +1.24¢ at 1.1 s). The narration leaves this out. | Add: "our pre-registered estimate, 0.68 s, falls in that zone." |
| 17 | P2 | video S02 | "A courtside camera with our vision model would know in about 95 ms": that 84.3 ms comes from a laptop benchmark with a **stand-in classifier, calls disabled, frame skipping**, `keeps_up_with_120fps: false` (`decay.json` `cv_measured_s`). The tier-0 row carries no counterfactual tag. | Tag the row "(laptop benchmark; no courtside camera)" and use the same latency as deck slide 4. |
| 18 | P2 | video S10, deck s8 | "Runs end to end on live order books": the live run covers market data, risk and the paper executor only (no vision input). The full chain ran on recorded books with table-tennis calls, as an illustration (the deck's own caption says so). | "The market-data and paper-trading legs run on live books; the full chain runs on a recorded book." |
| 19 | P2 | video S08 | v1's −$36.1k loss on the held-out window (opened once, blind) is in the deck but not the video. | Add a FAIL row. |
| 20 | P3 | video S07, deck s6/s17 | "Counting all 3,386 trials": `rigor.json` also has N = 3,410 (with the v2-safe grid). DSR is unchanged at 2 dp (IS 0.9969, OOS 0.0746). | Say 3,410, or "3,386 in NOTE §8". |
| 21 | P3 | video S11 | "Positive only up to about 34 thousand dollars": the scaling grid gives +$82.5/day at $33.9k and −$24.5/day at $53.8k, both **before** fixed costs. After central fixed costs, OOS is negative at every size. | "Positive at $34k, negative by $54k, before fixed costs." |
| 22 | P3 | video S07 | "CSCV, 16 blocks, all 12,870 splits" is hard-coded at `make_video.py:1098`, not read at render time (it matches `rigor.json` `S_blocks`, `n_splits`). | Read both from the file. |
| 23 | P3 | deck s18 vs s5/s6 | "39 of 360 days" (`oos_days` 38.7) vs "40 days" (UTC dates) for the same window. | Footnote "38.7 days, 40 UTC dates". |
| 24 | P3 | video S08 | "Table tennis markets had no fast tier at all" is stronger than the verdict, which reads "FAIL (no fast tier detected)". | "We detected no fast tier." |
| 25 | P3 | video S04 | "Pre-registered rule: precision ≥ 95%. Verdict: PASS" sits beside a 74% lower bound. | Add "on the point estimate; n = 11". |
| 26 | P3 | video, README | The CC BY-NC-SA credit is present (S01, S04, S12, deck s4), but it does not say the clips were adapted (overlays). The repo has no LICENSE or NOTICE. | Write "adapted (overlays added), CC BY-NC-SA 4.0" and add a NOTICE line to the README. |
| 27 | P3 | video S05 | "Reads the spin from the flight" (4.9 vs 759 rpm) is a self-consistent simulation. It is caveated on screen ("not measured on real tennis"). | Keep the caveat, or say "in simulation". |
| 28 | P3 | both | The repo name shown on slide 1, slide 10 and S12 ("…moneymachineouuushiii") will be read by Jane Street and Citadel judges. | Optional: rename (GitHub redirects the old URL). |

## Number trace

**Video.** All 166 on-screen values in `video_manifest.json` have a file and key. Re-running `build_values()` on
today's files changes only two of them:

- `peeks`: 51 → 60.
- `sess_status`: "QUOTING (paper)" → "warm-up…".

`fwd_verdict` and `engine_video` render as "pending", which is correct. The script's `{names}` all map to manifest
entries.

There are two kinds of exceptions:

- **Traced through a hard-coded constant.** `espn_s` 28.2 is `ESPN_BEHIND_BOOK` in `scripts/signal_decay.py:56`,
  copied from `research/v2/latency/RESULTS.md` (n = 40 games). It matches that file.
- **Not in the manifest at all.** These on-screen numbers are rule constants or literals: "16 blocks / 12,870
  splits", "0.95", "≥ 95% at 50 ms", "3× peak locked", and the "±3.6 mm" / "90 cm" text inside the replay asset.

**Deck.** The rebuild passes `run_checks()` and the build writes the deck. The repo URL on slide 1 is now
correct, and the earlier peek-count failure is gone. A manifest diff against `9e750a1` shows 7 changes, all of
them peeks or live-session fields. The build prints two warnings: NOTE.md quotes the peek log at 19 lines, and
the `pm_compute` clustered CI does not reproduce to 2 dp.

**Recomputed independently (15):**

| # | number (where) | recomputed from | result |
|---|---|---|---|
| 1 | v2 IS P&L $40,426, end value $68,728 (S06, s5) | sum of `lowloss/daily.csv` a/v2/u1_is; + capital $28,302 | $40,425.72; $68,728 ✓ |
| 2 | v2 IS Sharpe 14.5 (S06, s5) | daily P&L / capital, √365 | 14.483 ✓ (√252 would give 12.0; the convention is calendar days) |
| 3 | v2 IS max DD −2.0% (S06, s5) | running peak of cumulative daily P&L | −$569.5 = −2.012% ✓ |
| 4 | v2 OOS 6.7 Sharpe, −2.1% DD, $26,442 end (S06, s5) | same, u1_oos | 6.668, −2.063%, $3,687.54 + $22,754 ✓ |
| 5 | DSR OOS 0.48 / 0.07 (S07, s6) | Bailey–López de Prado, null variance 1/(T−1), skew and kurtosis of the daily series | N = 44: 0.4806; N = 3,386: 0.0748 ✓ |
| 6 | 74% lower bound, 27% recall (S04, s4) | Wilson 11/11; 11/41 | 11 / (11 + 1.96²) = 74.12%; 26.83% ✓ |
| 7 | 9/9 and 11/11 months (S03, s3) | the CSV rows; `summary.json` is+oos `h6_walkforward` | 9/9/9 (IS Dec–Aug); 8 IS (Dec–Jul) + 3/3 OOS = 11/11 ✓, but framed differently (#4b, #7) |
| 8 | Waterfall $282 − $86 = $196; −$167 → $29; OOS −$75 (S11, s9) | `financials.json`; fixed = ($5,000 + $77.42) × 12 / 365 | 196.24; 166.93; 29.31; −74.74 ✓ |
| 9 | Capacity bars (S11) | `financials.json` `scaling` | +62.1 / +92.2 / +82.5 / −24.5 $/day at $13.4k / $22.8k / $33.9k / $53.8k ✓ (wording #21) |
| 10 | Tier-0 stamp break-even 1.1 s (S09, s7, s20) | IS stamp curve | −1.756¢ at 1.0 s, +1.240¢ at 1.1 s, so the crossing is in (1.0, 1.1] ✓ |
| 11 | "$4.2 … 161 points, 5.7% per point" (s2) | `leverage_stats.json` | 161.19 × 5.716% = $9.21 ≠ $4.21 ✗ (#8) |
| 12 | Skew 0.53, kurtosis 4.3, worst day −1.9% (s13) | daily IS returns | 0.531 / 4.295 (bias-corrected) / −1.946% ✓ |
| 13 | Sharpe 9.8 / 4.3 / 3.0 under stress; OOS +½ tick +0.10¢ [−0.41, 0.63] (s13, s11) | `causal.json`, `cost_stress.json` | 9.76 / 4.34 / 2.99; +0.099 [−0.41, 0.63] ✓ |
| 14 | 270 bets/day; 3× peak locked $9.4k = $28.3k (s9, s13) | n_trades / days; peak_locked × 3 | 270.2; $9,434 × 3 = $28,302 ✓ |
| 15 | Peek log 45 (deck) / 51 (video) | non-empty lines of `results/oos_peeks.log` now | 60 ✗ (stale; #4a) |

**Labels and claims checked in deck and video:**

- **Counterfactual label.** It appears verbatim wherever tier-0 P&L appears: video S09 banner and S12; deck slides 7, 9 and 20.
- **No claim of real money.** Paper-only wording is on S06 ("end value (paper)"), S10 and S12, and deck slides 1, 5, 8 and 10.
- **Required failures.** Maker v1 blind OOS FAIL, fees ×2 OOS negative (−0.34¢) and U2 OOS FAIL are all shown in both.
- **Exceptions.** Missing failures: #1 and #19. Hype: #5, #6, #10, #17 and #18.

## Video QA

| scene | frame checked | legibility, overlap, typos | notes |
|---|---|---|---|
| S01 hook | 1.0, 3.0, 5.0–7.6, 8–11.5, 11.3 s | caption box dims the credit line (#13). P(miss) 0.99 → 0.00 after "MISS CALLED" (#5) | "REAL TIME", then "0.25× SLOW-MO REPLAY", labelled correctly. Title card readable |
| S02 economics | 29.0 s | "44.5 s behind" overlaps its subtitle (#12) | streams labelled "(assumed)"; feed price labelled "our assumption" |
| S03 evidence | 42.5 s | clean | in-sample only (#7) |
| S04 vision | 45.5, 52, 58.9 s | clean; two-line captions clear the credit | credit under the clip and inside the overlay |
| S05 tennis | 67, 73.9 s | clean; "SIMULATED PHYSICS" banner and caveat present | spin file untracked (#9) |
| S06 backtest | 95.6 s | the dashed IS/OOS divider crosses the "out of sample (burned) · 40 days" label | dense; needs a longer hold (#14) |
| S07 overfitting | 114.3 s | clean | DSR labels truncated (#4c); PBO 42% missing (#15) |
| S08 scoreboard | 128.0 s | clean | peeks 51 (stale); v1 and tier-0 v3 missing (#1, #19); "running tomorrow" (#11) |
| S09 tier0 | 152.5 s | the "break-even 1.1 s (stamp)" label starts at the 0.68 s line and reads as that line's label | banner exact ✓ |
| S10 live | 169.3 s | status dot renders dark grey beside "RUNNING" | stale session (#3) |
| S11 risk | 192.5 s | clean | kill switches match `docs/RISK.md` ✓ |
| S12 close | 203.8 s | clean | held 0.3 s (#14) |

- **Captions.** The SRT and the manifest agree on all 43 cues. Every cue start and end is within ±0.1 s of
  the speech onset and offset found by `silencedetect` (−40 dB, 40 ms). The single flag at cue 27 is a
  detector artifact. The captions are burned in, and the sidecar SRT is consistent with them.
- **Footage credit.** OpenTTGames (OSAI), CC BY-NC-SA 4.0 appears in S01, S04 and S12. Add "adapted" (#26).
  The synthetic narration voice is disclosed in S12.
- **Typos.** None found in the 26 frames read.

## Clean-clone re-runs (CLEAN_CLONE.md)

Fresh `git clone` of GitHub `597b0de` into the scratchpad. Core-only venv (`uv`, Python 3.13.12, `requirements.txt`; no
opencv). No `data/` and no `models/`.

| step | CLEAN_CLONE status | re-run today | verdict |
|---|---|---|---|
| F1 `bash run.sh help` | FAIL on `3d46204` (no run.sh) | exit 0 | **resolved on GitHub** |
| F2 `bash run.sh tests` on a core install | collection error (`No module named 'cv2'`); "still fails on GitHub until pushed" | prints the vision-skip notice; `tests/` collects; full run exit 0, 90 passed, 1 skipped (393 s) | **resolved on GitHub**: `8cd93a7` is now pushed, so the "push again" note in CLEAN_CLONE.md is out of date |
| F6 `bash run.sh money` | FAIL (needs `reproduce`) | `FileNotFoundError: … 'data/v2_trades_is_oos.parquet'`, exit 1 (1 min 51 s on the loaded laptop) | **still fails**, as documented in `run.sh help` |
| F8d CV calls from a clone | frozen call model not distributed | `models/vision/frozen_call_model.pkl` is on disk, not in `origin/main` | **still open** (#10) |

Full `run.sh tests` on the clean clone (core install, loaded laptop): exit 0, 91 tests run (90 passed, 1 skipped),
393 s. Vision tests were skipped with the notice, as designed.

## Fast path before the talk (≈5 min of machine time)

1. Wait until `results/tier0_v3/blind.json`, `results/spin/tennis/metrics_v2.csv` and the live summary are committed by their owners. Apply fixes 1–11 in `docs/deck/build_deck.py`, `scripts/make_video.py` and `docs/video_script.md`.
2. `.venv/bin/python scripts/make_video.py --stills --scenes S01,S02,S03,S08,S09,S10,S12` (≈7 s). Check the layout fixes.
3. `.venv/bin/python docs/deck/build_deck.py` (≈2 s), then `nice -n 10 .venv/bin/python scripts/make_video.py` (≈3 min; the narration audio is cached). Do both in the same minute, so the peek count and session status match.
4. Commit (not `data/` or `models/`), push, and confirm with `git ls-remote origin refs/heads/main`.
5. After the forward test, repeat step 3 only.

Why this has been slow: the laptop load average is 15–24 from parallel workflows (live paper trader, status
daemon, HiPerGator syncs, replays), so every render and test runs at 2–4× its normal time. The judge commands
themselves are fast (replay 7 s, deck 2 s). For the next check, re-run only the failing clean-clone steps (as
here), or render on HiPerGator with `hpg/run.sh`.
