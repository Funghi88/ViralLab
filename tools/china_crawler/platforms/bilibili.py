"""Bilibili (哔哩哔哩) search/popular via public API (no login required)."""

from src.china_sources import fetch_bilibili_popular, search_bilibili


def fetch_bilibili_search(keywords: str, max_results: int = 20, headless: bool = True) -> list[dict]:
    """Fetch Bilibili items with public API only.

    headless arg is kept for interface compatibility with other platform fetchers.
    If keywords look like "热门", use popular feed; otherwise do keyword search.
    """
    _ = headless  # Not used for API-based fetch.
    kw = (keywords or "").strip()
    if not kw or kw in {"热门", "热榜", "hot", "popular"}:
        return fetch_bilibili_popular(max_results=max_results)
    results = search_bilibili(kw, max_results=max_results)
    if results:
        return results
    return fetch_bilibili_popular(max_results=max_results)
