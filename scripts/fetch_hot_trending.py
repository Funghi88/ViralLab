#!/usr/bin/env python
"""Fetch platform hot topics (ZH + EN) and write to cache. Run with no-proxy env."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.hot_trending import fetch_all_platforms, CACHE_FILE


def main():
    import time
    try:
        zh, en = fetch_all_platforms()
        CACHE_FILE.parent.mkdir(exist_ok=True)
        CACHE_FILE.write_text(
            json.dumps({"ts": time.time(), "topics_zh": zh, "topics_en": en}, ensure_ascii=False),
            encoding="utf-8",
        )
        print(json.dumps({"ok": True, "zh": len(zh), "en": len(en)}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
