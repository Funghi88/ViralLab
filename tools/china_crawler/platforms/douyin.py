"""Douyin (抖音) search/trending via Playwright. May require login for full results.

Optional: save session with `.venv/bin/python -m tools.china_crawler login --platform douyin`;
then crawler loads config/china_crawler_douyin_state.json.
"""
from __future__ import annotations

import urllib.parse
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_STATE_PATH = _PROJECT_ROOT / "config" / "china_crawler_douyin_state.json"
_CHROME_USER_DATA = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Video card selectors — tried in priority order
_VIDEO_CARD_SELECTORS = [
    'a[href*="/video/"]',
    'a[href*="douyin.com/video"]',
    '[class*="video-card"] a',
    '[class*="videoCard"] a',
    '[class*="feed"] a[href*="/video"]',
    'li a[href*="/video"]',
    'div[data-e2e="search_video_card"] a',
    'div[data-e2e="feed-item"] a',
]

# Title extraction targets inside a card element
_TITLE_SELECTORS = [
    "[data-e2e='search-card-desc']",
    "[data-e2e='video-desc']",
    "p.title",
    ".video-title",
    "span.title",
    "h3",
    "h2",
]


def _extract_title_from_card(page, card_el) -> str:
    """Try to extract a meaningful title from a video card element."""
    # 1. Structured title elements
    for sel in _TITLE_SELECTORS:
        try:
            t = (card_el.locator(sel).first.inner_text() or "").strip()[:200]
            if t and len(t) > 2:
                return t
        except Exception:
            continue
    # 2. img alt attribute
    try:
        alt = (card_el.locator("img").first.get_attribute("alt") or "").strip()[:200]
        if alt and len(alt) > 2:
            return alt
    except Exception:
        pass
    # 3. Inner text of the element itself
    try:
        t = (card_el.inner_text() or "").strip()[:200]
        if t and len(t) > 2:
            return t
    except Exception:
        pass
    return ""


def _collect_video_links(page, max_results: int, seen: set) -> list[dict]:
    """Parse video links from the current page state using multiple selectors."""
    raw: list[dict] = []
    for selector in _VIDEO_CARD_SELECTORS:
        try:
            links = page.locator(selector).all()
            for el in links:
                if len(raw) >= max_results:
                    break
                href = (el.get_attribute("href") or "").strip()
                if not href:
                    continue
                if "douyin.com" not in href and href.startswith("/"):
                    href = "https://www.douyin.com" + href
                if "douyin.com" not in href or "/video/" not in href:
                    continue
                href = href.split("?")[0]
                if href in seen:
                    continue
                seen.add(href)
                title = _extract_title_from_card(page, el) or "Video"
                raw.append({
                    "title": title,
                    "url": href,
                    "description": "",
                    "views": "N/A",
                    "content_type": "video",
                })
            if raw:
                break
        except Exception:
            continue
    return raw


def _scroll_and_collect(page, max_results: int, seen: set, rounds: int = 4) -> list[dict]:
    """Scroll to trigger lazy-loading; collect video cards across multiple rounds."""
    all_raw: list[dict] = []
    for i in range(rounds):
        batch = _collect_video_links(page, max_results - len(all_raw), seen)
        all_raw.extend(batch)
        if len(all_raw) >= max_results:
            break
        fraction = (i + 1) / rounds
        page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {fraction:.2f})")
        page.wait_for_timeout(2200)
    return all_raw


def _try_profile_context(p, query_url: str, max_results: int, headless: bool) -> list[dict]:
    """Try using existing local Chrome profiles to access Douyin login state."""
    if not _CHROME_USER_DATA.exists():
        return []
    for profile in ["Default", "Profile 1", "Profile 2", "Profile 3"]:
        if not (_CHROME_USER_DATA / profile).exists():
            continue
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(_CHROME_USER_DATA),
                headless=headless,
                channel="chrome",
                args=[f"--profile-directory={profile}"],
                user_agent=_USER_AGENT,
            )
            try:
                page = context.new_page()
                page.goto(query_url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(3500)
                content = page.content()
                if "登录" in content or "login" in content.lower():
                    continue
                seen: set = set()
                raw = _scroll_and_collect(page, max_results, seen, rounds=3)
                if raw:
                    return raw
            finally:
                context.close()
        except Exception:
            continue
    return []


def fetch_douyin_search(keywords: str, max_results: int = 20, headless: bool = True) -> list[dict]:
    """Fetch Douyin search items.

    Without login often returns [].
    Run `.venv/bin/python -m tools.china_crawler login --platform douyin` to save a session.

    Flow:
    1. Saved state context (config/china_crawler_douyin_state.json).
    2. Multi-round scroll to collect video cards.
    3. If still empty, try local Chrome profile contexts.
    4. For generic trending keywords, also try the Douyin hot/trending page.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright required. Run: pip install playwright && playwright install chromium"
        ) from None

    kw = (keywords or "").strip()
    query = urllib.parse.quote(kw)
    is_trending = kw.lower() in {"热门", "热榜", "trending", "hot", "popular", ""}
    search_url = (
        "https://www.douyin.com/hot" if is_trending else f"https://www.douyin.com/search/{query}"
    )
    seen: set = set()
    raw: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = None
        try:
            if _STATE_PATH.exists():
                context = browser.new_context(
                    storage_state=str(_STATE_PATH), user_agent=_USER_AGENT
                )
            else:
                context = browser.new_context(user_agent=_USER_AGENT)
            page = context.new_page()
            page.set_viewport_size({"width": 1920, "height": 1080})
            page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)
            content = page.content()
            if "登录" not in content and "login" not in content.lower():
                raw = _scroll_and_collect(page, max_results, seen, rounds=4)
            # If still empty, try /hot as a secondary URL
            if not raw and not is_trending:
                page.goto("https://www.douyin.com/hot", wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(2500)
                raw = _scroll_and_collect(page, max_results, seen, rounds=2)
        finally:
            if context:
                context.close()
            browser.close()

        if not raw:
            raw = _try_profile_context(p, search_url, max_results=max_results, headless=headless)

    return raw[:max_results]
