#!/usr/bin/env bash
# Upgrade yt-dlp inside ViralLab's .venv (used by 「影片转文字」/ downloads).
#
# Note: Douyin often breaks when ByteDance changes web signing; ViralLab does not fork the
# extractor. If Douyin URLs still fail after upgrading, track yt-dlp issues or use local files.

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -x .venv/bin/pip ]]; then
  echo "Missing .venv. Run ./scripts/install.sh first."
  exit 1
fi

.venv/bin/pip install -U yt-dlp
echo "---"
.venv/bin/yt-dlp --version
