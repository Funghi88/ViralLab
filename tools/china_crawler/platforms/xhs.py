"""Xiaohongshu (小红书) search via Playwright. May require login for full results.

Optional: save session with `.venv/bin/python -m tools.china_crawler login --platform xhs`;
then crawler loads config/china_crawler_xhs_state.json.

Detail-page scraping (full note body, "展开", comments) is intentionally out of scope
here: use the global Cursor skill "content-scraper" (browser-automation + MCP) on a
single note URL so selectors/steps stay aligned with that skill:
  - Open explore detail URL (not search results list); PC www.xiaohongshu.com preferred.
  - Click expand if body is truncated; merge .note-text paragraphs; cap comments ~50.
This module only collects search-result cards (title + explore URL).
"""
from __future__ import annotations

import urllib.parse
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_STATE_PATH = _PROJECT_ROOT / "config" / "china_crawler_xhs_state.json"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Note card selectors — tried in priority order
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
_SEARCH_INPUT_SELECTORS = [
    'input[placeholder*="搜索"]',
    'input[data-testid="search"]',
    ".search-input input",
    '[data-testid="searchbar"] input',
]


def _extract_title(el, is_link: bool) -> str:
    """Best-effort title extraction from a note card element."""
    # 1. Try heading tags inside the element
    try:
        for tag in ("h1", "h2", "h3", "span.title", ".note-title", ".title"):
            heading = el.locator(tag).first
            text = (heading.inner_text() or "").strip()[:200]
            if text and len(text) > 2:
                return text
    except Exception:
        pass
    # 2. Try img[alt] (XHS often puts the note title as alt text)
    try:
        img = el.locator("img").first
        alt = (img.get_attribute("alt") or "").strip()[:200]
        if alt and len(alt) > 2 and "undefined" not in alt and "null" not in alt:
            return alt
    except Exception:
        pass
    # 3. Fall back to element inner text
    try:
        text = (el.inner_text() or "").strip()[:200]
        if text and len(text) > 2 and "undefined" not in text and "null" not in text:
            return text
    except Exception:
        pass
    return ""


def _parse_notes_from_page(page, max_results: int, seen_urls: set) -> list[dict]:
    """Parse note items from current page, trying multiple selectors. Mutates seen_urls."""
    raw: list[dict] = []
    link_selectors = {'a[href*="/explore/"]', 'a[href*="xiaohongshu.com/explore"]'}

    for selector in _NOTE_SELECTORS:
        try:
            elements = page.locator(selector).all()
            for el in elements:
                if len(raw) >= max_results:
                    break
                try:
                    is_link = selector in link_selectors
                    link_el = el if is_link else el.locator("a").first
                    href = link_el.get_attribute("href") or ""
                    if not href or "explore" not in href:
                        continue
                    if "xiaohongshu.com" not in href and href.startswith("/"):
                        href = "https://www.xiaohongshu.com" + href
                    href = href.split("?")[0]
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)
                    title = _extract_title(el, is_link) or _extract_title(link_el, True)
                    if not title:
                        title = "Note"
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


def _scroll_and_collect(page, max_results: int, seen_urls: set, rounds: int = 4) -> list[dict]:
    """Scroll the page in multiple rounds to trigger lazy loading and collect notes."""
    all_raw: list[dict] = []
    for i in range(rounds):
        batch = _parse_notes_from_page(page, max_results - len(all_raw), seen_urls)
        all_raw.extend(batch)
        if len(all_raw) >= max_results:
            break
        # Scroll progressively: 1/4, 1/2, 3/4, bottom
        fraction = (i + 1) / rounds
        page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {fraction:.2f})")
        page.wait_for_timeout(2000)
    return all_raw


def fetch_xhs_search(keywords: str, max_results: int = 20, headless: bool = True) -> list[dict]:
    """Fetch XHS search result notes.

    Without login, XHS shows a login wall and returns [].
    Run `.venv/bin/python -m tools.china_crawler login --platform xhs` to save a session.

    Flow:
    1. Try direct search URL.
    2. If blocked, try homepage → search box → Enter (LGXfufile-style).
    3. Multi-round scrolling to collect up to max_results notes.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright required. Run: pip install playwright && playwright install chromium"
        ) from None

    query = urllib.parse.quote(keywords)
    search_url = f"https://www.xiaohongshu.com/search_result?keyword={query}"
    seen_urls: set = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            if _STATE_PATH.exists():
                context = browser.new_context(
                    storage_state=str(_STATE_PATH), user_agent=_USER_AGENT
                )
            else:
                context = browser.new_context(user_agent=_USER_AGENT)
            page = context.new_page()
            page.set_viewport_size({"width": 1920, "height": 1080})

            # 1) Direct search URL
            page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)
            content = page.content()

            if "登录" in content and "/explore/" not in content:
                # 2) Homepage → search box → Enter
                page.goto(
                    "https://www.xiaohongshu.com", wait_until="domcontentloaded", timeout=20000
                )
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
                    page.wait_for_timeout(400)
                    search_input.fill(keywords)
                    page.wait_for_timeout(300)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(5000)
                content = page.content()

            if "登录" in content and "/explore/" not in content:
                return []

            raw = _scroll_and_collect(page, max_results, seen_urls, rounds=4)

        finally:
            context.close()
            browser.close()

    return raw[:max_results]
