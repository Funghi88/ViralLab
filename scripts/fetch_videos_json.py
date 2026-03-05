#!/usr/bin/env python
"""Fetch viral videos and output JSON. Used by /api/viral-videos with no-proxy env."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.video_tools import fetch_viral_videos


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "viral trending"
    max_results = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    try:
        videos = fetch_viral_videos(query, max_results=max_results)
        print(json.dumps(videos, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
