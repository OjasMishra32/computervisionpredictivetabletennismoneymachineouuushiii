#!/bin/bash
#SBATCH --job-name=track-demo
#SBATCH --account=ai-workshop
#SBATCH --qos=ai-workshop
#SBATCH --cpus-per-task=8
#SBATCH --mem=24gb
#SBATCH --time=00:45:00
#SBATCH --output=logs/%x_%j.log
# Presentation demo videos of the H3 early call (CPU only; run after STAGE=final and audit_labels.py).
# Changes no reported number: refits the frozen model identically and asserts it reproduces
# results/tracking/test_flights.csv before rendering. Output: results/tracking/demo/
set -euo pipefail
ROOT=${ROOT:-/blue/ai-workshop/$USER/courtside}
module load pytorch/2.7
source "$ROOT/venv_track/bin/activate"
cd "$ROOT/src/tracking"
export TRACK_RESULTS=${TRACK_RESULTS:-$ROOT/results/tracking}
python render_demo.py
ls -la "$TRACK_RESULTS/demo"
