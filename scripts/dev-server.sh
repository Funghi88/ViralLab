#!/usr/bin/env bash
set -euo pipefail

# Quick Queue: Cursor uses fixed http://127.0.0.1:18080 (gost); upstream QuickQ port is updated by qq-http-bridge.sh.
# To align this terminal with Cursor, export HTTP_PROXY/HTTPS_PROXY to 18080 in ~/.zshrc or set them in .env (loaded by server.py).

cd "$(dirname "$0")/.."

if [ ! -x ".venv/bin/python" ]; then
  echo "Missing .venv/bin/python. Run: ./scripts/install.sh"
  exit 1
fi

# Kill anything already on 5001 (including leftover livereload processes)
if lsof -ti tcp:5001 >/dev/null 2>&1; then
  echo "Stopping process on port 5001..."
  lsof -ti tcp:5001 | xargs kill -TERM >/dev/null 2>&1 || true
  sleep 1
fi
pkill -f "server.py" >/dev/null 2>&1 || true
sleep 0.5

# yt-dlp: include -v in stderr for 「影片转文字」 (proxy map, extractor). Disable: VIRALLAB_YTDLP_VERBOSE=0 ./scripts/dev-server.sh
export VIRALLAB_YTDLP_VERBOSE="${VIRALLAB_YTDLP_VERBOSE:-1}"

echo "Starting ViralLab → http://127.0.0.1:5001"
exec .venv/bin/python server.py
