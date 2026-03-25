#!/bin/bash
# Run search + ViralLab. Use: ./scripts/run-all.sh "AI news"
set -e
cd "$(dirname "$0")/.."
topic="${1:-AI news}"
PYTHON="${PYTHON:-.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3.12"
fi
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  PYTHON="python3"
fi
echo "Searching: $topic"
"$PYTHON" main.py --search-only "$topic"
echo "ViralLab at http://127.0.0.1:5001"
exec "$PYTHON" server.py
