#!/usr/bin/env bash
set -euo pipefail

# ViralLab local dev server.
# Proxy routing (QuickQ TUN mode or floating SOCKS5/HTTP via macOS `scutil --proxy`) is
# auto-detected dynamically by `src/proxy_env.py` — no fixed local proxy port required.

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

# Allow yt-dlp/VideoCaptioner to inherit any live resolved proxy (or clean TUN/direct routing).
export VIRALLAB_MEDIA_DOWNLOAD_USE_ENV_PROXY="${VIRALLAB_MEDIA_DOWNLOAD_USE_ENV_PROXY:-1}"
# Douyin is CN-domestic — do not pass overseas proxy to its subprocesses
export VIRALLAB_DOUYIN_SKIP_PROXY_RESTORE="${VIRALLAB_DOUYIN_SKIP_PROXY_RESTORE:-1}"
# Fix browser cookie extraction to Chrome only (avoids Vivaldi/missing-browser errors)
export YTDLP_COOKIES_BROWSER="${YTDLP_COOKIES_BROWSER:-chrome}"

# yt-dlp: include -v in stderr for 「影片转文字」 (proxy map, extractor). Disable: VIRALLAB_YTDLP_VERBOSE=0 ./scripts/dev-server.sh
export VIRALLAB_YTDLP_VERBOSE="${VIRALLAB_YTDLP_VERBOSE:-1}"

echo "Starting ViralLab → http://127.0.0.1:5001"
exec .venv/bin/python server.py
