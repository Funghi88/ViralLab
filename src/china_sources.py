"""China-native search sources. No VPN needed when used from China.

- Bilibili: Public API for video search.
- Douyin, Xiaohongshu, Shipinhao: Search URL templates (no public API).
"""
import urllib.parse
# Platform search URL templates (user searches directly on platform)
CHINA_PLATFORM_LINKS = {
    "douyin": {
        "name": "抖音 Douyin",
        "search_url": "https://www.douyin.com/search/{query}",
        "desc": "China's TikTok — short-form video",
    },
    "xiaohongshu": {
        "name": "小红书 Xiaohongshu",
        "search_url": "https://www.xiaohongshu.com/search_result?keyword={query}",
        "desc": "Lifestyle, beauty, fashion content",
    },
    "shipinhao": {
        "name": "视频号 Shipinhao (WeChat Channels)",
        "search_url": "https://channels.weixin.qq.com/search?query={query}",
        "desc": "WeChat's short-video channel",
    },
    "bilibili": {
        "name": "哔哩哔哩 Bilibili",
        "search_url": "https://search.bilibili.com/all?keyword={query}",
        "desc": "Long-form video, anime, tutorials",
    },
}


def get_china_search_url(platform: str, query: str) -> str:
    """Get search URL for a China platform."""
    info = CHINA_PLATFORM_LINKS.get(platform.lower())
    if not info:
        return ""
    encoded = urllib.parse.quote(query)
    return info["search_url"].format(query=encoded)


# Bilibili may block requests without Referer. Fetched via subprocess with no-proxy.
_BILIBILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/v/popular/rank/all",
    "Origin": "https://www.bilibili.com",
}


def _parse_bilibili_item(v: dict, max_results: int, out: list, category_filter: str) -> None:
    if category_filter:
        tname = (v.get("tname") or "")
        pid_name = (v.get("pid_name_v2") or "")
        tnamev2 = (v.get("tnamev2") or "")
        if not any(category_filter in x for x in (tname, pid_name, tnamev2) if x):
            return
    bvid = v.get("bvid", "") or f"av{v.get('aid', '')}"
    stat = v.get("stat", {})
    views = stat.get("view", 0) or stat.get("vv", 0)
    title = (v.get("title") or "").replace("<em class=\"keyword\">", "").replace("</em>", "")
    desc = (v.get("desc") or v.get("dynamic") or "")[:200]
    out.append({
        "title": title,
        "url": f"https://www.bilibili.com/video/{bvid}",
        "views": str(views) if views else "N/A",
        "views_int": int(views) if views else 0,
        "description": desc,
        "platform": "bilibili",
    })


def fetch_bilibili_popular(max_results: int = 20, category_filter: str = "") -> list[dict]:
    """Fetch Bilibili trending/popular videos. category_filter: filter by tname/pid_name_v2 (e.g. 鬼畜, 搞笑)."""
    import requests

    fetch_count = min(max_results * 3, 50) if category_filter else min(max_results, 50)
    out: list[dict] = []

    # Try popular API first, then ranking/v2 as fallback
    for url, params in [
        ("https://api.bilibili.com/x/web-interface/popular", {"ps": fetch_count, "pn": 1}),
        ("https://api.bilibili.com/x/web-interface/ranking/v2", {"rid": 0, "type": "all"}),
    ]:
        try:
            r = requests.get(url, params=params, headers=_BILIBILI_HEADERS, timeout=10)
            r.raise_for_status()
            data = r.json()
            if data.get("code") != 0:
                continue
            items = data.get("data", {}).get("list", [])
            for v in items:
                _parse_bilibili_item(v, max_results, out, category_filter)
                if len(out) >= max_results:
                    break
            if out:
                return out
        except Exception:
            continue
    if not out:
        raise RuntimeError("Bilibili API unavailable. Try Global source or check network.")
    return out


def search_bilibili(query: str, max_results: int = 10) -> list[dict]:
    """Search Bilibili videos via public API. Returns list of {title, url, views, desc}."""
    import requests

    url = "https://api.bilibili.com/x/web-interface/search/type"
    params = {"search_type": "video", "keyword": query, "page": 1}
    try:
        r = requests.get(
            url,
            params=params,
            headers={**_BILIBILI_HEADERS, "Referer": "https://search.bilibili.com/"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 0:
            return []

        results = data.get("data", {}).get("result", [])[:max_results]
        out = []
        for v in results:
            aid = v.get("aid")
            bvid = v.get("bvid", "")
            title = v.get("title", "").replace("<em class=\"keyword\">", "").replace("</em>", "")
            desc = (v.get("description") or "")[:200]
            views = v.get("play", 0) or v.get("view", 0)
            link = f"https://www.bilibili.com/video/{bvid or f'av{aid}'}"
            out.append({
                "title": title,
                "url": link,
                "views": str(views) if views else "N/A",
                "views_int": int(views) if views else 0,
                "description": desc,
                "platform": "bilibili",
            })
        return out
    except Exception as e:
        raise RuntimeError(f"Bilibili search failed: {e}") from e
