"""Creator-focused news fetchers. Each returns list of {title, snippet, url, date, source}."""
import html
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Callable, Optional
from urllib.parse import quote_plus

import requests
from src.ddg_client import get_ddgs_class
from src.pipeline import run_pipeline


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


# RSS feeds: top-tier, globally-recognised brands only.
# Rule: every entry must be a name readers already trust.
RSS_FEEDS_EN = [
    # Wire services — most authoritative
    ("https://feeds.reuters.com/reuters/technologyNews", "Reuters Technology"),
    ("https://feeds.bbci.co.uk/news/technology/rss.xml", "BBC Technology"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml", "New York Times Tech"),
    ("https://www.cnbc.com/id/19854910/device/rss/rss.html", "CNBC Technology"),
    # Major tech publications
    ("https://techcrunch.com/feed/", "TechCrunch"),
    ("https://www.theverge.com/rss/index.xml", "The Verge"),
    ("https://www.wired.com/feed/rss", "Wired"),
    ("https://feeds.arstechnica.com/arstechnica/index", "Ars Technica"),
    ("https://www.technologyreview.com/feed/", "MIT Technology Review"),
    ("https://venturebeat.com/feed/", "VentureBeat"),
    ("https://feeds.engadget.com/rss.xml", "Engadget"),
    ("https://www.cnet.com/rss/news/", "CNET"),
    ("https://www.techmeme.com/feed.xml", "Techmeme"),
    # Business & finance
    ("https://www.axios.com/feeds/feed.rss", "Axios"),
    ("https://www.fastcompany.com/feed", "Fast Company"),
    ("https://feeds.businessinsider.com/businessinsider/tech", "Business Insider Tech"),
    ("https://feeds.hbr.org/harvardbusiness/", "Harvard Business Review"),
    # Media, creator economy & marketing (brand-name only)
    ("https://variety.com/feed/", "Variety"),
    ("https://www.hollywoodreporter.com/feed/", "The Hollywood Reporter"),
    ("https://www.adweek.com/feed/", "Adweek"),
    ("https://adage.com/feed/", "Ad Age"),
    ("https://digiday.com/feed/", "Digiday"),
    ("https://tubefilter.com/feed/", "Tubefilter"),
    ("https://www.socialmediatoday.com/feeds/all.rss.xml", "Social Media Today"),
    ("https://podnews.net/rss", "Podnews"),
    ("https://restofworld.org/feed/", "Rest of World"),
]
RSS_FEEDS_ZH = [
    # 一线科技财经媒体
    ("https://36kr.com/feed", "36氪"),
    ("https://www.huxiu.com/rss/0.xml", "虎嗅"),
    ("https://www.tmtpost.com/?feed=rss2", "钛媒体"),
    ("https://cn.technode.com/feed/", "TechNode 中文"),
    ("https://www.ifanr.com/feed", "爱范儿"),
    ("https://www.jiqizhixin.com/rss", "机器之心"),
    ("https://www.qbitai.com/feed", "量子位"),
    ("https://www.geekpark.net/rss", "极客公园"),
    # 产品与创作者经济
    ("https://sspai.com/feed", "少数派"),
    ("https://www.woshipm.com/feed", "人人都是产品经理"),
    ("https://www.cyzone.cn/rss/", "创业邦"),
    ("https://www.infoq.cn/rss/", "InfoQ 中文"),
    # 深度报道
    ("https://www.pingwest.com/feed", "PingWest"),
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


# Shared with server.py for /news redirects and scripts/search_only.py output paths.
RAW_TOPIC_FILENAME_MAX_BYTES = 200

def raw_topic_file_stem(topic: str) -> str:
    """UTF-8-safe stem for ``output/raw_<stem>.md`` (avoids 30-char truncation vs long Chinese titles)."""
    s = (topic or "").strip().replace(" ", "_").replace("/", "_").replace("..", "_")
    if not s:
        return "unknown"
    enc = s.encode("utf-8")
    if len(enc) <= RAW_TOPIC_FILENAME_MAX_BYTES:
        return s
    cut = enc[:RAW_TOPIC_FILENAME_MAX_BYTES]
    while cut:
        try:
            return cut.decode("utf-8")
        except UnicodeDecodeError:
            cut = cut[:-1]
    return "topic"


def _zh_topic_matches_rss(query: str, title: str, snippet: str) -> bool:
    """Loose match for filtering Chinese RSS items by a user topic (substring + 2-gram)."""
    q = (query or "").strip()
    blob = f"{title or ''}{snippet or ''}"
    if not q or not blob:
        return False
    if q in blob:
        return True
    qc = q.replace(" ", "").replace("　", "")
    bc = blob.replace(" ", "").replace("　", "")
    if len(qc) >= 2 and qc in bc:
        return True
    if len(qc) >= 2:
        for i in range(len(qc) - 1):
            if qc[i : i + 2] in blob:
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
        DDGS = get_ddgs_class()
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


def fetch_duckduckgo_text_search(query: str, max_results: int = 8) -> list[dict[str, Any]]:
    """DuckDuckGo web search fallback when news search returns nothing (same stack as DDG news)."""
    if not (query or "").strip():
        return []
    region = "cn-zh" if _has_cjk(query) else "wt-wt"
    try:
        DDGS = get_ddgs_class()
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results, region=region))
        items = []
        for r in results[:max_results]:
            url = (r.get("href") or r.get("url") or "").strip()
            if not url:
                continue
            title = (r.get("title") or "").strip() or "N/A"
            body = (r.get("body") or "")[:250]
            items.append({
                "title": title,
                "snippet": body or "DuckDuckGo Web",
                "url": url,
                "date": "",
                "source": "DuckDuckGo Web",
            })
        return items
    except Exception as e:
        print(f"[DuckDuckGo Web] {e}")
        return []


def _zh_search_query_variants(query: str) -> list[str]:
    """Shorter / split queries so Google News / DDG are more likely to return hits."""
    q0 = (query or "").strip()
    if not q0:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for piece in (q0,):
        if piece and piece not in seen:
            seen.add(piece)
            out.append(piece)
    for sep in ("：", ":", "｜", "|", "——", "—"):
        if sep in q0:
            h = q0.split(sep, 1)[0].strip()
            if len(h) >= 4 and h not in seen:
                seen.add(h)
                out.append(h)
    if len(q0) > 28:
        short = q0[:28].strip()
        if len(short) >= 4 and short not in seen:
            out.append(short)
    return out[:6]


# Subreddits most useful for creator/viral content discovery
_REDDIT_SUBREDDITS_EN = [
    "marketing", "content_marketing", "socialmedia", "Entrepreneur",
    "YoutubeCreators", "TikTok", "videomarketing",
]
_REDDIT_SUBREDDITS_ZH: list[str] = []  # Reserved; Reddit is not accessible in CN.


def fetch_reddit_hot(max_results: int = 8, lang: str = "en") -> list[dict[str, Any]]:
    """Fetch hot posts from creator-relevant subreddits via Reddit RSS (no auth needed).
    Returns [] in zh mode (Reddit is not accessible in China).
    """
    if lang == "zh" or not _has_feedparser():
        return []
    import feedparser

    subreddits = _REDDIT_SUBREDDITS_EN
    items: list[dict[str, Any]] = []
    seen_urls: set = set()
    per = max(2, max_results // len(subreddits) + 1)
    headers = {"User-Agent": "ViralLab-news-fetcher/1.0 (rss)"}
    for sr in subreddits:
        if len(items) >= max_results:
            break
        try:
            r = requests.get(
                f"https://www.reddit.com/r/{sr}/hot.rss",
                params={"limit": per},
                headers=headers,
                timeout=8,
            )
            r.raise_for_status()
            d = feedparser.parse(r.content)
            for e in d.entries[:per]:
                if len(items) >= max_results:
                    break
                title = (e.get("title") or "").strip()
                url = e.get("link") or ""
                if not title or url in seen_urls:
                    continue
                seen_urls.add(url)
                summary = _sanitize_snippet(e.get("summary", "") or "", max_len=250)
                items.append({
                    "title": title,
                    "snippet": summary or f"r/{sr}",
                    "url": url,
                    "date": e.get("published", ""),
                    "source": f"Reddit r/{sr}",
                })
        except Exception as e:
            print(f"[Reddit r/{sr}] {e}")
    return items


def fetch_all_topic_sources(query: str, target_total: int = 18) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Search multiple sources by topic. DDG, Google News RSS, Serper (optional), HN, NewsAPI.
    Auto-detects lang from query (CJK = zh). Returns (items, sources_used).
    """
    q0 = (query or "").strip()
    if not q0:
        return [], []

    all_items: list[dict[str, Any]] = []
    sources_used: list[str] = []
    is_zh = _has_cjk(q0)
    threshold = min(8, max(4, target_total))
    search_queries = _zh_search_query_variants(q0) if is_zh else [q0]

    def _append_source(name: str) -> None:
        if name not in sources_used:
            sources_used.append(name)

    # Phase 1: Google News + DDG news — try zh query variants until we have enough.
    for sq in search_queries:
        if not sq:
            continue
        gnews = fetch_google_news_rss(sq, max_results=6)
        if gnews:
            all_items.extend(gnews)
            _append_source("Google News")
        ddg = fetch_duckduckgo_news(sq, max_results=6)
        if ddg:
            all_items.extend(ddg)
            _append_source("DuckDuckGo News")
        preliminary = run_pipeline(all_items)
        if len(preliminary) >= threshold:
            break

    serper = fetch_serper_news(q0, max_results=6)
    if serper:
        all_items.extend(serper)
        _append_source("Serper")

    if not is_zh:
        hn = fetch_hn_search(q0, max_results=5)
        if hn:
            all_items.extend(hn)
            _append_source("Hacker News")

    na = fetch_newsapi_search(q0, max_results=6)
    if na:
        all_items.extend(na)
        _append_source("NewsAPI")

    # Mainland / flaky VPN: Chinese RSS pool when results are thin.
    preliminary = run_pipeline(all_items)
    if is_zh and len(preliminary) < threshold:
        rss_zh = _run_with_timeout(lambda: fetch_rss_feeds(max_per_feed=5, lang="zh"), timeout_sec=45)
        if rss_zh:
            seen_urls = {str(x.get("url") or "").strip() for x in all_items if x.get("url")}
            matched: list[dict[str, Any]] = []
            other: list[dict[str, Any]] = []
            for it in rss_zh:
                u = str(it.get("url") or "").strip()
                if not u or u in seen_urls:
                    continue
                t, sn = it.get("title") or "", it.get("snippet") or ""
                if _zh_topic_matches_rss(q0, t, sn):
                    matched.append(it)
                else:
                    other.append(it)
            take = matched[: target_total + 6]
            need = max(0, min(12, target_total + 4) - len(take))
            take.extend(other[:need])
            for it in take:
                u = str(it.get("url") or "").strip()
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    all_items.append(it)
                    src = it.get("source") or ""
                    if src:
                        _append_source(src)

    # Last resort: DDG web (often works when news endpoint is empty).
    preliminary = run_pipeline(all_items)
    if len(preliminary) < max(3, min(6, target_total // 2)):
        for sq in search_queries[:4]:
            tw = fetch_duckduckgo_text_search(sq, max_results=8)
            if tw:
                all_items.extend(tw)
                _append_source("DuckDuckGo Web")
            if len(run_pipeline(all_items)) >= max(3, target_total // 2):
                break

    finalized = run_pipeline(all_items)
    return finalized[:target_total], sources_used


def fetch_duckduckgo_fallback(max_results: int = 5, lang: str = "en") -> list[dict[str, Any]]:
    """Fallback: DuckDuckGo news when no other sources configured."""
    query = "今日热门新闻" if lang == "zh" else "trending news today"
    try:
        DDGS = get_ddgs_class()
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
            for s in ["36氪", "虎嗅", "钛媒体", "TechNode 中文", "爱范儿", "机器之心", "量子位", "极客公园", "少数派", "人人都是产品经理", "创业邦", "InfoQ 中文", "PingWest"]:
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
            for feed_name in ["Reuters Technology", "BBC Technology", "New York Times Tech", "CNBC Technology", "TechCrunch", "The Verge", "Wired", "Ars Technica", "MIT Technology Review", "VentureBeat", "Engadget", "CNET", "Techmeme", "Axios", "Fast Company", "Business Insider Tech", "Harvard Business Review", "Variety", "The Hollywood Reporter", "Adweek", "Ad Age", "Digiday", "Tubefilter", "Social Media Today", "Podnews", "Rest of World"]:
                if any(i["source"] == feed_name for i in rss):
                    sources_used.append(feed_name)
        ddg = _run_with_timeout(lambda: fetch_duckduckgo_fallback(max_results=15, lang="en"), timeout_sec=15)
        if ddg:
            all_items.extend(ddg)
            sources_used.append("DuckDuckGo News")
        reddit = _run_with_timeout(lambda: fetch_reddit_hot(max_results=8, lang="en"), timeout_sec=12)
        if reddit:
            all_items.extend(reddit)
            sources_used.append("Reddit")
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

    finalized = run_pipeline(all_items)
    return finalized[:target_total], sources_used
