# Tennis ball tracking: how early can broadcast video call a ball out?

Question: from single-camera broadcast video (25–30 fps), how many ms before the bounce can the
tracked trajectory call a ball OUT, and how far off is the predicted landing point? How does that
compare with the Hawk-Eye-class physics Monte Carlo (`src/hawkeye.py`, `results/hawkeye_tennis_calls.csv`:
340 fps, 3.6 mm noise)?

All numbers are in `results/tennis_tracking/summary.json`; the `headline` and `comparison_to_hawkeye`
blocks are the short version.

## Short answer (test games 8–10, 132 bounces, 11 outs; thresholds and model choices from games 1–7)

| lead before bounce | 0 ms | 33 | 67 | 100 | 150 | 200 | 300 |
|---|---|---|---|---|---|---|---|
| Median landing error, best broadcast predictor (cm) | 16 (ground) | 56 (ground) | 76 (learned) | 83 (learned) | 91 (learned) | 101 (learned) | 120 (learned) |
| Callable margin at 95%, broadcast (cm)¹ | 14 | 32 | 57 | 59 | 47 | 46 | 78 |
| Callable margin at 95%, Hawk-Eye MC (1.645 SD, cm) | – | 1.2 (25 ms) | – | 3.9 | 6.5 | 9.5 | 17.5 |
| Out calls, "ground" predictor, test (correct / made) | 5/5 | 3/3 | 3/3 | 2/4 | 1/7 | 0/6 | 0/6 |

¹ 95th percentile of the error in the predicted signed distance to the line, using the better of
the two broadcast predictors at each lead. The model behind each column differs.

* Broadcast tracking can call an out at about 95% precision only within about one frame of the bounce.
  Train precision is 100% at 0 ms, 75% at 33 ms and 33% at 67 ms. Test precision is 5/5, 3/3 and 3/3
  (Wilson 95% CI lower bound 0.44–0.57). From 100 ms on, calls are no better than a coin flip. The
  rule is the margin rule with the "ground" predictor (below).
  First-call lead of the called test outs, counting only leads that held 95% on train: median, p10
  and p90 all 0 ms (5 of 10 outs called). Allowing every lead: median 67 ms, p10 0, p90 130 ms,
  but calls at 100 ms or more are mostly wrong.
  The online rule (one threshold, call at the first frame past the net) and the per-lead
  snapshot rule never reach 95% precision on train for any predictor before the bounce, so they make
  no test calls. The outs called at 0 ms landed 22–193 cm out; at 33–67 ms only the 63–193 cm ones
  were called. Test outs landed 1, 2, 8, 11, 22, 26, 28, 63, 63 and 193 cm out, and 6 of the 7 train
  outs within 35 cm. Balls that close cannot be called before the bounce at broadcast quality.
* Landing-point error is about 0.7–1.2 m median from 33 to 300 ms before the bounce. Hawk-Eye-class
  tracking is at 0.7–10.7 cm. The 95% callable margin is 4–27× wider (≈27× at 25–33 ms, ≈15× at
  100 ms, ≈5× at 200 ms, ≈4.5× at 300 ms). On broadcast the error hardly grows with lead: it is set
  by the single camera's depth ambiguity and the 25–30 fps sampling, not by extrapolation. That is
  why the gap closes at long leads.
* The fully automatic chain (TrackNet detector instead of the human labels) is about as good. Median
  landing error is 71–116 cm (learned) and out calls are 5/5, 3/3 and 3/4 at 0/33/67 ms. The detector
  reaches precision 0.97 and recall 0.94 within 5 px of the labels on the test games, median error
  1.4 px. The detector saw frames from these games in training (see Caveats).

## Data, code and weights (sources and licences)

| What | Source | Licence / terms |
|---|---|---|
| TrackNet tennis dataset: 10 broadcast matches, 95 clips, 19,835 frames at 1280×720, per-frame ball x, y, visibility, hit/bounce flags | Huang et al., *TrackNet*, AVSS 2019 ([arXiv:1907.03698](https://arxiv.org/abs/1907.03698)), NCTU. Downloaded from the Google Drive folder linked in the yastrebksv/TrackNet README (`11r0RUaQHX7I3ANkaYG4jOxXK1OYo01Ut`, `Dataset.zip`, 2.56 GB) | No licence file; released for research. The frames are TV broadcast images, so they are not redistributed here (only derived labels and statistics). |
| Ball detector TrackNet weights (`model_best.pt`) + model and post-processing code | [yastrebksv/TrackNet](https://github.com/yastrebksv/TrackNet) @ `730ea17`, weights GDrive `1XEYZ4myUN7QT-NeBYJI0xteLsvs-ZAOl`; code imported from [yastrebksv/TennisProject](https://github.com/yastrebksv/TennisProject) @ `b7552e9` (`ball_detector.py`, `tracknet.py`) | No licence file in either repository (all rights reserved by default). Used unmodified for a non-commercial research evaluation. Not vendored or redistributed. |
| Court keypoint detector weights (14 keypoints) | [yastrebksv/TennisCourtDetector](https://github.com/yastrebksv/TennisCourtDetector) @ `e5cd4f1`, GDrive `1f-Co64ehgq4uddcQm1aFBDtbnyZhQvgG`; `refine_kps` from TennisProject `postprocess.py` | No licence file. Same treatment. |

No video was scraped. Nothing under `data/` or any weights is committed. The Drive folder also holds
TennisProject's CatBoost bounce model (`ctb_regr_bounce.cbm`). It is not used: bounces come from the
labels.

## Commands, in order (HiPerGator; account `ai-workshop`, at most 2 GPUs)

```bash
# 0. copy code + scripts to /blue (ROOT=/blue/ai-workshop/$USER/courtside/tennis)
REPO="<path to courtside repo>"
rsync -a --exclude __pycache__ -e "ssh -o ControlPath=~/.ssh/cm-hpg" "$REPO/src/tennis_tracking" \
    ojasvamishra@hpg.rc.ufl.edu:/blue/ai-workshop/ojasvamishra/courtside/tennis/src/
rsync -a -e "ssh -o ControlPath=~/.ssh/cm-hpg" "$REPO"/hpg/tennis_*.sbatch \
    ojasvamishra@hpg.rc.ufl.edu:/blue/ai-workshop/ojasvamishra/courtside/tennis/hpg/
# then on HiPerGator, from $ROOT:
sbatch hpg/tennis_setup.sbatch    # CPU, ~5 min: venv on pytorch/2.7, clone 3 repos @ pinned commits,
                                  #   gdown weights + dataset (2.6 GB), unzip -> data/tracknet_unz/Dataset
sbatch hpg/tennis_detect.sbatch   # GPU array 1-10%2 (L4), ~4 min/game: TrackNet ball + court keypoints
                                  #   on every frame -> work/detect/game{g}_Clip{c}.npz
sbatch hpg/tennis_eval.sbatch     # CPU 16 cores, ~15 min: prep, detacc, tune (train only), final
# 4. copy the small results back into the repo
rsync -a -e "ssh -o ControlPath=~/.ssh/cm-hpg" \
    ojasvamishra@hpg.rc.ufl.edu:/blue/ai-workshop/ojasvamishra/courtside/tennis/results/tennis_tracking/ \
    "$REPO/results/tennis_tracking/"
```

The evaluation only needs the `Label.csv` files and `work/detect/*.npz` (~20 MB), so it also runs
on a laptop. The committed results came from that route on a 10-core Mac (Python 3.14, numpy 2.5,
numba 0.68, scikit-learn 1.9):

```bash
rsync -a -e "ssh -o ControlPath=~/.ssh/cm-hpg" --include='*/' --include='Label.csv' --exclude='*' \
    ojasvamishra@hpg.rc.ufl.edu:/blue/ai-workshop/ojasvamishra/courtside/tennis/data/tracknet_unz/Dataset/ LABELS/
rsync -a -e "ssh -o ControlPath=~/.ssh/cm-hpg" \
    ojasvamishra@hpg.rc.ufl.edu:/blue/ai-workshop/ojasvamishra/courtside/tennis/work/detect/ DETECT/
pip install numpy scipy pandas opencv-python-headless matplotlib numba scikit-learn
python src/tennis_tracking/run_eval.py --labels LABELS --detect DETECT --work WORK \
    --out results/tennis_tracking --stage prep detacc tune final
```

**Reproducibility check.** `tennis_eval.sbatch` was re-run on HiPerGator (job 44555788, 3 min 45 s
on 16 cores; Python 3.12, numpy 2.3, sklearn 1.9.1, numba 0.68):
* Flights, ground truth and the tuning choice match. The `ground` and `phys3d` numbers and calls are
  identical.
* The `learned` medians move by up to 8 cm (e.g. 84.5 vs 79.2 cm at 0 ms) and a few of its test calls
  flip. Read the learned numbers as ±~8 cm.

## Method

Files: `detect.py` runs the detectors. `geometry.py` holds the court model, homography and camera.
`events.py` builds the flights and the ground truth. `fit3d.py` is the 3D fit. `learn.py` is the
learned predictor. `run_eval.py` runs the stages. `plots.py` draws the figures.

1. **Court calibration.** The TennisCourtDetector keypoints are found on every frame. Each frame gets a
   RANSAC homography, its reprojected keypoints are taken to a per-clip median, and one homography
   is fitted from them (all ground-plane mapping uses it). A pinhole camera (f, R, t; principal point
   at the image centre; no distortion) comes from the homography plus `cv2.calibrateCamera`. Sanity
   check: game 1 has the camera 32.8 m behind centre court and 8.6 m up, and the net-cord projects
   to within ~2 px of where it is in the frame. 45 flights are dropped, all from game 4 (train), whose
   camera moves (keypoint drift above 3 px).
2. **Effective frame rate.** Each clip's serve toss is fitted with a parabola, using only pre-serve
   frames and so no outcomes. At the nominal 30 fps the toss implies g ≈ 14–16 m/s² in 7 of the 8
   games that have a usable toss. The frames are really ≈25 fps (PAL broadcasts), and serve flight times fit that too.
   Each game snaps to 25 or 30 fps (game 3 → 30 from 2 tosses; games 7 and 10 have no usable toss
   and default to 25). All leads in ms use this rate.
3. **Flights and ground truth.** A flight runs from a labelled hit to the next labelled event, kept
   if that event is a bounce: 444 flights in total, 399 usable. The bounce time and image point are
   sub-frame, taken where straight-line fits to the labelled track over 3 frames before and 3 after
   meet. The point is mapped to the court through the homography, with a camera-based correction for
   the ball radius. A serve is the first hit of a clip (or a hit after ≥1 s with no event), made from
   behind a baseline and bouncing within 17.5 frames. Serves are judged against the diagonal service
   box and everything else against the singles lines. The signed out-distance is metres beyond the
   nearest line crossed.
4. **Predictors.** All are causal: the decision at frame k uses only frames up to k.
   * `ground`: the last tracked point back-projected to the ground. Exact at the bounce, and the
     error grows with the ball's height.
   * `phys3d`: a monocular 3D ballistic fit with gravity, Cd = 0.55 drag and a free Magnus term
     (as in `hawkeye.py`). Priors sit on the spin and the hit height. It uses a multi-start robust
     least-squares fit and integrates to the ground. Hyper-parameters were tuned on games 1–7
     (`tuning_train_only.csv`).
   * `learned`: gradient boosting (sklearn HGB, absolute loss, fixed hyper-parameters) on court-frame
     kinematics plus the phys3d outputs. It predicts the landing offset from the `ground` point.
     Predictions for games 1–7 are leave-one-game-out out-of-fold. One model trained on 1–7 predicts
     8–10.
   * Primary predictor: the lowest mean median error on train, which is `learned`.
5. **Calls.**
   * Margin rule (the headline): call OUT at lead L if the predicted out-distance exceeds τ(L), the
     95th percentile of the train error at that lead. This uses all train bounces, not only the 7 outs.
   * Snapshot rule: a per-lead τ with train precision ≥95%.
   * Online rule: one τ, called at the first frame after the ball crosses the net.
   * The first-call lead of each true out is reported as median, p10 and p90.
6. **Test.** Games 8–10 were evaluated once with everything frozen. Both the human-label track and
   the TrackNet track are reported.

## Caveats (what is flaky)

* **Very few outs.** 7 in train and 11 in test (9 rally, 2 serve), so every precision figure rests on
  1–7 calls; the Wilson CIs are in `summary.json`. Landing error rests on all 399 bounces and is the
  sturdier result.
* **Label noise.** Labels have ±1–2 px noise, which is 5–20 cm of depth at the far baseline (about
  10 cm/px there). Ground truth is no better than that, and near-line in/out labels are uncertain.
* **Detector leakage.** The TrackNet weights were trained on a random 70% of frames from all 10
  games, test games included. The detector numbers are in-distribution and flatter it on new footage.
  The court-detector training set is unrelated YouTube highlights.
* **Effective fps.** The frame rate is inferred, not given. If game 3 is really 25 fps, its leads are
  20% off.
* **phys3d.** The monocular 3D fit fits the image within ~1 px but lands 1.2–1.6 m off (median).
  Spin and depth trade off against each other on a single camera at 25 fps. The fitter is right on
  synthetic data (≈20 cm at 1 px noise), so the limit is in the data, not a bug.
* **learned.** It regresses to typical landing spots, so it under-predicts long balls and seldom
  calls outs (`example_trajectory.png`: a ball 1.9 m long is predicted in). It is the best on median
  error and poor for out calls; `ground` is the reverse within about 67 ms.
* **Development history (honest log).** One full run, including the test scoring, was done before
  two ground-truth fixes:
  1. Serve detection. In 6 train clips the first labelled hit was not the serve, which made bogus
     "serve faults" out by 2–3 m.
  2. Homography-based ground mapping. The camera-rms cut was relaxed from 2 to 5 px after it dropped
     22 test flights in game 10 (static camera, ~3 px pinhole misfit). This was a data-coverage
     decision; no outcomes were looked at.

  Only train numbers were read from that run, but the test median-error figure was glimpsed. After
  the final test scoring only reporting changed: figures, the headline block, CSVs, per-out
  first-call leads, and a stricter "≥3 train calls" condition for the "max lead at 95%" field.
  Models, thresholds and data were not touched.

## Outputs (`results/tennis_tracking/`)

* `summary.json`: dataset and split, detector accuracy, bounce counts and base rates, landing error
  vs lead for every predictor, source and split, out-call tables (snapshot, online and margin
  rules), first-call leads, the Hawk-Eye comparison and the headline.
* `lead_vs_error.png`: callable margin vs lead (broadcast vs Hawk-Eye MC) and median landing error
  per predictor.
* `example_trajectory.png`: a test rally ball landing 1.9 m long, its track in the image (labels vs
  TrackNet) and the landing predictions from 300 ms to 0 ms.
* `flights.csv` (per-flight ground truth), `predictions_at_leads.csv` (per flight × lead × predictor
  × source) and `tuning_train_only.csv`.
