#!/bin/bash
#SBATCH --job-name=tennis-detect-video
#SBATCH --account=ai-workshop
#SBATCH --qos=ai-workshop
#SBATCH --partition=hpg-turin
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24gb
#SBATCH --time=00:20:00
#SBATCH --output=/blue/ai-workshop/%u/courtside/tennis/logs/%x_%j.log
# Pretrained TrackNet ball detector + court keypoint detector (same code as tennis_detect.sbatch)
# on every frame of one video file: VIDEO=<path to .mp4> sbatch hpg/tennis_detect_video.sbatch
# Setup (venv, repos, weights) comes from tennis_setup.sbatch.
set -euo pipefail
ROOT=${ROOT:-/blue/ai-workshop/$USER/courtside/tennis}
: "${VIDEO:?set VIDEO=<path to .mp4>}"
module load pytorch/2.7
source "$ROOT/venv/bin/activate"
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader || true
python "$ROOT/src/tennis_tracking/detect_video.py" --video "$VIDEO" \
  --ext "$ROOT/ext/TennisProject" --weights "$ROOT/weights" \
  --out "$ROOT/work/detect_video/$(basename "${VIDEO%.*}").npz"
