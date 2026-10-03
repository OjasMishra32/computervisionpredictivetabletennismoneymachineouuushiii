#!/bin/bash
#SBATCH --job-name=track-analyze
#SBATCH --account=ai-workshop
#SBATCH --qos=ai-workshop
#SBATCH --cpus-per-task=8
#SBATCH --mem=16gb
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x_%j.log
# H3 analysis after track_detect.sbatch has finished (CPU only).
#   STAGE=dev   sbatch track_analyze.sbatch   # tracks, flights, train detection accuracy, LOGO model selection
#   STAGE=final sbatch track_analyze.sbatch   # ONE test evaluation + summary (MODEL=hgb, GATE_H=0.10 frozen)
set -euo pipefail
ROOT=${ROOT:-/blue/ai-workshop/$USER/courtside}
STAGE=${STAGE:-dev}
module load pytorch/2.7
source "$ROOT/venv_track/bin/activate"
cd "$ROOT/src/tracking"
export TRACK_RESULTS=${TRACK_RESULTS:-$ROOT/results/tracking}
mkdir -p "$TRACK_RESULTS"
TRAIN="game_1 game_2 game_3 game_4 game_5"
TEST="test_1 test_2 test_3 test_4 test_5 test_6 test_7"
if [ "$STAGE" = dev ]; then
  python trajectories.py --model blurball
  python flights.py
  python eval_detection.py --videos $TRAIN --out "$TRACK_RESULTS/detection_accuracy_train.csv"
  python early_call.py --dev
  python spotcheck.py
else
  python eval_detection.py --videos $TRAIN $TEST --out "$TRACK_RESULTS/detection_accuracy.csv"
  # frozen from the dev stage (DEVIATIONS.md H3-D5): HGB, gate 0.10 s
  GATE_H=${GATE_H:-0.10} python early_call.py --final --model "${MODEL:-hgb}"
  cp "$ROOT/work/tracking/dev_report.json" "$TRACK_RESULTS/dev_report.json"
  python summarize.py
fi
