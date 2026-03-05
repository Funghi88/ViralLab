"""Fetch platform-wide hot topics for creators. Multi-source for better reference."""
import json
import re
from pathlib import Path

# 笒鬼鬼 API - 中文区聚合热榜
HOTLIST_URL = "https://api-v2.cenguigui.cn/api/juhe/hotlist.php"
PLATFORMS_ZH = [
    ("weibo", "微博"),
    ("zhihu", "知乎"),
    ("douyin", "抖音"),
    ("baidu", "百度"),
    ("sspai", "少数派"),  # 效率工具、数码、创作者
]
# 英文区：多源覆盖
REDDIT_SUBS = ["technology", "Entrepreneur", "SideProject", "YouTubeCreators", "content_marketing"]
HN_TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{}.json"
LOBSTERS_URL = "https://lobste.rs/hottest.json"
DEVTO_URL = "https://dev.to/api/articles?per_page=15&top=7"
GITHUB_TRENDING_URL = "https://githubtrending.lessx.xyz/trending?since=daily"

CACHE_FILE = Path(__file__).parent.parent / "output" / "hot_trending.json"
CACHE_TTL = 10 * 60  # 10 min — 近实时

# 创作者相关关键词
CREATOR_KEYWORDS_ZH = frozenset({
    "美妆", "护肤", "穿搭", "时尚", "种草", "直播", "带货", "短视频", "电商", "内容",
    "创作", "爆款", "网红", "UP主", "私域", "品牌", "营销", "教程", "AI", "小红书",
    "抖音", "B站", "知乎", "好物", "测评", "开箱", "vlog", "剪辑", "涨粉", "变现",
    "流量", "算法", "运营", "干货", "攻略", "分享", "推荐", "榜单", "热门",
})
CREATOR_KEYWORDS_EN = frozenset({
    "creator", "viral", "trending", "AI", "YouTube", "TikTok", "content", "marketing",
    "startup", "SaaS", "tool", "growth", "monetization", "subscriber", "algorithm",
    "tutorial", "review", "unboxing", "vlog", "podcast", "newsletter", "influencer",
    "developer", "open source", "framework", "API", "build", "launch",
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


def _is_noise_zh(s: str) -> bool:
    """过滤纯时政/难以跟风做内容的热搜。"""
    if len(s) < 2 or len(s) > 28:
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


def _fetch_platform_zh(platform_id: str, platform_name: str) -> list[tuple[str, str, int]]:
    """Fetch hot topics. Returns [(topic, platform_name, creator_score), ...]."""
    try:
        import requests
        r = requests.get(
            f"{HOTLIST_URL}?type={platform_id}",
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
            timeout=8,
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
    """Fetch Hacker News top stories. Returns [(title, creator_score), ...]."""
    try:
        import requests
        r = requests.get(HN_TOP, timeout=5)
        ids = r.json()[:15]
        result = []
        for i in ids:
            try:
                s = requests.get(HN_ITEM.format(i), timeout=2).json()
                title = (s.get("title") or "").strip()
                if title and not _is_noise_en(title):
                    score = _creator_score(title, "en")
                    result.append((title, score))
            except Exception:
                continue
        return result
    except Exception:
        return []


def _fetch_reddit() -> list[tuple[str, int]]:
    """Fetch Reddit hot from creator-relevant subs. May timeout from some networks."""
    try:
        import requests
        headers = {"User-Agent": "ViralLab/1.0 (creator trends; +https://github.com)"}
        result = []
        for sub in REDDIT_SUBS[:2]:
            try:
                r = requests.get(
                    f"https://www.reddit.com/r/{sub}/hot.json?limit=10",
                    headers=headers,
                    timeout=4,
                )
                if r.status_code != 200:
                    continue
                for c in r.json().get("data", {}).get("children", [])[:6]:
                    title = (c.get("data", {}).get("title") or "").strip()
                    if title and not _is_noise_en(title):
                        score = _creator_score(title, "en")
                        result.append((title, score))
            except Exception:
                continue
        return result
    except Exception:
        return []


def _fetch_lobsters() -> list[tuple[str, int]]:
    """Fetch Lobste.rs hottest. Tech/creator community."""
    try:
        import requests
        r = requests.get(LOBSTERS_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
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
        r = requests.get(DEVTO_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
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
        r = requests.get(GITHUB_TRENDING_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
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


def fetch_all_platforms_zh() -> list[str]:
    """Fetch ZH platforms, merge, prioritize creator-relevant."""
    seen = set()
    scored = []
    for platform_id, platform_name in PLATFORMS_ZH:
        for topic, _pn, score in _fetch_platform_zh(platform_id, platform_name):
            tl = topic.lower().strip()
            if tl not in seen:
                seen.add(tl)
                scored.append((topic, score))
    scored.sort(key=lambda x: -x[1])
    return [t for t, _ in scored[:40]]


def fetch_all_platforms_en() -> list[str]:
    """Fetch EN platforms (HN, Reddit, Lobsters, Dev.to, GitHub), merge, prioritize creator-relevant."""
    seen = set()
    scored = []
    for topic, score in (
        _fetch_hn()
        + _fetch_reddit()
        + _fetch_lobsters()
        + _fetch_devto()
        + _fetch_github_trending()
    ):
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


def get_cached_or_fetch(lang: str = "zh") -> tuple[list[str], bool]:
    """Get hot topics from cache or fetch fresh. Returns (topics, from_cache)."""
    now = __import__("time").time()
    key = "topics_zh" if lang == "zh" else "topics_en"
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if now - data.get("ts", 0) < CACHE_TTL:
                topics = data.get(key, [])
                if topics:
                    return topics, True
        except Exception:
            pass
    zh, en = fetch_all_platforms()
    CACHE_FILE.parent.mkdir(exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps({"ts": now, "topics_zh": zh, "topics_en": en}, ensure_ascii=False),
        encoding="utf-8",
    )
    return (zh if lang == "zh" else en), False
