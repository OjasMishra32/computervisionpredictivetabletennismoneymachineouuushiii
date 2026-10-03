#!/usr/bin/env bash
# Open http://localhost:8765 after running this. Read-only live dashboard.
cd "$(dirname "$0")/.." && python3 -m http.server 8765 -d docs/live
