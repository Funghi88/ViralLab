"""Video fetch and Berger scoring. Uses duckduckgo-search (no API key). YouTube API fallback when DDG rate-limited."""
import os
import re
import time
from typing import Optional

from duckduckgo_search import DDGS


# Jonah Berger STEPPS + magic words (Contagious + Magic Words). EN + ZH for scoring.
# Expanded with synonyms for better recall (e.g. "blew my mind" for emotion).
BERGER_STEPPS = {
    "social_currency": ["exclusive", "secret", "insider", "first", "discover", "you", "behind the scenes", "never seen", "rare", "独家", "秘诀", "首发", "发现", "你"],
    "triggers": ["remind", "when", "every time", "always", "routine", "morning", "commute", "daily", "weekly", "提醒", "每次", "總是", "日常"],
    "emotion": ["love", "hate", "amazing", "shocking", "incredible", "unbelievable", "blew my mind", "mind-blowing", "awe", "excited", "angry", "爱", "恨", "震惊", "不可思议", "难以置信"],
    "public": ["share", "tell", "show", "everyone", "viral", "trending", "going viral", "everyone's doing", "分享", "告诉", "展示", "爆款", "热门", "火"],
    "practical": ["how to", "tip", "trick", "easy", "simple", "free", "instant", "step by step", "in 5 minutes", "you can do", "教程", "方法", "技巧", "简单", "免费", "干货"],
    "stories": ["story", "experience", "journey", "because", "why", "before and after", "transformation", "what happened", "故事", "经验", "因为", "为什么"],
}
MAGIC_WORDS = ["you", "because", "new", "free", "instant", "easy", "secret", "discover", "你", "因为", "新", "免费", "简单", "秘诀", "发现"]

# English-only for display when lang=en (no mixed Chinese)
BERGER_STEPPS_EN = {
    "social_currency": ["exclusive", "secret", "insider", "first", "discover", "you", "behind the scenes", "never seen", "rare"],
    "triggers": ["remind", "when", "every time", "always", "routine", "morning", "commute", "daily", "weekly"],
    "emotion": ["love", "hate", "amazing", "shocking", "incredible", "unbelievable", "blew my mind", "mind-blowing", "awe", "excited", "angry"],
    "public": ["share", "tell", "show", "everyone", "viral", "trending", "going viral", "everyone's doing"],
    "practical": ["how to", "tip", "trick", "easy", "simple", "free", "instant", "step by step", "in 5 minutes", "you can do"],
    "stories": ["story", "experience", "journey", "because", "why", "before and after", "transformation", "what happened"],
}
MAGIC_WORDS_EN = ["you", "because", "new", "free", "instant", "easy", "secret", "discover"]


def _parse_views(val) -> int:
    """Parse view count string to int (e.g. '1.2M' -> 1200000)."""
    if val is None:
        return 0
    if isinstance(val, int):
        return val
    s = str(val).upper().replace(",", "").strip()
    mult = 1
    if s.endswith("M") or s.endswith("MIL"):
        mult, s = 1_000_000, s.rstrip("MIL")
    elif s.endswith("K"):
        mult, s = 1_000, s[:-1]
    elif s.endswith("B"):
        mult, s = 1_000_000_000, s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return 0


def _fetch_youtube_search(query: str, max_results: int) -> list[dict]:
    """Fallback: search YouTube via Data API when DDG is rate-limited. Needs YOUTUBE_API_KEY."""
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        return []
    try:
        from googleapiclient.discovery import build
        yt = build("youtube", "v3", developerKey=key)
        search_q = f"{query} viral" if "youtube" not in query.lower() else query
        req = yt.search().list(
            part="id,snippet",
            q=search_q,
            type="video",
            order="viewCount",
            maxResults=min(max_results, 25),
        )
        res = req.execute()
        video_ids = [i["id"]["videoId"] for i in res.get("items", []) if i.get("id", {}).get("kind") == "youtube#video"]
        if not video_ids:
            return []
        # Get stats for views
        stats_req = yt.videos().list(part="statistics,snippet", id=",".join(video_ids))
        stats_res = stats_req.execute()
        out = []
        for v in stats_res.get("items", []):
            snip = v.get("snippet", {})
            stats = v.get("statistics", {})
            vid = v.get("id", "")
            out.append({
                "title": snip.get("title", "N/A"),
                "url": f"https://www.youtube.com/watch?v={vid}",
                "description": (snip.get("description", "") or "")[:300],
                "views": stats.get("viewCount"),
                "views_int": _parse_views(stats.get("viewCount")),
                "duration": None,
                "uploader": snip.get("channelTitle"),
            })
        return out
    except Exception:
        return []


def fetch_trending_videos(query: str = "trending viral youtube", max_results: int = 10) -> list[dict]:
    """Fetch hot/trending videos via DuckDuckGo (no API key). Retries on rate limit; falls back to YouTube API if set."""
    last_err = None
    for attempt in range(3):
        try:
            with DDGS() as ddgs:
                results = list(ddgs.videos(query, max_results=max_results, timelimit="w"))
            break
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            if "ratelimit" in err_str or "202" in err_str:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
                continue
            raise RuntimeError(f"Video search error: {e}") from e
    else:
        # All retries failed — try YouTube API fallback
        fallback = _fetch_youtube_search(query, max_results)
        if fallback:
            return fallback
        raise RuntimeError(f"Video search error: {last_err}") from last_err

    out = []
    for r in results:
        url = r.get("content") or r.get("url") or ""
        if "youtube.com" not in url and "youtu.be" not in url:
            continue
        views_raw = r.get("statistics", {}).get("viewCount") if isinstance(r.get("statistics"), dict) else None
        views_int = _parse_views(views_raw)
        out.append({
            "title": r.get("title", "N/A"),
            "url": url,
            "description": (r.get("description") or "")[:300],
            "views": views_raw,
            "views_int": views_int,
            "duration": r.get("duration"),
            "uploader": r.get("uploader") or r.get("publisher"),
        })
    return out


def fetch_viral_videos(query: str = "viral youtube", max_results: int = 15) -> list[dict]:
    """Fetch viral YouTube videos, ranked by spread rate (views as proxy for first-week virality)."""
    videos = fetch_trending_videos(query, max_results=max_results)
    # Sort by views (highest first) as proxy for viral spread rate
    videos.sort(key=lambda v: v.get("views_int", 0), reverse=True)
    return videos


def _hook_score(hook_text: str) -> tuple[int, list[str]]:
    """Score first 15 words for shareability signals. Returns (pts, signals_found)."""
    words = hook_text.lower().split()[:15]
    if len(words) < 5:
        return 0, []
    hook = " ".join(words)
    signals = []
    pts = 0
    # Question hook
    if "?" in hook or any(w in hook for w in ["what", "why", "how", "which", "who"]):
        signals.append("question")
        pts += 8
    # Stat/number hook
    if re.search(r"\d+%|\d+x|\d+ (ways|tips|steps|minutes|seconds)", hook):
        signals.append("stat")
        pts += 10
    # Surprising/counterintuitive
    if any(w in hook for w in ["wrong", "mistake", "secret", "never", "actually", "really", "truth"]):
        signals.append("surprising")
        pts += 10
    # Conflict/tension
    if any(w in hook for w in ["but", "however", "problem", "vs", "versus", "vs.", "fight"]):
        signals.append("conflict")
        pts += 8
    return min(pts, 15), signals  # cap hook at 15


def _narrative_arc_score(text: str) -> tuple[int, bool]:
    """Detect setup→conflict→resolution. Returns (pts, has_arc)."""
    words = text.split()
    if len(words) < 60:
        return 0, False
    n = len(words)
    beg, mid, end = " ".join(words[: n // 3]).lower(), " ".join(words[n // 3 : 2 * n // 3]).lower(), " ".join(words[2 * n // 3 :]).lower()
    # Resolution signals in end
    resolution = any(w in end for w in ["result", "finally", "learned", "takeaway", "lesson", "so", "therefore", "that's why", "now you"])
    # Problem/conflict in mid
    conflict = any(w in mid for w in ["but", "problem", "challenge", "struggle", "however", "wrong", "failed", "mistake"])
    # Setup in beg
    setup = any(w in beg for w in ["start", "begin", "first", "when", "before", "used to", "story", "experience"])
    has_arc = sum([resolution, conflict, setup]) >= 2
    return (10 if has_arc else 0), has_arc


def score_berger(text: str) -> dict:
    """Score text against Jonah Berger's STEPPS and magic words. Returns 0-100."""
    if not text or not isinstance(text, str):
        return {"total": 0, "breakdown": {}, "magic_words_found": [], "hook_score": 0, "narrative_arc": False}

    lower = text.lower()
    breakdown = {}
    for principle, keywords in BERGER_STEPPS.items():
        count = sum(1 for k in keywords if k in lower)
        breakdown[principle] = min(count * 15, 20)  # cap 20 per principle

    magic_found = [w for w in MAGIC_WORDS if w in lower]
    magic_bonus = len(magic_found) * 5

    # Principle-count bonus: 3+ principles present → +10 (Berger research)
    principles_present = sum(1 for v in breakdown.values() if v > 0)
    principle_bonus = 10 if principles_present >= 3 else 0

    # Hook score (first 15 words) — strong predictor of shareability
    hook_pts, hook_signals = _hook_score(text)

    # Narrative arc (for longer content)
    arc_pts, has_arc = _narrative_arc_score(text)

    total = min(
        sum(breakdown.values()) + magic_bonus + principle_bonus + hook_pts + arc_pts,
        100,
    )
    return {
        "total": total,
        "breakdown": breakdown,
        "magic_words_found": magic_found,
        "hook_score": hook_pts,
        "hook_signals": hook_signals,
        "narrative_arc": has_arc,
        "principle_bonus": principle_bonus,
    }


def extract_youtube_id(url: str) -> Optional[str]:
    """Extract video ID from YouTube URL."""
    m = re.search(r"(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
    return m.group(1) if m else None
