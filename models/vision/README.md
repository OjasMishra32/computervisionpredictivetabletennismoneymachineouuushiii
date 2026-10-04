# models/vision

`frozen_call_model.pkl` (12 MB) is our own early-call classifier for the streaming engine (`engine/run.py --frozen`).
It is committed so judges can reproduce the CV calls without HiPerGator.

- **What it holds:** the fitted gradient-boosting model, its frozen training matrix, test decision samples, table
  geometry and test tracks. It was built by `engine/vision/export_frozen.py`, which asserts it reproduces
  `results/tracking/test_flights.csv` before writing. It holds no video frames.
- **Data licence:** features and tracks are derived from OpenTTGames (OSAI), CC BY-NC-SA 4.0. This file is shared
  under the same terms, with attribution, for non-commercial research use.
- **Not committed:** the BlurBall detector weights (third-party; `blurball_best*`). Fetch them with
  `bash scripts/get_models.sh`.
