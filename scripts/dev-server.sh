#!/usr/bin/env bash
set -euo pipefail

# Quick Queue: Cursor uses fixed http://127.0.0.1:18080 (gost); upstream QuickQ port is updated by qq-http-bridge.sh.
# To align this terminal with Cursor, export HTTP_PROXY/HTTPS_PROXY to 18080 in ~/.zshrc or set them in .env (loaded by server.py).
# YouTube / 「影片转文字」download timeouts: add VIRALLAB_MEDIA_DOWNLOAD_USE_ENV_PROXY=1 in .env (minimal recipe in .env.example).

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

# Proxy: ViralLab auto-detects live macOS system proxies (including QuickQ floating SOCKS/HTTP
# ports via `scutil --proxy`) and TUN VPN mode automatically via `src/proxy_env.py`.
# If a local gost bridge happens to be listening on 127.0.0.1:18080, use it; otherwise leave
# HTTP_PROXY unset so we never point requests at a dead port.
if [ -z "${HTTP_PROXY:-}" ] && lsof -iTCP:18080 -sTCP:LISTEN >/dev/null 2>&1; then
  export HTTP_PROXY="http://127.0.0.1:18080"
  export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:18080}"
fi
export VIRALLAB_MEDIA_DOWNLOAD_USE_ENV_PROXY="${VIRALLAB_MEDIA_DOWNLOAD_USE_ENV_PROXY:-1}"
# Douyin is CN-domestic — do not pass overseas proxy to its subprocesses
export VIRALLAB_DOUYIN_SKIP_PROXY_RESTORE="${VIRALLAB_DOUYIN_SKIP_PROXY_RESTORE:-1}"
# Fix browser cookie extraction to Chrome only (avoids Vivaldi/missing-browser errors)
export YTDLP_COOKIES_BROWSER="${YTDLP_COOKIES_BROWSER:-chrome}"

# yt-dlp: include -v in stderr for 「影片转文字」 (proxy map, extractor). Disable: VIRALLAB_YTDLP_VERBOSE=0 ./scripts/dev-server.sh
export VIRALLAB_YTDLP_VERBOSE="${VIRALLAB_YTDLP_VERBOSE:-1}"

echo "Starting ViralLab → http://127.0.0.1:5001"
exec .venv/bin/python server.py
