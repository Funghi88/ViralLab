"""Instagram trending/search scraper.

Three-tier strategy (tried in order):
1. yt-dlp --flat-playlist   — extracts public hashtag Reels without login
2. Playwright with session  — explore page / hashtag page with login
3. DuckDuckGo video search  — site:instagram.com fallback

Save your Instagram session:
  .venv/bin/python -m tools.china_crawler login --platform instagram

Why this matters for viral content discovery:
- Instagram Reels is TikTok's closest competitor in short-form video
- Hashtag trending on IG directly signals what is going viral in lifestyle/fashion/design
- Creator collab patterns and hook styles differ significantly from TikTok
- IG's explore algorithm rewards high saves + shares over pure watch time

yt-dlp works on:
  - https://www.instagram.com/explore/tags/<hashtag>/
  - https://www.instagram.com/<username>/reels/  (public accounts)
No login required for public hashtag pages.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_STATE_PATH = _PROJECT_ROOT / "config" / "china_crawler_instagram_state.json"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Post card selectors for Playwright explore/hashtag pages
_POST_SELECTORS = [
    'a[href*="/p/"]',
    'a[href*="/reel/"]',
    'article a[href*="/p/"]',
    'div[role="link"] a',
]


def _slug(keywords: str) -> str:
    """Convert keywords to an Instagram hashtag (no spaces, lowercase)."""
    return re.sub(r"[^\w]", "", keywords.strip().lower())


def _ytdlp_instagram(keywords: str, max_results: int) -> list[dict]:
    """Use yt-dlp flat-playlist to extract public Instagram Reels for a hashtag."""
    yt = shutil.which("yt-dlp") or str(_PROJECT_ROOT / ".venv" / "bin" / "yt-dlp")
    if not Path(yt).exists() and not shutil.which("yt-dlp"):
        return []

    slug = _slug(keywords) or "viral"
    # Try both hashtag explore page and a broad trending hashtag
    urls = [f"https://www.instagram.com/explore/tags/{slug}/"]
    if slug in {"viral", "trending", "hot", "reels", "explore", ""}:
        urls = [
            "https://www.instagram.com/explore/tags/viral/",
            "https://www.instagram.com/explore/tags/trending/",
            "https://www.instagram.com/explore/tags/reels/",
        ]

    for url in urls:
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
                cmd, capture_output=True, text=True, timeout=60,
                env=dict(__import__("os").environ, PYTHONWARNINGS="ignore"),
            )
            lines = [l.strip() for l in result.stdout.splitlines() if l.strip().startswith("{")]
            items = []
            for line in lines[:max_results]:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                title = (data.get("title") or data.get("description") or "").strip()[:200]
                if not title or title in {"[Private]", "[Deleted]"}:
                    continue
                post_url = (
                    data.get("webpage_url") or data.get("original_url") or data.get("url") or ""
                )
                if not post_url:
                    vid_id = data.get("id", "")
                    post_url = f"https://www.instagram.com/p/{vid_id}/" if vid_id else ""
                uploader = data.get("uploader") or data.get("creator") or ""
                views = data.get("view_count") or data.get("like_count") or 0
                desc = f"@{uploader} · 👁 {views:,}" if uploader and views else (uploader or "")
                items.append({
                    "title": title,
                    "url": post_url,
                    "description": desc[:300],
                    "views": str(views) if views else "N/A",
                    "content_type": "video",
                })
            if items:
                return items[:max_results]
        except (subprocess.TimeoutExpired, Exception):
            continue
    return []


def _playwright_instagram(keywords: str, max_results: int, headless: bool) -> list[dict]:
    """Playwright-based Instagram hashtag page. Requires saved session."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []
    if not _STATE_PATH.exists():
        return []

    slug = _slug(keywords) or "viral"
    url = f"https://www.instagram.com/explore/tags/{slug}/"
    items: list[dict] = []
    seen: set = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            context = browser.new_context(
                storage_state=str(_STATE_PATH), user_agent=_USER_AGENT
            )
            page = context.new_page()
            page.set_viewport_size({"width": 1280, "height": 900})
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(4000)
            content = page.content()
            if "log in" in content.lower() and "/p/" not in content:
                return []

            for _ in range(3):
                for selector in _POST_SELECTORS:
                    try:
                        links = page.locator(selector).all()
                        for el in links:
                            if len(items) >= max_results:
                                break
                            href = (el.get_attribute("href") or "").strip()
                            if not href:
                                continue
                            if not href.startswith("http"):
                                href = "https://www.instagram.com" + href
                            href = href.split("?")[0]
                            if href in seen or ("/p/" not in href and "/reel/" not in href):
                                continue
                            seen.add(href)
                            # Try to get alt text from thumbnail image
                            try:
                                img = el.locator("img").first
                                title = (img.get_attribute("alt") or "").strip()[:200]
                            except Exception:
                                title = ""
                            if not title:
                                title = f"#{slug} post"
                            items.append({
                                "title": title,
                                "url": href,
                                "description": "",
                                "views": "N/A",
                                "content_type": "video",
                            })
                        if items:
                            break
                    except Exception:
                        continue
                if len(items) >= max_results:
                    break
                page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
                page.wait_for_timeout(2200)
        finally:
            context.close()
            browser.close()
    return items


def _ddg_instagram(keywords: str, max_results: int) -> list[dict]:
    """DuckDuckGo video/news search filtered to instagram.com."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return []
    query = f"site:instagram.com {keywords} reel"
    try:
        with DDGS() as ddgs:
            raw = list(ddgs.videos(keywords=query, max_results=max_results))
        items = []
        for r in raw:
            url = r.get("content") or r.get("url") or ""
            if "instagram.com" not in url:
                continue
            title = (r.get("title") or "").strip()[:200] or "Instagram Reel"
            items.append({
                "title": title,
                "url": url,
                "description": (r.get("description") or "")[:300],
                "views": "N/A",
                "content_type": "video",
            })
        return items
    except Exception:
        return []


def fetch_instagram_search(keywords: str, max_results: int = 20, headless: bool = True) -> list[dict]:
    """Fetch Instagram Reels/posts for the given keywords.

    Strategy:
    1. yt-dlp on public hashtag explore pages (no login needed for public content)
    2. Playwright with saved session (run login first for best results)
    3. DuckDuckGo video search as last resort

    Run: .venv/bin/python -m tools.china_crawler login --platform instagram
    """
    # 1. yt-dlp (works for public hashtags without login)
    items = _ytdlp_instagram(keywords, max_results)
    if items:
        return items[:max_results]

    # 2. Playwright (needs saved session)
    items = _playwright_instagram(keywords, max_results, headless)
    if items:
        return items[:max_results]

    # 3. DDG fallback
    return _ddg_instagram(keywords, max_results)
