"""Long-form and podcast RSS sources for ViralLab.

Returns normalized items: {title, snippet, url, date, source}.
"""
import html
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from src.proxy_env import requests_proxies_for

_RSS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
}


def _clean_rss_snippet(text: str, max_len: int = 250) -> str:
    if not text or not isinstance(text, str):
        return ""
    s = html.unescape(text)
    s = re.sub(r"<[^>]*>?", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len]


def _has_feedparser() -> bool:
    try:
        import feedparser  # noqa: F401

        return True
    except ImportError:
        return False


# Global English long-form writing — verified live top-tier publications & newsletters.
LONGFORM_FEEDS_EN = [
    # Major magazine/newspaper long-form
    ("https://www.theatlantic.com/feed/all/", "The Atlantic"),
    ("https://www.newyorker.com/feed/everything", "The New Yorker"),
    ("https://www.economist.com/international/rss.xml", "The Economist"),
    ("https://www.niemanlab.org/feed/", "Nieman Lab"),
    # Strategy & tech analysis (most-read newsletters)
    ("https://stratechery.com/feed/", "Stratechery"),
    ("https://www.ben-evans.com/benedictevans?format=rss", "Benedict Evans"),
    ("https://newsletter.pragmaticengineer.com/feed", "The Pragmatic Engineer"),
    ("https://www.notboring.co/feed", "Not Boring"),
    # Creator economy & media business
    ("https://bigtechnology.substack.com/feed", "Big Technology (Alex Kantrowitz)"),
    ("https://therebooting.substack.com/feed", "The Rebooting"),
    ("https://simonowens.substack.com/feed", "The Business of Content"),
    # Behaviour, society & economy
    ("https://theconversation.com/us/articles.atom", "The Conversation (US)"),
]

# Chinese long-form — verified live publications & deep analysis.
LONGFORM_FEEDS_ZH = [
    # 全球华文深度报道
    ("https://www.ftchinese.com/rss/news", "FT中文网"),
    ("https://cn.nytimes.com/rss/", "纽约时报中文网"),
    ("https://www.twreporter.org/a/rss2.xml", "報導者"),
    ("https://theinitium.com/feed", "端傳媒"),
    # 华语科技 / 产品 / 创作者深度
    ("https://www.woshipm.com/feed", "人人都是产品经理"),
    ("https://buzzorange.com/techorange/feed", "TechOrange"),
    ("https://www.ruanyifeng.com/blog/atom.xml", "阮一峰的网络日志"),
]

# English podcasts — verified live RSS, top-tier by audience and influence.
PODCAST_FEEDS_EN = [
    # Business & entrepreneurship
    ("https://feeds.npr.org/510313/podcast.xml", "How I Built This (NPR)"),
    ("https://rss.art19.com/tim-ferriss-show", "The Tim Ferriss Show"),
    # Tech & AI
    ("https://feeds.transistor.fm/acquired", "Acquired"),
    ("https://feeds.simplecast.com/tOjNXec5", "Lenny's Podcast"),
    ("https://feeds.simplecast.com/54nAGcIl", "a16z Podcast"),
    ("https://feeds.simplecast.com/l2i9YnTd", "Hard Fork (NYT)"),
    ("https://feeds.megaphone.fm/recodedecode", "Decoder with Nilay Patel"),
    # Creators & operator KOLs
    ("https://feeds.megaphone.fm/LI6529969937", "The Colin and Samir Show"),
    # Behaviour, design & economics
    ("https://feeds.99percentinvisible.org/99percentinvisible", "99% Invisible"),
    ("https://feeds.feedburner.com/hiddenbrain", "Hidden Brain (NPR)"),
    ("https://feeds.simplecast.com/Y8lFbOT4", "Freakonomics Radio"),
    ("https://feeds.npr.org/510289/podcast.xml", "Planet Money (NPR)"),
]

# Chinese podcasts — verified live public RSS feeds.
PODCAST_FEEDS_ZH = [
    ("https://uxcoffee.typlog.io/episodes/feed.xml", "UX Coffee 设计咖"),
]

LONGFORM_SOURCE_NAMES = {name for _, name in LONGFORM_FEEDS_EN + LONGFORM_FEEDS_ZH}
PODCAST_SOURCE_NAMES = {name for _, name in PODCAST_FEEDS_EN + PODCAST_FEEDS_ZH}
LONGFORM_SOURCE_ALIASES = {"DeepTech", "甲子光年", "阿里研究院"}

# Region tags shown on /longform
REGION_TAGS = ("CN", "TW", "SG", "Diaspora", "Global EN")
SOURCE_REGION_MAP = {
    # English ecosystem
    "The Atlantic": "Global EN",
    "The New Yorker": "Global EN",
    "The Economist": "Global EN",
    "Harvard Business Review": "Global EN",
    "New York Magazine": "Global EN",
    "Nieman Lab": "Global EN",
    "Stanford HAI": "Global EN",
    "Stratechery": "Global EN",
    "Benedict Evans": "Global EN",
    "Lenny's Newsletter": "Global EN",
    "The Pragmatic Engineer": "Global EN",
    "Not Boring": "Global EN",
    "One Useful Thing (Prof. Mollick)": "Global EN",
    "Big Technology (Alex Kantrowitz)": "Global EN",
    "Hot Pod (Spotify/audio)": "Global EN",
    "The Rebooting": "Global EN",
    "The Business of Content": "Global EN",
    "First Round Review": "Global EN",
    "a16z": "Global EN",
    "The Generalist": "Global EN",
    "AIGA Eye on Design": "Global EN",
    "It's Nice That": "Global EN",
    "The Conversation (US)": "Global EN",
    "How I Built This (NPR)": "Global EN",
    "Masters of Scale (Reid Hoffman)": "Global EN",
    "All-In Podcast": "Global EN",
    "My First Million": "Global EN",
    "The Tim Ferriss Show": "Global EN",
    "20VC": "Global EN",
    "Lex Fridman Podcast": "Global EN",
    "Acquired": "Global EN",
    "Lenny's Podcast": "Global EN",
    "a16z Podcast": "Global EN",
    "Hard Fork (NYT)": "Global EN",
    "Decoder with Nilay Patel": "Global EN",
    "The Colin and Samir Show": "Global EN",
    "Design Better Podcast": "Global EN",
    "99% Invisible": "Global EN",
    "Hidden Brain (NPR)": "Global EN",
    "Freakonomics Radio": "Global EN",
    "Planet Money (NPR)": "Global EN",
    # Chinese ecosystem
    "FT中文网": "Diaspora",
    "纽约时报中文网": "Diaspora",
    "關鍵評論網": "TW",
    "報導者": "TW",
    "端傳媒": "Diaspora",
    "联合早报": "SG",
    "數位時代": "TW",
    "INSIDE": "TW",
    "TechOrange": "TW",
    "人人都是产品经理": "CN",
    "界面新闻": "CN",
    "腾讯研究院": "CN",
    "阮一峰的网络日志": "CN",
    "UX Coffee 设计咖": "CN",
    "故事 FM": "CN",
    "商业访谈播客": "CN",
}

# Priority themes: AI-era transition pain points and practical pathways
FOCUS_KEYWORDS_EN = (
    "layoff", "laid off", "job market", "career pivot", "career transition",
    "reskilling", "upskilling", "design engineer", "staff engineer", "frontend engineer",
    "designer", "product designer", "creative", "creativity", "ai workflow", "ai tools",
    "openai", "anthropic", "gemini", "gpt", "llm", "machine learning", "neural",
    "musk", "tesla", "spacex", "startup", "startups", "youtube", "creator", "podcast",
    "one-person", "solo founder", "indie hacker", "micro saas", "bootstrapped",
    "survival", "freelance", "portfolio", "consulting",
    "burnout", "stress", "anxiety", "mental health", "depression", "therapy",
    "recession", "unemployment", "economy", "inflation", "financial",
    "belief", "superstition", "paranormal", "spiritual", "astrology", "manifest", "psychology",
)
FOCUS_KEYWORDS_ZH = (
    "裁员", "被裁", "失业", "转型", "再就业", "副业", "一人公司", "超级个体",
    "设计师", "程序员", "工程师", "生存", "求职", "作品集", "自由职业", "接单",
    "AI 时代", "AIGC", "创意", "创造力", "设计", "品牌设计", "工业设计",
    "有效实践", "成功路径", "增长路径",
    "焦虑", "内耗", "抑郁", "心理", "疗愈", "身心灵",
    "经济下行", "通胀", "收入", "就业",
    "玄学", "占星", "塔罗", "运势", "灵修", "能量",
)

THEME_KEYWORDS = {
    "transition": {
        "en": ("layoff", "laid off", "career pivot", "career transition", "reskilling", "upskilling", "job market", "survival"),
        "zh": ("裁员", "被裁", "失业", "转型", "再就业", "求职", "生存"),
    },
    "one_person_business": {
        "en": ("one-person", "solo founder", "indie hacker", "micro saas", "bootstrapped", "freelance", "consulting"),
        "zh": ("一人公司", "超级个体", "副业", "自由职业", "接单", "咨询"),
    },
    "design_creativity_ai": {
        "en": ("designer", "design", "creative", "creativity", "ai workflow", "ai tools", "product designer", "design engineer"),
        "zh": ("设计师", "设计", "创意", "创造力", "AI 时代", "AIGC", "品牌设计", "工业设计", "程序员", "工程师"),
    },
    "collective_wellbeing": {
        "en": (
            "burnout", "stress", "anxiety", "mental health", "depression",
            "recession", "layoff", "unemployment", "economy",
            "superstition", "paranormal", "spiritual", "belief", "astrology",
            "manifest", "wellness",
        ),
        "zh": (
            "焦虑", "内耗", "心理", "情绪", "抑郁",
            "裁员", "失业", "下岗", "经济下行", "副业",
            "玄学", "塔罗", "占卜", "星座", "运势",
            "疗愈", "身心灵", "灵修", "能量",
        ),
    },
}


def classify_source_type(source_name: str) -> str:
    """Classify a source label into news / longform / podcast."""
    s = (source_name or "").strip()
    if s in PODCAST_SOURCE_NAMES:
        return "podcast"
    if s in LONGFORM_SOURCE_NAMES or s in LONGFORM_SOURCE_ALIASES:
        return "longform"
    return "news"


def source_region_tag(source_name: str) -> str:
    """Map source name to region tag."""
    return SOURCE_REGION_MAP.get((source_name or "").strip(), "")


def region_tags_for_lang(lang: str) -> list[str]:
    """Available region tags for current language mode."""
    if lang == "zh":
        return ["CN", "TW", "SG", "Diaspora"]
    return ["Global EN"]


def _focus_score(title: str, snippet: str, lang: str) -> int:
    text = f"{title or ''} {snippet or ''}".lower()
    kws = FOCUS_KEYWORDS_ZH if lang == "zh" else FOCUS_KEYWORDS_EN
    score = 0
    for kw in kws:
        if kw.lower() in text:
            score += 2
    # Light bonus for action-oriented transformation guidance
    if lang == "zh":
        if "如何" in text or "指南" in text or "案例" in text:
            score += 1
    else:
        if "how to" in text or "guide" in text or "case study" in text:
            score += 1
    return score


def _parse_item_date(s: str) -> float:
    """Parse RSS date to UTC timestamp; 0 if unknown."""
    if not s or not isinstance(s, str):
        return 0.0
    s = s.strip()
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        pass
    try:
        if ("T" in s or (len(s) >= 10 and s[4] == "-" and s[7] == "-")):
            iso = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
    except Exception:
        pass
    return 0.0


def _recency_boost(date_str: str) -> float:
    """Small score bump for newer items so stale episodes do not dominate the list."""
    ts = _parse_item_date(date_str)
    if ts <= 0:
        return 0.0
    age_days = max(0.0, (time.time() - ts) / 86400.0)
    return max(0.0, 3.0 - age_days / 40.0)


def classify_focus_theme(title: str, snippet: str, lang: str) -> str:
    """Classify an item into a longform focus theme."""
    text = f"{title or ''} {snippet or ''}".lower()
    lang_key = "zh" if lang == "zh" else "en"
    scores: dict[str, int] = {
        "transition": 0,
        "one_person_business": 0,
        "design_creativity_ai": 0,
        "collective_wellbeing": 0,
    }
    for theme, buckets in THEME_KEYWORDS.items():
        for kw in buckets[lang_key]:
            if kw.lower() in text:
                scores[theme] += 1
    best_theme = max(scores, key=scores.get)
    return best_theme if scores[best_theme] > 0 else "all"


def _read_rss_items(
    feeds: list[tuple[str, str]], max_per_feed: int, default_snippet: str
) -> tuple[list[dict[str, Any]], list[str]]:
    if not _has_feedparser():
        return [], []
    import feedparser

    def _normalize_http_url(raw_url: str, base_url: str = "") -> str:
        u = (raw_url or "").strip()
        if not u:
            return ""
        if u.startswith("//"):
            u = f"https:{u}"
        elif not (u.startswith("http://") or u.startswith("https://")) and base_url:
            u = urljoin(base_url, u)
        try:
            p = urlparse(u)
            if p.scheme in ("http", "https") and p.netloc:
                return u
        except Exception:
            return ""
        return ""

    def _extract_entry_url(entry: Any, feed_home_url: str = "") -> str:
        candidates = [
            entry.get("link", ""),
            entry.get("id", ""),
            entry.get("guid", ""),
        ]
        for l in entry.get("links", []) or []:
            candidates.append((l or {}).get("href", ""))
        for c in candidates:
            normalized = _normalize_http_url(c, feed_home_url)
            if normalized:
                return normalized
        return ""

    def _fetch_one(url: str, source_name: str) -> tuple[str, list[dict[str, Any]]]:
        proxies = requests_proxies_for(overseas=True)
        try:
            r = requests.get(url, timeout=7, headers=_RSS_HEADERS, proxies=proxies)
            r.raise_for_status()
            parsed = feedparser.parse(r.content)
            feed_home_url = _normalize_http_url(parsed.feed.get("link", ""))
            local_items: list[dict[str, Any]] = []
            for entry in parsed.entries[:max_per_feed]:
                snippet = _clean_rss_snippet(entry.get("summary", "") or "", max_len=250)
                local_items.append(
                    {
                        "title": (entry.get("title") or "N/A").strip(),
                        "snippet": snippet or default_snippet,
                        "url": _extract_entry_url(entry, feed_home_url),
                        "date": entry.get("published", "") or entry.get("updated", ""),
                        "source": source_name,
                    }
                )
            return source_name, local_items
        except Exception:
            if proxies:
                try:
                    r = requests.get(url, timeout=7, headers=_RSS_HEADERS, proxies={})
                    r.raise_for_status()
                    parsed = feedparser.parse(r.content)
                    feed_home_url = _normalize_http_url(parsed.feed.get("link", ""))
                    local_items = []
                    for entry in parsed.entries[:max_per_feed]:
                        snippet = _clean_rss_snippet(entry.get("summary", "") or "", max_len=250)
                        local_items.append(
                            {
                                "title": (entry.get("title") or "N/A").strip(),
                                "snippet": snippet or default_snippet,
                                "url": _extract_entry_url(entry, feed_home_url),
                                "date": entry.get("published", "") or entry.get("updated", ""),
                                "source": source_name,
                            }
                        )
                    return source_name, local_items
                except Exception:
                    pass
            return source_name, []

    items: list[dict[str, Any]] = []
    sources: list[str] = []
    max_workers = min(8, max(1, len(feeds)))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_fetch_one, url, source_name) for url, source_name in feeds]
        for fut in as_completed(futures):
            source_name, local_items = fut.result()
            if not local_items:
                continue
            if source_name not in sources:
                sources.append(source_name)
            items.extend(local_items)
    return items, sources


def fetch_longform_and_podcasts(
    lang: str = "en", max_per_feed: int = 2
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch long-form articles + podcast episodes for EN/ZH."""
    if lang == "zh":
        long_items, long_sources = _read_rss_items(
            LONGFORM_FEEDS_ZH, max_per_feed=max_per_feed, default_snippet="长文深度内容"
        )
        podcast_items, podcast_sources = _read_rss_items(
            PODCAST_FEEDS_ZH, max_per_feed=max_per_feed, default_snippet="播客节目更新"
        )
    else:
        long_items, long_sources = _read_rss_items(
            LONGFORM_FEEDS_EN, max_per_feed=max_per_feed, default_snippet="Long-form article"
        )
        podcast_items, podcast_sources = _read_rss_items(
            PODCAST_FEEDS_EN, max_per_feed=max_per_feed, default_snippet="Podcast episode"
        )

    items = long_items + podcast_items
    # Theme relevance first, then slight preference for newer publishes (avoids years-old podcast episodes on top).
    items.sort(
        key=lambda it: (
            _focus_score(it.get("title", ""), it.get("snippet", ""), lang)
            + _recency_boost(it.get("date") or ""),
            _parse_item_date(it.get("date") or ""),
        ),
        reverse=True,
    )
    sources: list[str] = []
    for s in long_sources + podcast_sources:
        if s not in sources:
            sources.append(s)
    return items, sources
