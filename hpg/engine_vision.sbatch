#!/bin/bash
#SBATCH --job-name=engine-vision
#SBATCH --account=ai-workshop
#SBATCH --qos=ai-workshop
#SBATCH --partition=hpg-turin
#SBATCH --gpus=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=24gb
#SBATCH --time=00:45:00
#SBATCH --output=logs/%x_%j.log
# Streaming call engine on one GPU (paper only; nothing here can place an order).
#  1. engine/vision/export_frozen.py: rebuild the frozen H3 classifier exactly as early_call --final did and
#     ASSERT it reproduces results/tracking/test_flights.csv -> models/vision/frozen_call_model.pkl
#  2. stream held-out test_2 frames 2000-2999 (the clip the laptop uses) through the engine on the GPU:
#     realtime (120 fps arrivals) and max (flat out), BlurBall in torch fp16 as detect.py ran it
#     -> results/engine/vision_bench.json (+ results/engine/vision_events_<host>.jsonl)
# Before submitting, from the laptop repo root (HPG = ojasvamishra@hpg.rc.ufl.edu, ROOT below):
#   rsync -a -e "ssh -S ~/.ssh/cm-hpg" engine models/vision hpg/engine_vision.sbatch $HPG:$ROOT/ --relative
# After: rsync models/vision/frozen_call_model.pkl and results/engine/ back.
set -euo pipefail
ROOT=${ROOT:-/blue/ai-workshop/$USER/courtside}
module load pytorch/2.7
source "$ROOT/venv_track/bin/activate"
pip install -q threadpoolctl onnxruntime 2>/dev/null || true
cd "$ROOT"
mkdir -p logs results/engine models/vision
export TRACK_RESULTS=$ROOT/results/tracking OTTG_ROOT=$ROOT/openttgames BLURBALL_ROOT=$ROOT/ext/blurball
cp -n "$ROOT/ext/blurball/weights/blurball_best" models/vision/blurball_best || true
python engine/vision/export_frozen.py
GPU=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1 | tr ' ' '_')
for B in torch-cuda torch-cuda-fp32; do
  python -m engine.vision.run_demo --backend $B --blurball_root "$BLURBALL_ROOT" \
      --source "$ROOT/openttgames/test_2.mp4" --frame-offset 0 --start-frame 2000 --max-frames 1000 \
      --video test_2 --host "hpg-$GPU" --modes realtime,max
done
nvidia-smi
