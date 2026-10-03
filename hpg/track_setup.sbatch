#!/bin/bash
#SBATCH --job-name=track-setup
#SBATCH --account=ai-workshop
#SBATCH --qos=ai-workshop
#SBATCH --cpus-per-task=4
#SBATCH --mem=8gb
#SBATCH --time=00:45:00
#SBATCH --output=%x_%j.log
# One-time setup for the ball-tracking half (H3):
#  1. python venv on top of the HiPerGator pytorch/2.7 module (torch 2.7.1+cu128)
#  2. clone BlurBall (MIT, built on WASB-SBDT) and download its pretrained table-tennis weights
set -euo pipefail
ROOT=${ROOT:-/blue/ai-workshop/$USER/courtside}
module load pytorch/2.7
if [ ! -d "$ROOT/venv_track" ]; then
  python -m venv --system-site-packages "$ROOT/venv_track"
fi
source "$ROOT/venv_track/bin/activate"
pip install -q --upgrade pip
pip install -q opencv-python-headless av omegaconf hydra-core scipy pandas scikit-learn matplotlib tqdm
mkdir -p "$ROOT/ext"
cd "$ROOT/ext"
[ -d blurball ] || git clone https://github.com/cogsys-tuebingen/blurball.git
(cd blurball && git checkout 2f0f5496f7ba4b5b1a36790749935121b2ce972d)
mkdir -p blurball/weights
for f in blurball_best wasb_midpoint_best wasb_endpoint_best; do
  [ -s blurball/weights/$f ] || curl -s -u 6Z8TpM3sXRKHzGC: -o blurball/weights/$f \
      https://cloud.cs.uni-tuebingen.de/public.php/webdav/$f
done
python -c "import torch, cv2, av, omegaconf, scipy, sklearn; print('torch', torch.__version__, 'cv2', cv2.__version__, 'av', av.__version__)"
