#!/bin/bash
#SBATCH --job-name=ttg-download
#SBATCH --account=ai-workshop
#SBATCH --qos=ai-workshop
#SBATCH --cpus-per-task=4
#SBATCH --mem=8gb
#SBATCH --time=04:00:00
#SBATCH --output=%x_%j.log
# OpenTTGames (OSAI, CC BY-NC-SA 4.0): 120 fps Full-HD table tennis video with
# labeled bounce/net events and ball coordinates. https://lab.osai.ai/
set -euo pipefail
DEST=${DEST:-/blue/ai-workshop/$USER/courtside/openttgames}
mkdir -p "$DEST" && cd "$DEST"
BASE=https://lab.osai.ai/datasets/openttgames/data
FILES=""
for i in 1 2 3 4 5; do FILES="$FILES game_$i.zip game_$i.mp4"; done
for i in 1 2 3 4 5 6 7; do FILES="$FILES test_$i.zip test_$i.mp4"; done
# markup first (small), then video, 4 at a time, resumable
echo $FILES | tr ' ' '\n' | xargs -P 4 -I{} wget -q -c "$BASE/{}" -O {}
for z in *.zip; do d="${z%.zip}"; mkdir -p "markup/$d"; unzip -oq "$z" -d "markup/$d"; done
ls -la "$DEST"; du -sh "$DEST"
