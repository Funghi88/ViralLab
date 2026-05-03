"""Long-form and podcast RSS sources for ViralLab.

Returns normalized items: {title, snippet, url, date, source}.
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

import requests


def _has_feedparser() -> bool:
    try:
        import feedparser  # noqa: F401

        return True
    except ImportError:
        return False


# Global English long-form writing — top-tier publications only.
# Rule: must be globally recognisable brand or widely-cited newsletter.
LONGFORM_FEEDS_EN = [
    # Major magazine/newspaper long-form
    ("https://www.theatlantic.com/feed/all/", "The Atlantic"),
    ("https://www.newyorker.com/feed/everything", "The New Yorker"),
    ("https://feeds.hbr.org/harvardbusiness/", "Harvard Business Review"),
    ("https://nymag.com/feed/all", "New York Magazine"),
    ("https://www.niemanlab.org/feed/", "Nieman Lab"),
    # Strategy & tech analysis (most-read newsletters)
    ("https://stratechery.com/feed/", "Stratechery"),
    ("https://www.ben-evans.com/benedictevans?format=rss", "Benedict Evans"),
    ("https://open.substack.com/pub/lennysnewsletter/feed", "Lenny's Newsletter"),
    ("https://newsletter.pragmaticengineer.com/feed", "The Pragmatic Engineer"),
    ("https://www.notboring.co/feed", "Not Boring"),
    ("https://open.substack.com/pub/oneusefulthing/feed", "One Useful Thing (Prof. Mollick)"),
    # Creator economy & media business (must-reads in this space)
    ("https://bigtechnology.substack.com/feed", "Big Technology (Alex Kantrowitz)"),
    ("https://hotpod.substack.com/feed", "Hot Pod (Spotify/audio)"),
    ("https://therebooting.substack.com/feed", "The Rebooting"),
    ("https://simonowens.substack.com/feed", "The Business of Content"),
    ("https://review.firstround.com/rss/", "First Round Review"),
    # Venture & startup
    ("https://a16z.com/feed/", "a16z"),
    ("https://open.substack.com/pub/thegeneralist/feed", "The Generalist"),
    # Design & creativity
    ("https://eyeondesign.aiga.org/feed/", "AIGA Eye on Design"),
    ("https://www.itsnicethat.com/rss", "It's Nice That"),
]

# Chinese long-form — top-tier publications and widely-read newsletters.
LONGFORM_FEEDS_ZH = [
    # 台灣 / 港澳 / 全球華文
    ("https://www.thenewslens.com/rss", "關鍵評論網"),
    ("https://www.twreporter.org/a/rss2.xml", "報導者"),
    ("https://theinitium.com/feed", "端傳媒"),
    ("https://www.zaobao.com.sg/realtime/china/rss.xml", "联合早报"),
    ("https://www.bnext.com.tw/rss", "數位時代"),
    # 大陆 — 产品 / 创作者 / 商业
    ("http://www.woshipm.com/feed", "人人都是产品经理"),
    ("https://www.inside.com.tw/feed", "INSIDE"),
    ("https://buzzorange.com/techorange/feed", "TechOrange"),
    ("https://jiemian.com/rss/", "界面新闻"),
]

# English podcasts — verified RSS, top-tier by audience and influence.
PODCAST_FEEDS_EN = [
    # Business & entrepreneurship (massive audiences)
    ("https://feeds.npr.org/510313/podcast.xml", "How I Built This (NPR)"),
    ("https://feeds.simplecast.com/Kf0D7OJ8", "Masters of Scale (Reid Hoffman)"),
    ("https://feeds.megaphone.fm/all-in", "All-In Podcast"),
    ("https://feeds.simplecast.com/n44TzStf", "My First Million"),
    ("https://rss.art19.com/tim-ferriss-show", "The Tim Ferriss Show"),
    ("https://feeds.simplecast.com/7mQx7Hsy", "20VC"),
    # Tech & AI (widely trusted)
    ("https://feeds.lexfridman.com/lex-fridman-podcast", "Lex Fridman Podcast"),
    ("https://feeds.transistor.fm/acquired", "Acquired"),
    ("https://feeds.simplecast.com/tOjNXec5", "Lenny's Podcast"),
    ("https://feeds.simplecast.com/54nAGcIl", "a16z Podcast"),
    # Creator economy & design
    ("https://feeds.transistor.fm/design-better", "Design Better Podcast"),
    ("https://feeds.99percentinvisible.org/99percentinvisible", "99% Invisible"),
]

# Chinese podcasts — only those with confirmed public RSS feeds.
PODCAST_FEEDS_ZH = [
    ("https://uxcoffee.typlog.io/episodes/feed.xml", "UX Coffee 设计咖"),
    ("https://storyfm.com.cn/feed/episodes", "故事 FM"),
    ("https://feed.xyzfm.space/gbmFM", "商业访谈播客"),
]

LONGFORM_SOURCE_NAMES = {name for _, name in LONGFORM_FEEDS_EN + LONGFORM_FEEDS_ZH}
PODCAST_SOURCE_NAMES = {name for _, name in PODCAST_FEEDS_EN + PODCAST_FEEDS_ZH}

# Region tags shown on /longform
REGION_TAGS = ("CN", "TW", "SG", "Diaspora", "Global EN")
SOURCE_REGION_MAP = {
    # English ecosystem
    "The Atlantic": "Global EN",
    "The New Yorker": "Global EN",
    "Harvard Business Review": "Global EN",
    "New York Magazine": "Global EN",
    "Nieman Lab": "Global EN",
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
    "Design Better Podcast": "Global EN",
    "99% Invisible": "Global EN",
    # Chinese ecosystem
    "關鍵評論網": "TW",
    "報導者": "TW",
    "端傳媒": "Diaspora",
    "联合早报": "SG",
    "數位時代": "TW",
    "INSIDE": "TW",
    "TechOrange": "TW",
    "人人都是产品经理": "CN",
    "界面新闻": "CN",
    "UX Coffee 设计咖": "CN",
    "故事 FM": "CN",
    "商业访谈播客": "CN",
}

# Priority themes: AI-era transition pain points and practical pathways
FOCUS_KEYWORDS_EN = (
    "layoff", "laid off", "job market", "career pivot", "career transition",
    "reskilling", "upskilling", "design engineer", "staff engineer", "frontend engineer",
    "designer", "product designer", "creative", "creativity", "ai workflow", "ai tools",
    "one-person", "solo founder", "indie hacker", "micro saas", "bootstrapped",
    "survival", "freelance", "portfolio", "consulting",
)
FOCUS_KEYWORDS_ZH = (
    "裁员", "被裁", "失业", "转型", "再就业", "副业", "一人公司", "超级个体",
    "设计师", "程序员", "工程师", "生存", "求职", "作品集", "自由职业", "接单",
    "AI 时代", "AIGC", "创意", "创造力", "设计", "品牌设计", "工业设计",
    "有效实践", "成功路径", "增长路径",
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
}


def classify_source_type(source_name: str) -> str:
    """Classify a source label into news / longform / podcast."""
    s = (source_name or "").strip()
    if s in PODCAST_SOURCE_NAMES:
        return "podcast"
    if s in LONGFORM_SOURCE_NAMES:
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

    def _fetch_one(url: str, source_name: str) -> tuple[str, list[dict[str, Any]]]:
        try:
            r = requests.get(url, timeout=4)
            r.raise_for_status()
            parsed = feedparser.parse(r.content)
            local_items: list[dict[str, Any]] = []
            for entry in parsed.entries[:max_per_feed]:
                local_items.append(
                    {
                        "title": entry.get("title", "N/A"),
                        "snippet": (entry.get("summary", "") or "")[:250] or default_snippet,
                        "url": entry.get("link", ""),
                        "date": entry.get("published", "") or entry.get("updated", ""),
                        "source": source_name,
                    }
                )
            return source_name, local_items
        except Exception:
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
