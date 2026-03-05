"""Creator-focused news fetchers. Each returns list of {title, snippet, url, date, source}."""
import html
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime
from typing import Any, Callable, Optional
from urllib.parse import quote_plus

import requests


def _run_with_timeout(func: Callable, timeout_sec: float = 12, default: Any = None) -> Any:
    """Run func() in a thread; return default (or []) on timeout."""
    if default is None:
        default = []
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(func)
            return future.result(timeout=timeout_sec)
    except FuturesTimeoutError:
        return default


def _sanitize_snippet(text: str, max_len: int = 250) -> str:
    """Strip HTML tags and decode entities. HN/RSS can return raw HTML in snippets."""
    if not text or not isinstance(text, str):
        return ""
    s = html.unescape(text)
    s = re.sub(r"<[^>]*>?", "", s)  # strip tags including malformed/unclosed
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len]

# Optional deps - import only when used
def _has_feedparser():
    try:
        import feedparser
        return True
    except ImportError:
        return False

def _has_google_api():
    try:
        from googleapiclient.discovery import build
        return True
    except ImportError:
        return False


def fetch_hacker_news(max_results: int = 5) -> list[dict[str, Any]]:
    """Fetch top stories from Hacker News via Algolia (no API key)."""
    items = []
    try:
        r = requests.get(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={"tags": "front_page", "hitsPerPage": max_results},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        for hit in data.get("hits", [])[:max_results]:
            title = hit.get("title") or hit.get("story_title", "N/A")
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
            items.append({
                "title": title,
                "snippet": _sanitize_snippet(hit.get("story_text") or hit.get("comment_text") or "") or "Hacker News front page",
                "url": url,
                "date": hit.get("created_at", ""),
                "source": "Hacker News",
            })
    except Exception as e:
        print(f"[HN] {e}")
    return items


def fetch_product_hunt(max_results: int = 5) -> list[dict[str, Any]]:
    """Fetch today's top products from Product Hunt. Needs PRODUCT_HUNT_TOKEN."""
    token = os.environ.get("PRODUCT_HUNT_TOKEN")
    if not token:
        return []
    items = []
    try:
        r = requests.post(
            "https://api.producthunt.com/v2/api/graphql",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "query": """
                query {
                    posts(first: %d, order: RANKING) {
                        edges {
                            node {
                                name
                                tagline
                                url
                                createdAt
                            }
                        }
                    }
                }
                """ % max_results,
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        edges = data.get("data", {}).get("posts", {}).get("edges", [])
        for e in edges[:max_results]:
            node = e.get("node", {})
            items.append({
                "title": node.get("name", "N/A"),
                "snippet": node.get("tagline", "Product Hunt")[:250],
                "url": node.get("url", "https://producthunt.com"),
                "date": node.get("createdAt", ""),
                "source": "Product Hunt",
            })
    except Exception as e:
        print(f"[Product Hunt] {e}")
    return items


def fetch_newsapi(max_results: int = 5, language: str = "en") -> list[dict[str, Any]]:
    """Fetch top headlines from NewsAPI. Needs NEWSAPI_KEY. language: en or zh."""
    key = os.environ.get("NEWSAPI_KEY")
    if not key:
        return []
    items = []
    try:
        r = requests.get(
            "https://newsapi.org/v2/top-headlines",
            params={
                "apiKey": key,
                "language": language,
                "pageSize": max_results,
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        for a in data.get("articles", [])[:max_results]:
            if a.get("title") and a.get("title") != "[Removed]":
                items.append({
                    "title": a.get("title", "N/A"),
                    "snippet": (a.get("description") or "")[:250] or a.get("source", {}).get("name", ""),
                    "url": a.get("url", ""),
                    "date": a.get("publishedAt", ""),
                    "source": a.get("source", {}).get("name", "NewsAPI"),
                })
    except Exception as e:
        print(f"[NewsAPI] {e}")
    return items


def fetch_youtube_trending(max_results: int = 5, region: str = "US") -> list[dict[str, Any]]:
    """Fetch trending videos from YouTube. Needs YOUTUBE_API_KEY. region: US, TW, HK."""
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key or not _has_google_api():
        return []
    items = []
    try:
        from googleapiclient.discovery import build
        yt = build("youtube", "v3", developerKey=key)
        req = yt.videos().list(
            part="snippet,statistics",
            chart="mostPopular",
            regionCode=region,
            maxResults=max_results,
        )
        res = req.execute()
        for v in res.get("items", [])[:max_results]:
            snip = v.get("snippet", {})
            vid = v.get("id", "")
            items.append({
                "title": snip.get("title", "N/A"),
                "snippet": (snip.get("description", ""))[:250] or "YouTube trending",
                "url": f"https://youtube.com/watch?v={vid}",
                "date": snip.get("publishedAt", ""),
                "source": "YouTube Trending",
            })
    except Exception as e:
        print(f"[YouTube] {e}")
    return items


# RSS feeds: (url, source_name). Add more here for diversity.
RSS_FEEDS_EN = [
    # Tech & startups
    ("https://techcrunch.com/feed/", "TechCrunch"),
    ("https://www.theverge.com/rss/index.xml", "The Verge"),
    ("https://tubefilter.com/feed/", "Tubefilter"),  # YouTube/creator industry
    ("https://feeds.arstechnica.com/arstechnica/index", "Ars Technica"),
    ("https://www.wired.com/feed/rss", "Wired"),
    ("https://www.geekwire.com/feed", "GeekWire"),
    ("https://feeds.engadget.com/rss.xml", "Engadget"),
    ("https://www.digitaltrends.com/feed/", "Digital Trends"),
    ("https://www.technologyreview.com/feed/", "MIT Technology Review"),
    ("https://www.cnet.com/rss/news/", "CNET"),
    ("https://gizmodo.com/rss", "Gizmodo"),
    ("https://www.techradar.com/feeds.xml", "TechRadar"),
    ("https://www.zdnet.com/news/rss.xml", "ZDNet"),
    ("https://www.techrepublic.com/rssfeeds/articles/", "TechRepublic"),
    ("https://venturebeat.com/feed/", "VentureBeat"),
    ("https://feeds.mashable.com/mashable", "Mashable"),
    # Creator & social media
    ("https://feed.indiehackers.world/posts.rss", "Indie Hackers"),
    ("https://buffer.com/resources/feed/", "Buffer"),
    ("https://www.socialmediaexaminer.com/feed/", "Social Media Examiner"),
    ("https://later.com/blog/feed/", "Later"),
    ("https://blog.hootsuite.com/feed/", "Hootsuite"),
    # Business & media
    ("https://www.fastcompany.com/feed", "Fast Company"),
    ("https://www.adweek.com/feed/", "Adweek"),
    ("https://variety.com/feed/", "Variety"),
    ("https://digiday.com/feed/", "Digiday"),
    ("https://www.axios.com/feeds/feed.rss", "Axios"),
]
RSS_FEEDS_ZH = [
    # 科技创投
    ("https://cn.technode.com/feed/", "TechNode"),
    ("https://36kr.com/feed", "36氪"),
    ("https://www.ifanr.com/feed", "爱范儿"),
    ("https://www.pingwest.com/feed", "PingWest"),
    ("https://www.huxiu.com/rss/0.xml", "虎嗅"),
    ("https://36kr.com/feed-article", "36氪文章"),
    ("https://www.tmtpost.com/?feed=rss2", "钛媒体"),
    # 产品与工具
    ("https://sspai.com/feed", "少数派"),
    ("https://www.leiphone.com/feed", "雷锋网"),
    ("https://www.zhihu.com/rss", "知乎日报"),
    # 新增：优质科技媒体
    ("https://www.infoq.cn/rss/", "InfoQ"),
    ("https://www.geekpark.net/rss", "极客公园"),
    ("https://www.gcores.com/rss", "机核"),
    ("https://www.jiqizhixin.com/rss", "机器之心"),
    ("https://www.qbitai.com/feed", "量子位"),
    ("https://rss.mydrivers.com/rss.aspx?Tid=1", "快科技"),
]


def fetch_rss_feeds(max_per_feed: int = 2, lang: str = "en") -> list[dict[str, Any]]:
    """Fetch RSS. Uses RSS_FEEDS_EN or RSS_FEEDS_ZH. Add feeds to those lists to diversify."""
    if not _has_feedparser():
        return []
    import feedparser
    items = []
    feeds = RSS_FEEDS_ZH if lang == "zh" else RSS_FEEDS_EN
    for url, name in feeds:
        try:
            r = requests.get(url, timeout=6)
            r.raise_for_status()
            d = feedparser.parse(r.content)
            for e in d.entries[:max_per_feed]:
                title = e.get("title", "N/A")
                link = e.get("link", "")
                summary = _sanitize_snippet(e.get("summary", "") or "", max_len=250)
                items.append({
                    "title": title,
                    "snippet": summary or name,
                    "url": link,
                    "date": e.get("published", ""),
                    "source": name,
                })
        except Exception as e:
            print(f"[RSS {name}] {e}")
    return items


def fetch_hn_search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search Hacker News by topic. No API key. Creator-relevant tech/startup news."""
    items = []
    try:
        r = requests.get(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={"query": query, "tags": "story", "hitsPerPage": max_results},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        for hit in data.get("hits", [])[:max_results]:
            title = hit.get("title") or hit.get("story_title", "N/A")
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
            items.append({
                "title": title,
                "snippet": _sanitize_snippet(hit.get("story_text") or "") or "Hacker News",
                "url": url,
                "date": hit.get("created_at", ""),
                "source": "Hacker News",
            })
    except Exception as e:
        print(f"[HN Search] {e}")
    return items


def _has_cjk(s: str) -> bool:
    """True if string contains CJK characters."""
    for c in s:
        if "\u4e00" <= c <= "\u9fff" or "\u3000" <= c <= "\u303f" or "\uac00" <= c <= "\ud7af":
            return True
    return False


def fetch_newsapi_search(query: str, max_results: int = 5, language: Optional[str] = None) -> list[dict[str, Any]]:
    """Search NewsAPI by topic. Needs NEWSAPI_KEY. language: en, zh, or None (auto from query)."""
    key = os.environ.get("NEWSAPI_KEY")
    if not key:
        return []
    if language is None:
        language = "zh" if _has_cjk(query) else "en"
    items = []
    try:
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "apiKey": key,
                "q": query,
                "pageSize": max_results,
                "sortBy": "publishedAt",
                "language": language,
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        for a in data.get("articles", [])[:max_results]:
            if a.get("title") and a.get("title") != "[Removed]":
                items.append({
                    "title": a.get("title", "N/A"),
                    "snippet": (a.get("description") or "")[:250] or a.get("source", {}).get("name", ""),
                    "url": a.get("url", ""),
                    "date": a.get("publishedAt", ""),
                    "source": a.get("source", {}).get("name", "NewsAPI"),
                })
    except Exception as e:
        print(f"[NewsAPI Search] {e}")
    return items


def fetch_google_news_rss(query: str, max_results: int = 6, lang: Optional[str] = None) -> list[dict[str, Any]]:
    """Search Google News via RSS. No API key. lang: en or zh (auto from query)."""
    if lang is None:
        lang = "zh" if _has_cjk(query) else "en"
    if lang == "zh":
        hl, gl, ceid = "zh-CN", "CN", "CN:zh"
    else:
        hl, gl, ceid = "en-US", "US", "US:en"
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl={hl}&gl={gl}&ceid={ceid}"
    items = []
    if not _has_feedparser():
        return items
    try:
        import feedparser
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        d = feedparser.parse(r.content)
        for e in d.entries[:max_results]:
            title = e.get("title", "N/A")
            link = e.get("link", "")
            summary = (e.get("summary", "") or "").replace("<[^>]+>", "")
            summary = re.sub(r"<[^>]+>", "", summary)[:250]
            items.append({
                "title": title,
                "snippet": summary or "Google News",
                "url": link,
                "date": e.get("published", ""),
                "source": "Google News",
            })
    except Exception as e:
        print(f"[Google News RSS] {e}")
    return items


def fetch_serper_news(query: str, max_results: int = 6, lang: Optional[str] = None) -> list[dict[str, Any]]:
    """Search news via Serper (Google News API). Needs SERPER_API_KEY."""
    key = os.environ.get("SERPER_API_KEY")
    if not key:
        return []
    if lang is None:
        lang = "zh" if _has_cjk(query) else "en"
    gl = "cn" if lang == "zh" else "us"
    hl = "zh-cn" if lang == "zh" else "en"
    items = []
    try:
        r = requests.post(
            "https://google.serper.dev/news",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": query, "num": max_results, "gl": gl, "hl": hl},
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
        for n in data.get("news", [])[:max_results]:
            items.append({
                "title": n.get("title", "N/A"),
                "snippet": (n.get("snippet") or "")[:250],
                "url": n.get("link", ""),
                "date": n.get("date", ""),
                "source": n.get("source", "Serper"),
            })
    except Exception as e:
        print(f"[Serper News] {e}")
    return items


def fetch_duckduckgo_news(query: str, max_results: int = 5, region: Optional[str] = None) -> list[dict[str, Any]]:
    """Search DuckDuckGo news by topic. No API key. region: us-en (default), cn-zh for Chinese."""
    if region is None:
        region = "cn-zh" if _has_cjk(query) else "us-en"
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.news(query, max_results=max_results, region=region))
        items = []
        for r in results[:max_results]:
            items.append({
                "title": r.get("title", "N/A"),
                "snippet": (r.get("body") or "")[:250],
                "url": r.get("url", ""),
                "date": r.get("date", ""),
                "source": "DuckDuckGo News",
            })
        return items
    except Exception as e:
        print(f"[DuckDuckGo] {e}")
        return []


def fetch_all_topic_sources(query: str, target_total: int = 18) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Search multiple sources by topic. DDG, Google News RSS, Serper (optional), HN, NewsAPI.
    Auto-detects lang from query (CJK = zh). Returns (items, sources_used).
    """
    all_items = []
    sources_used = []
    is_zh = _has_cjk(query)

    gnews = fetch_google_news_rss(query, max_results=6)
    if gnews:
        all_items.extend(gnews)
        sources_used.append("Google News")

    ddg = fetch_duckduckgo_news(query, max_results=6)
    if ddg:
        all_items.extend(ddg)
        sources_used.append("DuckDuckGo News")

    serper = fetch_serper_news(query, max_results=6)
    if serper:
        all_items.extend(serper)
        sources_used.append("Serper")

    if not is_zh:
        hn = fetch_hn_search(query, max_results=5)
        if hn:
            all_items.extend(hn)
            sources_used.append("Hacker News")

    na = fetch_newsapi_search(query, max_results=6)
    if na:
        all_items.extend(na)
        sources_used.append("NewsAPI")

    seen = set()
    unique = []
    for it in all_items:
        key = (it["title"] or "").lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(it)

    def _sort_key(x):
        d = x.get("date") or ""
        if not d:
            return 0
        try:
            d = d.replace("Z", "+00:00")[:26]
            return datetime.fromisoformat(d).timestamp()
        except Exception:
            return 0

    unique.sort(key=_sort_key, reverse=True)
    return unique[:target_total], sources_used


def fetch_duckduckgo_fallback(max_results: int = 5, lang: str = "en") -> list[dict[str, Any]]:
    """Fallback: DuckDuckGo news when no other sources configured."""
    query = "今日热门新闻" if lang == "zh" else "trending news today"
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.news(query, max_results=max_results, timelimit="d"))
        items = []
        for r in results[:max_results]:
            items.append({
                "title": r.get("title", "N/A"),
                "snippet": (r.get("body") or "")[:250],
                "url": r.get("url", ""),
                "date": r.get("date", ""),
                "source": "DuckDuckGo News",
            })
        return items
    except Exception as e:
        print(f"[DuckDuckGo] {e}")
        return []


def fetch_all_sources(target_total: int = 10, lang: str = "en") -> tuple[list[dict[str, Any]], list[str]]:
    """
    Fetch from all configured sources, merge and dedupe by title.
    lang: en (English) or zh (Chinese).
    Returns (items, list of source names that contributed).
    """
    all_items = []
    sources_used = []

    if lang == "zh":
        # Chinese sources
        rss = _run_with_timeout(lambda: fetch_rss_feeds(max_per_feed=4, lang="zh"), timeout_sec=25)
        if rss:
            all_items.extend(rss)
            for s in ["TechNode", "36氪", "36氪文章", "爱范儿", "PingWest", "少数派", "虎嗅", "雷锋网", "钛媒体", "知乎日报", "InfoQ", "极客公园", "机核", "机器之心", "量子位", "快科技"]:
                if any(i["source"] == s for i in rss):
                    sources_used.append(s)
        ddg = _run_with_timeout(lambda: fetch_duckduckgo_fallback(max_results=25, lang="zh"), timeout_sec=15)
        if ddg:
            all_items.extend(ddg)
            sources_used.append("DuckDuckGo 新闻")
        na = fetch_newsapi(max_results=15, language="zh")
        if na:
            all_items.extend(na)
            sources_used.append("NewsAPI")
        yt = fetch_youtube_trending(max_results=10, region="TW")
        if yt:
            all_items.extend(yt)
            sources_used.append("YouTube 热门")
    else:
        # English sources
        hn = fetch_hacker_news(max_results=10)
        if hn:
            all_items.extend(hn)
            sources_used.append("Hacker News")
        rss = _run_with_timeout(lambda: fetch_rss_feeds(max_per_feed=3, lang="en"), timeout_sec=40)
        if rss:
            all_items.extend(rss)
            for feed_name in ["TechCrunch", "The Verge", "Tubefilter", "Ars Technica", "Wired", "GeekWire", "Engadget", "Digital Trends", "MIT Technology Review", "CNET", "Gizmodo", "TechRadar", "ZDNet", "TechRepublic", "VentureBeat", "Mashable", "Indie Hackers", "Buffer", "Social Media Examiner", "Later", "Hootsuite", "Fast Company", "Adweek", "Variety", "Digiday", "Axios"]:
                if any(i["source"] == feed_name for i in rss):
                    sources_used.append(feed_name)
        ddg = _run_with_timeout(lambda: fetch_duckduckgo_fallback(max_results=15, lang="en"), timeout_sec=15)
        if ddg:
            all_items.extend(ddg)
            sources_used.append("DuckDuckGo News")
        ph = fetch_product_hunt(max_results=10)
        if ph:
            all_items.extend(ph)
            sources_used.append("Product Hunt")
        na = fetch_newsapi(max_results=15, language="en")
        if na:
            all_items.extend(na)
            sources_used.append("NewsAPI")
        yt = fetch_youtube_trending(max_results=10, region="US")
        if yt:
            all_items.extend(yt)
            sources_used.append("YouTube Trending")

    # Dedupe by title (case-insensitive)
    seen = set()
    unique = []
    for it in all_items:
        key = (it["title"] or "").lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(it)

    # Sort by date if available, else keep order (newest first)
    def _sort_key(x):
        d = x.get("date") or ""
        if not d:
            return 0
        try:
            d = d.replace("Z", "+00:00")[:26]
            return datetime.fromisoformat(d).timestamp()
        except Exception:
            return 0

    unique.sort(key=_sort_key, reverse=True)
    return unique[:target_total], sources_used
