# Ball tracking and the H3 early-call test

This folder tests pre-registered hypothesis **H3** (`HYPOTHESIS.md`) on OpenTTGames: can a MISS (out or net)
be called from the ball's trajectory with at least 95% precision 50 ms or more before contact? The analysis
uses game_1..5 for development and evaluates test_1..7 once. Results go to `results/tracking/`. Deviations
from the pre-registration are listed in `DEVIATIONS.md` (H3 section).

## Reused open-source code (not reimplemented)

- **Ball detector:** [BlurBall](https://github.com/cogsys-tuebingen/blurball) (Gossard, Radovic, Ziegler, Zell,
  *BlurBall: Joint Ball and Motion Blur Estimation for Table Tennis Ball Tracking*, CVPRW 2026, arXiv:2509.18387,
  MIT licence), commit `2f0f549`. We use their pretrained table-tennis weights (`blurball_best`, from their public
  Nextcloud share) zero-shot. BlurBall is an HRNet heatmap model with 3 frames in and 3 out, built on
  [WASB-SBDT](https://github.com/nttcom/WASB-SBDT) (Tarashima et al., BMVC 2023). Their WASB table-tennis weights
  (`wasb_midpoint_best`) were also compared, on game_1/game_2 only. We import their model code (`src/models`);
  `detect.py` only adds frame streaming, heatmap averaging and blob extraction.
- We looked at [TTNet-Pytorch](https://github.com/maudzung/TTNet-Real-time-Analysis-System-for-Table-Tennis-Pytorch)
  (an unofficial TTNet implementation for OpenTTGames). It publishes no weights, and the pretrained BlurBall
  model was already accurate on the OpenTTGames labels (about 96% of frames within 5 px), so we did not train
  anything.
- Data: [OpenTTGames](https://lab.osai.ai/) (Voeikov, Falaleev, Baikulov, *TTNet*, CVPRW 2020), CC BY-NC-SA 4.0.

## Pipeline (HiPerGator; run from `hpg/` on the login node, all heavy work goes through sbatch)

```bash
ROOT=/blue/ai-workshop/$USER/courtside        # repo src/ and hpg/ are rsynced here; data in $ROOT/openttgames
cd $ROOT/hpg
sbatch download_openttgames.sbatch            # 0. videos + markup (34 GB), ~1 h
sbatch track_setup.sbatch                     # 1. venv on pytorch/2.7, clone BlurBall @2f0f549, weights, ~5 min
cd $ROOT/src/tracking && python3 make_chunks.py 12000 && cd $ROOT/hpg
                                              # 2. rally frame ranges -> 29 chunks (pure python, seconds)
sbatch --array=1-29%3 track_detect.sbatch     # 3. detector on 273k rally frames, 3 L4 GPUs at a time
STAGE=dev sbatch track_analyze.sbatch         # 4. tracks, flights, train accuracy, LOGO model selection, spot check
STAGE=final sbatch track_analyze.sbatch      # 5. ONE test evaluation (HGB, gate 0.10 s, frozen) -> results/tracking/*
cd $ROOT/src/tracking                         # 6. POST-HOC (after step 5), CPU, ~1 min each, via srun:
python spotcheck.py --audit-test              #    picture of the test flights called MISS at 50 ms
python audit_labels.py                        #    unannotated-bounce audit, frozen model re-scored
python summarize.py && python plots.py        #    summary.json; redraw precision_vs_lead.png from saved curves
```

Step 5 appends a line to `results/tracking/test_peeks.log` every time it runs. It was run once.

## Files

| file | what it does |
|---|---|
| `common.py` | paths, markup loading, table geometry from the segmentation masks (R = table, G = humans, B = scoreboard), rally ranges |
| `make_chunks.py` | splits the rally frame ranges (annotated events ±1.5–2.5 s) into GPU chunks |
| `detect.py` | streams frames with PyAV, runs BlurBall over sliding triplets (step 1, fp16), averages the 3 heatmaps per frame, keeps up to 3 blobs per frame |
| `trajectories.py` | causal constant-velocity gating that turns per-frame blobs into one ball track |
| `eval_detection.py` | recall, precision@10 px, % within 5/10 px against `ball_markup.json` |
| `flights.py` | one flight per shot (anchored at its `net` event); label BOUNCE / MISS(out, net); reference time T_ref; flight start t0 |
| `early_call.py` | prefix features (robust quadratic arc in table-normalised image coordinates, extrapolated to the table levels, net and end line), models, LOGO CV, threshold, test evaluation |
| `plots.py`, `spotcheck.py`, `extract_frames.py` | figures |
| `audit_labels.py` | post-hoc: finds test flights labelled MISS whose bounce is missing from the markup, and re-scores the frozen model on corrected labels |
| `summarize.py` | writes `results/tracking/summary.json` |

## Definitions used in the test

- **Flight:** every shot that reaches the net plane. OpenTTGames' `net` event marks that frame on every shot,
  not only net touches. **BOUNCE** means a far-side `bounce` event follows within 0.5 s, and T_ref is the bounce
  frame. **MISS** means no such bounce follows. A MISS is a net hit if the ball stops at the net (T_ref = net
  frame); otherwise it is out, and T_ref is the frame where the ball passes the table end line, drops below the
  near edge, or is lost.
- **Decision at frame t** uses track points in [t0, t − 2] only. The detector's 3-frame window gives a 2-frame
  look-ahead, and this offset removes it.
- **Online call (primary):** a MISS is called by lead L if P(miss) ≥ τ at some decision frame ≤ T_ref − L.
  τ is frozen from leave-one-game-out predictions on game_1..5. It is the smallest threshold whose train
  precision at 50 ms is ≥ 95% and stays ≥ 95% for every higher threshold that still makes at least 5 calls.
- **H3 verdict:** PASS iff the test precision of MISS calls at the 50 ms lead is ≥ 0.95 under the snapshot rule.
  The decision is made at exactly T_ref − 50 ms. Model and gate were selected by leave-one-game-out CV on
  game_1..5 (DEVIATIONS.md H3-D5).

## Results (test_1..7, evaluated once)

- Detection, tracked, pooled over labelled frames: train recall 0.960, 94.1% within 5 px, 95.5% within
  10 px; test recall 0.967, 94.0% within 5 px, 96.0% within 10 px. Precision@10 px is 0.98 on both.
- Flights: train 1,059 BOUNCE / 110 MISS; test 130 / 41 as labelled (150 / 21 after the post-hoc audit).
- MISS-call precision at the 50 ms lead (snapshot): **11/11 = 1.00** (Wilson 95% CI 0.74–1.00), recall 0.27.
  **H3: PASS by the pre-registered rule**, on thin evidence. Audit-corrected labels give 8/8, recall 0.38.
- Online first call, i.e. what a trader acting on the first call gets: precision 1.0, but it rarely fires
  early. Test recall at 50 ms is 7%. The median lead on the 8 called test misses is 25 ms (p10 17 ms,
  p90 210 ms). Train OOF: recall 30% at 50 ms, median lead 83 ms.
- The lead grows with how far out the ball lands. It does not grow with ball speed. See `summary.json`.
