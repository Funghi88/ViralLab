#!/usr/bin/env python
"""Fetch platform hot topics (ZH + EN) and write to cache. Run with no-proxy env."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.hot_trending import fetch_all_platforms, save_hot_trending_cache
from src.proxy_env import load_dotenv_safe

load_dotenv_safe(Path(__file__).resolve().parent.parent / ".env")


def main():
    try:
        zh, en = fetch_all_platforms()
        saved = save_hot_trending_cache(zh, en)
        print(
            json.dumps(
                {
                    "ok": True,
                    "zh": len(zh),
                    "en": len(en),
                    "cached_zh": len(saved.get("topics_zh") or []),
                    "cached_en": len(saved.get("topics_en") or []),
                },
                ensure_ascii=False,
            )
        )
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
