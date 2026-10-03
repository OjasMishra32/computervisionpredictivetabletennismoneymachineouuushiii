#!/bin/bash
#SBATCH --job-name=tier0-latency
#SBATCH --account=ai-workshop
#SBATCH --qos=ai-workshop
#SBATCH --partition=hpg-turin,hpg-milan,hpg-default
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=48gb
#SBATCH --time=02:00:00
#SBATCH --output=/blue/ai-workshop/%u/courtside_repo/hpg_logs/%x_%j.log
# Tier-0 feed-latency sweep (assumed data: licensed feed/video not purchased; parameters measured).
# One task, 32 CPUs (<= 64 allowed; peak RSS 19 GB at 64 workers): scripts/tier0_latency_sweep.py runs ~19k (cell, period, seed) simulations in a process pool.
set -euo pipefail
ROOT=${ROOT:-/blue/ai-workshop/$USER/courtside_repo}
PY=${PY:-/blue/ai-workshop/$USER/envs/cs314/bin/python}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1
cd "$ROOT"
"$PY" scripts/tier0_latency_sweep.py --workers "$SLURM_CPUS_PER_TASK" ${EXTRA_ARGS:-}
