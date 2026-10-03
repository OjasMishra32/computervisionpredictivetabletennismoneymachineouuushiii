#!/bin/bash
#SBATCH --job-name=tennis-setup
#SBATCH --account=ai-workshop
#SBATCH --qos=ai-workshop
#SBATCH --partition=hpg-turin
#SBATCH --cpus-per-task=4
#SBATCH --mem=16gb
#SBATCH --time=01:30:00
#SBATCH --output=/blue/ai-workshop/%u/courtside/tennis/logs/%x_%j.log
# One-time setup for the tennis ball-tracking module (CPU only, no GPU):
#  1. python venv on top of the HiPerGator pytorch/2.7 module
#  2. clone yastrebksv/TrackNet, TennisCourtDetector, TennisProject at pinned commits
#  3. download their pretrained weights (Google Drive links from the repo READMEs)
#  4. download the TrackNet tennis dataset (Huang et al. 2019; Google Drive link from the
#     yastrebksv/TrackNet README): 10 broadcast matches, 1280x720 @ 30 fps, per-frame labels
set -euo pipefail
ROOT=${ROOT:-/blue/ai-workshop/$USER/courtside/tennis}
mkdir -p "$ROOT"/{ext,weights,data,logs,work}
module load pytorch/2.7
[ -d "$ROOT/venv" ] || python -m venv --system-site-packages "$ROOT/venv"
source "$ROOT/venv/bin/activate"
pip install -q --upgrade pip
pip install -q gdown opencv-python-headless scipy pandas matplotlib tqdm
cd "$ROOT/ext"
clone() { [ -d "$1" ] || git clone -q "https://github.com/yastrebksv/$1.git"; (cd "$1" && git checkout -q "$2"); }
clone TrackNet 730ea17a324321c553c480179caa8ff13e4cf553
clone TennisCourtDetector e5cd4f1ce26b15361700d3d89e068cbf0e82749e
clone TennisProject b7552e955253c008c7612298cb40694682a74ef9
cd "$ROOT/weights"
[ -s tracknet_ball.pt ] || gdown -q 1XEYZ4myUN7QT-NeBYJI0xteLsvs-ZAOl -O tracknet_ball.pt
[ -s court_kps.pt ] || gdown -q 1f-Co64ehgq4uddcQm1aFBDtbnyZhQvgG -O court_kps.pt
ls -la "$ROOT/weights"
cd "$ROOT/data"
if [ ! -f .dataset_done ]; then
  gdown --folder https://drive.google.com/drive/folders/11r0RUaQHX7I3ANkaYG4jOxXK1OYo01Ut -O tracknet_raw
  ls -R tracknet_raw | sed -n 1,20p || true
  for z in $(find tracknet_raw -name '*.zip'); do unzip -q -o "$z" -d tracknet_unz; done
  touch .dataset_done
fi
du -sh "$ROOT/data"/* || true
ls "$ROOT/data/tracknet_unz/Dataset" || true
python -c "import torch, cv2, scipy, pandas; print('torch', torch.__version__, 'cuda', torch.version.cuda, 'cv2', cv2.__version__)"
