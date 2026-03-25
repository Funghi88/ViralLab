"""Optional: fetch China platform data via Just One API or Apify using your API key.

- Just One API: set JUSTONEAPI_TOKEN, pip install justoneapi. No platform login needed.
- Apify: set APIFY_TOKEN, pip install apify-client. Run actor (e.g. Xiaohongshu Search), normalize output.

See docs/CHINA_CRAWLER_LOGIN.md section 5.
"""

from __future__ import annotations


def _normalize_item(
    *,
    title: str = "",
    url: str = "",
    description: str = "",
    views: str | int = "N/A",
    platform: str = "",
    content_type: str = "video",
) -> dict:
    """Same shape as tools.china_crawler.normalize.normalize_item."""
    views_int = 0
    if isinstance(views, int):
        views_int = views
    elif isinstance(views, str) and views.isdigit():
        views_int = int(views)
    return {
        "title": (title or "").strip()[:500],
        "url": (url or "").strip(),
        "description": (description or "")[:500],
        "views": str(views) if views else "N/A",
        "views_int": views_int,
        "platform": (platform or "").lower(),
        "content_type": (content_type or "video").lower() if content_type else "video",
    }


def fetch_xhs_via_justoneapi(keyword: str, max_results: int = 20, token: str | None = None) -> list[dict]:
    """Fetch Xiaohongshu search via Just One API. Returns list of normalized items or [] if token/sdk missing or error."""
    token = token or __import__("os").environ.get("JUSTONEAPI_TOKEN", "").strip()
    if not token:
        return []
    try:
        from justoneapi.client import JustOneAPIClient
    except ImportError:
        return []

    try:
        client = JustOneAPIClient(token=token)
        if not hasattr(client, "xiaohongshu"):
            return []
        xhs = client.xiaohongshu
        data = None
        for method_name in ("search_notes", "note_search", "search_note"):
            if not hasattr(xhs, method_name):
                continue
            try:
                fn = getattr(xhs, method_name)
                out_call = fn(keyword=keyword, page=1)
                if isinstance(out_call, (list, tuple)) and len(out_call) >= 2:
                    result, data = out_call[0], out_call[1]
                    if result and data:
                        break
            except (TypeError, Exception):
                continue
        if not data:
            return []

        items = data if isinstance(data, list) else (data.get("items") or data.get("list") or data.get("data") or [])
        out = []
        for i in items[:max_results]:
            if not isinstance(i, dict):
                continue
            url = i.get("url") or i.get("href") or i.get("link") or ""
            title = i.get("title") or i.get("name") or ""
            if not url and not title:
                continue
            if url and "xiaohongshu.com" not in url and "explore" in str(i.get("href", "")):
                url = (i.get("href") or "").strip()
            if not url.startswith("http"):
                url = "https://www.xiaohongshu.com/explore/" + (i.get("note_id") or i.get("id") or "") if (i.get("note_id") or i.get("id")) else ""
            out.append(_normalize_item(
                title=title,
                url=url or "https://www.xiaohongshu.com",
                description=i.get("desc") or i.get("description") or "",
                views=i.get("like_count") or i.get("views") or "N/A",
                platform="xiaohongshu",
                content_type="note",
            ))
        return out
    except Exception:
        return []


def fetch_douyin_via_justoneapi(keyword: str, max_results: int = 20, token: str | None = None) -> list[dict]:
    """Fetch Douyin video search via Just One API. Returns list of normalized items or []."""
    token = token or __import__("os").environ.get("JUSTONEAPI_TOKEN", "").strip()
    if not token:
        return []
    try:
        from justoneapi.client import JustOneAPIClient
    except ImportError:
        return []

    try:
        client = JustOneAPIClient(token=token)
        result, data, msg, _ = client.douyin.search_video_v4(
            keyword=keyword,
            sort_type="_0",
            publish_time="_0",
            duration="_0",
            page=1,
        )
        if not result or not data:
            return []
        items = data if isinstance(data, list) else (data.get("items") or data.get("list") or data.get("data") or [])
        out = []
        for i in items[:max_results]:
            if not isinstance(i, dict):
                continue
            aweme_id = i.get("aweme_id") or i.get("video_id") or i.get("id")
            url = i.get("url") or i.get("share_url") or (f"https://www.douyin.com/video/{aweme_id}" if aweme_id else "")
            title = i.get("title") or i.get("desc") or i.get("description") or ""
            out.append(_normalize_item(
                title=title[:500],
                url=url or "https://www.douyin.com",
                description=i.get("desc") or i.get("description") or "",
                views=i.get("play_count") or i.get("statistics", {}).get("play_count") or "N/A",
                platform="douyin",
                content_type="video",
            ))
        return out
    except Exception:
        return []


def fetch_xhs_via_apify(keyword: str, max_results: int = 20, token: str | None = None) -> list[dict]:
    """Fetch Xiaohongshu search via Apify actor kuaima/xiaohongshu-search. Returns list of normalized items or []."""
    token = token or __import__("os").environ.get("APIFY_TOKEN", "").strip()
    if not token:
        return []
    try:
        from apify_client import ApifyClient
    except ImportError:
        return []

    try:
        client = ApifyClient(token=token)
        run = client.actor("kuaima/xiaohongshu-search").call(
            run_input={"search_key": keyword, "maxItems": min(max_results, 50), "filter": "最新"}
        )
        dataset_id = run.get("defaultDatasetId")
        if not dataset_id:
            return []
        items = list(client.dataset(dataset_id).iterate_items())[:max_results]
        out = []
        for i in items:
            if not isinstance(i, dict):
                continue
            url = (i.get("href") or "").strip()
            if not url.startswith("http"):
                continue
            out.append(_normalize_item(
                title=i.get("title") or "",
                url=url,
                description=i.get("desec") or "",
                views=i.get("like_count") or "N/A",
                platform="xiaohongshu",
                content_type="note",
            ))
        return out
    except Exception:
        return []


def fetch_platform_via_third_party(platform: str, keyword: str, max_results: int = 20) -> list[dict]:
    """If third-party API token is set, fetch from Just One API or Apify; else return []."""
    platform = (platform or "").lower()
    if platform == "xhs":
        items = fetch_xhs_via_justoneapi(keyword, max_results)
        if not items:
            items = fetch_xhs_via_apify(keyword, max_results)
        return items
    if platform == "douyin":
        return fetch_douyin_via_justoneapi(keyword, max_results)
    return []
