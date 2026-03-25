#!/bin/sh
# Install Python deps. Bypasses proxy (PyPI works direct for you).
# FULL=1 for CrewAI (main.py --daily-news, needs Python 3.10–3.13)
set -e
if [ -z "$PYTHON" ]; then
  if command -v python3.12 >/dev/null 2>&1; then
    PYTHON="python3.12"
  else
    PYTHON="python3"
  fi
fi
PIP="${PIP:-$PYTHON -m pip}"
RUN="env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy"
if [ "$FULL" = "1" ]; then
  $RUN $PIP install -r requirements-full.txt
else
  $RUN $PIP install -r requirements.txt
fi
