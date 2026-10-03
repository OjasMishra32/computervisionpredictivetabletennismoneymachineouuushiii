#!/usr/bin/env bash
# Store your ElevenLabs API key in .env (gitignored, chmod 600) without it appearing on screen or in shell history.
#   bash scripts/set_elevenlabs_key.sh
set -euo pipefail
cd "$(dirname "$0")/.."
read -r -s -p "Paste your ElevenLabs API key (input hidden), then press Enter: " KEY; echo
[ -n "$KEY" ] || { echo "No key entered."; exit 1; }
touch .env && chmod 600 .env
grep -v '^ELEVENLABS_API_KEY=' .env > .env.tmp 2>/dev/null || true
printf 'ELEVENLABS_API_KEY=%s\n' "$KEY" >> .env.tmp && mv .env.tmp .env && chmod 600 .env
unset KEY
git check-ignore -q .env && echo "Saved to .env (gitignored)." || echo "WARNING: .env is not gitignored!"
