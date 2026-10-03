#!/bin/bash
#SBATCH --job-name=engine-vision
#SBATCH --account=ai-workshop
#SBATCH --qos=ai-workshop
#SBATCH --partition=hpg-turin
#SBATCH --gpus=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32gb
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x_%j.log
# Streaming call engine on one GPU (paper only; nothing here can place an order). Submit from $ROOT:
#   STAGE=bench sbatch hpg/engine_vision.sbatch    # benchmark  -> results/engine/vision_bench_gpu.json
#   STAGE=eval  sbatch hpg/engine_vision.sbatch    # test set   -> results/engine/online_vs_offline.json
# (two jobs = two GPUs, the account limit; STAGE=all runs both in one job)
#  0. engine/vision/export_frozen.py (if the pickle is missing, or STAGE=export): rebuild the frozen H3
#     classifier as early_call --final did and ASSERT it reproduces results/tracking/test_flights.csv
#     -> models/vision/frozen_call_model.pkl (CPU only; done as its own job 44603438 on 2026-10-03)
#  1. bench: test_2 frames 2000-2999 (the laptop clip) decoded from the 120 fps 1080p file, fp16 / fp32, eager /
#     CUDA graph, detector batch 1..32; realtime (120 fps arrivals) for batch 1, the best batch and dynamic
#  2. eval: test_1..test_7, every frame, paced at 120 fps through the streaming engine (default: fp16 +
#     channels-last + folded BN + torch.compile, batch 1, the fastest config that keeps up on an L4), scored
#     with src/tracking/early_call.py code against the labelled flights (summary.json definitions)
# Runs behind results/engine/ (2026-10-03, NVIDIA L4): export 44603438 (CPU); bench 44606460 with
#   BENCH_SPECS="torch-cuda;torch-cuda-graph;torch-cuda-cl-fuse-graph;torch-cuda-fp32;torch-cuda-fp32-graph;..."
#   BENCH_BATCHES=1,2,4,8,16,32 and 44608026 (the compile specs, re-measured after the torch.compile cache fix),
#   merged with `python -m engine.vision.bench_gpu --merge`; eval 44607191
#   (EVAL_FLAGS="--label fp16_cl_fuse_compile_b1_realtime --raw ...") and 44605927 (EVAL_BACKEND=torch-cuda-graph),
#   rescored on the laptop with eval_online --from-raw (the *_raw.pkl files stay on HPG: results/engine/)
# Before submitting, from the laptop repo root (HPG = ojasvamishra@hpg.rc.ufl.edu, ROOT below):
#   rsync -a --relative --exclude __pycache__ -e "ssh -S ~/.ssh/cm-hpg" engine models/vision hpg/engine_vision.sbatch $HPG:$ROOT/
# After: rsync models/vision/frozen_call_model.pkl and results/engine/{vision_bench_gpu,online_vs_offline}.json back.
set -euo pipefail
ROOT=${ROOT:-/blue/ai-workshop/$USER/courtside}
STAGE=${STAGE:-all}
module load pytorch/2.7
source "$ROOT/venv_track/bin/activate"
cd "$ROOT"
mkdir -p logs results/engine models/vision
export TRACK_RESULTS=$ROOT/results/tracking OTTG_ROOT=$ROOT/openttgames BLURBALL_ROOT=$ROOT/ext/blurball
cp -n "$ROOT/ext/blurball/weights/blurball_best" models/vision/blurball_best || true
hostname; date; nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
if [ ! -f models/vision/frozen_call_model.pkl ] || [ "$STAGE" = export ]; then
  python engine/vision/export_frozen.py
fi
if [ "$STAGE" = bench ] || [ "$STAGE" = all ]; then
  # default: fp16 / fp32 x eager / CUDA graph x batch 1..32. BENCH_SPECS=';'-separated backend specs (speed options,
  # e.g. torch-cuda-cl-fuse-graph) with BENCH_BATCHES, written to BENCH_OUT and merged into vision_bench_gpu.json later
  if [ -n "${BENCH_SPECS:-}" ]; then EXTRA=(--specs "$BENCH_SPECS" --batches "${BENCH_BATCHES:-1,2,4}"); else EXTRA=(); fi
  python -m engine.vision.bench_gpu --blurball_root "$BLURBALL_ROOT" --source "$OTTG_ROOT/test_2.mp4" \
      --video test_2 --start-frame 2000 --max-frames 1000 --out "${BENCH_OUT:-results/engine/vision_bench_gpu.json}" \
      "${EXTRA[@]}"
fi
if [ "$STAGE" = eval ] || [ "$STAGE" = all ]; then
  # EVAL_BACKEND / EVAL_BATCH / EVAL_FLAGS (e.g. "--dynamic", "--no-realtime") pick the engine config
  python -m engine.vision.eval_online --backend "${EVAL_BACKEND:-torch-cuda-cl-fuse-compile}" --batch "${EVAL_BATCH:-1}" ${EVAL_FLAGS:-} \
      --blurball_root "$BLURBALL_ROOT" --ottg_root "$OTTG_ROOT" --out results/engine/online_vs_offline.json
fi
nvidia-smi
date
