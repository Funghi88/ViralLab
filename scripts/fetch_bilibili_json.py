#!/usr/bin/env python
"""Fetch Bilibili videos and output JSON. Used by /api/viral-videos with no-proxy env."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.china_sources import fetch_bilibili_popular, search_bilibili


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "热门"
    max_results = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    china_tags = ("鬼畜", "搞笑", "数码", "游戏", "知识", "时尚", "影视", "汽车", "日常", "穿搭")
    try:
        if query in ("", "热门", "trending"):
            videos = fetch_bilibili_popular(max_results=max_results)
        elif query in china_tags:
            videos = fetch_bilibili_popular(max_results=max_results, category_filter=query)
        else:
            videos = search_bilibili(query, max_results=16)
            if not videos:
                videos = fetch_bilibili_popular(max_results=max_results)
        print(json.dumps(videos, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
