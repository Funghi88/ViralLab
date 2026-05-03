"""X (formerly Twitter) trending/search scraper.

Three-tier strategy (tried in order):
1. Playwright with saved session  — full search results + trending
2. Nitter RSS                     — open-source Twitter frontend, no login
3. DuckDuckGo news search         — site:x.com keyword fallback

Save your X session:
  .venv/bin/python -m tools.china_crawler login --platform x

Why this matters for viral content discovery:
- X is where breaking trends surface first (hours before other platforms)
- Real-time signals: what creators/journalists talk about right now
- Thread virality differs from TikTok/IG — text-led, argument-driven

Nitter instances (public, no login required):
  https://nitter.privacydev.net — typically most stable
  https://nitter.poast.org
  https://nitter.cz
Nitter RSS URL pattern: https://<instance>/search/rss?q=<query>&f=tweets
"""
from __future__ import annotations

import urllib.parse
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_STATE_PATH = _PROJECT_ROOT / "config" / "china_crawler_x_state.json"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Nitter instances to try in order (fallback to next if one is down)
_NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.cz",
    "https://nitter.1d4.us",
]

# Tweet card selectors for Playwright path
_TWEET_SELECTORS = [
    'article[data-testid="tweet"]',
    '[data-testid="tweetText"]',
    'div[data-testid="tweet"]',
]


def _nitter_rss(keywords: str, max_results: int) -> list[dict]:
    """Try Nitter RSS feed for keyword search. No login needed."""
    try:
        import feedparser
        import requests
    except ImportError:
        return []

    query = urllib.parse.quote(keywords)
    for base in _NITTER_INSTANCES:
        url = f"{base}/search/rss?q={query}&f=tweets"
        try:
            r = requests.get(url, timeout=8, headers={"User-Agent": _USER_AGENT})
            if r.status_code != 200:
                continue
            d = feedparser.parse(r.content)
            if not d.entries:
                continue
            items = []
            for e in d.entries[:max_results]:
                title = (e.get("title") or "").strip()
                link = e.get("link") or ""
                # Normalise nitter links → x.com links
                for inst in _NITTER_INSTANCES:
                    link = link.replace(inst.replace("https://", ""), "x.com")
                link = link.replace("nitter.privacydev.net", "x.com")
                summary = (e.get("summary") or "")[:300]
                if not title:
                    continue
                items.append({
                    "title": title[:200],
                    "url": link,
                    "description": summary,
                    "views": "N/A",
                    "content_type": "post",
                })
            if items:
                return items[:max_results]
        except Exception:
            continue
    return []


def _ddg_x(keywords: str, max_results: int) -> list[dict]:
    """DuckDuckGo news search filtered to x.com — last-resort fallback."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return []
    query = f"site:x.com {keywords}"
    try:
        with DDGS() as ddgs:
            raw = list(ddgs.news(keywords=query, max_results=max_results))
        items = []
        for r in raw:
            url = r.get("url") or ""
            if "x.com" not in url and "twitter.com" not in url:
                continue
            title = (r.get("title") or "").strip()[:200]
            if not title:
                continue
            items.append({
                "title": title,
                "url": url,
                "description": (r.get("body") or "")[:300],
                "views": "N/A",
                "content_type": "post",
            })
        return items
    except Exception:
        return []


def _playwright_x(keywords: str, max_results: int, headless: bool) -> list[dict]:
    """Playwright-based X search. Requires a saved session (login command)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []
    if not _STATE_PATH.exists():
        return []

    query = urllib.parse.quote(keywords)
    search_url = f"https://x.com/search?q={query}&src=typed_query&f=live"
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
            page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(4000)

            for _ in range(3):  # scroll rounds
                try:
                    tweets = page.locator('article[data-testid="tweet"]').all()
                    for tweet in tweets:
                        if len(items) >= max_results:
                            break
                        try:
                            text_el = tweet.locator('[data-testid="tweetText"]').first
                            text = (text_el.inner_text() or "").strip()[:200]
                            if not text or text in seen:
                                continue
                            seen.add(text)
                            link_el = tweet.locator('a[href*="/status/"]').first
                            href = link_el.get_attribute("href") or ""
                            if href and not href.startswith("http"):
                                href = "https://x.com" + href
                            items.append({
                                "title": text,
                                "url": href or search_url,
                                "description": "",
                                "views": "N/A",
                                "content_type": "post",
                            })
                        except Exception:
                            continue
                except Exception:
                    pass
                if len(items) >= max_results:
                    break
                page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.7)")
                page.wait_for_timeout(2000)
        finally:
            context.close()
            browser.close()
    return items


def fetch_x_search(keywords: str, max_results: int = 20, headless: bool = True) -> list[dict]:
    """Fetch X (Twitter) posts for the given keywords.

    Strategy:
    1. Playwright with saved session (run login first for best results)
    2. Nitter RSS (open-source frontend, no login, may be unreliable)
    3. DuckDuckGo news search as last resort

    Without a saved session, results come from Nitter or DDG only.
    Run: .venv/bin/python -m tools.china_crawler login --platform x
    """
    # 1. Playwright (best quality, needs session)
    items = _playwright_x(keywords, max_results, headless)
    if items:
        return items[:max_results]

    # 2. Nitter RSS (free, no auth, may be down)
    items = _nitter_rss(keywords, max_results)
    if items:
        return items[:max_results]

    # 3. DDG fallback
    return _ddg_x(keywords, max_results)
