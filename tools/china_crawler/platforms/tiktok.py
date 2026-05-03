"""TikTok trending/search via yt-dlp (primary) and DDG video search (fallback).

No login required for public hashtag/tag content when yt-dlp can access TikTok.
For geo-restricted environments, the DDG fallback returns discovery links.

Usage:
  from tools.china_crawler.platforms.tiktok import fetch_tiktok_search
  items = fetch_tiktok_search("viral", max_results=20)

Login: TikTok does not support Playwright session save; yt-dlp cookie support via
  --cookies-from-browser is possible but not required for public content.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Trending hashtag seeds — used when no specific keyword is given
_TRENDING_TAGS = ["viral", "trending", "fyp", "foryou"]


def _slug(text: str) -> str:
    """Normalise keyword to a valid TikTok hashtag slug."""
    return re.sub(r"[^\w]", "", text.strip().lower())


def _ytdlp_flat(url: str, max_results: int) -> list[dict]:
    """Run yt-dlp --flat-playlist --dump-json on a URL; return parsed items."""
    yt = shutil.which("yt-dlp") or str(_PROJECT_ROOT / ".venv" / "bin" / "yt-dlp")
    if not Path(yt).exists() and not shutil.which("yt-dlp"):
        return []
    cmd = [
        yt,
        "--flat-playlist",
        "--dump-json",
        "--no-warnings",
        "--ignore-errors",
        "--playlist-end", str(max_results),
        "--extractor-retries", "1",
        url,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            env=dict(__import__("os").environ, PYTHONWARNINGS="ignore"),
        )
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip().startswith("{")]
        items = []
        for line in lines[:max_results]:
            try:
                data: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                continue
            title = (data.get("title") or data.get("description") or "").strip()[:200]
            if not title or title in {"[Private video]", "[Deleted video]"}:
                continue
            video_url = (
                data.get("webpage_url")
                or data.get("original_url")
                or data.get("url")
                or ""
            )
            if not video_url:
                vid_id = data.get("id", "")
                if vid_id:
                    video_url = f"https://www.tiktok.com/@_/video/{vid_id}"
            uploader = data.get("uploader") or data.get("creator") or ""
            views = data.get("view_count") or data.get("viewCount") or 0
            likes = data.get("like_count") or 0
            desc = f"👤 {uploader} · 👁 {views:,} views · ❤ {likes:,} likes" if views else uploader
            items.append({
                "title": title,
                "url": video_url,
                "description": desc[:500],
                "views": str(views) if views else "N/A",
                "content_type": "video",
            })
        return items
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return []


def _ddg_tiktok(keywords: str, max_results: int) -> list[dict]:
    """DuckDuckGo video search filtered to tiktok.com — discovery fallback."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return []
    query = f"site:tiktok.com {keywords}"
    try:
        with DDGS() as ddgs:
            raw = list(ddgs.videos(keywords=query, max_results=max_results))
        items = []
        for r in raw:
            url = r.get("content") or r.get("url") or ""
            if not url or "tiktok.com" not in url:
                continue
            title = (r.get("title") or "").strip()[:200] or "TikTok video"
            views = r.get("statistics", {}).get("viewCount", 0) if isinstance(r.get("statistics"), dict) else 0
            items.append({
                "title": title,
                "url": url,
                "description": (r.get("description") or "")[:300],
                "views": str(views) if views else "N/A",
                "content_type": "video",
            })
        return items
    except Exception:
        return []


def fetch_tiktok_search(keywords: str, max_results: int = 20, headless: bool = True) -> list[dict]:
    """Fetch TikTok videos for the given keywords.

    Strategy:
    1. yt-dlp on hashtag URL  (e.g. /tag/viral) — works for public content
    2. yt-dlp on @search URL  (https://www.tiktok.com/search?q=...)
    3. DDG video search fallback (tiktok.com domain filter)

    headless arg is kept for interface compatibility; yt-dlp runs headlessly by nature.
    """
    kw = (keywords or "").strip()
    slug = _slug(kw) if kw else "viral"

    # Try multiple URL patterns
    ytdlp_urls = [
        f"https://www.tiktok.com/tag/{urllib.parse.quote(slug)}",
        f"https://www.tiktok.com/search?q={urllib.parse.quote(kw)}",
    ]
    # If user passes a generic "trending / hot / viral" keyword, try all seeds
    if slug in {"trending", "hot", "viral", "foryou", "fyp", ""}:
        ytdlp_urls = [f"https://www.tiktok.com/tag/{t}" for t in _TRENDING_TAGS]

    results: list[dict] = []
    for url in ytdlp_urls:
        results = _ytdlp_flat(url, max_results)
        if results:
            break

    if not results:
        results = _ddg_tiktok(kw or "viral tiktok", max_results)

    return results[:max_results]
