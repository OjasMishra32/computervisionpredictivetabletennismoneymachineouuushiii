#!/bin/bash
#SBATCH --job-name=track-detect
#SBATCH --account=ai-workshop
#SBATCH --qos=ai-workshop
#SBATCH --partition=hpg-turin
#SBATCH --gpus=1
#SBATCH --cpus-per-task=12
#SBATCH --mem=32gb
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x_%A_%a.log
# Ball detection over all rally frames (train + test videos), one chunk per array task.
# Submit (after `python make_chunks.py`):  sbatch --array=1-$(wc -l < $WORK/chunks.txt)%3 track_detect.sbatch
set -euo pipefail
ROOT=${ROOT:-/blue/ai-workshop/$USER/courtside}
WORK=$ROOT/work/tracking
module load pytorch/2.7
source "$ROOT/venv_track/bin/activate"
read -r VIDEO K < <(sed -n "${SLURM_ARRAY_TASK_ID}p" "$WORK/chunks.txt")
mkdir -p "$WORK/det"
cd "$ROOT/src/tracking"
python detect.py --video "$ROOT/openttgames/$VIDEO.mp4" --ranges "$WORK/ranges/${VIDEO}_${K}.txt" \
    --out "$WORK/det/${VIDEO}_${K}" --fp16 --threads 10 --batch 32
