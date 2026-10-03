#!/bin/bash
#SBATCH --job-name=tennis-eval
#SBATCH --account=ai-workshop
#SBATCH --qos=ai-workshop
#SBATCH --partition=hpg-turin
#SBATCH --cpus-per-task=16
#SBATCH --mem=32gb
#SBATCH --time=02:00:00
#SBATCH --output=/blue/ai-workshop/%u/courtside/tennis/logs/%x_%j.log
# CPU only: court cameras, flights + ground truth, train-only tuning, final test evaluation.
# Writes results/tennis_tracking/{summary.json,tuning_train_only.csv,lead_vs_error.png,example_trajectory.png}
set -euo pipefail
ROOT=${ROOT:-/blue/ai-workshop/$USER/courtside/tennis}
module load pytorch/2.7
source "$ROOT/venv/bin/activate"
python "$ROOT/src/tennis_tracking/run_eval.py" --labels "$ROOT/data/tracknet_unz/Dataset" \
  --detect "$ROOT/work/detect" --work "$ROOT/work/eval" --out "$ROOT/results/tennis_tracking" \
  --procs "$SLURM_CPUS_PER_TASK" --stage prep detacc tune final
