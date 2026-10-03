#!/usr/bin/env bash
# Fetch the pretrained BlurBall table-tennis detector (Gossard et al., cogsys-tuebingen/blurball, MIT code)
# from the authors' public share, then export the ONNX files the engine uses. Weights are not committed.
#   bash scripts/get_models.sh        (needs requirements-extra.txt for the ONNX export: torch, onnx)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
mkdir -p models/vision ext
[ -s models/vision/blurball_best ] || curl -fsS -u 6Z8TpM3sXRKHzGC: -o models/vision/blurball_best \
    https://cloud.cs.uni-tuebingen.de/public.php/webdav/blurball_best
[ -d ext/blurball ] || git clone -q https://github.com/cogsys-tuebingen/blurball.git ext/blurball
(cd ext/blurball && git checkout -q 2f0f5496f7ba4b5b1a36790749935121b2ce972d)
[ -s models/vision/blurball_best_b1_fp16.onnx ] || $PY -m engine.vision.export_onnx --blurball_root ext/blurball \
    --weights models/vision/blurball_best --out models/vision/blurball_best.onnx
ls -la models/vision
