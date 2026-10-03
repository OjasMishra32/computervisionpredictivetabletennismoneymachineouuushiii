#!/usr/bin/env bash
# Serve the read-only live dashboard, then open http://localhost:${PORT}
# Usage: bash scripts/serve_live.sh [port]   (default 8765)
PORT=${1:-8765}
cd "$(dirname "$0")/.." && echo "COURTSIDE Live -> http://localhost:${PORT}" && python3 -m http.server "$PORT" -d docs/live
