#!/bin/sh
# Install Python deps. Bypasses proxy (PyPI works direct for you).
# FULL=1 for CrewAI (needs Python 3.10+)
set -e
PYTHON="${PYTHON:-python3}"
PIP="${PIP:-$PYTHON -m pip}"
RUN="env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy"
if [ "$FULL" = "1" ]; then
  $RUN $PIP install -r requirements.txt
else
  $RUN $PIP install -r requirements-minimal.txt
fi
