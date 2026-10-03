#!/bin/bash
#SBATCH --job-name=tier0-v3
#SBATCH --account=ai-workshop
#SBATCH --qos=ai-workshop
#SBATCH --cpus-per-task=1
#SBATCH --mem=6gb
#SBATCH --time=01:00:00
#SBATCH --array=0-7%8
#SBATCH --output=/blue/ai-workshop/%u/courtside/v3/logs/%x_%A_%a.log
# Tier-0 v3 (COUNTERFACTUAL WITH ASSUMED DATA; IS only): one array task = every 8th job of the grid
# (or bracket) job list. JOBS=grid|bracket. <= 8 CPUs in total.
set -euo pipefail
ROOT=${ROOT:-/blue/ai-workshop/$USER/courtside/v3}
JOBS=${JOBS:-grid}
cd "$ROOT"
"$ROOT/.venv/bin/python" scripts/tier0_v3_optimise.py --part "$SLURM_ARRAY_TASK_ID" --nparts 8 --jobs "$JOBS" --workers 1
