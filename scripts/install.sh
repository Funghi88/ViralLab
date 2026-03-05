#!/bin/sh
# Install Python deps. Bypasses proxy (PyPI works direct for you).
# FULL=1 for CrewAI (main.py --daily-news, needs Python 3.10–3.13)
set -e
PYTHON="${PYTHON:-python3}"
PIP="${PIP:-$PYTHON -m pip}"
RUN="env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy"
if [ "$FULL" = "1" ]; then
  $RUN $PIP install -r requirements-full.txt
else
  $RUN $PIP install -r requirements.txt
fi
