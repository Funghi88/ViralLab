"""Creator-focused news fetchers. Each returns list of {title, snippet, url, date, source}."""
import html
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from typing import Any, Callable, Optional
from urllib.parse import quote_plus, urlparse

import requests
from src.ddg_client import get_ddgs_class
from src.pipeline import run_pipeline
from src.podcast_rss_sources import classify_source_type
from src.proxy_env import requests_proxies_for


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


_BLOCKED_SOCIAL_DOMAINS = {
    "reddit.com",
    "redd.it",
    "x.com",
    "twitter.com",
    "t.co",
    "nitter.net",
}


def _hostname(url: str) -> str:
    try:
        host = (urlparse((url or "").strip()).hostname or "").lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _is_blocked_social_url(url: str) -> bool:
    host = _hostname(url)
    if not host:
        return False
    if host == "redd.it" or host.endswith(".redd.it"):
        return True
    if host == "reddit.com" or host.endswith(".reddit.com"):
        return True
    return any(host == d or host.endswith(f".{d}") for d in _BLOCKED_SOCIAL_DOMAINS if d not in ("reddit.com", "redd.it"))


def _filter_social_noise(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop forum/social threads (Reddit, X, etc.); daily news should be publisher coverage only."""
    filtered: list[dict[str, Any]] = []
    for item in items:
        source = (item.get("source", "") or "").lower()
        url = item.get("url", "") or ""
        if "reddit" in source or "subreddit" in source or "twitter" in source or source.startswith("x "):
            continue
        if _is_blocked_social_url(url):
            continue
        if "reddit.com/" in (url or "").lower() or "redd.it/" in (url or "").lower():
            continue
        filtered.append(item)
    return filtered

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
    # Global wire & international broadcasters (verified live)
    ("https://feeds.bbci.co.uk/news/world/rss.xml", "BBC World"),
    ("https://feeds.bbci.co.uk/news/technology/rss.xml", "BBC Technology"),
    ("https://feeds.npr.org/1004/rss.xml", "NPR World"),
    ("https://feeds.npr.org/1019/rss.xml", "NPR Technology"),
    ("https://www.theguardian.com/world/rss", "The Guardian World"),
    ("https://www.theguardian.com/uk/technology/rss", "The Guardian Tech"),
    ("https://www.aljazeera.com/xml/rss/all.xml", "Al Jazeera"),
    ("https://rss.dw.com/rdf/rss-en-all", "Deutsche Welle (DW)"),
    ("https://www.france24.com/en/rss", "France 24"),
    ("https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml", "CNA (Singapore)"),
    ("https://www.scmp.com/rss/91/feed", "South China Morning Post"),
    ("https://www.japantimes.co.jp/feed/", "The Japan Times"),
    ("https://www.abc.net.au/news/feed/2942460/rss.xml", "ABC News Australia"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml", "New York Times Tech"),
    ("https://www.cnbc.com/id/19854910/device/rss/rss.html", "CNBC Technology"),
    ("https://www.ft.com/rss/home/international", "Financial Times"),
    ("https://www.semafor.com/rss.xml", "Semafor"),
    # Major tech publications
    ("https://techcrunch.com/feed/", "TechCrunch"),
    ("https://www.theverge.com/rss/index.xml", "The Verge"),
    ("https://www.wired.com/feed/rss", "Wired"),
    ("https://feeds.arstechnica.com/arstechnica/index", "Ars Technica"),
    ("https://www.technologyreview.com/feed/", "MIT Technology Review"),
    ("https://venturebeat.com/feed/", "VentureBeat"),
    ("https://www.engadget.com/rss.xml", "Engadget"),
    ("https://www.cnet.com/rss/news/", "CNET"),
    ("https://www.techmeme.com/feed.xml", "Techmeme"),
    ("https://www.axios.com/feeds/feed.rss", "Axios"),
    # Media, creator economy & global reporting
    ("https://variety.com/feed/", "Variety"),
    ("https://www.hollywoodreporter.com/feed/", "The Hollywood Reporter"),
    ("https://www.adweek.com/feed/", "Adweek"),
    ("https://digiday.com/feed/", "Digiday"),
    ("https://tubefilter.com/feed/", "Tubefilter"),
    ("https://podnews.net/rss", "Podnews"),
    ("https://restofworld.org/feed/", "Rest of World"),
]

# Hollywood / entertainment RSS — used only in the light “entertainment” slice of Daily News.
_HOLLYWOOD_SOURCE_LABELS_EN = frozenset({"Variety", "The Hollywood Reporter"})
RSS_FEEDS_EN_CORE = [p for p in RSS_FEEDS_EN if p[1] not in _HOLLYWOOD_SOURCE_LABELS_EN]
RSS_FEEDS_EN_HOLLYWOOD = [p for p in RSS_FEEDS_EN if p[1] in _HOLLYWOOD_SOURCE_LABELS_EN]

RSS_FEEDS_ZH = [
    # 国际华文与全球视角（实测可用）
    ("https://rss.dw.com/xml/rss-chi-all", "德国之声中文"),
    ("https://www.rfi.fr/cn/rss", "法广中文 RFI"),
    # 一线科技与开发者媒体（实测可用）
    ("https://www.ithome.com/rss/", "IT之家"),
    ("https://www.qbitai.com/feed", "量子位"),
    ("https://www.ifanr.com/feed", "爱范儿"),
    ("https://sspai.com/feed", "少数派"),
    ("https://www.solidot.org/index.rss", "Solidot"),
    ("https://www.oschina.net/news/rss", "开源中国"),
    # 产品与创作者经济
    ("https://www.woshipm.com/feed", "人人都是产品经理"),
    ("https://www.cyzone.cn/rss/", "创业邦"),
]

# High-authority AI sources for founder-grade signal tracking (verified live).
AI_AUTHORITY_FEEDS_EN = [
    ("https://openai.com/news/rss.xml", "OpenAI Blog"),
    ("https://blog.google/technology/ai/rss/", "Google AI Blog"),
    ("https://deepmind.google/blog/rss.xml", "Google DeepMind Blog"),
    ("https://huggingface.co/blog/feed.xml", "Hugging Face Blog"),
    ("https://bair.berkeley.edu/blog/feed.xml", "BAIR Blog"),
    ("https://simonwillison.net/atom/everything/", "Simon Willison (AI)"),
    ("https://www.technologyreview.com/feed/", "MIT Technology Review"),
    ("https://stratechery.com/feed/", "Stratechery"),
]
AI_AUTHORITY_FEEDS_ZH = [
    ("https://www.qbitai.com/feed", "量子位"),
    ("https://www.ithome.com/rss/", "IT之家"),
]
AI_AUTHORITY_TARGETED_ZH = [
    {"label": "机器之心", "domains": ("jiqizhixin.com",), "query": "site:jiqizhixin.com 人工智能 OR 大模型"},
    {"label": "DeepTech", "domains": ("mittrchina.com",), "query": "site:mittrchina.com 人工智能 OR 科技趋势"},
    {"label": "甲子光年", "domains": ("jazzyear.com",), "query": "site:jazzyear.com 人工智能 OR 投融资"},
    {"label": "阿里研究院", "domains": ("aliresearch.com",), "query": "site:aliresearch.com 人工智能 OR 数字经济"},
    {"label": "新智元", "domains": ("aiera.com.cn",), "query": "site:aiera.com.cn 人工智能 OR AGI OR ASI"},
]
AI_AUTHORITY_SEARCH_EN = [
    "OpenAI official blog",
    "Anthropic research news",
    "Google DeepMind blog",
    "Stanford HAI AI Index",
    "The Batch DeepLearning.AI",
    "Hugging Face blog",
    "AI startup funding venture capital",
    "AI policy governance regulation labor impact",
    "Nvidia AI datacenter capex",
    "OpenAI Anthropic valuation funding",
]
AI_INTEL_LAYER_ORDER = ("Research", "Industry", "Investment", "Strategy & Society")
AI_INTEL_CADENCE_ORDER = ("Daily", "Weekly", "Monthly", "Quarterly")
AI_AUTHORITY_SOURCE_PROFILE: dict[str, tuple[str, str]] = {
    "OpenAI Blog": ("Industry", "Daily"),
    "Google AI Blog": ("Research", "Daily"),
    "Google DeepMind Blog": ("Research", "Daily"),
    "Simon Willison (AI)": ("Industry", "Daily"),
    "Hugging Face Blog": ("Industry", "Daily"),
    "BAIR Blog": ("Research", "Monthly"),
    "AI2 Blog": ("Research", "Monthly"),
    "Stanford HAI": ("Strategy & Society", "Monthly"),
    "MIT Technology Review": ("Strategy & Society", "Daily"),
    "The Batch": ("Industry", "Weekly"),
    "Stratechery": ("Investment", "Weekly"),
    "机器之心": ("Research", "Daily"),
    "量子位": ("Industry", "Daily"),
    "DeepTech": ("Strategy & Society", "Weekly"),
    "腾讯研究院": ("Strategy & Society", "Monthly"),
    "阿里研究院": ("Industry", "Monthly"),
    "新智元": ("Industry", "Daily"),
    "甲子光年": ("Investment", "Weekly"),
}
AI_AUTHORITY_LAYER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Research": (
        "research", "paper", "benchmark", "model", "inference", "training",
        "robotics", "reinforcement learning", "alignment eval", "science",
        "world model", "dataset", "arxiv", "论文", "研究", "模型评测", "实验",
    ),
    "Industry": (
        "launch", "product", "api", "agent", "enterprise", "deployment",
        "customer", "feature", "assistant", "release", "platform",
        "发布", "产品", "落地", "公司", "商业化", "应用",
    ),
    "Investment": (
        "funding", "venture", "vc", "valuation", "ipo", "m&a",
        "acquisition", "capital", "revenue", "earnings", "market cap",
        "financing", "investor", "融资", "投资", "估值", "资本", "并购",
    ),
    "Strategy & Society": (
        "policy", "regulation", "governance", "jobs", "employment", "labor",
        "geopolitics", "sanction", "safety", "risk", "society", "ethics",
        "education", "ai index", "report", "政策", "治理", "就业", "社会", "战略", "趋势报告",
    ),
}
AI_LAYER_DEFAULT_CADENCE = {
    "Research": "Monthly",
    "Industry": "Daily",
    "Investment": "Weekly",
    "Strategy & Society": "Weekly",
}


def classify_ai_authority_item(item: dict[str, Any]) -> dict[str, str]:
    """
    Classify authority items into 4 strategic layers + refresh cadence.
    Falls back to keyword inference when source profile is unknown.
    """
    source = (item.get("source") or "").strip()
    prof = AI_AUTHORITY_SOURCE_PROFILE.get(source)
    if prof:
        return {"layer": prof[0], "cadence": prof[1]}

    text = " ".join(
        str(item.get(k, "") or "").lower() for k in ("title", "snippet", "url", "source")
    )
    scores = {layer: 0 for layer in AI_INTEL_LAYER_ORDER}
    for layer, kws in AI_AUTHORITY_LAYER_KEYWORDS.items():
        for kw in kws:
            if kw in text:
                scores[layer] += 1
    layer = max(scores, key=scores.get) if max(scores.values()) > 0 else "Industry"

    cadence = AI_LAYER_DEFAULT_CADENCE.get(layer, "Weekly")
    if "ai index" in text or "annual report" in text:
        cadence = "Quarterly"
    elif "weekly" in text or "newsletter" in text:
        cadence = "Weekly"
    elif "daily" in text:
        cadence = "Daily"
    return {"layer": layer, "cadence": cadence}


def summarize_ai_authority_items(items: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Counts by strategic layer and cadence for dashboard summaries."""
    layer_counts = {k: 0 for k in AI_INTEL_LAYER_ORDER}
    cadence_counts = {k: 0 for k in AI_INTEL_CADENCE_ORDER}
    for item in items:
        cls = classify_ai_authority_item(item)
        layer = cls["layer"]
        cadence = cls["cadence"]
        if layer in layer_counts:
            layer_counts[layer] += 1
        if cadence in cadence_counts:
            cadence_counts[cadence] += 1
    return {"layers": layer_counts, "cadence": cadence_counts}


def fetch_rss_feeds(
    max_per_feed: int = 2,
    lang: str = "en",
    feed_pairs: Optional[list[tuple[str, str]]] = None,
) -> list[dict[str, Any]]:
    """Fetch RSS in parallel. Uses RSS_FEEDS_EN or RSS_FEEDS_ZH unless feed_pairs is set."""
    if not _has_feedparser():
        return []
    import feedparser
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    }
    feeds = feed_pairs if feed_pairs is not None else (RSS_FEEDS_ZH if lang == "zh" else RSS_FEEDS_EN)
    proxies = requests_proxies_for(overseas=(lang != "zh"))

    def _fetch_one(url: str, name: str) -> list[dict[str, Any]]:
        local: list[dict[str, Any]] = []
        try:
            r = requests.get(url, timeout=7, headers=headers, proxies=proxies)
            r.raise_for_status()
            d = feedparser.parse(r.content)
            for e in d.entries[:max_per_feed]:
                title = e.get("title", "N/A")
                link = e.get("link", "")
                summary = _sanitize_snippet(e.get("summary", "") or "", max_len=250)
                local.append({
                    "title": title,
                    "snippet": summary or name,
                    "url": link,
                    "date": e.get("published", ""),
                    "source": name,
                })
        except Exception as e:
            print(f"[RSS {name}] {e}")
        return local

    items: list[dict[str, Any]] = []
    if not feeds:
        return items
    workers = min(10, len(feeds))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_fetch_one, url, name) for url, name in feeds]
        for fut in futs:
            try:
                items.extend(fut.result(timeout=12))
            except Exception:
                continue
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


def _item_blob_text(item: dict[str, Any]) -> str:
    return " ".join(
        [
            str(item.get("title", "") or ""),
            str(item.get("snippet", "") or ""),
            str(item.get("source", "") or ""),
        ]
    )


def _filter_items_by_lang(items: list[dict[str, Any]], lang: str) -> list[dict[str, Any]]:
    """Strict language split: zh pages show zh items, en pages show en items."""
    if lang not in ("en", "zh"):
        return items
    out: list[dict[str, Any]] = []
    for item in items:
        has_cjk = _has_cjk(_item_blob_text(item))
        if lang == "zh" and has_cjk:
            out.append(item)
        elif lang == "en" and not has_cjk:
            out.append(item)
    return out


def _filter_non_news_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep news-only stream; longform/podcast should live in /longform."""
    out: list[dict[str, Any]] = []
    for item in items:
        source = (item.get("source") or "").strip()
        if source and classify_source_type(source) != "news":
            continue
        out.append(item)
    return out


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
        r = requests.get(
            url,
            timeout=6,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
            proxies=requests_proxies_for(overseas=True),
        )
        r.raise_for_status()
        d = feedparser.parse(r.content)
        for e in d.entries[:max_results]:
            title = e.get("title", "N/A")
            link = e.get("link", "")
            summary = _sanitize_snippet(e.get("summary", "") or "", max_len=250)
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
        with DDGS(timeout=6) as ddgs:
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
        with DDGS(timeout=6) as ddgs:
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
        preliminary = run_pipeline(_filter_social_noise(all_items))
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
    preliminary = run_pipeline(_filter_social_noise(all_items))
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
    preliminary = run_pipeline(_filter_social_noise(all_items))
    if len(preliminary) < max(3, min(6, target_total // 2)):
        for sq in search_queries[:4]:
            tw = fetch_duckduckgo_text_search(sq, max_results=8)
            if tw:
                all_items.extend(tw)
                _append_source("DuckDuckGo Web")
            if len(run_pipeline(_filter_social_noise(all_items))) >= max(3, target_total // 2):
                break

    finalized = run_pipeline(_filter_social_noise(all_items))
    finalized = _filter_non_news_items(finalized)
    finalized = _filter_items_by_lang(finalized, "zh" if is_zh else "en")
    return finalized[:target_total], sources_used


# Daily digest: AI & tech → US–China → public mood (economy/psyche/belief culture) → light entertainment.
DAILY_SECTOR_SEARCH_EN = {
    "ai_tech": [
        "OpenAI artificial intelligence news",
        "Google DeepMind Anthropic Claude AI model",
        "Elon Musk Tesla SpaceX xAI",
        "AI startup funding venture capital",
        "machine learning research breakthrough",
    ],
    "us_china": [
        "US China relations trade tariffs",
        "US China technology semiconductor export controls",
        "Taiwan strait Washington Beijing policy",
    ],
    # Economy, work stress, belief & sensation culture (audience mood / “why nothing works” discourse)
    "public_mood": [
        "recession layoffs mental health workforce news",
        "economic anxiety unemployment burnout news",
        "superstition paranormal belief psychology study news",
        "astrology wellness manifestation spending Gen Z news",
        "financial stress coping uncertainty news",
    ],
    "entertainment": [
        "Hollywood box office streaming television",
    ],
}
DAILY_SECTOR_SEARCH_ZH = {
    "ai_tech": [
        "人工智能 大模型 最新",
        "马斯克 科技 最新",
        "AI 创业 融资 科技",
    ],
    "us_china": [
        "中美关系 时政 经济",
        "中美贸易 关税 芯片",
        "台海局势 半导体",
    ],
    "public_mood": [
        "裁员 心理健康 职场压力 新闻",
        "经济下行 年轻人 副业 焦虑 报道",
        "玄学 消费 占星 疗愈 热潮 新闻",
        "疗愈经济 塔罗 心理消费 新闻报道",
        "中年人 失业 心理 调适 新闻报道",
    ],
    "entertainment": [
        "好莱坞 欧美影视 动态",
    ],
}


def _daily_sector_sizes(target_total: int) -> tuple[int, int, int, int]:
    """Return (ai_tech_cap, us_china_cap, public_mood_cap, entertainment_cap). Sums to target_total."""
    if target_total <= 24:
        n_ent = max(2, min(4, target_total // 6))
        n_mood = max(2, min(5, target_total // 7))
        n_geo = max(2, min(6, target_total // 6))
        n_ai = target_total - n_geo - n_mood - n_ent
        if n_ai < 1:
            n_ai = 1
            n_ent = target_total - n_ai - n_geo - n_mood
        return n_ai, n_geo, n_mood, n_ent
    # ~AI/tech, ~US–China, mood/economy & sensation culture, light entertainment (daily_news uses ~60 items)
    n_geo = max(6, round(target_total * 0.25))
    n_mood = max(6, round(target_total * 0.14))
    n_ent = max(4, round(target_total * 0.10))
    n_ai = target_total - n_geo - n_mood - n_ent
    if n_ai < 10:
        need = 10 - n_ai
        take_ent = min(need, max(0, n_ent - 4))
        n_ent -= take_ent
        need -= take_ent
        if need > 0:
            take_mood = min(need, max(0, n_mood - 5))
            n_mood -= take_mood
            need -= take_mood
        if need > 0:
            take_geo = min(need, max(0, n_geo - 6))
            n_geo -= take_geo
            need -= take_geo
        if need > 0:
            over = min(need, max(0, n_ent - 3))
            n_ent -= over
        n_ai = target_total - n_geo - n_mood - n_ent
    return n_ai, n_geo, n_mood, n_ent


def _add_distinct_sources(from_items: list[dict[str, Any]], sources_used: list[str]) -> None:
    for it in from_items:
        s = (it.get("source") or "").strip()
        if s and s not in sources_used:
            sources_used.append(s)


def _host_matches_domains(url: str, domains: tuple[str, ...]) -> bool:
    host = _hostname(url)
    if not host:
        return False
    return any(host == d or host.endswith(f".{d}") for d in domains)


def _fetch_zh_source_targeted_items(
    label: str,
    domains: tuple[str, ...],
    query: str,
    max_per_engine: int = 2,
) -> list[dict[str, Any]]:
    """
    Minimal-risk fallback for Chinese sources lacking stable RSS.
    Uses site-targeted search and maps results back to trusted source labels.
    """
    out: list[dict[str, Any]] = []

    # Google News links are indirect but query-targeted to source domain.
    gnews = fetch_google_news_rss(query, max_results=max_per_engine, lang="zh")
    for it in gnews:
        x = dict(it)
        x["source"] = label
        out.append(x)

    if len(out) >= max_per_engine:
        return out

    # DDG returns direct links; keep only matched domains (fallback when Google News is empty).
    ddg = fetch_duckduckgo_news(query, max_results=max_per_engine, region="cn-zh")
    for it in ddg:
        if domains and not _host_matches_domains(it.get("url", ""), domains):
            continue
        x = dict(it)
        x["source"] = label
        out.append(x)
    return out


def fetch_ai_authority_sources(
    target_total: int = 20,
    max_per_feed: int = 2,
    lang: str = "en",
    news_only: bool = True,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Founder-oriented, high-authority AI stream.
    Prioritizes official/lab feeds, then fills holes with Google News/DDG.
    """
    cap = max(6, target_total)
    all_items: list[dict[str, Any]] = []
    sources_used: list[str] = []
    is_zh = lang == "zh"
    authority_feed_pairs = AI_AUTHORITY_FEEDS_ZH if is_zh else AI_AUTHORITY_FEEDS_EN
    authority_source_names = {name for _, name in authority_feed_pairs}
    fallback_label = "DuckDuckGo 新闻" if is_zh else "DuckDuckGo News"
    gnews_label = "Google News"

    rss_items = _run_with_timeout(
        lambda: fetch_rss_feeds(
            max_per_feed=max_per_feed,
            lang="zh" if is_zh else "en",
            feed_pairs=authority_feed_pairs,
        ),
        timeout_sec=50,
    )
    if rss_items:
        all_items.extend(rss_items)
        _add_distinct_sources(rss_items, sources_used)

    # If some feeds are unavailable, use source-targeted searches in parallel as backup.
    if len(run_pipeline(_filter_social_noise(all_items))) < cap:
        if is_zh:
            with ThreadPoolExecutor(max_workers=min(5, len(AI_AUTHORITY_TARGETED_ZH))) as ex:
                futs = {
                    ex.submit(
                        _fetch_zh_source_targeted_items,
                        label=cfg["label"],
                        domains=cfg["domains"],
                        query=cfg["query"],
                        max_per_engine=2,
                    ): cfg["label"]
                    for cfg in AI_AUTHORITY_TARGETED_ZH
                }
                for fut, label in futs.items():
                    try:
                        extra = fut.result(timeout=12)
                    except Exception:
                        continue
                    if extra:
                        all_items.extend(extra)
                        if label not in sources_used:
                            sources_used.append(label)
                        if gnews_label not in sources_used:
                            sources_used.append(gnews_label)
        else:
            def _one_en_auth(q: str) -> list[dict[str, Any]]:
                gn = fetch_google_news_rss(q, max_results=4, lang="en")
                if gn:
                    return gn
                return fetch_duckduckgo_news(q, max_results=3, region="us-en")

            with ThreadPoolExecutor(max_workers=6) as ex:
                futs = [ex.submit(_one_en_auth, q) for q in AI_AUTHORITY_SEARCH_EN[:6]]
                for fut in futs:
                    try:
                        res = fut.result(timeout=12)
                    except Exception:
                        continue
                    if res:
                        all_items.extend(res)
                        if gnews_label not in sources_used:
                            sources_used.append(gnews_label)

    finalized = run_pipeline(_filter_social_noise(all_items))
    if news_only:
        finalized = _filter_non_news_items(finalized)
    finalized = _filter_items_by_lang(finalized, "zh" if is_zh else "en")
    preferred = [it for it in finalized if (it.get("source") or "") in authority_source_names]
    others = [it for it in finalized if (it.get("source") or "") not in authority_source_names]
    merged = (preferred + others)[:cap]
    return merged, sources_used


def _pool_finalize(raw: list[dict[str, Any]], cap: int, lang: Optional[str] = None) -> list[dict[str, Any]]:
    if cap <= 0:
        return []
    finalized = run_pipeline(_filter_social_noise(raw))
    finalized = _filter_non_news_items(finalized)
    if lang in ("en", "zh"):
        finalized = _filter_items_by_lang(finalized, lang)
    return finalized[:cap]


def _merge_preserve_order(sectors: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for sec in sectors:
        for item in sec:
            t = (item.get("title") or "").strip().lower()
            if not t or t in seen:
                continue
            seen.add(t)
            out.append(item)
    return out


def _sector_query_news(queries: list[str], lang: str, per_query: int, sources_used: list[str]) -> list[dict[str, Any]]:
    """Fetch Google News RSS (+ DDG fallback only when Google News yields few items) in parallel."""
    out: list[dict[str, Any]] = []
    if not queries:
        return out
    is_zh = lang == "zh"
    region = "cn-zh" if is_zh else "us-en"
    g_lang = "zh" if is_zh else "en"
    ddg_label = "DuckDuckGo 新闻" if is_zh else "DuckDuckGo News"

    def _one_query(q: str) -> tuple[list[dict[str, Any]], bool, bool]:
        local: list[dict[str, Any]] = []
        used_gn = False
        used_ddg = False
        gn = fetch_google_news_rss(q, max_results=per_query, lang=g_lang)
        if gn:
            local.extend(gn)
            used_gn = True
        if len(local) < max(2, per_query // 2):
            ddg = fetch_duckduckgo_news(q, max_results=per_query, region=region)
            if ddg:
                local.extend(ddg)
                used_ddg = True
        return local, used_gn, used_ddg

    with ThreadPoolExecutor(max_workers=min(6, len(queries))) as ex:
        futs = [ex.submit(_one_query, q) for q in queries]
        for fut in futs:
            try:
                local, used_gn, used_ddg = fut.result(timeout=15)
                out.extend(local)
                if used_gn and "Google News" not in sources_used:
                    sources_used.append("Google News")
                if used_ddg and ddg_label not in sources_used:
                    sources_used.append(ddg_label)
            except Exception:
                continue
    return out


def _fetch_weighted_daily_sources(target_total: int, lang: str) -> tuple[list[dict[str, Any]], list[str]]:
    sources_used: list[str] = []
    n_ai, n_geo, n_mood, n_ent = _daily_sector_sizes(target_total)
    qmap = DAILY_SECTOR_SEARCH_ZH if lang == "zh" else DAILY_SECTOR_SEARCH_EN

    ai_raw: list[dict[str, Any]] = []
    # Put high-authority AI feeds first so top cards carry stronger signal.
    ai_authority_items, ai_authority_sources = fetch_ai_authority_sources(
        target_total=max(10, n_ai),
        max_per_feed=2,
        lang=lang,
    )
    if ai_authority_items:
        ai_raw.extend(ai_authority_items)
    for s in ai_authority_sources:
        if s not in sources_used:
            sources_used.append(s)

    if lang == "en":
        hn_s = fetch_hn_search("AI", max_results=6)
        if hn_s:
            ai_raw.extend(hn_s)
            if "Hacker News" not in sources_used:
                sources_used.append("Hacker News")
        hn_top = fetch_hacker_news(5)
        if hn_top:
            ai_raw.extend(hn_top)
            if "Hacker News" not in sources_used:
                sources_used.append("Hacker News")
        rss_core = _run_with_timeout(
            lambda: fetch_rss_feeds(max_per_feed=4, lang="en", feed_pairs=RSS_FEEDS_EN_CORE),
            timeout_sec=40,
        )
        if rss_core:
            ai_raw.extend(rss_core)
            _add_distinct_sources(rss_core, sources_used)
    else:
        rss_zh = _run_with_timeout(lambda: fetch_rss_feeds(max_per_feed=5, lang="zh"), timeout_sec=25)
        if rss_zh:
            ai_raw.extend(rss_zh)
            _add_distinct_sources(rss_zh, sources_used)

    ai_raw.extend(_sector_query_news(qmap["ai_tech"], lang, 4, sources_used))

    if lang == "en":
        na_ai = fetch_newsapi_search("artificial intelligence OR OpenAI OR Anthropic", max_results=10, language="en")
    else:
        na_ai = fetch_newsapi_search("人工智能 OR 大模型", max_results=10, language="zh")
    if na_ai:
        ai_raw.extend(na_ai)
        if "NewsAPI" not in sources_used:
            sources_used.append("NewsAPI")

    ai_pool = _pool_finalize(ai_raw, n_ai, lang=lang)

    geo_raw = _sector_query_news(qmap["us_china"], lang, 5, sources_used)
    geo_pool = _pool_finalize(geo_raw, n_geo, lang=lang)

    mood_raw = _sector_query_news(qmap["public_mood"], lang, 4, sources_used)
    mood_pool = _pool_finalize(mood_raw, n_mood, lang=lang)

    ent_raw = _sector_query_news(qmap["entertainment"], lang, 3, sources_used)
    if lang == "en":
        holly = _run_with_timeout(
            lambda: fetch_rss_feeds(max_per_feed=2, lang="en", feed_pairs=RSS_FEEDS_EN_HOLLYWOOD),
            timeout_sec=12,
        )
        if holly:
            ent_raw.extend(holly)
            _add_distinct_sources(holly, sources_used)

    ent_pool = _pool_finalize(ent_raw, n_ent, lang=lang)

    merged = _merge_preserve_order([ai_pool, geo_pool, mood_pool, ent_pool])
    merged = merged[:target_total]

    if len(merged) < target_total:
        need = target_total - len(merged)
        extra_label = "DuckDuckGo 新闻" if lang == "zh" else "DuckDuckGo News"
        fill = _run_with_timeout(
            lambda: fetch_duckduckgo_fallback(max_results=max(20, need + 8), lang=lang),
            timeout_sec=15,
        )
        if fill:
            if extra_label not in sources_used:
                sources_used.append(extra_label)
            merged = _merge_preserve_order([merged, _pool_finalize(fill, target_total, lang=lang)])

    return merged[:target_total], sources_used


def fetch_duckduckgo_fallback(max_results: int = 5, lang: str = "en") -> list[dict[str, Any]]:
    """Fallback: DuckDuckGo news when no other sources configured."""
    query = (
        "AI 科技 职场 副业 心理健康 玄学 疗愈 经济新闻"
        if lang == "zh"
        else "AI technology economy layoffs burnout anxiety wellness belief culture news"
    )
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
    Daily digest: weighted mix (AI & tech → US–China → economy & public mood / sensation culture → entertainment).
    lang: en (English) or zh (Chinese).
    Returns (items, list of source names that contributed).
    """
    return _fetch_weighted_daily_sources(target_total, lang)
