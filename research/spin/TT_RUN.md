# Table-tennis spin model: run log (HiPerGator, 2026-10-03)

Footage: real match footage (OpenTTGames, held-out games; CC BY-NC-SA 4.0). Code: `src/spin/tt_*.py`,
`hpg/spin_tt.sbatch`. Results: `results/spin/tt/dev/` (train only) and `results/spin/tt/test/` (the single
test evaluation). Write-up: `research/spin/TT_RESULTS.md`.

## 1. Verifier review (workflow wf_057b300e-128, step `verify:spin`, result read 17:30 EDT)

The verifier found **no test-set leakage** in the table-tennis pipeline and listed no defect in
`src/spin/tt_*` that blocks the run. **No code in `src/spin/` was changed.** The six `tt_*.py` files on
HiPerGator are byte-identical (md5) to the laptop copies the verifier reviewed. How each item was handled:

| verifier item | blocking? | what was done |
|---|---|---|
| Plumbing test ran on the test_2 video and masks (no labels, no metric) before a `tt_features.py` edit | no | Logged here. No change to the model. The masks are an allowed input under DEVIATIONS H3-D8(a). |
| A dev run appeared while it was checking (`results/spin/tt/dev/`, 17:11–17:22) | no | That was this run's train-only dev stage (job 44611964, below). |
| Train camera focal lengths are 1317–1390 px, not the 1324–1384 px the builder quoted | no | Corrected in TT_RESULTS.md: f = 1317–1390 px on game_1..5 (edge fit). |
| The spin model's advantage depends on the re-chosen gate (spin: none, frozen: 0.10 s); the frozen model was never tried without a gate | no (attribution) | Train-only ablation run **before** the test stage: `research/spin/tt_gate_ablation.py` → `results/spin/tt/dev/train_gate_ablation.json`. See section 3. The test stage still evaluates only the pre-specified spin model. |
| Train precision is quoted at a threshold picked on the same OOF predictions (optimistic) | no | Stated in TT_RESULTS.md. |
| `--final` does not check `train_feature_hash` | no | Not added (no code change). The final stage reused the dev-stage `feats_train.pkl` cache: its log has no "physics fits for 1169 train flights" line. It also re-ran the train CV and reproduced τ and the gate, or it would have stopped. |
| Test features are built up to the later of the original and audited T_ref | no | Features only look backwards. Audited-label scores are reported as post hoc. |

## 2. Runs

Everything ran from the HPG project directory `/blue/ai-workshop/ojasvamishra/courtside`, which holds the
videos, markup, BlurBall tracks (`work/tracking/tracks`), `flights.csv` and `table_geometry.json`. The
`courtside_repo` mirror has no `work/tracking`, so `hpg/spin_tt.sbatch` was used unchanged with its
default `ROOT`. Only `src/spin/{__init__,tt_*}.py`, `hpg/spin_tt.sbatch`, `scripts/cv_showcase_tt_fits.py` and
`research/spin/tt_gate_ablation.py` were synced up. The frozen code (`src/tracking/{early_call,common,flights}.py`),
`results/tracking/test_flights{,_audited}.csv` and `results/tracking/test_peeks.log` were identical on
both sides before the run (md5).

| step | job | what | split |
|---|---|---|---|
| dev | 44611964 (8 CPUs, 11 min) | cameras game_1..5, physics fits of 1,169 train flights (48,096 decision frames), LOGO CV, gate + τ frozen in `frozen_spec.json` | train only |
| smoke | 44613070 | `scripts/cv_showcase_tt_fits.py --split train` (checks the showcase refit; reproduces the stored features exactly) | train only |
| gate ablation | srun | `research/spin/tt_gate_ablation.py` | train only |
| final | 44614275 | `STAGE=final`: cameras test_1..7, the guard, then ONE evaluation of the spin model on test_1..7 | test (once) |
| showcase | srun | `scripts/cv_showcase_tt_fits.py` on 6 test flights, after the evaluation; no metric | test (display only) |

Frozen at the end of dev (`results/spin/tt/dev/frozen_spec.json`, 21:22:52Z): spin model = HGB on 23 frozen +
40 physics/spin features, gate = none (∞), τ_snapshot = 0.9304, τ_online = 0.9879, train feature hash
396d9b6f3e2c7543. The frozen model's τ came out as 0.8854 / 0.9799, the same as its published values.

## 3. Train-only gate ablation (before the test stage)

`results/spin/tt/dev/train_gate_ablation.json` uses LOGO on game_1..5. Every feature set and gate pair gets its
own τ.

| snapshot at 50 ms | gate none | 0.25 s | 0.15 s | 0.10 s |
|---|---|---|---|---|
| frozen features | 36/37 | 36/37 | 36/37 | 60/63 |
| spin features | 64/67 | 63/66 | 64/67 | 60/63 |
| no-spin physics | 51/53 | 51/53 | 51/53 | 56/58 |

Under the H3-D5 rule the frozen features would still choose 0.10 s, so re-tuning the frozen model's gate would
not have helped it. On train, the spin model's extra recall needs the ungated operation, and the physics fit is
what makes that operation work. Nothing in `frozen_spec.json` changed.

## 4. The test stage (job 44614275, 3 min 39 s)

- **The guard passed.**
  - `frozen_spec.json` was present.
  - The train CV was re-run from the dev cache and reproduced τ = 0.9304 / 0.9879 and gate = ∞.
  - `test_peeks.log` had no `[spin_tt]` line, and the stage then appended one before loading any test flight:
    `2026-10-03T21:36:58.718087Z final evaluation on test_1..7 model=hgb_spin (SECOND model evaluated on test: ...) [spin_tt]`
  - The log now has exactly two lines: the frozen model's run at 10:57:29Z and this one. The HPG copy was synced
    back to `results/tracking/test_peeks.log`.
- **Test cameras for test_1..7** came from the segmentation masks, as allowed by H3-D8(a).
- **Test physics fits:** 171 flights, 6,324 decision frames, median 1.3 s per flight. Anchors: incoming 126,
  bounce 26, none 19.
- **The frozen model reproduced exactly:** largest difference in p(MISS) at 50 ms against
  `results/tracking/test_flights.csv` is 1.1e-16 (170 flights).
- **Outputs** were copied to `results/spin/tt/test/`. The job log is in `results/spin/tt/test/logs/`, which git
  ignores.

## 5. After the evaluation (no metric, no refit of any classifier)

- **Tables and figure.** `research/spin/tt_report.py` builds `report_numbers.json`, `test_spin_readout.csv` and
  `fig_spin_readout_test.png`. It only re-tabulates the test-stage outputs, adding Wilson intervals for recall
  and per-flight lead comparisons.
- **Showcase refit.** `scripts/cv_showcase_tt_fits.py` re-ran the online physics fit on 6 test flights, chosen by
  the display rules in its docstring (the test labels and the audit file were read for that choice). It
  computes no metric. The refit reproduces the stored test features exactly. The first version picked only one
  MISS flight, because its outlier rule (0% outliers) was too strict, and one flight left the top of the image.
  The rules were loosened and given an in-image margin, and the script was re-run. Output:
  `results/spin/tt/test/showcase/`.
- **Commit history.** A separate commit (62a5b07, the spin workflow's) had already committed
  `results/spin/tt/dev/` from this run's dev stage. This run's commit adds `train_gate_ablation.json`, the
  test outputs, these notes and the scripts.
