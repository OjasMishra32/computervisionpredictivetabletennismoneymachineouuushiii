#!/bin/bash
#SBATCH --job-name=spin-tt
#SBATCH --account=ai-workshop
#SBATCH --qos=ai-workshop
#SBATCH --cpus-per-task=8
#SBATCH --mem=16gb
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x_%j.log
# Spin-aware early call for table tennis (src/spin/tt_*.py). CPU only: it reuses the frozen BlurBall
# tracks and flights of track_detect/track_analyze (WORK/tracking/{tracks,flights.csv,table_geometry.json})
# and the segmentation masks in $ROOT/openttgames/markup; no GPU and no new detection are needed.
#
#   cd $ROOT/hpg
#   STAGE=dev   sbatch spin_tt.sbatch   # cameras, train physics fits, LOGO CV on game_1..5, frozen thresholds
#                                       #   -> results/spin/tt/{dev_report.json,frozen_spec.json,train_*}
#   STAGE=final sbatch spin_tt.sbatch   # ONE test evaluation of the spin model (appends a [spin_tt] line to
#                                       #   results/tracking/test_peeks.log; refuses to run twice)
#                                       #   -> results/spin/tt/{test_summary.json,test_*}
set -euo pipefail
ROOT=${ROOT:-/blue/ai-workshop/$USER/courtside}
STAGE=${STAGE:-dev}
module load pytorch/2.7
source "$ROOT/venv_track/bin/activate"
cd "$ROOT"
export COURTSIDE_ROOT=$ROOT
export TRACK_RESULTS=${TRACK_RESULTS:-$ROOT/results/tracking}
export SPIN_RESULTS=${SPIN_RESULTS:-$ROOT/results/spin/tt}
export SPIN_WORK=${SPIN_WORK:-$ROOT/work/tracking/spin_tt}
export GATE_H=${GATE_H:-0.10}                   # frozen horizon gate of the H3 model (DEVIATIONS.md H3-D5)
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1   # one thread per fitting process
mkdir -p "$SPIN_RESULTS" "$SPIN_WORK"
NPROC=${SLURM_CPUS_PER_TASK:-8}
python - <<'EOF'
import cv2, numpy, pandas, scipy, sklearn
print("versions: numpy", numpy.__version__, "scipy", scipy.__version__, "sklearn", sklearn.__version__,
      "pandas", pandas.__version__, "cv2", cv2.__version__)
EOF
for f in work/tracking/flights.csv work/tracking/table_geometry.json; do
  test -s "$f" || { echo "missing $ROOT/$f (run track_analyze.sbatch first)"; exit 1; }
done
if [ "$STAGE" = dev ]; then
  python src/spin/tt_camera.py --videos game_1 game_2 game_3 game_4 game_5 --cache "$SPIN_WORK/cameras.json"
  python src/spin/tt_synth.py --n 150 --seed 11 --out "$SPIN_RESULTS/synthetic_check_noanchor.json" &
  python src/spin/tt_early_call.py --dev --procs $((NPROC - 1))
  wait
elif [ "$STAGE" = final ]; then
  python src/spin/tt_camera.py --videos test_1 test_2 test_3 test_4 test_5 test_6 test_7 --cache "$SPIN_WORK/cameras.json"
  python src/spin/tt_early_call.py --final --procs "$NPROC"
else
  echo "STAGE must be dev or final"; exit 1
fi
