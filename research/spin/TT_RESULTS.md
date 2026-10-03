# Spin-aware early call on table tennis: test results

Footage: **real match footage (OpenTTGames, held-out games; CC BY-NC-SA 4.0)**. It is not live match video
and has nothing to do with any Polymarket market. The model was trained on game_1..5. It was evaluated
**once** on test_1..7 (171 flights: 130 BOUNCE, 41 MISS) on 2026-10-03 at 21:36:58Z, and that run is logged in
`results/tracking/test_peeks.log` as the second model ever evaluated on this test set. The run log is in
`research/spin/TT_RUN.md`, and the numbers are in `results/spin/tt/test/`.

## Result in brief

- **On test, the spin model does not beat the frozen model.**
  - At 50 ms before contact (snapshot rule), the spin model is right on 10 of 12 calls: precision 0.83, 95% Wilson
    interval 0.55–0.95, recall 0.24. The frozen model is right on 11 of 11: precision 1.00 (0.74–1.00), recall 0.27.
  - The H3 bar is precision ≥ 0.95 at 50 ms. The frozen model passed it. **The spin model would fail it.**
  - Both models were scored on the same flights. The frozen model's re-run reproduces its published test scores
    exactly: largest difference 1e-16 on 170 flights.
- **With the online rule, it calls a few more misses early, plus one false call.**
  - By 50 ms, the spin model calls 6 misses with 1 false call. The frozen model calls 3 with none.
  - At any lead, the spin model calls 7 misses and the frozen model 8.
  - The models disagree on 7 misses: 3 are called only by the spin model, 4 only by the frozen model.
  - Of the 4 misses both models call, the spin model is earlier on 1 and later on 3; the median difference is 25 ms later.
- **Train CV had promised more.** Over game_1..5 leave-one-game-out, recall at 100 ms was 0.52 for the spin model
  against 0.25 for the frozen model. That gain did not carry over to test.
- **Spin readout looks plausible but cannot be checked.**
  - The median fitted topspin on test flights is 51 rps (3,060 rpm), with an interquartile range of 11–87 rps.
  - 93% of flights fall within ±150 rps, about the highest rate reported for table tennis. Typical rally topspin is
    80 to above 110 rps, and serves are 14–63 rps (sources below).
  - The typical 1σ is 18 rps per flight. OpenTTGames has no measured spin, so this is a range check, not a validation.

## 1. Precision and recall against lead, test_1..7 (pre-specified labels)

Each cell is hits/calls = precision (95% Wilson interval), then recall (95% Wilson interval). There are 41 MISS
flights. The spin model uses its frozen thresholds (τ = 0.9304 snapshot, 0.9879 online) and no horizon gate.
The frozen model uses its published thresholds (τ = 0.8854 / 0.9799) and a 0.10 s gate.

**Snapshot rule** (call if the score at exactly this lead is ≥ τ; this is the rule behind the H3 verdict):

| lead (ms) | spin: precision | spin: recall | frozen: precision | frozen: recall |
|---|---|---|---|---|
| 0 | 19/21 = 0.90 (0.71–0.97) | 0.46 (0.32–0.61) | 24/24 = 1.00 (0.86–1.00) | 0.59 (0.43–0.72) |
| 25 | 12/14 = 0.86 (0.60–0.96) | 0.29 (0.18–0.44) | 19/19 = 1.00 (0.83–1.00) | 0.46 (0.32–0.61) |
| **50** | **10/12 = 0.83 (0.55–0.95)** | **0.24 (0.14–0.39)** | **11/11 = 1.00 (0.74–1.00)** | **0.27 (0.16–0.42)** |
| 100 | 8/11 = 0.73 (0.43–0.90) | 0.20 (0.10–0.34) | 6/6 = 1.00 (0.61–1.00) | 0.15 (0.07–0.28) |
| 200 | 3/4 = 0.75 (0.30–0.95) | 0.07 (0.03–0.19) | 2/2 = 1.00 (0.34–1.00) | 0.05 (0.01–0.16) |

**Online rule** (a call is made once the score has stayed ≥ τ for 3 frames; the lead is when that happens):

| lead (ms) | spin: precision | spin: recall | frozen: precision | frozen: recall |
|---|---|---|---|---|
| 0 | 7/8 = 0.88 (0.53–0.98) | 0.17 (0.09–0.31) | 8/8 = 1.00 (0.68–1.00) | 0.20 (0.10–0.34) |
| 25 | 6/7 = 0.86 (0.49–0.97) | 0.15 (0.07–0.28) | 5/5 = 1.00 (0.57–1.00) | 0.12 (0.05–0.26) |
| **50** | **6/7 = 0.86 (0.49–0.97)** | **0.15 (0.07–0.28)** | **3/3 = 1.00 (0.44–1.00)** | **0.07 (0.03–0.19)** |
| 100 | 1/2 = 0.50 (0.09–0.91) | 0.02 (0.00–0.13) | 2/2 = 1.00 (0.34–1.00) | 0.05 (0.01–0.16) |
| 200 | 0/1 = 0.00 (0.00–0.79) | 0.00 (0.00–0.09) | 1/1 = 1.00 (0.21–1.00) | 0.02 (0.00–0.13) |

Every interval overlaps the other model's. With 41 misses and 2–24 calls per cell, none of these differences
is statistically clear. The one consistent pattern is false calls. The spin model makes them at every lead in
these tables (2 at 50 ms, snapshot; 1 online) and the frozen model at none of them; its only false call is at
150 ms, snapshot. The figure is `results/spin/tt/test/test_precision_vs_lead_spin.png`.

## 2. Which misses get called, and how early

The online rule is used here. Per-flight data: `results/spin/tt/test/test_flights_spin_vs_frozen.csv`.

| | spin | frozen |
|---|---|---|
| MISS flights called at any lead (of 41) | 7 | 8 |
| ... of those, called only by this model | 3 (leads 150, 50, 0 ms) | 4 (leads 25, 25, 17, 17 ms) |
| MISS flights called ≥ 50 ms before contact | 6 | 3 |
| BOUNCE flights called (false calls) | 1 (at 267 ms) | 0 |
| median first-call lead of the called misses | 75 ms (p10 30, p90 115) | 25 ms (p10 17, p90 210) |
| mean lead over all 41 misses (a miss never called counts as 0) | 12.4 ms | 17.5 ms |

- **Misses called by both models (4):**

  | flight | spin model | frozen model | difference |
  |---|---|---|---|
  | test_2 f_net 2760 | 83 ms | 125 ms | −42 ms |
  | test_2 f_net 2819 | 92 ms | 408 ms | −317 ms |
  | test_4 f_net 5750 | 75 ms | 83 ms | −8 ms |
  | test_6 f_net 3070 | 58 ms | 17 ms | +42 ms |

  The spin model is earlier on 1 of 4. The median difference is −25 ms.
- **So: "more misses called, earlier" holds only for the ≥ 50 ms online window.** There the spin model calls 3
  more misses and makes 1 more false call. Counted at every lead, it calls 1 miss fewer than the frozen model.
- **On the snapshot rule at 50 ms, the models swap a few calls.** The spin model adds 1 correct call and 2 false
  ones, and drops 2 correct calls.

**Post hoc, with the audited labels of DEVIATIONS H3-D10.** This is the same run, with no refit and the same τ.
The audit relabels 20 test MISS flights as unannotated bounces, leaving 21 misses.

- **Audited labels:**
  - Snapshot at 50 ms: spin model 9/11 calls correct (recall 0.43), frozen model 8/8 (recall 0.38).
  - Online by 50 ms: spin 5/6, frozen 3/3.
  - First calls: 5 misses each, both with a median lead of 83 ms.
- **Dropping the 5 "rally continues" flights as well:**
  - Snapshot at 50 ms: spin 8/10, frozen 7/7.
  - Online by 50 ms: spin 4/5, frozen 2/2.
- **Same picture:** the spin model gets slightly more recall but loses precision.
- **Some original "hits" are unannotated bounces:** two of the spin model's (test_5 f_net 5483 and test_6 f_net
  3070) and two of the frozen model's (test_1 f_net 2448 and test_3 f_net 5552).

## 3. Spin readout on the test flights

Spin is fitted at each flight's last decision frame, using the whole flight up to t_ref − 2 frames. 170 of
171 flights have a fit. Positive topspin means topspin and negative means backspin; 1 rps = 60 rpm. Data:
`results/spin/tt/test/test_spin_readout.csv`; figure: `fig_spin_readout_test.png`.

| | p5 | p25 | median | p75 | p95 |
|---|---|---|---|---|---|
| topspin, rps (all 170) | −64 | 11 | **51** (3,060 rpm) | 87 | 139 |
| sidespin, rps (all 170) | −13 | 11 | **27** (1,600 rpm) | 44 | 99 |
| 1σ of topspin, rps | 3 | 10 | 18 | 31 | 54 |
| topspin, rps, 86 flights with 1σ ≤ 20 rps | −26 | −1 | 21 | 46 | 82 |
| topspin at the 50 ms lead, rps | −31 | 17 | 49 | 74 | 113 |

- **Sign:** 64% of flights read as topspin at more than 2σ, and 7.6% as backspin at more than 2σ. That fits
  rally play built mostly on topspin strokes.
- **By label:** BOUNCE flights have a median of 53 rps (n = 130); MISS flights 26 rps (n = 40, wider spread).
- **Range check against published measurements:**
  - Rally topspin by skilled players: travel time to the receiver changes at 80 and 110 rps, and ≥ 110 rps is
    reached in play (Kidokoro, Inaba, Yoshida, Yamada and Ozaki, *Sports Biomechanics* 24(3), 2022/2025,
    doi:10.1080/14763141.2022.2156916).
  - Serves at the 2009 World Championships quarter-finals: 13.7–62.5 rps; men 46.0 ± 9.0 rps, women 39.2 ± 9.3
    (Yoshida, Yamada, Tamaki, Naito and Kaga, *Japan J. Phys. Educ. Health Sport Sci.* 59(1), 2014).
  - Spin "reaches 150 rps" (SICE JCMSI 18(1), 2025, doi:10.1080/18824889.2025.2466881).
- **Most fits are in range, and the tails show where the fit fails:**
  - 93% of topspin values and 99% of sidespin values are within ±150 rps.
  - The median (51 rps) and upper quartile (87 rps) sit between the published serve range and the rally range.
  - About 7% of flights read beyond ±150 rps, down to −230 rps for some MISS flights. These are fits the monocular
    track cannot pin down (large 1σ, many outliers). They are not real spins.
- **Two limits on calling this a validation:**
  1. OpenTTGames has no spin ground truth, so this checks plausibility, not accuracy.
  2. The fitted spin is a parameter of the lift model (C_L = S / (1 + 2S), slope 1 at low spin). If the real
     table-tennis lift curve is flatter or steeper, the spin magnitudes scale with it.

## 4. Train side (game_1..5, leave-one-game-out) and the gate question

Data: `results/spin/tt/dev/dev_report.json` and `train_gate_ablation.json`. These train precisions are
optimistic, because each τ is chosen on the same out-of-fold scores.

| snapshot rule | 25 ms | 50 ms | 100 ms | 200 ms |
|---|---|---|---|---|
| frozen (gate 0.10 s) | 67/72, R 0.61 | 60/63, R 0.55 | 28/29, R 0.25 | 8/12, R 0.07 |
| spin (no gate, as frozen for test) | 68/73, R 0.62 | 64/67, R 0.58 | 57/64, R 0.52 | 32/34, R 0.29 |
| no-spin physics ablation (gate 0.10 s) | 70/76, R 0.64 | 56/58, R 0.51 | 30/33, R 0.27 | 7/12, R 0.06 |

**The gate.** The verifier pointed out that the spin model gets no horizon gate while the frozen model keeps
0.10 s. Before the test run I ran a train-only ablation that gives every feature set its own τ at every gate:

| features | best gate (H3-D5 rule) | snapshot hits/calls at 50 ms with no gate | at 0.10 s gate | recall at 100 ms with no gate |
|---|---|---|---|---|
| frozen | 0.10 s | 36/37 | 60/63 | 0.30 |
| spin | none | 64/67 | 60/63 | 0.52 |
| no-spin physics | 0.10 s | 51/53 | 56/58 | 0.41 |

- **At the same 0.10 s gate, the spin model equals the frozen model at 50 ms** (60/63 each).
- **Without a gate, the frozen model gets worse** (36/37). So re-tuning the frozen model's gate would not have
  helped it.
- **On train, the gain came from calling without a gate**, that is, from making long extrapolations. The 3D physics
  fit made that possible, and the fitted spin added about 0.1 recall at 50–100 ms over the no-spin fit.
- **On test, the extra calls came with false calls** on two BOUNCE flights: test_1 f_net 15430 (snapshot at
  50 ms) and test_5 f_net 6984 (snapshot at 50 ms, and online at 267 ms). I did not check whether a 0.10 s gate
  would have blocked them; checking now would mean scoring a third model on test. Long single-camera
  extrapolations are where missing depth matters most (DEVIATIONS H3-D7).

## 5. Showcase flights (fitted 3D trajectories and spin)

Files are in `results/spin/tt/test/showcase/`: one `<video>_<f_net>.json` per flight, a QA still `.png`,
`index.json` and `candidates.csv`.

- **Each JSON holds:**
  - the tracked pixels;
  - every decision frame's fit (spin in rps and rpm with 1σ, speed, landing point, P(in/long/net/wide));
  - full 3D trajectories, also projected to pixels, at the 50 ms lead, at the spin model's first call and at
    t_ref, each continued to landing;
  - the same trajectories with spin switched off;
  - the camera and the table corners in pixels.
- **Reproduction:** the refit matches the features stored by the test run exactly (largest difference 0.0).
- **Selection was post hoc and for display only.**
  - Track: covers ≥ 90% of the flight and stays ≥ 60 px inside the image.
  - Fit at t_ref: rms ≤ 2.5 px and ≤ 15% outliers.
  - MISS flights must not have been questioned by the label audit.

| flight | label | what it shows | fitted spin at t_ref (rps) | first call, spin / frozen |
|---|---|---|---|---|
| test_5 f_net 902 | MISS (long) | spin-only early call | top +7 ± 4, side +16 | 150 ms / none |
| test_2 f_net 2819 | MISS (long) | both call; frozen much earlier | top +62 ± 17, side +25 | 92 ms / 408 ms |
| test_6 f_net 1484 | MISS (long) | frozen-only call; heavy topspin | top +146 ± 38, side +72 | none / 25 ms |
| test_7 f_net 9699 | MISS | neither model calls it | top −97 ± 37, side +20 | none / none |
| test_6 f_net 3381 | BOUNCE | clean topspin rally ball | top +45 ± 3, side +9 | none / none |
| test_4 f_net 30262 | BOUNCE | clean backspin (push) | top −21 ± 4, side +28 | none / none |

## Caveats

- **This is the second model evaluated on this test set.** The first (frozen) model's verdict stands. This run was
  pre-specified (`frozen_spec.json` was written before any test flight was loaded) and evaluated once.
- **The test labels are incomplete** (DEVIATIONS H3-D10). The tables in sections 1 and 2 use the pre-specified
  labels; the audited numbers are post hoc.
- **The test set is small.** With 41 misses and a handful of calls per cell, the intervals are wide.
- **Spin has no ground truth here.** The readout is model-dependent.

## Files

- `results/spin/tt/test/`:
  - `test_summary.json`, `report_numbers.json` (the tables above, with Wilson intervals);
  - `test_flights_spin_vs_frozen.csv`, `test_precision_vs_lead_spin{_snapshot,_online}.csv` and `.png`;
  - `test_spin_readout.csv`, `fig_spin_readout_test.png`;
  - `feats_test.pkl` (every physics feature row), `anchors_test.csv`, `cameras.json`;
  - `showcase/`.
- `results/spin/tt/dev/`: train-only outputs, including `train_gate_ablation.json`.
- `research/spin/tt_report.py` builds the tables and the spin figure from those files.
- `research/spin/tt_gate_ablation.py` is the train-only gate ablation.
- `scripts/cv_showcase_tt_fits.py` is the showcase refit.

## Sources

- Kidokoro S., Inaba Y., Yoshida K., Yamada K., Ozaki H. "A topspin rate exceeding 110 rps reduces the ball
  time of arrival to the opponent: a table tennis rally study." *Sports Biomechanics* 24(3).
  https://www.tandfonline.com/doi/full/10.1080/14763141.2022.2156916
- Yoshida K., Yamada K., Tamaki S., Naito H., Kaga M. "The rotation speed of the service ball delivered by
  world-class table tennis players." *Japan J. Phys. Educ. Health Sport Sci.* 59(1), 2014.
  https://www.jstage.jst.go.jp/article/jjpehss/59/1/59_13068/_article
- "High-speed spin measurement system for dotted table tennis ball using single-frame M-sequence
  multi-exposures." *SICE JCMSI* 18(1), 2025. https://www.tandfonline.com/doi/full/10.1080/18824889.2025.2466881
