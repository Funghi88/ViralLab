"""Fetch platform-wide hot topics for creators. Multi-source for better reference."""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.proxy_env import requests_proxies_for

# 笒鬼鬼 API - 中文区聚合热榜
HOTLIST_URL = "https://api-v2.cenguigui.cn/api/juhe/hotlist.php"
PLATFORMS_ZH = [
    ("weibo", "微博"),
    ("zhihu", "知乎"),
    ("douyin", "抖音"),
    ("baidu", "百度"),
    ("bilihot", "B站"),  # 哔哩哔哩热搜
    ("sspai", "少数派"),  # 效率工具、数码、创作者
]
# 英文区：多源覆盖（避免社交帖源，优先技术与媒体站点）
HN_TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{}.json"
LOBSTERS_URL = "https://lobste.rs/hottest.json"
DEVTO_URL = "https://dev.to/api/articles?per_page=15&top=7"
GITHUB_TRENDING_URL = "https://githubtrending.lessx.xyz/trending?since=daily"

# 台湾 PTT 热門看板
PTT_HOTBOARDS_URL = "https://www.ptt.cc/bbs/hotboards.html"

# Pearktrue 今日热榜 API - 补充平台（IT之家、36氪、今日头条等）
PEARKTRUE_DAILYHOT_URL = "https://api.pearktrue.cn/api/dailyhot/"
PEARKTRUE_PLATFORMS = [
    ("IT之家", "IT之家"),  # 科技数码
    ("36氪", "36氪"),  # 创投科技
    ("今日头条", "头条"),  # 综合热点
    ("稀土掘金", "掘金"),  # 开发者社区
]

CACHE_FILE = Path(__file__).parent.parent / "output" / "hot_trending.json"
CACHE_TTL = 10 * 60  # 10 min — 近实时

# 创作者相关关键词
CREATOR_KEYWORDS_ZH = frozenset({
    "美妆", "护肤", "穿搭", "时尚", "种草", "直播", "带货", "短视频", "电商", "内容",
    "创作", "爆款", "网红", "UP主", "私域", "品牌", "营销", "教程", "AI", "小红书",
    "抖音", "B站", "知乎", "好物", "测评", "开箱", "vlog", "剪辑", "涨粉", "变现",
    "流量", "算法", "运营", "干货", "攻略", "分享", "推荐", "榜单", "热门", "遊戲",
    "焦虑", "内耗", "心理", "疗愈", "玄学", "占星", "副业",
})
CREATOR_KEYWORDS_EN = frozenset({
    "creator", "viral", "trending", "AI", "YouTube", "TikTok", "content", "marketing",
    "startup", "SaaS", "tool", "growth", "monetization", "subscriber", "algorithm",
    "tutorial", "review", "unboxing", "vlog", "podcast", "newsletter", "influencer",
    "developer", "open source", "framework", "API", "build", "launch",
    "burnout", "anxiety", "mental health", "wellness", "recession",
})


def _creator_score(topic: str, lang: str = "zh") -> int:
    """创作者相关度 0-10。"""
    keywords = CREATOR_KEYWORDS_ZH if lang == "zh" else CREATOR_KEYWORDS_EN
    topic_lower = topic.lower()
    score = 0
    for kw in keywords:
        if kw.lower() in topic_lower:
            score += 2
    if lang == "zh" and 4 <= len(topic) <= 15:
        score += 1
    if lang == "en" and 10 <= len(topic) <= 80:
        score += 1
    return min(score, 10)


def _is_noise_zh(s: str, max_len: int = 60) -> bool:
    """过滤纯时政/难以跟风做内容的热搜。"""
    if len(s) < 2 or len(s) > max_len:
        return True
    if re.match(r"^[\d\s\-\.]+$", s):
        return True
    noise_prefix = ("我使馆", "外交部", "国务院", "通报", "辟谣")
    if any(s.startswith(p) for p in noise_prefix):
        return True
    return False


def _is_noise_en(s: str) -> bool:
    """Filter noise for EN topics."""
    if len(s) < 5 or len(s) > 120:
        return True
    if re.match(r"^[\d\s\-\.\#]+$", s):
        return True
    return False


def _fetch_pearktrue_dailyhot(platform_title: str, platform_name: str) -> list[tuple[str, str, int]]:
    """Fetch from Pearktrue 今日热榜. Returns [(topic, platform_name, creator_score), ...]."""
    try:
        import requests
        r = requests.get(
            f"{PEARKTRUE_DAILYHOT_URL}?title={platform_title}",
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
            timeout=4,
            proxies={},
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 200 or not data.get("data"):
            return []
        result = []
        for item in data["data"][:20]:
            title = (item.get("title") or "").strip()
            if title and not _is_noise_zh(title, max_len=80):
                score = _creator_score(title, "zh")
                result.append((title, platform_name, score))
        return result
    except Exception:
        return []


def _fetch_ptt_hotboards() -> list[tuple[str, str, int]]:
    """Fetch PTT (台湾) 熱門看板. Returns [(topic, platform_name, creator_score), ...]."""
    try:
        import requests
        r = requests.get(
            PTT_HOTBOARDS_URL,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
            timeout=4,
            proxies=requests_proxies_for(overseas=True),
        )
        r.raise_for_status()
        html = r.text
        # 解析 board-class 如 <div class="board-class">棒球</div>
        matches = re.findall(r'<div class="board-class">([^<]+)</div>', html)
        result = []
        seen = set()
        for name in matches[:20]:
            name = name.strip().rstrip(".")
            if len(name) >= 2 and len(name) <= 12 and name not in seen and not re.match(r"^[A-Za-z]+$", name):
                seen.add(name)
                score = _creator_score(name, "zh")
                result.append((name, "PTT", score))
        return result
    except Exception:
        return []


def _fetch_platform_zh(platform_id: str, platform_name: str) -> list[tuple[str, str, int]]:
    """Fetch hot topics. Returns [(topic, platform_name, creator_score), ...]."""
    try:
        import requests
        r = requests.get(
            f"{HOTLIST_URL}?type={platform_id}",
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
            timeout=4,
            proxies={},
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success") or not data.get("data"):
            return []
        result = []
        for item in data["data"][:25]:
            title = (item.get("title") or "").strip()
            if title and not _is_noise_zh(title):
                score = _creator_score(title, "zh")
                result.append((title, platform_name, score))
        return result
    except Exception:
        return []


def _fetch_hn() -> list[tuple[str, int]]:
    """Fetch Hacker News top stories via single fast Algolia request (fallback to Firebase)."""
    try:
        import requests
        proxies = requests_proxies_for(overseas=True)
        r = requests.get(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={"tags": "front_page", "hitsPerPage": 18},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=6,
            proxies=proxies,
        )
        r.raise_for_status()
        result = []
        for hit in (r.json().get("hits") or [])[:18]:
            title = (hit.get("title") or hit.get("story_title") or "").strip()
            if title and not _is_noise_en(title):
                result.append((title, _creator_score(title, "en")))
        if result:
            return result
    except Exception:
        pass
    try:
        import requests
        proxies = requests_proxies_for(overseas=True)
        r = requests.get(HN_TOP, timeout=5, proxies=proxies)
        ids = r.json()[:15]

        def _one(i):
            try:
                s = requests.get(HN_ITEM.format(i), timeout=3, proxies=proxies).json()
                title = (s.get("title") or "").strip()
                if title and not _is_noise_en(title):
                    return (title, _creator_score(title, "en"))
            except Exception:
                return None
            return None

        result = []
        with ThreadPoolExecutor(max_workers=8) as ex:
            for item in ex.map(_one, ids):
                if item:
                    result.append(item)
        return result
    except Exception:
        return []


def _fetch_lobsters() -> list[tuple[str, int]]:
    """Fetch Lobste.rs hottest. Tech/creator community."""
    try:
        import requests
        r = requests.get(
            LOBSTERS_URL,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=6,
            proxies=requests_proxies_for(overseas=True),
        )
        r.raise_for_status()
        items = r.json()[:15]
        result = []
        for item in items:
            title = (item.get("title") or "").strip()
            if title and not _is_noise_en(title):
                score = _creator_score(title, "en")
                result.append((title, score))
        return result
    except Exception:
        return []


def _fetch_devto() -> list[tuple[str, int]]:
    """Fetch Dev.to top articles. Developer/creator content."""
    try:
        import requests
        r = requests.get(
            DEVTO_URL,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=6,
            proxies=requests_proxies_for(overseas=True),
        )
        r.raise_for_status()
        items = r.json()[:12]
        result = []
        for item in items:
            title = (item.get("title") or "").strip()
            if title and not _is_noise_en(title):
                score = _creator_score(title, "en")
                result.append((title, score))
        return result
    except Exception:
        return []


def _fetch_github_trending() -> list[tuple[str, int]]:
    """Fetch GitHub trending repos. Use description as topic when meaningful."""
    try:
        import requests
        r = requests.get(
            GITHUB_TRENDING_URL,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=6,
            proxies=requests_proxies_for(overseas=True),
        )
        r.raise_for_status()
        items = r.json()[:12]
        result = []
        for item in items:
            desc = (item.get("description") or "").strip()
            name = (item.get("name") or "").strip()
            topic = desc if desc and len(desc) > 15 else name
            if topic and not _is_noise_en(topic):
                score = _creator_score(topic, "en")
                result.append((topic, score))
        return result
    except Exception:
        return []


def _fetch_zh_direct_fallback() -> list[tuple[str, str, int]]:
    """Resilient direct ZH trending fallback (Bilibili popular + reliable ZH tech RSS)."""
    out: list[tuple[str, str, int]] = []
    try:
        import requests
        r = requests.get(
            "https://api.bilibili.com/x/web-interface/popular",
            params={"ps": 15, "pn": 1},
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": "https://www.bilibili.com/",
            },
            timeout=6,
            proxies={},
        )
        if r.ok:
            data = r.json()
            if data.get("code") == 0:
                for v in (data.get("data", {}).get("list") or [])[:15]:
                    t = (v.get("title") or "").strip()
                    if t and not _is_noise_zh(t):
                        out.append((t, "B站", _creator_score(t, "zh")))
    except Exception:
        pass
    try:
        import feedparser
        import requests
        for url, label in (
            ("https://36kr.com/feed", "36氪"),
            ("https://sspai.com/feed", "少数派"),
            ("https://www.qbitai.com/feed", "量子位"),
            ("https://www.ifanr.com/feed", "爱范儿"),
        ):
            try:
                r = requests.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
                    timeout=5,
                    proxies={},
                )
                if not r.ok:
                    continue
                d = feedparser.parse(r.content)
                for e in d.entries[:6]:
                    t = (e.get("title") or "").strip()
                    if t and not _is_noise_zh(t, max_len=80):
                        out.append((t, label, _creator_score(t, "zh")))
            except Exception:
                continue
    except Exception:
        pass
    return out


def fetch_all_platforms_zh() -> list[str]:
    """Fetch ZH platforms in parallel (含台湾 PTT + direct fallback), merge, prioritize creator-relevant."""
    tasks = []
    for platform_id, platform_name in PLATFORMS_ZH:
        tasks.append((_fetch_platform_zh, (platform_id, platform_name)))
    tasks.append((_fetch_ptt_hotboards, ()))
    for platform_title, platform_name in PEARKTRUE_PLATFORMS:
        tasks.append((_fetch_pearktrue_dailyhot, (platform_title, platform_name)))

    raw: list[tuple[str, str, int]] = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(fn, *args) for fn, args in tasks]
        for fut in as_completed(futs):
            try:
                raw.extend(fut.result(timeout=10) or [])
            except Exception:
                continue

    if len(raw) < 10:
        raw.extend(_fetch_zh_direct_fallback())

    seen = set()
    scored = []
    for topic, _pn, score in raw:
        tl = topic.lower().strip()
        if tl not in seen:
            seen.add(tl)
            scored.append((topic, score))
    scored.sort(key=lambda x: -x[1])
    return [t for t, _ in scored[:40]]


def fetch_all_platforms_en() -> list[str]:
    """Fetch EN platforms in parallel (HN, Lobsters, Dev.to, GitHub), merge, prioritize creator-relevant."""
    fns = (_fetch_hn, _fetch_lobsters, _fetch_devto, _fetch_github_trending)
    raw: list[tuple[str, int]] = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(fn) for fn in fns]
        for fut in as_completed(futs):
            try:
                raw.extend(fut.result(timeout=10) or [])
            except Exception:
                continue
    seen = set()
    scored = []
    for topic, score in raw:
        tl = topic.lower().strip()
        if tl not in seen:
            seen.add(tl)
            scored.append((topic, score))
    scored.sort(key=lambda x: -x[1])
    return [t for t, _ in scored[:40]]


def fetch_all_platforms() -> tuple[list[str], list[str]]:
    """Fetch both ZH and EN. Returns (topics_zh, topics_en)."""
    zh = fetch_all_platforms_zh()
    en = fetch_all_platforms_en()
    return zh, en


# Audience segments (Tier 1): approximate taste by topic/source. See docs/AUDIENCE_INSIGHT_STRATEGY.md
AUDIENCE_SEGMENTS = {
    "general": {"name_en": "General", "name_zh": "综合", "keywords_zh": set(), "keywords_en": set()},
    "tech": {
        "name_en": "Tech",
        "name_zh": "科技",
        "keywords_zh": frozenset({"科技", "AI", "人工智能", "产品", "效率", "数码", "开发", "编程", "开源", "算法", "互联网", "创业", "融资"}),
        "keywords_en": frozenset({"tech", "ai", "developer", "startup", "api", "open source", "algorithm", "software", "product", "saas"}),
    },
    "entrepreneurs": {
        "name_en": "Entrepreneurs",
        "name_zh": "创业·出海",
        "keywords_zh": frozenset({"创业", "副业", "出海", "跨境", "个人品牌", "变现", "运营", "品牌", "营销", "融资", "增长", "流量"}),
        "keywords_en": frozenset({"startup", "entrepreneur", "side project", "monetization", "growth", "marketing", "launch", "build", "indie"}),
    },
    "creator": {
        "name_en": "Creator",
        "name_zh": "创作者",
        "keywords_zh": frozenset(CREATOR_KEYWORDS_ZH),
        "keywords_en": frozenset(CREATOR_KEYWORDS_EN),
    },
    "geopolitics": {
        "name_en": "US–China",
        "name_zh": "中美政经",
        "keywords_zh": frozenset({
            "中美", "美国", "中国", "华盛顿", "北京", "关税", "贸易", "台海", "台湾", "芯片",
            "半导体", "制裁", "外交", "出口", "禁令", "冷战", "拜登", "特朗普", "国会",
        }),
        "keywords_en": frozenset({
            "us-china", "u.s.-china", "china trade", "beijing", "washington", "taiwan",
            "tariff", "trade war", "export control", "sanctions", "semiconductor", "chips",
            "strait", "ccp", "xi jinping", "biden", "trump", "congress", "pentagon",
        }),
    },
}


def _segment_score(topic: str, lang: str, segment: str) -> int:
    """Score how well a topic fits the audience segment (0–10)."""
    if not topic or segment not in AUDIENCE_SEGMENTS or segment == "general":
        return 0
    seg = AUDIENCE_SEGMENTS[segment]
    keywords = seg["keywords_zh"] if lang == "zh" else seg["keywords_en"]
    if not keywords:
        return 0
    topic_lower = topic.lower().strip()
    score = 0
    for kw in keywords:
        if kw.lower() in topic_lower:
            score += 2
    return min(score, 10)


def rerank_topics_by_segment(topics: list[str], lang: str, segment: str) -> list[str]:
    """Re-rank topics so segment-relevant ones float up. Stable sort: same score keeps original order."""
    if not topics or segment not in AUDIENCE_SEGMENTS or segment == "general":
        return topics
    scored = [(_segment_score(t, lang, segment), i, t) for i, t in enumerate(topics)]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [t for _, _, t in scored]


def save_hot_trending_cache(zh: list[str], en: list[str], *, now: float | None = None) -> dict:
    """Write hot_trending.json without overwriting previously valid lists with empty lists."""
    ts = now if now is not None else time.time()
    prev: dict = {}
    if CACHE_FILE.exists():
        try:
            prev = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
    final_zh = zh if zh else (prev.get("topics_zh") or [])
    final_en = en if en else (prev.get("topics_en") or [])
    payload = {
        "ts": ts if (zh or en) else prev.get("ts", ts),
        "topics_zh": final_zh,
        "topics_en": final_en,
    }
    if final_zh or final_en or not CACHE_FILE.exists():
        CACHE_FILE.parent.mkdir(exist_ok=True)
        CACHE_FILE.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    return payload


def get_cached_or_fetch(lang: str = "zh") -> tuple[list[str], bool]:
    """Get hot topics from cache or fetch fresh. Returns (topics, from_cache)."""
    now = time.time()
    key = "topics_zh" if lang == "zh" else "topics_en"
    prev_topics: list[str] = []
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            prev_topics = data.get(key, []) or []
            if now - data.get("ts", 0) < CACHE_TTL and prev_topics:
                return prev_topics, True
        except Exception:
            pass
    zh, en = fetch_all_platforms()
    saved = save_hot_trending_cache(zh, en, now=now)
    fresh = zh if lang == "zh" else en
    if fresh:
        return fresh, False
    return (saved.get(key) or prev_topics), True
