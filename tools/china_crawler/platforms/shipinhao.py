"""Shipinhao (视频号 WeChat Channels) search via Playwright. May require login. All content: videos.

Optional: save session with `.venv/bin/python -m tools.china_crawler login --platform shipinhao`; then crawler loads config/china_crawler_shipinhao_state.json.
"""

import urllib.parse
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_STATE_PATH = _PROJECT_ROOT / "config" / "china_crawler_shipinhao_state.json"

_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def fetch_shipinhao_search(keywords: str, max_results: int = 20, headless: bool = True) -> list[dict]:
    """Fetch Shipinhao search items. WeChat login usually required. Use login subcommand to save session."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright required. Run: pip install playwright && playwright install chromium"
        ) from None

    query = urllib.parse.quote(keywords)
    url = f"https://channels.weixin.qq.com/search?query={query}"
    raw: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            if _STATE_PATH.exists():
                context = browser.new_context(storage_state=str(_STATE_PATH), user_agent=_USER_AGENT)
            else:
                context = browser.new_context(user_agent=_USER_AGENT)
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(3000)
            content = page.content()
            if "登录" in content or "login" in content.lower():
                return []
            for selector in ['a[href*="/channels/"]', 'a[href*="weixin.qq.com"]']:
                try:
                    links = page.locator(selector).all()
                    seen = set()
                    for el in links:
                        if len(raw) >= max_results:
                            break
                        href = el.get_attribute("href") or ""
                        if not href or href in seen:
                            continue
                        if "weixin.qq.com" not in href and "channels" not in href:
                            continue
                        if not href.startswith("http"):
                            href = "https://channels.weixin.qq.com" + (href if href.startswith("/") else "/" + href)
                        seen.add(href)
                        title = (el.inner_text() or "").strip()[:200]
                        raw.append({
                            "title": title or "Video",
                            "url": href.split("?")[0],
                            "description": "",
                            "views": "N/A",
                            "content_type": "video",
                        })
                    if raw:
                        break
                except Exception:
                    continue
        finally:
            context.close()
            browser.close()
    return raw[:max_results]
