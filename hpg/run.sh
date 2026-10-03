#!/usr/bin/env bash
# Run any repo command on a HiPerGator compute node and bring the outputs back.
#   bash hpg/run.sh [--cpus N] [--mem 32gb] [--time 120] [--gpu] -- <command run from the repo root>
#   e.g. bash hpg/run.sh --cpus 32 -- python scripts/tier0_backtest.py
# Needs the SSH control socket (~/.ssh/cm-hpg) opened by the user. Syncs code (not data/) up first,
# runs with srun under the ai-workshop account, then syncs results/ and research/ back.
set -euo pipefail
cd "$(dirname "$0")/.."
CPUS=8; MEM=32gb; TIME=120; GPU=""
while [ $# -gt 0 ]; do
  case "$1" in
    --cpus) CPUS=$2; shift 2 ;; --mem) MEM=$2; shift 2 ;; --time) TIME=$2; shift 2 ;;
    --gpu) GPU="--partition=hpg-turin --gpus=1"; shift ;; --) shift; break ;; *) break ;;
  esac
done
[ $# -gt 0 ] || { echo "usage: bash hpg/run.sh [--cpus N] [--mem M] [--time MIN] [--gpu] -- <command>"; exit 2; }
HOST=ojasvamishra@hpg.rc.ufl.edu
SSH=(ssh -S "$HOME/.ssh/cm-hpg" -o BatchMode=yes)
R=/blue/ai-workshop/ojasvamishra/courtside_repo
ENV=/blue/ai-workshop/ojasvamishra/envs/cs314
"${SSH[@]}" -O check "$HOST" 2>/dev/null || { echo "HiPerGator socket is closed: run  ssh -fNM -S ~/.ssh/cm-hpg -o ControlPersist=12h $HOST"; exit 3; }
rsync -a --exclude .venv --exclude .git --exclude data/ --exclude models/ --exclude __pycache__ --exclude docs/live/figs \
  -e "${SSH[*]}" ./ "$HOST:$R/"
CMD="$*"; CMD=${CMD/#python /$ENV/bin/python }
"${SSH[@]}" "$HOST" "cd $R && module load conda/26.7 >/dev/null 2>&1; srun --account=ai-workshop --qos=ai-workshop $GPU -c $CPUS --mem=$MEM -t $TIME bash -lc 'cd $R && export PATH=$ENV/bin:\$PATH OMP_NUM_THREADS=$CPUS COURTSIDE_WORKERS=$CPUS && $CMD'"
rsync -a -e "${SSH[*]}" "$HOST:$R/results/" results/
rsync -a -e "${SSH[*]}" "$HOST:$R/research/" research/
