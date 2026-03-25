"""Xiaohongshu (小红书) search via Playwright. May require login for full results.

Optional: save session with `.venv/bin/python -m tools.china_crawler login --platform xhs`; then crawler loads config/china_crawler_xhs_state.json.
Selectors and flow inspired by LGXfufile/xiaohongshu-scraper (homepage → search → multiple note selectors).
"""

import urllib.parse
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_STATE_PATH = _PROJECT_ROOT / "config" / "china_crawler_xhs_state.json"

_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Note card selectors (try in order; LGXfufile-style + fallbacks)
_NOTE_SELECTORS = [
    'a[href*="/explore/"]',
    'a[href*="xiaohongshu.com/explore"]',
    'section[role="listitem"]',
    ".note-item",
    ".feed-item",
    '[data-testid="note"]',
    ".note-container",
    "article",
    ".card",
]
# Search box selectors for homepage-then-search flow
_SEARCH_INPUT_SELECTORS = [
    'input[placeholder*="搜索"]',
    'input[data-testid="search"]',
    ".search-input input",
    '[data-testid="searchbar"] input',
]


def _parse_notes_from_page(page, max_results: int, seen_urls: set) -> list[dict]:
    """Parse note items from current page using multiple selectors. Mutates seen_urls."""
    raw: list[dict] = []
    link_selectors = ('a[href*="/explore/"]', 'a[href*="xiaohongshu.com/explore"]')
    for selector in _NOTE_SELECTORS:
        try:
            elements = page.locator(selector).all()
            for el in elements:
                if len(raw) >= max_results:
                    break
                try:
                    if selector in link_selectors:
                        link_el = el
                    else:
                        link_el = el.locator("a").first
                    href = link_el.get_attribute("href") or ""
                    if not href or "explore" not in href:
                        continue
                    if "xiaohongshu.com" not in href and href.startswith("/"):
                        href = "https://www.xiaohongshu.com" + href
                    href = href.split("?")[0]
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)
                    title = (link_el.inner_text() or el.inner_text() or "").strip()[:200]
                    if not title or len(title) < 2:
                        title = "Note"
                    if "undefined" in title or "null" in title:
                        continue
                    raw.append({
                        "title": title,
                        "url": href,
                        "description": "",
                        "views": "N/A",
                        "content_type": "note",
                    })
                except Exception:
                    continue
            if raw:
                return raw
        except Exception:
            continue
    return raw


def fetch_xhs_search(keywords: str, max_results: int = 20, headless: bool = True) -> list[dict]:
    """Fetch XHS search result items. Returns raw list of dicts (title, url, description, views).
    Without login, XHS often shows a login wall and returns [].
    Use `.venv/bin/python -m tools.china_crawler login --platform xhs` to save a session locally.
    Tries direct search URL first; if empty, tries homepage → search box → Enter (LGXfufile-style).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright required. Run: pip install playwright && playwright install chromium"
        ) from None

    query = urllib.parse.quote(keywords)
    search_url = f"https://www.xiaohongshu.com/search_result?keyword={query}"
    raw: list[dict] = []
    seen_urls: set = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            if _STATE_PATH.exists():
                context = browser.new_context(storage_state=str(_STATE_PATH), user_agent=_USER_AGENT)
            else:
                context = browser.new_context(user_agent=_USER_AGENT)
            page = context.new_page()
            page.set_viewport_size({"width": 1920, "height": 1080})

            # 1) Direct search URL
            page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(3000)
            content = page.content()
            if "登录" in content and "/explore/" not in content:
                # 2) Try homepage → search flow (LGXfufile-style)
                page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)
                search_input = None
                for sel in _SEARCH_INPUT_SELECTORS:
                    try:
                        if page.locator(sel).count() > 0:
                            search_input = page.locator(sel).first
                            break
                    except Exception:
                        continue
                if search_input:
                    search_input.click()
                    page.wait_for_timeout(500)
                    search_input.fill(keywords)
                    page.wait_for_timeout(300)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(5000)
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                    page.wait_for_timeout(3000)
                    content = page.content()
            if "登录" in content and "/explore/" not in content:
                return []

            raw = _parse_notes_from_page(page, max_results, seen_urls)
            if not raw:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                page.wait_for_timeout(2000)
                raw = _parse_notes_from_page(page, max_results, seen_urls)

        finally:
            context.close()
            browser.close()

    return raw[:max_results]
