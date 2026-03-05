#!/bin/bash
# Run search + ViralLab. Use: ./scripts/run-all.sh "AI news"
set -e
cd "$(dirname "$0")/.."
topic="${1:-AI news}"
echo "Searching: $topic"
python3 main.py --search-only "$topic"
echo "ViralLab at http://127.0.0.1:5001"
exec python3 server.py
