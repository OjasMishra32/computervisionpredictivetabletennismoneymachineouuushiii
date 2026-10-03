#!/bin/bash
#SBATCH --job-name=tennis-detect
#SBATCH --account=ai-workshop
#SBATCH --qos=ai-workshop
#SBATCH --partition=hpg-turin
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=40gb
#SBATCH --time=01:00:00
#SBATCH --array=1-10%2
#SBATCH --output=/blue/ai-workshop/%u/courtside/tennis/logs/%x_%A_%a.log
# Pretrained TrackNet ball detector + court keypoint detector on every frame of one game
# (array index = game id). At most 2 GPUs at once (shared account).
set -euo pipefail
ROOT=${ROOT:-/blue/ai-workshop/$USER/courtside/tennis}
module load pytorch/2.7
source "$ROOT/venv/bin/activate"
python "$ROOT/src/tennis_tracking/detect.py" --data "$ROOT/data/tracknet_unz/Dataset" \
  --ext "$ROOT/ext/TennisProject" --weights "$ROOT/weights" --out "$ROOT/work/detect" \
  --games "$SLURM_ARRAY_TASK_ID"
