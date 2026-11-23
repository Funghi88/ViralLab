#!/bin/sh
# Install Python deps into .venv (creates it if missing).
# FULL=1 for CrewAI (main.py --daily-news, needs Python 3.10–3.13)
set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_DIR/.venv"

# Pick python binary
if [ -z "$PYTHON" ]; then
  if command -v python3.12 >/dev/null 2>&1; then
    PYTHON="python3.12"
  else
    PYTHON="python3"
  fi
fi

# Create venv if missing
if [ ! -f "$VENV/bin/python" ]; then
  echo "Creating virtual environment at $VENV …"
  $PYTHON -m venv "$VENV"
fi

PIP="$VENV/bin/pip"
RUN="env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy"

if [ "$FULL" = "1" ]; then
  $RUN $PIP install -r "$REPO_DIR/requirements-full.txt"
else
  $RUN $PIP install -r "$REPO_DIR/requirements.txt"
fi
echo "Done. Activate with: source $VENV/bin/activate"
