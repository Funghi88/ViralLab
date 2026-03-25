"""Long-form and podcast RSS sources for ViralLab.

Returns normalized items: {title, snippet, url, date, source}.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests


def _has_feedparser() -> bool:
    try:
        import feedparser  # noqa: F401

        return True
    except ImportError:
        return False


# Global English long-form writing (intentionally separated from daily news sources)
LONGFORM_FEEDS_EN = [
    ("https://stratechery.com/feed/", "Stratechery"),
    ("https://www.niemanlab.org/feed/", "Nieman Lab"),
    ("https://a16z.com/feed/", "a16z"),
    ("https://open.substack.com/pub/lennysnewsletter/feed", "Lenny's Newsletter"),
    ("https://www.notboring.co/feed", "Not Boring"),
    ("https://www.ben-evans.com/benedictevans?format=rss", "Benedict Evans"),
    ("https://newsletter.pragmaticengineer.com/feed", "The Pragmatic Engineer"),
    ("https://open.substack.com/pub/oneusefulthing/feed", "One Useful Thing"),
    ("https://open.substack.com/pub/thegeneralist/feed", "The Generalist"),
    ("https://www.creativeboom.com/feed/", "Creative Boom"),
    ("https://www.itsnicethat.com/rss", "It's Nice That"),
    ("https://eyeondesign.aiga.org/feed/", "AIGA Eye on Design"),
    ("https://review.firstround.com/rss/", "First Round Review"),
    ("https://uxdesign.cc/feed", "UX Collective"),
    ("https://www.core77.com/rss", "Core77"),
    ("https://www.smashingmagazine.com/feed/", "Smashing Magazine"),
]

# Chinese long-form/public commentary (CN + Traditional Chinese + SG/TW + diaspora)
LONGFORM_FEEDS_ZH = [
    ("https://www.thenewslens.com/rss", "關鍵評論網"),
    ("https://www.twreporter.org/a/rss2.xml", "報導者"),
    ("https://www.zaobao.com.sg/realtime/china/rss.xml", "联合早报"),
    ("http://www.woshipm.com/feed", "人人都是产品经理"),
    ("https://theinitium.com/feed", "端傳媒"),
    ("https://www.inside.com.tw/feed", "INSIDE"),
    ("https://www.bnext.com.tw/rss", "數位時代"),
    ("https://buzzorange.com/techorange/feed", "TechOrange"),
]

# Global podcast feeds
PODCAST_FEEDS_EN = [
    ("https://feeds.simplecast.com/54nAGcIl", "a16z Podcast"),
    ("https://feeds.lexfridman.com/lex-fridman-podcast", "Lex Fridman Podcast"),
    ("https://feeds.transistor.fm/acquired", "Acquired"),
    ("https://feeds.simplecast.com/7mQx7Hsy", "20VC"),
    ("https://feeds.simplecast.com/tOjNXec5", "Lenny's Podcast"),
    ("https://feeds.transistor.fm/design-better", "Design Better Podcast"),
    ("https://feeds.99percentinvisible.org/99percentinvisible", "99% Invisible"),
]

# Chinese podcast feeds (where public RSS is available)
PODCAST_FEEDS_ZH = [
    ("https://uxcoffee.typlog.io/episodes/feed.xml", "UX Coffee 设计咖"),
    ("https://feed.xyzfm.space/gbmFM", "设计相关播客"),
]

LONGFORM_SOURCE_NAMES = {name for _, name in LONGFORM_FEEDS_EN + LONGFORM_FEEDS_ZH}
PODCAST_SOURCE_NAMES = {name for _, name in PODCAST_FEEDS_EN + PODCAST_FEEDS_ZH}

# Region tags shown on /longform
REGION_TAGS = ("CN", "TW", "SG", "Diaspora", "Global EN")
SOURCE_REGION_MAP = {
    # English ecosystem
    "Stratechery": "Global EN",
    "Nieman Lab": "Global EN",
    "a16z": "Global EN",
    "Lenny's Newsletter": "Global EN",
    "Not Boring": "Global EN",
    "Benedict Evans": "Global EN",
    "The Pragmatic Engineer": "Global EN",
    "One Useful Thing": "Global EN",
    "The Generalist": "Global EN",
    "Creative Boom": "Global EN",
    "It's Nice That": "Global EN",
    "AIGA Eye on Design": "Global EN",
    "First Round Review": "Global EN",
    "UX Collective": "Global EN",
    "Core77": "Global EN",
    "Smashing Magazine": "Global EN",
    "a16z Podcast": "Global EN",
    "Lex Fridman Podcast": "Global EN",
    "Acquired": "Global EN",
    "20VC": "Global EN",
    "Lenny's Podcast": "Global EN",
    "Design Better Podcast": "Global EN",
    "99% Invisible": "Global EN",
    # Chinese ecosystem
    "關鍵評論網": "TW",
    "報導者": "TW",
    "联合早报": "SG",
    "人人都是产品经理": "CN",
    "端傳媒": "Diaspora",
    "INSIDE": "TW",
    "數位時代": "TW",
    "TechOrange": "TW",
    "UX Coffee 设计咖": "CN",
    "设计相关播客": "Diaspora",
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
    # Prioritize AI-era transition pain points and practical pathways.
    items.sort(
        key=lambda it: _focus_score(it.get("title", ""), it.get("snippet", ""), lang),
        reverse=True,
    )
    sources: list[str] = []
    for s in long_sources + podcast_sources:
        if s not in sources:
            sources.append(s)
    return items, sources
