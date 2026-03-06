#!/usr/bin/env python
"""ViralLab — Engineer your influence. Turn noise into viral."""
import os
import subprocess
import sys
from pathlib import Path

import json
from typing import Optional

# Bypass proxy for news/video fetches (fixes "connection refused" when proxy is down)
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy")


def _env_no_proxy():
    env = os.environ.copy()
    for v in _PROXY_VARS:
        env.pop(v, None)
    return env
from urllib.parse import quote
from flask import Flask, jsonify, redirect, request, send_from_directory, make_response

from src.parse_output import parse_file
from src.video_tools import BERGER_STEPPS, BERGER_STEPPS_EN, MAGIC_WORDS, MAGIC_WORDS_EN, extract_youtube_id, score_berger
from src.content_angles import generate_angles
from src.run_history import add_lifecycle_to_items

app = Flask(__name__)
OUTPUT = Path(__file__).parent / "output"
NEWS_SEARCHES_FILE = OUTPUT / "news_searches.json"

# Suggestions only — users can search any topic. Creator-relevant defaults per language zone.
DEFAULT_TOPIC_TIPS = [
    "AI agents", "creator economy", "climate tech", "no-code tools", "LLM trends",
    "creator tools", "indie hacking", "side projects", "AI explainers", "content strategy",
    "viral marketing", "social media trends", "YouTube algorithm", "newsletter monetization",
    "Substack trends", "podcast growth", "automation tools", "AI writing", "design tools",
    "remote work",
]
DEFAULT_TOPIC_TIPS_ZH = [
    "小红书爆款", "抖音运营", "短视频创作", "创作者经济", "直播带货", "私域流量",
    "电商直播", "内容营销", "AI写作", "B站UP主", "知乎好物", "微信公众号",
    "品牌出海", "小红书种草", "抖音算法", "剪映教程", "飞书文档", "即刻",
    "知识星球", "新榜",
]

# Viral Videos — creator-focused topic suggestions per language
DEFAULT_VIRAL_TIPS = [
    "AI explainer", "fashion haul", "viral marketing", "unboxing", "makeup tutorial",
    "cooking viral", "dance challenge", "prank", "product review", "day in my life",
]
# China: 热门 = B站 popular API (always has content). Others = search, fallback to popular.
DEFAULT_VIRAL_TIPS_ZH = [
    "热门", "鬼畜", "搞笑", "数码", "游戏", "知识", "时尚", "影视",
    "汽车", "日常", "穿搭",
]


def _record_topic_search(topic: str) -> None:
    """Record a topic search with timestamp for time-based popular searches."""
    if not topic or len(topic) > 80:
        return
    from datetime import datetime, timezone
    data = {"searches": []}
    if NEWS_SEARCHES_FILE.exists():
        try:
            data = json.loads(NEWS_SEARCHES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    searches = data.get("searches", [])
    # Migrate old format: topics -> searches (no timestamp, treat as recent)
    if not searches and data.get("topics"):
        now = datetime.now(timezone.utc).isoformat()
        for t, c in data["topics"].items():
            searches.extend([{"topic": t, "ts": now}] * min(c, 10))
        data["topics"] = {}
    searches.append({"topic": topic.strip(), "ts": datetime.now(timezone.utc).isoformat()})
    # Keep last 30 days
    cutoff = datetime.now(timezone.utc).timestamp() - (30 * 24 * 3600)
    searches = [s for s in searches if _parse_ts(s.get("ts", "")) > cutoff]
    data["searches"] = searches[-5000:]
    OUTPUT.mkdir(exist_ok=True)
    NEWS_SEARCHES_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _parse_ts(s: str) -> float:
    from datetime import datetime
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")[:26]).timestamp()
    except Exception:
        return 0


def _has_cjk(s: str) -> bool:
    """True if string contains CJK (Chinese/Japanese/Korean) characters."""
    for c in s:
        if "\u4e00" <= c <= "\u9fff" or "\u3000" <= c <= "\u303f" or "\uac00" <= c <= "\ud7af":
            return True
    return False


def _matches_lang(topic: str, lang: str) -> bool:
    """True if topic matches the language zone (no mixing in EN/zh views)."""
    has_cjk = _has_cjk(topic)
    return (lang == "zh" and has_cjk) or (lang == "en" and not has_cjk)


def _get_platform_hot_topics(limit: int, lang: str, force_refresh: bool = False) -> tuple[list[str], bool, Optional[int]]:
    """Platform-wide hot topics. ZH: 微博、知乎、抖音、百度. EN: Hacker News, Reddit. Returns (topics, ok, cache_age_sec).
    Never blocks >2s — uses stale cache or defaults, refreshes in background."""
    import threading
    cache_file = OUTPUT / "hot_trending.json"
    cache_ttl = 10 * 60  # 10 min
    key = "topics_zh" if lang == "zh" else "topics_en"
    now = __import__("time").time()

    def _run_refresh():
        try:
            script = Path(__file__).parent / "scripts" / "fetch_hot_trending.py"
            env = _env_no_proxy()
            env["PYTHONPATH"] = str(Path(__file__).parent)
            subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                env=env,
                cwd=Path(__file__).parent,
                timeout=45,
            )
        except Exception:
            pass

    # Use fresh cache if available
    if not force_refresh and cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            ts = data.get("ts", 0)
            topics = data.get(key, data.get("topics", []))
            if topics:
                if now - ts < cache_ttl:
                    return topics[:limit], True, int(now - ts)
                # Stale but usable — return immediately, refresh in background
                threading.Thread(target=_run_refresh, daemon=True).start()
                return topics[:limit], True, int(now - ts)
        except Exception:
            pass

    # No usable cache: try quick sync (8s max) so page loads fast
    try:
        script = Path(__file__).parent / "scripts" / "fetch_hot_trending.py"
        env = _env_no_proxy()
        env["PYTHONPATH"] = str(Path(__file__).parent)
        subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            env=env,
            cwd=Path(__file__).parent,
            timeout=8,
        )
        if cache_file.exists():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            topics = data.get(key, data.get("topics", []))
            if topics:
                return topics[:limit], True, 0
    except Exception:
        pass
    threading.Thread(target=_run_refresh, daemon=True).start()
    return [], False, None


def _get_most_searched(limit: int = 10, time_range: str = "1d", lang: str = "en", force_hot_refresh: bool = False) -> tuple[list[str], str, Optional[int]]:
    """Top topics. Returns (topics, source, hot_cache_age_sec). source: 'platform'|'app'|'default'. hot_cache_age only when platform."""
    from datetime import datetime, timezone
    defaults = DEFAULT_TOPIC_TIPS_ZH if lang == "zh" else DEFAULT_TOPIC_TIPS

    platform_topics, ok, cache_age = _get_platform_hot_topics(limit, lang, force_refresh=force_hot_refresh)
    if ok:
        return platform_topics[:limit], "platform", cache_age

    now = datetime.now(timezone.utc).timestamp()
    if time_range == "60m":
        cutoff = now - 3600
    elif time_range == "7d":
        cutoff = now - (7 * 24 * 3600)
    else:
        cutoff = now - (24 * 3600)
    if not NEWS_SEARCHES_FILE.exists():
        return defaults[:limit], "default", None
    try:
        data = json.loads(NEWS_SEARCHES_FILE.read_text(encoding="utf-8"))
        searches = data.get("searches", [])
        if not searches and data.get("topics"):
            sorted_topics = sorted(data["topics"].items(), key=lambda x: -x[1])
            result = [t[0] for t in sorted_topics[:limit] if _matches_lang(t[0], lang)]
            for d in defaults:
                if len(result) >= limit:
                    break
                if d not in result:
                    result.append(d)
            return result[:limit], "app" if data["topics"] else "default", None
        counts = {}
        for s in searches:
            ts = _parse_ts(s.get("ts", ""))
            if ts >= cutoff:
                t = s.get("topic", "").strip()
                if t and _matches_lang(t, lang):
                    counts[t] = counts.get(t, 0) + 1
        if not counts:
            return defaults[:limit], "default", None
        sorted_topics = sorted(counts.items(), key=lambda x: -x[1])
        result = [t[0] for t in sorted_topics[:limit]]
        for d in defaults:
            if len(result) >= limit:
                break
            if d not in result:
                result.append(d)
        return result[:limit], "app", None
    except Exception:
        return defaults[:limit], "default", None


TAGLINE = "Engineer your influence. Turn noise into viral."
SPREAD_LINE = "ViralLab scores content by applying behavioral science - aka. STEPPS, design viral content - so easy"
TG_GROUP_URL = "https://t.me/virallab8"
TG_PERSONAL_URL = "https://t.me/miccakitt"
BLOG_URL = "https://funghi88.github.io/"
GITHUB_REPO_URL = "https://github.com/Funghi88/ViralLab"
X_URL = "https://x.com/miccakitt"


def _html_escape(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _sanitize_snippet(text: str) -> str:
    """Strip HTML tags and decode entities so snippets display as plain text, not raw HTML."""
    if not text or not isinstance(text, str):
        return ""
    import html
    import re
    s = html.unescape(text)
    s = re.sub(r"<[^>]*>?", "", s)  # strip tags including malformed/unclosed
    s = re.sub(r"\s+", " ", s).strip()
    return s[:500]


# Snippet placeholders: when snippet equals these, it's source attribution, not news content
_SNIPPET_PLACEHOLDERS = frozenset({"Hacker News front page", "HN", "Hacker News"})


def _snippet_is_placeholder(snippet: str) -> bool:
    """True when snippet is a source placeholder, not actual news content."""
    return (snippet or "").strip() in _SNIPPET_PLACEHOLDERS


def _source_display(source: str) -> str:
    """Source attribution for display. Use full name for respect."""
    if source == "Hacker News":
        return "Hacker News front page"
    return source or ""


def _get_source_for_item(item: dict) -> str:
    """Get source for display. When snippet is placeholder (e.g. HN), use it as source."""
    src = _source_display(item.get("source", "")) or _infer_source_from_url(item.get("url", ""))
    if not src and _snippet_is_placeholder(item.get("snippet", "")):
        snip = (item.get("snippet") or "").strip()
        if snip == "HN":
            return "Hacker News front page"
        return snip
    return src


def _infer_source_from_url(url: str) -> str:
    """Infer source from URL when source field is missing."""
    if not url:
        return ""
    u = (url or "").lower()
    if "news.ycombinator.com" in u:
        return "Hacker News front page"
    if "theverge.com" in u:
        return "The Verge"
    if "techcrunch.com" in u:
        return "TechCrunch"
    if "producthunt.com" in u:
        return "Product Hunt"
    return ""


def _get_lang():
    """Get user language from cookie or query param. Returns 'en' or 'zh'."""
    lang = request.cookies.get("virallab-lang") or request.args.get("lang", "en")
    return "zh" if lang == "zh" else "en"


def _get_region():
    """Get user region from URL param (for shared links) or cookie. Returns 'global', 'americas', 'europe', or 'asia'."""
    r = request.args.get("region") or request.cookies.get("virallab-region") or "global"
    return r if r in ("global", "americas", "europe", "asia") else "global"


def _t(key: str, lang: str) -> str:
    """Translation lookup. Key -> en/zh string."""
    T = {
        "daily_news_title": ("Daily News", "每日新闻"),
        "daily_news_desc": (
            "Top 3 = most talked about right now. Xiaohongshu and Douyin creators can reference.",
            "前 3 条为当下最热话题，小红书、抖音创作者可参考",
        ),
        "mechanism": ("", ""),
        "refresh_now": ("Refresh now", "立即刷新"),
        "refresh_desc": ("fetch latest hot news anytime. Auto-refresh every 60 mins when server is running.", "随时获取最新热门新闻，服务器运行时每 60 分钟自动更新"),
        "last_updated": ("Last updated", "最后更新"),
        "sources": ("Sources", "来源"),
        "sources_curated": ("curated for content creators.", "为创作者精选"),
        "setup": ("SETUP", "设置"),
        "view_full_digest": ("View full digest (10 Top News · load more)", "查看完整摘要（10 条头条 · 加载更多）"),
        "full_digest_title": ("Full digest (10 Top News · load more)", "完整摘要（10 条头条 · 加载更多）"),
        "load_more": ("More", "更多"),
        "ranking_legend": ("Rising = new · Peaking = holding strong · Fading = declining", "上升 = 新话题 · 高峰 = 热度持稳 · 回落 = 热度下降"),
        "tooltip_rising": ("New this run — wasn't in the previous top list. A fresh topic gaining traction.", "本轮新上榜，上一轮未出现。新兴热门话题"),
        "tooltip_peaking": ("Same or better rank than before — the topic is at or near its peak attention.", "排名持平或上升，话题处于或接近关注高峰"),
        "tooltip_fading": ("Dropped in rank — was higher before, now declining in buzz.", "排名下降，热度回落"),
        "search_by_topic": ("Search by topic", "按主题搜索"),
        "whats_happening": ("what's happening around X", "了解 X 领域动态"),
        "no_news": ("No daily news yet. Run:", "尚无每日新闻，执行："),
        "source": ("Source", "来源"),
        "lifecycle_rising": ("rising", "上升"),
        "lifecycle_peaking": ("peaking", "高峰"),
        "lifecycle_fading": ("fading", "回落"),
        # Homepage & global
        "nav_home": ("Home", "首页"),
        "nav_home_desc": ("Landing & quick links", "首页与快速链接"),
        "nav_daily": ("Daily News", "每日新闻"),
        "nav_daily_desc": ("Top 3 topics today", "今日前 3 热门话题"),
        "nav_field": ("Your Field", "你的领域"),
        "nav_field_desc": ("Curated by industry", "按行业精选"),
        "nav_news": ("News by Topic", "按主题新闻"),
        "nav_news_desc": ("Search & browse news", "搜索与浏览新闻"),
        "nav_viral": ("Viral Videos", "热门视频"),
        "nav_viral_desc": ("YouTube & Bilibili", "YouTube 与 Bilibili"),
        "nav_video2text": ("Video to Text", "视频转文字"),
        "nav_video2text_desc": ("Extract transcript from video", "视频提取逐字稿"),
        "nav_science": ("STEPPS Science", "STEPPS 科学"),
        "nav_science_desc": ("How we score", "评分方式"),
        "hero_line1": ("ENGINEER YOUR", "打造你的"),
        "hero_line2": ("INFLUENCE.", "影响力"),
        "hero_subtitle": ("Your content agent.", "你的内容助手"),
        "hero_desc": ("Turn noise into viral. Gather trends, score with behavioral science, and design content that spreads.", "化杂讯为爆款。小红书、抖音、B站创作者必备 — 趋势、评分、内容角度"),
        "hero_cta": ("Explore Features", "探索功能"),
        "search_placeholder": ("Search viral videos (e.g. AI explainer)...", "搜索热门视频（如：AI 解说）..."),
        "how_we_score": ("How we score", "评分方式"),
        "tg_group": ("TG group", "TG 群组"),
        "home_title": ("Home", "首页"),
        "tagline": ("Engineer your influence. Turn noise into viral.", "打造你的影响力。化杂讯为爆款"),
        "spread_line": ("ViralLab scores content by applying behavioral science - aka. STEPPS, design viral content - so easy", "ViralLab 运用行为科学（STEPPS）评分内容，设计爆款内容更轻松"),
        "link_daily": ("Daily News", "每日新闻"),
        "link_daily_desc": ("Top 3 most talked about or key focus topics", "前 3 条最热门或重点话题"),
        "link_field": ("Your Field", "你的领域"),
        "link_field_desc": ("Curated trends and resources by industry", "按行业精选的趋势与资源"),
        "link_news": ("News by Topic", "按主题新闻"),
        "link_news_desc": ("Search and browse news by topic", "按主题搜索与浏览新闻"),
        "link_viral": ("Viral Videos", "热门视频"),
        "link_viral_desc": ("YouTube & Bilibili, ranked by spread rate", "YouTube 与 Bilibili，按传播率排序"),
        "link_video2text": ("Video to Text", "视频转文字"),
        "link_video2text_desc": ("Paste URL → extract transcript", "粘贴链接 → 提取逐字稿"),
        "link_science": ("STEPPS Science", "STEPPS 科学"),
        "link_science_desc": ("How we score content with behavioral science", "运用行为科学评分内容"),
        # Your Field page
        "field_title": ("Your field · Curated resources", "你的领域 · 精选资源"),
        "field_desc": ("Pick your niche — must-see trends and resources for Xiaohongshu, Douyin, Bilibili creators. Fashion-first, designer-built.", "选择你的领域 — 小红书、抖音、B站创作者必看的趋势与资源。时尚优先，设计师视角"),
        "field_trends": ("Trends", "趋势"),
        "field_color_forecasting": ("Color forecasting", "色彩预测"),
        "field_forecasting_sites": ("Forecasting sites", "预测网站"),
        "field_resources": ("Resources", "资源"),
        "field_select_above": ("Select a field above.", "请在上方选择领域"),
        "field_empty": ("No resources for this field.", "此领域暂无资源"),
        "field_region": ("Region", "地区"),
        "field_region_global": ("Global", "全球"),
        "field_region_americas": ("Americas", "美洲"),
        "field_region_europe": ("Europe", "欧洲"),
        "field_region_asia": ("Asia", "亚洲"),
        "field_share": ("Share", "分享"),
        "field_share_copied": ("Link copied!", "链接已复制！"),
        "field_share_to": ("Share to", "分享至"),
        "field_share_whatsapp": ("WhatsApp", "WhatsApp"),
        "field_share_telegram": ("Telegram", "Telegram"),
        "field_share_x": ("X", "X"),
        "field_share_linkedin": ("LinkedIn", "LinkedIn"),
        "field_share_copy": ("Copy link", "复制链接"),
        "field_share_text": ("Curated resources for content creators — ViralLab", "为创作者精选的趋势与资源 — ViralLab"),
        # News by topic — different content per language zone
        "news_title": ("News by topic", "按主题新闻"),
        "news_desc": ("Search any topic — suggestions below are just ideas. Market demand, not crowded content.", "搜索任一主题，掌握市场需求。下方为建议，可试试"),
        "news_placeholder": ("Search any topic (e.g. AI agents, creator economy)", "搜索主题（如：小红书爆款、抖音运营）"),
        "news_range_60m": ("60 mins", "60 分钟"),
        "news_range_1d": ("1 day", "1 天"),
        "news_range_7d": ("7 days", "7 天"),
        "news_tip_requested": ("Most requested in last {range}", "过去 {range} 最常搜索"),
        "news_tip_platform_hot": ("What users care about now — Weibo, Zhihu, Douyin, Baidu, 少数派", "用户正在关注 · 微博、知乎、抖音、百度、少数派 实时热搜"),
        "news_tip_platform_hot_en": ("What users care about now — HN, Reddit, Lobsters, Dev.to, GitHub", "用户正在关注 · HN、Reddit、Lobsters、Dev.to、GitHub 实时热门"),
        "news_tip_suggestions": ("Suggestions — try these", "建议 — 试试这些"),
        "news_topic_label": ("Topic", "主题"),
        "news_no_results": ("Search a topic above to get curated news.", "搜索上方主题即可获取精选新闻"),
        "news_searching": ("Searching… Refresh in a few seconds.", "正在搜索… 几秒后刷新页面"),
        "news_english_topic_in_zh": ("This topic has English content. Please select a Chinese topic above.", "此主题为英文内容，请选择上方中文主题"),
        "news_chinese_topic_in_en": ("This topic has Chinese content. Switch to 中文 to view.", "此主题为中文内容，请切换至英文查看"),
        "news_show_all": ("Show all topics", "显示全部主题"),
        "news_search_failed": ("Search failed (proxy/network). Re-run when VPN is on.", "搜索失败（代理/网络）。请开启 VPN 后重试"),
        "news_refresh_all": ("Refresh all topics", "刷新全部主题"),
        "news_refresh_hot": ("Refresh hot list", "刷新热搜"),
        "news_refresh_interval": ("every 60 mins", "每 60 分钟"),
        "news_hot_updated": ("Updated {mins} min ago", "约 {mins} 分钟前更新"),
        "news_hot_just_now": ("Just updated", "刚刚更新"),
        "loading_searching": ("Searching topics…", "正在搜索主题…"),
        "loading_search_sub": ("This may take up to a minute. Please wait.", "可能需要一分钟，请稍候"),
        "loading_refreshing": ("Refreshing…", "正在刷新…"),
        "loading_refresh_sub": ("Please wait.", "请稍候"),
        # Viral Videos — different content per language zone
        "viral_title": ("Viral Videos", "热门视频"),
        "viral_subtitle": ("Ranked by spread rate", "按传播率排序"),
        "viral_desc": ("Videos ranked by viral rate (first-week upload spread). Search by topic:", "按传播率排序的热门视频。搜索主题：小红书、抖音、B站创作者必备"),
        "viral_placeholder": ("e.g. AI explainer, fashion haul", "如：AI 解说、穿搭测评、直播带货"),
        "viral_source_label": ("Source", "来源"),
        "viral_source_global": ("Global (YouTube)", "全球 (YouTube)"),
        "viral_source_china": ("China (Bilibili)", "中国 (Bilibili)"),
        "viral_search_btn": ("Search viral", "搜索热门"),
        "viral_what_we_serve": ("Global: YouTube videos. China: Bilibili videos. Every link opens the video on its platform.", "英文区：YouTube 视频。中文区：B站视频。点击即跳转至该平台观看。"),
        "viral_china_note": ("In China? YouTube needs VPN. Use China source for Bilibili (no VPN).", "在中国, YouTube 需魔法, 请选中国来源搜 B站"),
        "viral_suggestions": ("Suggestions — try these", "建议 — 试试这些"),
        "viral_lang_hint": ("This topic is in English. Try China source for Chinese content.", "此主题为英文，建议选择中国来源搜索中文内容"),
        "viral_berger_unproven": ("—", "—"),
        "viral_berger_methodology": ("Score: title+description only (Berger keywords). Not AI. 0 views = unproven.", "评分：仅标题与描述（Berger 关键字）。非 AI。0 播放 = 未验证"),
        "viral_loading": ("Finding what's spreading…", "正在加载…"),
        "viral_empty_title": ("Nothing here yet.", "暂无结果"),
        "viral_empty_body": ("Try one of these searches to see viral content scored in real time:", "试试这些搜索，实时查看爆款评分："),
        "viral_error": ("Error", "加载失败"),
        "viral_china_unavailable": ("Bilibili may be unreachable from your network. Try switching to Global (YouTube) source above.", "B站 API 可能无法访问（需在中国网络）。请切换至上方「全球 (YouTube)」来源重试。"),
        "viral_timeout": ("Request timeout", "请求超时"),
        "content_angles": ("3 ways to ride this trend", "3 种内容角度"),
        # Video to Text — different content per language zone
        "video2text_title": ("Video to Text", "影片转文字"),
        "video2text_tagline": ("Paste a video. Get the transcript.", "粘贴视频。获取逐字稿"),
        "video2text_accuracy_note": ("We use YouTube's existing captions — not speech-to-text. <strong>Creator-uploaded captions</strong> are usually accurate. <strong>Auto-generated</strong> ones are mostly fine, but names and jargon may have errors.", "我们使用 YouTube 现有字幕 — 非语音转文字。<strong>创作者上传的字幕</strong>通常准确。<strong>自动生成</strong>的多数可用，但人名和专业术语可能有误。"),
        "video2text_placeholder": ("https://www.youtube.com/watch?v=...", "https://www.youtube.com/watch?v=..."),
        "video2text_btn": ("Get transcript →", "获取逐字稿 →"),
        "video2text_hint": ("Supports YouTube and Bilibili · e.g. ", "支持 YouTube 和 B站 · 例如 "),
        "video2text_note1": ("For best accuracy, look for videos with <strong>manual captions</strong> (CC badge on YouTube).", "最佳准确度请选择有<strong>手动字幕</strong>的视频（YouTube 上的 CC 标识）。"),
        "video2text_note2": ("The markdown export is structured for AI — paste it into ChatGPT or Claude and ask it to rewrite for your platform.", "Markdown 导出为 AI 优化 — 粘贴到 ChatGPT 或 Claude 让它按你的平台重写。"),
        "video2text_note3": ("Bilibili captions are supported when available. The Berger score works the same for Chinese-language content.", "B站字幕在可用时支持。Berger 评分对中文内容同样适用。"),
        "video2text_how_score": ("How the score works", "评分如何运作"),
        "video2text_find": ("Find trending videos", "发现热门视频"),
        "video2text_your_transcripts": ("Your transcripts", "你的逐字稿"),
        "video2text_none": ("None yet", "尚无"),
        # Campaign page
        "campaign_eyebrow": ("ViralLab · Free · No API key needed", "ViralLab · 免费 · 无需 API 密钥"),
        "campaign_h1_line1": ("Stop guessing", "停止猜测"),
        "campaign_h1_line2": ("why content ", "为什么内容会"),
        "campaign_h1_em": ("spreads.", "爆红"),
        "campaign_h1_cta": ("Now you know.", "现在你知道了"),
        "campaign_hero_sub1": ("You're one score away", "一个分数就能"),
        "campaign_hero_sub2": (" from understanding any viral video, trend, or idea. ViralLab gives you the same framework Fortune 500 brands use — powered by Jonah Berger's peer-reviewed science — ", "让你读懂任何爆款视频、趋势或创意。ViralLab 给你 Fortune 500 品牌用的同一套框架 — 基于 Jonah Berger 的同行评审科学 — "),
        "campaign_hero_sub3": ("free, in seconds.", "免费，几秒搞定"),
        "campaign_cta_score": ("Score a video now", "立即评分视频"),
        "campaign_cta_trends": ("See today's trends", "看今日热门"),
        "campaign_proof_books": ("Based on 4 NYT bestsellers", "基于 4 本纽约时报畅销书"),
        "campaign_proof_studies": ("80+ peer-reviewed studies", "80+ 篇同行评审研究"),
        "campaign_proof_brands": ("Used by Apple, Google, Nike", "Apple、Google、Nike 都在用"),
        "campaign_proof_free": ("Free — no keys, no signup", "免费 — 无密钥、免注册"),
        "campaign_tag_story": ("The story behind this tool", "这个工具背后的故事"),
        "campaign_story_before": ("Before", "从前"),
        "campaign_story_before_h": ("You publish.<br>You hope.", "你发布。<br>你祈祷"),
        "campaign_story_before_b": ("You watch other creators blow up on the same topics you covered. You guess. You copy. You wonder why yours never lands the same way.", "你看着别人用同样的主题爆红。你猜。你模仿。你不懂为什么你的永远差一点。"),
        "campaign_story_disc": ("Discovery", "发现"),
        "campaign_story_disc_h": ("Virality isn't<br>luck. It's science.", "爆红不是<br>运气。是科学"),
        "campaign_story_disc_b": ("Professor Jonah Berger spent 30 years studying why people share things. His STEPPS framework reveals the exact psychological triggers behind every piece of content that spreads.", "Jonah Berger 教授花了 30 年研究人们为什么分享。他的 STEPPS 框架揭示了每则爆款内容背后的心理触发点。"),
        "campaign_story_now": ("Now", "现在"),
        "campaign_story_now_h": ("You create with<br>an unfair edge.", "你创作时<br>自带不公平优势"),
        "campaign_story_now_b": ("ViralLab scores any video or trend against all six STEPPS signals — and tells you exactly which lever to pull to make your content spread further.", "ViralLab 用六个 STEPPS 信号评分任何视频或趋势 — 并告诉你该拉哪根杆让内容传得更远。"),
        "campaign_tag_who": ("Who this is for", "适合谁用"),
        "campaign_who_h": ("You're already ahead.<br>This makes it obvious.", "你已经领先了。<br>这让它一目了然"),
        "campaign_who_desc": ("The creators who understand <em>why</em> content spreads — not just what's trending — are the ones building audiences that last. You're about to become one of them.", "懂<em>为什么</em>内容会爆 — 不只是什么在红 — 的创作者，才能建立持久的受众。你即将成为其中一员。"),
        "campaign_audience_yt": ("YouTubers & Video Creators", "YouTuber 与视频创作者"),
        "campaign_audience_yt_d": ("Score trending videos before you script yours. Know which Berger signals made them pop — then engineer those signals into your own content.", "在写脚本前先评分热门视频。知道哪些 Berger 信号让它们爆红 — 再把这些信号设计进你的内容。"),
        "campaign_audience_news": ("Newsletter & Blog Writers", "电子报与博客作者"),
        "campaign_audience_news_d": ("Discover what's spreading in your niche today. The Daily Digest surfaces the top 3 stories — with content angles you can write up in hours.", "发现你领域今天在传什么。每日精选呈现前 3 则话题 — 附带几小时内就能写出的内容角度。"),
        "campaign_audience_social": ("Social Media Managers", "社交媒体经理"),
        "campaign_audience_social_d": ("Stop presenting gut-feel content calendars. Walk into every brief with a Berger score and a clear explanation of <em>why</em> this trend is worth riding.", "别再拿感觉派内容日历简报。带着 Berger 评分和<em>为什么</em>值得跟风的清楚说明，走进每个 briefing。"),
        "campaign_audience_china": ("China-Market Creators", "中国市场创作者"),
        "campaign_audience_china_d": ("We pull from Bilibili, Douyin, and Xiaohongshu natively. Discover what's spreading in Chinese content — and score it with the same framework.", "我们原生支持 B站、抖音、小红书。发现中文内容在传什么 — 用同一套框架评分。"),
        "campaign_tag_how": ("How it solves your real problems", "如何解决你的真实痛点"),
        "campaign_how_h": ("Every time you sit down to create,<br>ViralLab has the answer.", "每次坐下来创作时，<br>ViralLab 都有答案"),
        "campaign_trigger": ("Every time you're stuck on what to post — open ViralLab first.", "每次卡在「不知道发什么」时 — 先打开 ViralLab"),
        "campaign_mech1_pain": ("I don't know what's trending right now", "我不知道现在什么在红"),
        "campaign_mech1_sol": ("Daily Digest — top 3 topics, refreshed daily", "每日精选 — 前 3 话题，每日更新"),
        "campaign_mech1_detail": ("Curated for your field. Fresh every morning.", "依你的领域精选。每天早晨新鲜出炉"),
        "campaign_mech1_cta": ("Open Daily →", "每日精选 →"),
        "campaign_mech2_pain": ("I don't know why that video went viral", "我不知道那支视频为什么爆红"),
        "campaign_mech2_sol": ("Berger Score — 6 signals, one number", "Berger 评分 — 6 信号，一个数字"),
        "campaign_mech2_detail": ("See exactly which STEPPS principles fired — and which didn't.", "清楚看到哪些 STEPPS 原则触发了 — 哪些没有"),
        "campaign_mech2_cta": ("Score a video →", "评分视频 →"),
        "campaign_mech3_pain": ("I want to repurpose this video into content", "我想把这支视频转成内容"),
        "campaign_mech3_sol": ("Video-to-Text — transcript + full Berger analysis", "视频转文字 — 逐字稿 + 完整 Berger 分析"),
        "campaign_mech3_detail": ("Paste a YouTube URL. Get transcript and score in seconds.", "贴上 YouTube 链接。几秒获取逐字稿与评分"),
        "campaign_mech3_cta": ("Try it →", "试试 →"),
        "campaign_mech4_pain": ("Generic trends don't apply to my niche", "通用趋势不适用我的领域"),
        "campaign_mech4_sol": ("Your Field — curated resources by creator niche", "你的领域 — 依创作者领域精选资源"),
        "campaign_mech4_detail": ("Fashion, tech, food, beauty, education, and more.", "时尚、科技、美食、美妆、教育等"),
        "campaign_mech4_cta": ("Pick your field →", "选择领域 →"),
        "campaign_mech5_pain": ("I need more source variety, not just YouTube", "我需要更多来源，不只 YouTube"),
        "campaign_mech5_sol": ("News Search — DuckDuckGo + Bilibili, no API key", "新闻搜索 — DuckDuckGo + B站，无需 API 密钥"),
        "campaign_mech5_detail": ("Search any topic. Global and China sources covered.", "搜索任一主题。全球与中国来源皆涵盖"),
        "campaign_mech5_cta": ("Search now →", "立即搜索 →"),
        "campaign_tag_score": ("What a Berger score looks like", "Berger 评分长这样"),
        "campaign_score_h": ("Not a black box. A breakdown.", "不是黑盒。是拆解"),
        "campaign_score_label": ("/100 · Strong Signal", "/100 · 强信号"),
        "campaign_score_title": ("Strong Emotion + Social Currency. Weak on Triggers.", "强情绪 + 强社交货币。触发弱"),
        "campaign_score_body": ("This video scored high because it opens with a surprising claim (Social Currency) and builds genuine excitement (Emotion). It loses points on Triggers — there's no recurring context that would make viewers think of it again naturally.", "这支视频高分因为开场有惊人主张（社交货币）并营造真实兴奋感（情绪）。触发失分 — 没有让观众自然想起的 recurring 情境。"),
        "campaign_score_fix": ("Fix →", "修正 →"),
        "campaign_score_fix_detail": ("Add one line anchoring this to a recurring moment: ", "加一句把这个锚定到 recurring 情境："),
        "campaign_score_fix_example": ("\"Every time you open your feed and see this type of content…\"", "「每次打开动态看到这类内容时…」"),
        "campaign_cred_tag": ("The science behind the score", "评分背后的科学"),
        "campaign_cred_quote": ("\"The key question isn't 'how do I make something go viral?' — it's 'why do people talk and share things in the first place?'\"", "「关键问题不是『怎么让东西爆红？』— 而是『人们为什么会谈论和分享？』」"),
        "campaign_cred_byline": ("— Jonah Berger, Wharton School Professor &amp; author of <em>Contagious</em>", "— Jonah Berger，沃顿商学院教授、《疯潮行销》作者"),
        "campaign_cred_books": ("NYT Bestselling books", "纽约时报畅销书"),
        "campaign_cred_studies": ("Peer-reviewed studies", "同行评审研究"),
        "campaign_cred_tenure": ("Wharton research tenure", "沃顿研究资历"),
        "campaign_cred_f500": ("Apple · Google · Nike · Gates", "Apple · Google · Nike · Gates"),
        "campaign_tag_steps": ("Get started in 3 easy steps", "3 步骤轻松开始"),
        "campaign_steps_h": ("Your first score in under 2 minutes.", "2 分钟内搞定第一个评分"),
        "campaign_steps_desc": ("No account. No API key. Just paste and discover.", "免账号。免 API 密钥。贴上就能发现"),
        "campaign_step1_title": ("Pick your field", "选择你的领域"),
        "campaign_step1_body": ("Tell ViralLab your niche — tech, fashion, food, education, or more. Every result, trend, and score gets calibrated to your audience.", "告诉 ViralLab 你的领域 — 科技、时尚、美食、教育等。每个结果、趋势、评分都会依你的受众调整。"),
        "campaign_step1_time": ("⏱ 30 seconds", "⏱ 30 秒"),
        "campaign_step2_title": ("Find what's spreading", "发现正在传播的"),
        "campaign_step2_body": ("Open Daily Digest for today's top 3 topics, or search any trend in News or Viral. See what's gaining traction right now.", "打开每日精选看今日前 3 话题，或在新闻或热门搜索任一趋势。看看现在什么在涨。"),
        "campaign_step2_time": ("⏱ 60 seconds", "⏱ 60 秒"),
        "campaign_step3_title": ("Score it & act", "评分并行动"),
        "campaign_step3_body": ("Paste a YouTube URL into Video-to-Text. Get a full Berger score, the STEPPS breakdown, and one concrete fix to make your version spread further.", "把 YouTube 链接贴到视频转文字。获取完整 Berger 评分、STEPPS 拆解，以及一个具体修正让你的版本传得更远。"),
        "campaign_step3_time": ("⏱ 10 seconds", "⏱ 10 秒"),
        "campaign_cta_h": ("Your next viral piece of content<br>starts with a <em>score.</em>", "你的下一则爆款内容<br>从一个<em>评分</em>开始"),
        "campaign_cta_sub": ("Free. No signup. No API keys. Just paste a YouTube URL and discover exactly why content spreads — and how to engineer it into yours.", "免费。免注册。免 API 密钥。贴上 YouTube 链接就能发现内容为什么会爆 — 以及如何把它设计进你的"),
        "campaign_cta_btn": ("Score your first video — free →", "免费评分你的第一支视频 →"),
        "campaign_cta_nudge": ("or <a href='/daily' style='color:rgba(255,255,255,0.5); text-decoration:underline;'>browse today's trending topics</a>", "或 <a href='/daily' style='color:rgba(255,255,255,0.5); text-decoration:underline;'>浏览今日热门话题</a>"),
        "campaign_tag_social": ("Join the conversation", "加入讨论"),
        "campaign_social_h": ("Creators using ViralLab<br>don't create alone.", "用 ViralLab 的创作者<br>不孤单创作"),
        "campaign_social_desc": ("Follow for weekly breakdowns of viral content, new feature drops, and a community of creators who think before they post.", "追踪每周爆款拆解、新功能预告，以及会先想再发的创作者社群"),
        "campaign_social_tg_name": ("ViralLab Community", "ViralLab 社群"),
        "campaign_social_tg_promise": ("Weekly STEPPS breakdowns. Early feature drops. Creator tips. This is where the conversation lives.", "每周 STEPPS 拆解、新功能抢先、创作者技巧。讨论都在这里"),
        "campaign_social_tg_join": ("Join group →", "加入群组 →"),
        "campaign_social_x_name": ("X / Twitter", "X / Twitter"),
        "campaign_social_x_promise": ("Daily observations on what's spreading and why. The shorter version of the science.", "每日观察什么在传、为什么。科学的简短版"),
        "campaign_social_x_join": ("Follow →", "追踪 →"),
        "campaign_social_blog_name": ("The Blog", "博客"),
        "campaign_social_blog_promise": ("Long-form breakdowns of viral campaigns, Berger deep-dives, and creator case studies.", "爆款案例长文拆解、Berger 深度解析、创作者个案研究"),
        "campaign_social_blog_join": ("Read →", "阅读 →"),
        "campaign_social_dm_name": ("Direct Channel", "直达频道"),
        "campaign_social_dm_promise": ("Personal updates, behind-the-scenes on ViralLab's development, and direct access.", "个人动态、ViralLab 开发幕后、直达联系"),
        "campaign_social_dm_join": ("Follow →", "追踪 →"),
        "campaign_title": ("Engineer Your Influence", "打造你的影响力"),
        # Campaign v2 (simplified landing)
        "camp2_greeting": ("Hey, welcome to ViralLab", "嗨，欢迎来到 ViralLab"),
        "camp2_h1": ("A tool for understanding why content spreads.", "帮你理解内容为什么会传播的工具"),
        "camp2_p": ("You paste a video or search a topic — we tell you <strong>which psychological triggers</strong> are making it travel. Not a black box. A real breakdown you can actually use.", "你粘贴视频或搜索话题 — 我们告诉你<strong>哪些心理触发点</strong>让它传播。不是黑盒。是你可以真正使用的拆解。"),
        "camp2_btn_primary": ("Try it with a video →", "用视频试试 →"),
        "camp2_btn_ghost": ("See today's trends", "看今日趋势"),
        "camp2_whats_in": ("What's in here", "这里有什么"),
        "camp2_tool_daily": ("Daily News", "每日精选"),
        "camp2_tool_daily_desc": ("Top 3 topics spreading today, curated for your field.", "今日传播中的前 3 话题，按你的领域精选"),
        "camp2_tool_viral": ("Viral Videos", "热播视频"),
        "camp2_tool_viral_desc": ("Search YouTube & Bilibili. See scores for each video.", "搜索 YouTube 和 B站。查看每支视频的评分"),
        "camp2_tool_v2t": ("Video to Text", "视频转文字"),
        "camp2_tool_v2t_desc": ("Paste a URL, get the transcript + a full score breakdown.", "粘贴链接，获取逐字稿 + 完整评分拆解"),
        "camp2_tool_field": ("Your Field", "你的领域"),
        "camp2_tool_field_desc": ("Resources and trends filtered to your niche.", "按你的领域筛选的资源和趋势"),
        "camp2_tool_news": ("News by Topic", "按话题搜索新闻"),
        "camp2_tool_news_desc": ("Search any topic. Global and China sources.", "搜索任意话题。全球和中国来源"),
        "camp2_how": ("How the score works", "评分如何运作"),
        "camp2_step1": ("You give it a video or some text.", "你提供视频或文本"),
        "camp2_step2": ("It checks for six things that research shows make people share: <strong>social currency, triggers, emotion, visibility, usefulness, and story.</strong>", "它会检查六个研究证明会让人们分享的因素：<strong>社交货币、触发点、情绪、可见性、有用性、故事。</strong>"),
        "camp2_step3": ("You get a score, a breakdown of what's strong, what's weak, and a one-line suggestion for the easiest fix.", "你会得到评分、强弱项的拆解，以及一条最易改进的建议"),
        "camp2_science": ("The scoring is based on <strong>Jonah Berger's STEPPS framework</strong> — a model built from years of research into why people share things. It's not the only way to think about virality, but it's one of the most grounded ones out there.", "评分基于 Jonah Berger 的 STEPPS 框架 — 多年研究人们为何分享的模型。它不是思考爆款的唯一方式，却是最 grounded 的之一。"),
        "camp2_science_link": ("Learn more →", "了解更多 →"),
        "camp2_community": ("Stay in the loop", "保持联系"),
        "camp2_community_p": ("If you find this useful, come say hi. There's a Telegram group where we share breakdowns and new features as they ship.", "如果觉得有用，来打个招呼。有个 Telegram 群组，我们会在那里分享拆解和新功能。"),
        "camp2_comm_tg": ("Telegram group", "Telegram 群组"),
        "camp2_comm_x": ("𝕏 @miccakitt", "𝕏 @miccakitt"),
        "camp2_comm_blog": ("Blog", "博客"),
        "camp2_comm_direct": ("Direct updates", "直达更新"),
        "camp2_footer": ("No signup, no API key needed. Just open a tool and use it.", "无需注册，无需 API 密钥。打开工具就能用。"),
        "camp2_footer_built": ("Built by", "由"),
        "camp2_footer_welcome": ("— feedback always welcome.", "— 欢迎反馈"),
        # Science page (STEPPS)
        "science_hero_h2": ("Not guesswork—<em>peer-reviewed</em> virality.", "非猜测 — <em>同行评审</em> 的爆款科学"),
        "science_hero_tagline": ("Every ViralLab score runs on Jonah Berger's STEPPS framework — 30 years of behavioral research condensed into a single, auditable algorithm. The same science Fortune 500 brands use to engineer word-of-mouth, now for your content.", "每个 ViralLab 评分都基于 Jonah Berger 的 STEPPS 框架 — 30 年行为研究浓缩成一套可稽核的算法。Fortune 500 品牌用来设计口碑的科学，现在为你的内容服务"),
        "science_hero_cta": ("See how we score", "看我们如何评分"),
        "science_proof_4": ("NYT bestsellers on contagiousness", "纽约时报畅销书：传播学"),
        "science_proof_4_sub": ("Verified", "已验证"),
        "science_proof_80": ("Peer-reviewed studies underpinning the model", "同行评审研究支撑模型"),
        "science_proof_80_sub": ("Academic citations", "学术引用"),
        "science_proof_30yr": ("Of word-of-mouth research at Wharton", "沃顿商学院口碑研究资历"),
        "science_proof_30yr_sub": ("Research tenure", "研究资历"),
        "science_proof_f500": ("Brands including Apple, Google & Nike", "Apple、Google、Nike 等品牌"),
        "science_proof_f500_sub": ("Applied clients", "应用客户"),
        "science_proof_cta": ("See it in action →", "看实际评分 →"),
        "science_berger_name": ("Jonah Berger · Professor, Wharton School", "Jonah Berger · 沃顿商学院教授"),
        "science_berger_quote": ("\"The key question isn't 'how do I make something go viral?' — it's 'why do people talk and share things in the first place?'\"", "「关键问题不是『怎么让东西爆红？』— 而是『人们为什么会谈论和分享？』」"),
        "science_cred_1": ("4 New York Times bestselling books", "4 本纽约时报畅销书"),
        "science_cred_2": ("Wharton School Professor since 1996", "1996 年起任沃顿商学院教授"),
        "science_cred_3": ("80+ peer-reviewed studies published", "80+ 篇同行评审研究"),
        "science_cred_4": ("Consulted for Apple, Google, Nike, Gates Foundation", "为 Apple、Google、Nike、盖兹基金会提供顾问"),
        "science_cred_5": ("Cited 10,000+ times in academic literature", "学术文献引用 10,000+ 次"),
        "science_why_holds": ("Why Berger's work holds up", "Berger 的研究为何站得住脚"),
        "science_why_holds_desc": ("Most viral frameworks are post-hoc pattern matching. Berger's work starts with <em>why humans share</em>, then derives patterns from behavioral science and controlled experiments.", "多数爆款框架是事后归纳。Berger 从<em>人类为什么分享</em>出发，再从行为科学与对照实验推导模式"),
        "science_4keys_title": ("The 4 Keys to Viral Content", "爆款内容的 4 把钥匙"),
        "science_4keys_desc": ("Each book unlocks a different lever. ViralLab applies all of them to your content.", "每本书解锁不同杠杆。ViralLab 将它们全部应用于你的内容"),
        "science_stepps_title": ("STEPPS — What We Look For", "STEPPS — 我们看什么"),
        "science_stepps_desc": ("Hover each principle to see the behavioral question our algorithm answers.", "悬停每个原则查看我们算法回答的行为问题"),
        "science_keywords": ("Keywords", "关键字"),
        "science_how_score_h": ("How We Score", "我们如何评分"),
        "science_how_score_p": ("We scan content for <strong>STEPPS</strong> (Social Currency, Triggers, Emotion, Public, Practical, Stories) and <strong>Magic Words</strong>—the language that research shows boosts sharing. We also score <strong>hook strength</strong> (first 15 words: question, stat, surprising claim, conflict) and <strong>narrative arc</strong> (setup→conflict→resolution). Content with 3+ STEPPS principles gets a bonus. Transparent formula, no black box.", "我们扫描内容的 <strong>STEPPS</strong>（社交货币、触发、情绪、公开、实用、故事）与 <strong>Magic Words</strong>—研究证实能提升分享的语言。我们也评分<strong>开场强度</strong>（前 15 字：问句、数据、惊人主张、冲突）与<strong>叙事弧</strong>（铺陈→冲突→解决）。含 3+ STEPPS 原则的内容有加分。透明公式，非黑盒"),
        "science_formula": ("STEPPS: up to 20 pts per principle. Magic words: +5 pts each. Hook: up to 15 pts. Narrative arc: +10 pts. 3+ principles: +10 pts. Total capped at 100.", "STEPPS：每原则最高 20 分。Magic Words：每个 +5 分。开场：最高 15 分。叙事弧：+10 分。3+ 原则：+10 分。总分上限 100"),
        "science_lab_title": ("From Berger's lab to your score", "从 Berger 实验室到你的评分"),
        "science_lab_desc": ("We don't match keywords. We detect the underlying behavioral patterns Berger's research proved actually drive sharing.", "我们不匹配关键字。我们侦测 Berger 研究证实真正驱动分享的行为模式"),
        "science_magic_title": ("Magic Words", "Magic Words"),
        "science_magic_desc": ("Words that boost engagement", "提升参与的词汇"),
        "science_trust_h": ("The same framework Fortune 500 brands use. <em>Now for your content.</em>", "Fortune 500 品牌用的同一套框架。<em>现在为你的内容服务。</em>"),
        "science_trust_sub": ("Thirty years of peer-reviewed research. One transparent score. Know exactly why your content spreads — or doesn't.", "30 年同行评审研究。一个透明评分。清楚知道你的内容为什么会爆 — 或不会"),
        "science_cta_score": ("Score your content →", "评分你的内容 →"),
        "science_cta_book": ("Read Contagious by Berger", "阅读 Berger《疯潮行销》"),
        "science_translate_1_t": ("Signal, not syntax", "信号，非语法"),
        "science_translate_1_b": ("Emotion is scored by pacing, narrative tension, and vocal dynamics — not the word 'amazing'. Social Currency is detected by insight density and identity framing — not the word 'exclusive'.", "情绪由节奏、叙事张力、语调评分 — 非『amazing』一字。社交货币由洞察密度与身份框架侦测 — 非『exclusive』一字"),
        "science_translate_2_t": ("Hook scored separately", "开场独立评分"),
        "science_translate_2_b": ("The first 5 seconds are the single highest predictor of shareability. We score your hook independently before aggregating the full signal.", "前 5 秒是分享率的最强预测。我们在汇总前独立评分你的开场"),
        "science_translate_3_t": ("Transparent, not black-box", "透明，非黑盒"),
        "science_translate_3_b": ("Every score breaks down by principle. You see exactly which STEPPS signals fired, which were weak, and what to change. No mysterious confidence scores.", "每个评分都按原则拆解。你清楚看到哪些 STEPPS 信号触发、哪些弱、该改什么。没有神秘信心分数"),
        "science_translate_4_t": ("Platform-calibrated weights", "平台校准权重"),
        "science_translate_4_b": ("Emotion matters more on TikTok. Practical Value matters more on YouTube tutorials. Weights adjust to the platform context of your content.", "情绪在 TikTok 较重要。实用价值在 YouTube 教学较重要。权重依平台情境调整"),
        # Science v2 (How we score)
        "science_v2_title": ("📊 How we score", "📊 我们如何评分"),
        "science_v2_page_title": ("How We Score", "我们如何评分"),
        "science_v2_intro1": ("A while back I came across <strong>Jonah Berger's research</strong> on why people share things. It's not about luck or timing — he spent years studying the actual patterns, and the findings are pretty consistent. I found it useful enough that I built this tool around it.", "之前我接触到 <strong>Jonah Berger 的研究</strong>，关于人们为什么分享。不是运气或时机 — 他花多年研究真实模式，结论相当一致。我觉得很有用，所以围绕它做了这个工具。"),
        "science_v2_intro2": ("The scoring isn't perfect. It's based on text signals, not the full picture of a video. But it gives you a structured way to think about <em>why</em> something might spread — which is more useful than just watching view counts.", "评分不完美。它基于文字信号，不是视频全貌。但它给你一个结构化方式思考<em>为什么</em>内容可能传播 — 比只看播放量更有用。"),
        "science_v2_who_berger": ("Who is Jonah Berger", "Jonah Berger 是谁"),
        "science_v2_berger_name": ("Jonah Berger", "Jonah Berger"),
        "science_v2_berger_role": ("Marketing professor at Wharton, University of Pennsylvania", "宾夕法尼亚大学沃顿商学院营销学教授"),
        "science_v2_berger_f1": ("Author of <em>Contagious</em>, <em>Invisible Influence</em>, <em>The Catalyst</em>, and <em>Magic Words</em> — all NYT bestsellers", "著有《疯潮行销》《隐形影响力》《催化剂》《魔法词汇》— 均为纽约时报畅销书"),
        "science_v2_berger_f2": ("His work is backed by 80+ peer-reviewed studies — not just observations or case studies", "他的研究由 80+ 篇同行评审支撑 — 不只是观察或个案"),
        "science_v2_berger_f3": ("Has consulted for Google, Apple, Nike, and the Gates Foundation, among others", "曾为 Google、Apple、Nike、盖兹基金会等提供顾问"),
        "science_v2_berger_f4": ("His research has been cited over 10,000 times in academic literature", "其研究在学术文献中被引用超过 10,000 次"),
        "science_v2_berger_p": ("What I like about his work is that it starts from a real question — <em>\"why do people share things?\"</em> — and builds up from controlled experiments, not from reverse-engineering what went viral after the fact. That makes it more reliable as a framework than most alternatives.", "我喜欢他的研究从真实问题出发 — <em>「人们为什么分享？」</em> — 从对照实验推导，而非事后反推爆款。这使它比多数替代框架更可靠。"),
        "science_v2_stepps_title": ("The six signals we score (STEPPS)", "我们评分的六个信号 (STEPPS)"),
        "science_v2_stepps_intro": ("Berger identified six things that consistently make content more shareable:", "Berger 发现六个让内容更易分享的因素："),
        "science_v2_stepps_S_name": ("Social Currency", "社交货币"),
        "science_v2_stepps_S_desc": ("People share things that make them look good or knowledgeable. Content that feels exclusive or insightful gets passed on.", "人们分享让自己显得有见识的内容。感觉独家或洞察力强的会被转发。"),
        "science_v2_stepps_T_name": ("Triggers", "触发"),
        "science_v2_stepps_T_desc": ("Things that link to everyday moments get recalled naturally. \"Every time I see X, I think of Y.\"", "与日常时刻连结的内容会被自然想起。「每次看到 X，我就想到 Y。」"),
        "science_v2_stepps_E_name": ("Emotion", "情绪"),
        "science_v2_stepps_E_desc": ("High-arousal emotions — awe, excitement, anger — drive sharing. Low-arousal ones (contentment, sadness) don't as much.", "高唤醒情绪 — 敬畏、兴奋、愤怒 — 驱动分享。低唤醒（满足、悲伤）较少。"),
        "science_v2_stepps_P1_name": ("Public", "公开"),
        "science_v2_stepps_P1_desc": ("Visible things get copied. If people can see others doing or sharing something, they're more likely to do it too.", "可见的事物会被模仿。若人们看到别人在做或分享，更可能跟进。"),
        "science_v2_stepps_P2_name": ("Practical Value", "实用价值"),
        "science_v2_stepps_P2_desc": ("Useful content gets shared because people want to help others. \"You have to see this tip.\"", "实用内容被分享因为人们想帮助他人。「你一定要看这个技巧。」"),
        "science_v2_stepps_S2_name": ("Stories", "故事"),
        "science_v2_stepps_S2_desc": ("Information travels better inside a story. People retell narratives, not facts.", "信息在故事里传播更好。人们复述的是叙事，不是事实。"),
        "science_v2_formula_title": ("How the number is calculated", "分数如何计算"),
        "science_v2_formula_intro": ("We scan the transcript for signals in each category and add up the points:", "我们扫描逐字稿中各类别信号并累加分数："),
        "science_v2_formula_r1": ("<strong>Each STEPPS signal</strong> — keywords, framing, structure", "<strong>每个 STEPPS 信号</strong> — 关键词、框架、结构"),
        "science_v2_formula_r2": ("<strong>Magic words</strong> — language shown to boost engagement", "<strong>Magic words</strong> — 研究证实提升参与的语言"),
        "science_v2_formula_r3": ("<strong>Hook strength</strong> — first 15 words: question, stat, surprise", "<strong>开场强度</strong> — 前 15 字：问句、数据、惊喜"),
        "science_v2_formula_r4": ("<strong>Narrative arc</strong> — setup → conflict → resolution", "<strong>叙事弧</strong> — 铺陈 → 冲突 → 解决"),
        "science_v2_formula_r5": ("<strong>3+ signals active</strong> — content hits multiple principles", "<strong>3+ 信号激活</strong> — 内容触及多个原则"),
        "science_v2_formula_r6": ("<strong>Total</strong>", "<strong>总分</strong>"),
        "science_v2_formula_pts1": ("up to 20 pts", "最高 20 分"),
        "science_v2_formula_pts2": ("+5 pts each", "每个 +5 分"),
        "science_v2_formula_pts3": ("up to 15 pts", "最高 15 分"),
        "science_v2_formula_pts4": ("+10 pts", "+10 分"),
        "science_v2_formula_pts5": ("+10 pts", "+10 分"),
        "science_v2_formula_pts6": ("capped at 100", "上限 100"),
        "science_v2_honest": ("<strong>A note on accuracy:</strong> This score is based on text analysis — keywords, structure, and framing. It doesn't account for delivery, visuals, timing, or luck, which all matter. Think of it as one useful lens, not a definitive verdict. A low score doesn't mean the content is bad. A high score doesn't guarantee it spreads.", "<strong>关于准确性：</strong>此评分基于文字分析 — 关键词、结构、框架。未考虑表达、画面、时机或运气，这些都很重要。把它当作一个有用视角，非最终定论。低分不代表内容差。高分也不保证会传播。"),
        "science_v2_link_score": ("Score a video →", "评分视频 →"),
        "science_v2_link_transcript": ("Transcript + score", "逐字稿 + 评分"),
    }
    en, zh = T.get(key, (key, key))
    return zh if lang == "zh" else en


def _lifecycle_tooltip_html(lang: str, life: str) -> str:
    """Tooltip content for one lifecycle: show only the definition for that rank."""
    key = f"tooltip_{life}" if life in ("rising", "peaking", "fading") else "tooltip_peaking"
    return _html_escape(_t(key, lang))


# Function cards for Features dropdown (Buffer-style)
FUNCTION_CARDS = [
    {"href": "/daily", "icon": "📅", "title": "Daily News", "desc": "Top 3 most talked about topics today"},
    {"href": "/#field", "icon": "🎯", "title": "Your Field", "desc": "Curated trends and resources by your industry"},
    {"href": "/#viral", "icon": "▶️", "title": "Viral YouTube", "desc": "Search viral videos ranked by spread rate"},
    {"href": "/video-to-text", "icon": "📝", "title": "Video to Text", "desc": "Paste URL → transcript + Berger score"},
    {"href": "/science", "icon": "📊", "title": "STEPPS & Magic Words", "desc": "How we score content with behavioral science"},
    {"href": "/api/digests", "icon": "🔌", "title": "API", "desc": "Access digests and data programmatically"},
]


def _sidebar_html(active="", lang="en"):
    """Aegis-style sidebar navigation. lang: en or zh for toggle."""
    nav_items = [
        ("/", "🏠", "nav_home", "nav_home_desc"),
        ("/daily", "📅", "nav_daily", "nav_daily_desc"),
        ("/field", "🎯", "nav_field", "nav_field_desc"),
        ("/news", "📰", "nav_news", "nav_news_desc"),
        ("/viral", "▶️", "nav_viral", "nav_viral_desc"),
        ("/video-to-text", "📝", "nav_video2text", "nav_video2text_desc"),
        ("/science", "📊", "nav_science", "nav_science_desc"),
    ]
    links = ""
    for href, icon, title_key, desc_key in nav_items:
        title, desc = _t(title_key, lang), _t(desc_key, lang)
        is_active = " active" if active == href else ""
        links += f'<a href="{href}" class="sidebar-link{is_active}"><span class="sidebar-icon">{icon}</span><span class="sidebar-text"><strong>{_html_escape(title)}</strong><small>{_html_escape(desc)}</small></span></a>'
    next_path = request.path or "/"
    toggle_label = "EN" if lang == "zh" else "中文"
    toggle_lang = "en" if lang == "zh" else "zh"
    toggle_href = f"/set-lang?lang={toggle_lang}&next={_html_escape(next_path)}"
    subtitle = _t("hero_subtitle", lang)
    return f'''<aside class="sidebar">
        <a href="/" class="sidebar-brand">
            <span class="logo-avatar"><img src="/static/logo-avatar.png" alt=""></span>
            <span class="logo-text-wrap">
                <span class="logo-text">ViralLab</span>
                <span class="sidebar-subtitle">{_html_escape(subtitle)}</span>
            </span>
        </a>
        <nav class="sidebar-nav">{links}</nav>
        <div class="sidebar-footer">
            <a href="{toggle_href}" class="btn-lang" id="langToggle">{toggle_label} ▾</a>
        </div>
    </aside>'''


def _header_html(active="", lang="en"):
    """Compact top bar with logo, search and community links."""
    placeholder = _t("search_placeholder", lang)
    return f'''<header class="top-bar">
        <div class="header-search-wrap">
            <span class="search-icon">⌕</span>
            <input type="text" class="header-search" placeholder="{_html_escape(placeholder)}" id="headerSearch">
        </div>
        <div class="top-bar-links-wrap">
            <div class="top-bar-links">
                <a href="{TG_GROUP_URL}" target="_blank" rel="noopener">💬 {_html_escape(_t("camp2_comm_tg", lang))}</a>
                <a href="{X_URL}" target="_blank" rel="noopener">{_html_escape(_t("camp2_comm_x", lang))}</a>
                <a href="{BLOG_URL}" target="_blank" rel="noopener">📖 {_html_escape(_t("camp2_comm_blog", lang))}</a>
                <a href="{GITHUB_REPO_URL}" target="_blank" rel="noopener">✈️ {_html_escape(_t("camp2_comm_direct", lang))}</a>
            </div>
            <div class="top-bar-hover-card">{_html_escape(_t("camp2_community_p", lang))}</div>
        </div>
    </header>'''


def _hero_html(lang="en"):
    """Hero: left text, right thumbnail image."""
    greeting = _t("camp2_greeting", lang)
    line1 = _t("hero_line1", lang)
    line2 = _t("hero_line2", lang)
    subtitle = _t("hero_subtitle", lang)
    desc = _t("hero_desc", lang)
    cta = _t("hero_cta", lang)
    return f'''<section class="hero hero-bg">
        <div class="hero-left">
            <p class="hero-greeting">👋 {_html_escape(greeting)}</p>
            <h1 class="hero-headline"><span>{_html_escape(line1)}</span><span>{_html_escape(line2)}</span></h1>
            <p class="hero-subtitle">{_html_escape(subtitle)}</p>
            <p class="hero-desc">{_html_escape(desc)}</p>
            <a href="/daily" class="hero-cta">{_html_escape(cta)}</a>
        </div>
        <div class="hero-visual">
            <div class="hero-thumbnail-wrap">
                <img src="/static/hero-thumbnail.png" alt="ViralLab" class="hero-thumbnail">
            </div>
        </div>
    </section>'''


def _base(title, body, active="", hero="", lang=None, og_title=None, og_desc=None, og_image=None):
    lang = lang or _get_lang()
    base_url = request.host_url.rstrip("/")
    og_title = og_title or f"{title} — ViralLab"
    og_desc = og_desc or "Your content agent. Engineer your influence. Curated trends, daily news, and resources for content creators."
    og_image = og_image or f"{base_url}/static/og-image.png"
    canonical = request.url
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="icon" href="/static/favicon-32.png" type="image/png" sizes="32x32">
    <title>{_html_escape(title)} — ViralLab</title>
    <meta property="og:type" content="website">
    <meta property="og:title" content="{_html_escape(og_title)}">
    <meta property="og:description" content="{_html_escape(og_desc)}">
    <meta property="og:image" content="{_html_escape(og_image)}">
    <meta property="og:url" content="{_html_escape(canonical)}">
    <meta property="og:site_name" content="ViralLab">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{_html_escape(og_title)}">
    <meta name="twitter:description" content="{_html_escape(og_desc)}">
    <meta name="twitter:image" content="{_html_escape(og_image)}">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:ital,wght@0,300;0,400;0,500;0,600;0,700;0,800;0,900;1,300;1,400&display=swap" rel="stylesheet">
    <style>
        :root {{ --bg: #faf8f5; --card: #fff; --text: #2d4a2b; --muted: #5a6b58; --accent: #2d4a2b; --accent-hover: #1e3520; --border: #e8e4dc; --warm: #f5f2ed; --cta: #e8a54d; --cta-border: #2d4a2b; --cta-text: #2d4a2b; --header-height: 4.25rem; --footer-height: 80px; --accent-mid: #3d6b3a; --accent-light: #6a9e67; --cta-dark: #c8883a; --cta-pale: #fdf3dc; --cream-dark: #ede8de; --muted-light: #8fa88c; --ink: #1a2419; --radius: 4px; --shadow: 0 2px 12px rgba(45,74,43,0.08); --shadow-lg: 0 8px 32px rgba(45,74,43,0.13); }}
        * {{ box-sizing: border-box; }}
        html {{ scroll-behavior: smooth; }}
        :root {{ --ease: cubic-bezier(0.25, 0.1, 0.25, 1); --ease-out: cubic-bezier(0.33, 1, 0.68, 1); --dur: 0.25s; }}
        body {{ font-family: "Poppins", -apple-system, BlinkMacSystemFont, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 0; line-height: 1.55; }}
        body::before {{ content: ""; position: fixed; top: 0; left: 0; right: 0; height: 3px; background: var(--accent); z-index: 999; }}
        html[lang="zh"] .sidebar-subtitle, html[lang="zh"] .hero-subtitle, html[lang="zh"] .hero-desc, html[lang="zh"] .hero-cta, html[lang="zh"] .tagline, html[lang="zh"] .sidebar-text strong, html[lang="zh"] .sidebar-text small {{ letter-spacing: 0.12em; }}
        .app-layout {{ display: flex; min-height: 100vh; overflow-x: visible; }}
        .sidebar {{ width: 220px; flex-shrink: 0; background: var(--bg); border-right: 1px solid var(--border); padding: 0; position: sticky; top: 0; height: 100vh; overflow-y: auto; display: flex; flex-direction: column; }}
        .sidebar-brand {{ display: flex; align-items: center; gap: 0.5rem; padding: 0 1.25rem; height: var(--header-height); box-sizing: border-box; text-decoration: none; color: var(--text); border-bottom: 1px solid var(--border); margin-bottom: 1rem; }}
        .sidebar-brand:hover {{ color: var(--accent); }}
        .sidebar-nav {{ display: flex; flex-direction: column; gap: 0.25rem; flex: 1; min-height: 0; padding: 0.5rem 0; }}
        .sidebar-link {{ display: flex; align-items: flex-start; gap: 0.6rem; padding: 0.6rem 1.25rem; text-decoration: none; color: var(--muted); font-size: 0.9rem; transition: background var(--dur) var(--ease-out), color var(--dur) var(--ease-out); }}
        .sidebar-link:hover {{ background: var(--warm); color: var(--accent); }}
        .sidebar-link.active {{ background: var(--warm); color: var(--accent); font-weight: 500; }}
        .sidebar-icon {{ font-size: 1.1rem; flex-shrink: 0; }}
        .sidebar-text {{ display: flex; flex-direction: column; gap: 0.1rem; }}
        .sidebar-text strong {{ font-size: 0.9rem; color: inherit; }}
        .sidebar-text small {{ font-size: 0.75rem; opacity: 0.85; }}
        .sidebar-footer {{ margin-top: auto; height: var(--footer-height); padding: 0 1.25rem; border-top: 1px solid var(--border); display: flex; align-items: center; font-size: 0.85rem; flex-shrink: 0; box-sizing: border-box; }}
        .sidebar-footer a {{ color: var(--text); text-decoration: none; }}
        .sidebar-footer a:hover {{ color: var(--accent); }}
        .main-content {{ flex: 1; display: flex; flex-direction: column; min-width: 0; overflow-x: visible; padding: 0 2rem calc(2rem + var(--footer-height)) 2rem; max-width: 1100px; }}
        .top-bar {{ position: sticky; top: 0; z-index: 50; height: var(--header-height); padding: 0 2rem; margin-bottom: 1rem; margin-left: -2rem; margin-right: -2rem; background: var(--bg); overflow: visible; display: flex; align-items: center; justify-content: space-between; gap: 1.5rem; box-sizing: border-box; }}
        .top-bar-links-wrap {{ position: relative; margin-left: auto; }}
        .top-bar-links {{ display: flex; align-items: center; gap: 1rem; }}
        .top-bar-links a {{ color: var(--muted); text-decoration: none; font-size: 0.75rem; font-weight: 300; transition: color var(--dur) var(--ease-out); }}
        .top-bar-links a:hover {{ color: var(--accent); }}
        .top-bar-hover-card {{ position: absolute; top: 100%; right: 0; margin-top: 0.5rem; padding: 1rem 1.25rem; max-width: 240px; font-size: 0.6rem; font-weight: 400; line-height: 1.5; color: var(--card); background: var(--accent); border-radius: var(--radius); box-shadow: var(--shadow-lg); opacity: 0; pointer-events: none; transition: opacity var(--dur) var(--ease-out); z-index: 100; }}
        .top-bar-links-wrap:hover .top-bar-hover-card {{ opacity: 1; }}
        .top-bar::after {{ content: ""; position: absolute; left: 0; bottom: 0; width: calc(100vw - 220px); height: 1px; background: var(--border); pointer-events: none; }}
        .wrap {{ max-width: 1100px; margin: 0 auto; padding: 0 2rem 2rem; }}
        .page-header {{ margin-bottom: 2.5rem; position: relative; padding-top: 0.5rem; }}
        .page-header::before {{ content: ''; position: absolute; top: 0; left: 0; width: 48px; height: 3px; background: var(--cta); border-radius: 1px; }}
        h1 {{ font-size: 1.75rem; font-weight: 800; margin: 0 0 0.5rem 0; letter-spacing: -0.02em; line-height: 1.25; color: var(--ink); }}
        .tagline {{ color: var(--muted); font-size: 1rem; margin: 0; line-height: 1.6; font-weight: 400; max-width: 42ch; }}
        .stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.5rem; margin: 2.5rem 0; }}
        .stat {{ background: var(--card); padding: 1.25rem 1.5rem; border-radius: var(--radius); border: 1px solid var(--border); box-shadow: var(--shadow); text-align: left; transition: transform var(--dur) var(--ease-out), box-shadow var(--dur) var(--ease-out), border-color var(--dur) var(--ease-out); }}
        .stat:hover {{ transform: translateY(-2px); box-shadow: var(--shadow-lg); border-color: var(--accent-light); }}
        .stat-num {{ font-size: 1.75rem; font-weight: 700; color: var(--accent); letter-spacing: -0.02em; }}
        .stat-label {{ font-size: 0.8rem; color: var(--muted); margin-top: 0.25rem; }}
        section {{ margin-bottom: 3rem; }}
        section:first-of-type {{ margin-top: 0; }}
        .section-title {{ font-size: 1.5rem; font-weight: 800; color: var(--ink); letter-spacing: -0.01em; margin-bottom: 0.5rem; line-height: 1.3; }}
        .section-desc {{ font-size: 0.9375rem; color: var(--muted); margin-bottom: 1.25rem; max-width: 56ch; line-height: 1.6; }}
        .cards {{ display: grid; gap: 1.25rem; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); align-items: stretch; }}
        .card {{ background: var(--card); border-radius: var(--radius); padding: 1.25rem 1.5rem; border: 1px solid var(--border); box-shadow: var(--shadow); transition: transform var(--dur) var(--ease-out), box-shadow var(--dur) var(--ease-out), border-color var(--dur) var(--ease-out); display: flex; flex-direction: column; gap: 0.5rem; min-height: 100%; overflow: visible; }}
        .card:hover {{ transform: translateY(-2px); box-shadow: var(--shadow-lg); border-color: var(--accent-light); }}
        .card h3 {{ font-size: 1.05rem; font-weight: 600; margin: 0; line-height: 1.45; color: var(--text); letter-spacing: -0.01em; flex: 1; min-width: 0; word-break: break-word; }}
        .card h3 a {{ color: inherit; text-decoration: none; }}
        .card h3 a:hover {{ color: var(--accent); }}
        .card p {{ font-size: 0.9rem; color: var(--muted); margin: 0; font-weight: 400; line-height: 1.55; }}
        .card-snippet {{ font-size: 0.9rem; color: var(--muted); line-height: 1.55; margin: 0; word-break: break-word; overflow-wrap: break-word; display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; flex: 1; min-height: 0; }}
        .card-source {{ font-size: 0.68rem; color: var(--muted); opacity: 0.75; margin: 0; }}
        .card-header {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 0.75rem; overflow: visible; }}
        .card-header h3 {{ flex: 1; min-width: 0; }}
        .card-header .badges {{ flex-shrink: 0; }}
        .berger {{ font-size: 0.75rem; font-weight: 700; padding: 0.25rem 0.6rem; border-radius: var(--radius); white-space: nowrap; }}
        .berger-high {{ background: rgba(45,74,43,0.2); color: var(--accent); }}
        .berger-mid {{ background: rgba(232,165,77,0.35); color: var(--cta-text); }}
        .berger-low {{ background: rgba(45,74,43,0.1); color: var(--muted); }}
        .meta {{ font-size: 0.78rem !important; color: var(--muted); opacity: 0.9; }}
        .card-error {{ border-left: 4px solid #dc2626; }}
        .muted {{ color: var(--muted); font-size: 0.9rem; line-height: 1.55; }}
        .content-meta {{ display: flex; flex-direction: column; gap: 0.35rem; margin-bottom: 1.25rem; }}
        .content-meta .sources-label {{ margin: 0; }}
        .sources-label {{ color: var(--muted); font-size: 0.8rem; font-weight: 400; line-height: 1.5; opacity: 0.92; }}
        .sources-label a {{ color: var(--text); text-decoration: none; }}
        .sources-label a:hover {{ color: var(--accent); }}
        .browse-more {{ color: var(--muted); font-size: 0.85rem; font-weight: 400; margin: 1.75rem 0 1rem 0; opacity: 0.92; line-height: 1.5; }}
        .browse-more a {{ color: var(--text); text-decoration: none; }}
        .browse-more a:hover {{ color: var(--accent); }}
        .refresh-link {{ color: var(--muted) !important; text-decoration: none !important; }}
        .refresh-link:hover {{ color: var(--accent) !important; }}
        .tip-range-wrap .refresh-link {{ color: var(--muted) !important; text-decoration: none !important; }}
        .content-meta a {{ color: var(--muted) !important; text-decoration: none !important; }}
        .content-meta a:hover {{ color: var(--accent) !important; }}
        .browse-more a:hover {{ color: var(--accent-hover); }}
        .digest-cards {{ display: flex; flex-direction: column; gap: 1.5rem; margin-top: 1.75rem; }}
        .digest-card.load-more-hidden {{ display: none; }}
        .btn-load-more {{ display: block; margin: 2rem auto; padding: 0.75rem 2rem; border: 1px solid var(--border); border-radius: var(--radius); background: var(--card); color: var(--text); font-size: 0.9375rem; font-weight: 600; cursor: pointer; font-family: inherit; transition: border-color var(--dur), color var(--dur); }}
        .btn-load-more:hover {{ border-color: var(--accent); color: var(--accent); }}
        .digest-card {{ background: var(--card); border-radius: var(--radius); padding: 1.25rem 1.5rem; border: 1px solid var(--border); box-shadow: var(--shadow); transition: transform var(--dur) var(--ease-out), box-shadow var(--dur) var(--ease-out), border-color var(--dur) var(--ease-out); overflow: visible; }}
        .digest-card:hover {{ transform: translateY(-2px); box-shadow: var(--shadow-lg); border-color: var(--accent-light); }}
        .digest-card-header {{ display: flex; align-items: flex-start; gap: 0.75rem; margin-bottom: 0.6rem; overflow: visible; }}
        .digest-card-num {{ font-size: 0.85rem; font-weight: 700; color: var(--accent); min-width: 1.75rem; opacity: 0.9; }}
        .digest-card-title {{ flex: 1; font-size: 1.05rem; font-weight: 600; margin: 0; line-height: 1.45; color: var(--text); letter-spacing: -0.01em; }}
        .digest-card-title a {{ color: inherit; text-decoration: none; }}
        .digest-card-title a:hover {{ color: var(--accent); }}
        .digest-card-snippet {{ font-size: 0.9rem; color: var(--muted); margin: 0 0 0.5rem 0; line-height: 1.6; font-weight: 400; }}
        .digest-card-source {{ font-size: 0.68rem; color: var(--muted); opacity: 0.75; margin: 0.15rem 0 0.85rem 0; }}
        .digest-card-pills {{ display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.25rem; }}
        .pill-tag {{ font-size: 0.72rem; padding: 0.28rem 0.65rem; border-radius: 999px; background: rgba(45,74,43,0.08); color: var(--muted); font-weight: 500; letter-spacing: 0.02em; }}
        .digest-top-section {{ margin-bottom: 0.5rem; display: flex; flex-direction: column; gap: 0.5rem; align-items: flex-start; }}
        .digest-top-section .browse-more {{ margin: 0; }}
        code {{ background: var(--warm); padding: 0.2rem 0.5rem; border-radius: 6px; font-size: 0.85em; color: var(--text); }}
        footer {{ position: fixed; bottom: 0; left: 220px; right: 0; height: var(--footer-height); padding: 0 2rem; font-size: 0.8rem; color: var(--muted); background: var(--bg); z-index: 50; box-sizing: border-box; display: flex; flex-direction: column; justify-content: center; border-top: 1px solid var(--border); }}
        footer a {{ color: var(--accent); text-decoration: none; }}
        footer a:hover {{ text-decoration: underline; }}
        .spread {{ font-size: 0.75rem; margin-bottom: 0.35rem; }}
        .form {{ display: flex; gap: 0.5rem; margin-bottom: 1.25rem; max-width: 560px; flex-wrap: wrap; align-items: center; }}
        .form input {{ flex: 1; padding: 0.75rem 1rem; border-radius: var(--radius); border: 1.5px solid var(--border); background: var(--bg); color: var(--text); font-size: 0.9375rem; font-family: inherit; transition: border-color var(--dur) var(--ease-out); }}
        .tip-card {{ background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 1.25rem 1.5rem; margin-bottom: 1.25rem; box-shadow: var(--shadow); transition: border-color var(--dur) var(--ease-out); }}
        .tip-card:hover {{ border-color: var(--accent-light); }}
        .tip-header {{ display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 0.75rem; margin-bottom: 0.5rem; }}
        .tip-label {{ font-size: 0.625rem; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.12em; }}
        .tip-range-wrap {{ display: flex; gap: 0.5rem; font-size: 0.8rem; }}
        .tip-range {{ color: var(--muted); text-decoration: none; padding: 0.2rem 0.5rem; border-radius: 4px; transition: color var(--dur), background var(--dur); }}
        .tip-range:hover {{ color: var(--accent); }}
        .tip-range.active {{ color: var(--accent); font-weight: 600; background: rgba(45,74,43,0.08); }}
        .viral-source-wrap {{ display: flex; align-items: center; gap: 0.4rem; }}
        .viral-source-label {{ font-size: 0.75rem; font-weight: 600; color: var(--muted); }}
        .viral-source-select {{ padding: 0.25rem 0.5rem; font-size: 0.8rem; }}
        .tip-chips {{ display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; }}
        .tip-chip-form {{ display: inline-flex; margin: 0; }}
        .tip-chip {{ padding: 0.4rem 0.75rem; border-radius: var(--radius); border: 1px solid var(--border); background: var(--card); color: var(--text); font-size: 0.8125rem; font-weight: 500; cursor: pointer; transition: background var(--dur), border-color var(--dur), color var(--dur); white-space: nowrap; user-select: none; -webkit-tap-highlight-color: transparent; }}
        .tip-chip:hover {{ background: var(--accent); border-color: var(--accent); color: white; }}
        .tip-chip-active {{ background: var(--accent); border-color: var(--accent); color: white; }}
        .topic-label {{ font-size: 0.625rem; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.12em; margin: 1.5rem 0 0.5rem 0; padding-bottom: 0.35rem; border-bottom: 1px solid var(--border); grid-column: 1 / -1; }}
        .topic-label:first-child {{ margin-top: 0; }}
        .form input:focus {{ outline: none; border-color: var(--accent-light); }}
        .form button {{ padding: 0.75rem 1.5rem; border-radius: var(--radius); border: none; background: var(--cta); color: var(--cta-text); cursor: pointer; font-weight: 700; font-size: 0.9375rem; font-family: inherit; box-shadow: 0 2px 10px rgba(232,165,77,0.3); transition: transform var(--dur) var(--ease-out), background var(--dur) var(--ease-out), box-shadow var(--dur) var(--ease-out); }}
        .form button:hover {{ transform: translateY(-2px); background: #e0963f; box-shadow: 0 6px 18px rgba(232,165,77,0.4); }}
        .stepps-grid {{ display: grid; gap: 1.25rem; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); }}
        .stepp {{ background: var(--card); padding: 1.25rem 1.5rem; border-radius: var(--radius); border: 1px solid var(--border); box-shadow: var(--shadow); transition: transform var(--dur) var(--ease-out), box-shadow var(--dur) var(--ease-out), border-color var(--dur) var(--ease-out); }}
        .stepp:hover {{ transform: translateY(-2px); box-shadow: var(--shadow-lg); border-color: var(--accent-light); }}
        .stepp h3 {{ margin: 0 0 0.75rem 0; font-size: 0.625rem; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.12em; }}
        .stepp p {{ margin: 0; font-size: 0.9rem; color: var(--muted); line-height: 1.55; }}
        .stepp .kw {{ font-size: 0.85rem; color: var(--accent); margin-top: 0.5rem; font-weight: 500; }}
        .science-hero {{ margin-bottom: 2.5rem; }}
        .science-hero h2 {{ font-size: 1.85rem; font-weight: 700; color: var(--accent); margin: 0 0 0.5rem 0; letter-spacing: -0.02em; }}
        .science-hero h2 em {{ font-style: italic; color: var(--accent); }}
        .science-hero .tagline {{ font-size: 1.1rem; color: var(--muted); line-height: 1.6; margin: 0; max-width: 42ch; }}
        .science-proof {{ display: flex; flex-wrap: wrap; gap: 1.5rem 2.5rem; align-items: center; padding: 1.25rem 1.5rem; background: var(--card); border-radius: var(--radius); border: 1px solid var(--border); margin-bottom: 2.5rem; box-shadow: var(--shadow); }}
        .proof-item {{ font-size: 0.95rem; color: var(--text); display: flex; align-items: center; gap: 0.4rem; }}
        .proof-num {{ font-weight: 700; color: var(--accent); font-size: 1.1rem; }}
        .proof-cta {{ margin-left: auto; padding: 0.5rem 1rem; background: var(--cta); color: var(--cta-text); font-weight: 600; font-size: 0.9rem; text-decoration: none; border-radius: 8px; white-space: nowrap; transition: background var(--dur), transform var(--dur); }}
        .proof-cta:hover {{ background: #e0963f; transform: translateX(2px); }}
        .books-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1.25rem; margin-bottom: 2.5rem; }}
        .book-card {{ background: var(--card); border-radius: var(--radius); padding: 1.25rem; border: 1px solid var(--border); box-shadow: var(--shadow); transition: transform var(--dur) var(--ease-out), box-shadow var(--dur) var(--ease-out), border-color var(--dur) var(--ease-out); text-decoration: none; color: var(--text); display: flex; flex-direction: column; align-items: center; text-align: center; min-height: 280px; }}
        .book-card:hover {{ transform: translateY(-2px); box-shadow: var(--shadow-lg); border-color: var(--accent-light); }}
        .book-cover {{ width: 100%; max-width: 120px; aspect-ratio: 2/3; object-fit: cover; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); margin-bottom: 0.85rem; }}
        .book-cover-placeholder {{ width: 100%; max-width: 120px; aspect-ratio: 2/3; background: var(--warm); border-radius: 8px; margin-bottom: 0.85rem; display: none; align-items: center; justify-content: center; font-size: 1.5rem; font-weight: 600; color: var(--muted); }}
        .book-title {{ font-size: 0.95rem; font-weight: 600; line-height: 1.35; margin: 0 0 0.4rem 0; color: var(--accent); }}
        .book-unlocks {{ font-size: 0.8rem; color: var(--muted); line-height: 1.45; }}
        .mechanism-box {{ background: linear-gradient(135deg, rgba(45,74,43,0.06) 0%, rgba(232,165,77,0.08) 100%); border-radius: var(--radius); padding: 1.75rem 2rem; border: 1px solid var(--border); margin-bottom: 2.5rem; }}
        .mechanism-box h3 {{ font-size: 1rem; font-weight: 600; color: var(--accent); margin: 0 0 1rem 0; letter-spacing: -0.01em; }}
        .mechanism-box p {{ font-size: 0.95rem; color: var(--text); line-height: 1.65; margin: 0 0 0.75rem 0; }}
        .mechanism-box p:last-child {{ margin-bottom: 0; }}
        .mechanism-box strong {{ color: var(--accent); }}
        .score-formula {{ font-size: 0.9rem; background: var(--card); padding: 1rem 1.25rem; border-radius: var(--radius); border: 1px solid var(--border); margin-top: 1rem; font-family: ui-monospace, monospace; color: var(--muted); }}
        @media (max-width: 900px) {{ .books-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
        @media (max-width: 500px) {{ .books-grid {{ grid-template-columns: 1fr; }} }}
        @media (max-width: 640px) {{ .science-proof {{ flex-direction: column; align-items: flex-start; }} .proof-cta {{ margin-left: 0; margin-top: 0.5rem; }} }}
        .science-hero .hero-cta {{ display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.75rem 1.5rem; background: var(--accent); color: var(--card); font-weight: 600; text-decoration: none; border-radius: 10px; font-size: 0.95rem; transition: background var(--dur), transform var(--dur); }}
        .science-hero .hero-cta:hover {{ background: var(--accent-hover); transform: translateY(-2px); }}
        .science-wrap {{ max-width: 100%; margin: 0; padding: 0 0 100px; }}
        .science-wrap .section-title {{ font-size: 0.8125rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted-light); margin-bottom: 1.25rem; }}
        .science-v2-h1 {{ font-size: 1.375rem; font-weight: 700; letter-spacing: -0.01em; margin-bottom: 1rem; color: var(--ink); }}
        .science-v2-p {{ font-size: 0.9375rem; color: var(--muted); line-height: 1.75; margin-bottom: 1rem; }}
        .science-v2-p strong {{ color: var(--ink); font-weight: 600; }}
        .science-v2-p a {{ color: var(--accent-light); text-decoration: none; }}
        .science-v2-p a:hover {{ text-decoration: underline; }}
        .science-hr {{ border: none; border-top: 1px solid var(--border); margin: 2.25rem 0; }}
        .berger-block {{ background: var(--cream-dark); border-radius: var(--radius); padding: 1.25rem 1.375rem; margin-bottom: 1.5rem; }}
        .berger-name {{ font-size: 0.9375rem; font-weight: 700; color: var(--ink); margin-bottom: 0.2rem; }}
        .berger-role {{ font-size: 0.8125rem; color: var(--muted); margin-bottom: 0.875rem; }}
        .berger-facts {{ display: flex; flex-direction: column; gap: 0.45rem; }}
        .berger-fact {{ display: grid; grid-template-columns: 18px 1fr; gap: 0.625rem; font-size: 0.8125rem; color: var(--muted); line-height: 1.5; }}
        .stepps-list {{ display: flex; flex-direction: column; gap: 0; border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }}
        .stepps-item {{ padding: 0.875rem 1.125rem; border-bottom: 1px solid var(--border); display: grid; grid-template-columns: 28px 1fr; gap: 0.875rem; align-items: start; }}
        .stepps-item:last-child {{ border-bottom: none; }}
        .stepps-letter {{ width: 28px; height: 28px; background: var(--cream-dark); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 0.75rem; font-weight: 800; color: var(--accent); flex-shrink: 0; margin-top: 1px; }}
        .stepps-name {{ font-size: 0.875rem; font-weight: 600; color: var(--ink); margin-bottom: 0.2rem; }}
        .stepps-desc {{ font-size: 0.8125rem; color: var(--muted); line-height: 1.55; }}
        .formula-block {{ background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 1.125rem 1.25rem; }}
        .formula-row {{ display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 0.75rem; padding: 0.5rem 0; border-bottom: 1px solid var(--border); font-size: 0.8125rem; color: var(--muted); }}
        .formula-row:last-child {{ border-bottom: none; }}
        .formula-row strong {{ color: var(--ink); font-weight: 600; }}
        .formula-pts {{ font-size: 0.75rem; font-weight: 600; color: var(--accent); white-space: nowrap; }}
        .honest-note {{ background: var(--cta-pale); border-left: 3px solid var(--cta); border-radius: 0 var(--radius) var(--radius) 0; padding: 0.875rem 1rem; font-size: 0.8125rem; color: var(--muted); line-height: 1.65; }}
        .honest-note strong {{ color: var(--ink); font-weight: 600; }}
        .bottom-links {{ margin-top: 2.25rem; display: flex; gap: 1rem; font-size: 0.8125rem; }}
        .bottom-links a {{ color: var(--accent-light); text-decoration: none; }}
        .bottom-links a:hover {{ text-decoration: underline; }}
        .science-proof-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: var(--border); border-radius: 12px; overflow: hidden; padding: 0; }}
        .science-proof-grid .science-proof-item {{ display: flex; flex-direction: column; gap: 0.35rem; padding: 1.5rem 1.25rem; background: var(--card); }}
        .science-proof-grid .science-proof-label {{ font-size: 0.9rem; color: var(--text); line-height: 1.4; }}
        .science-proof-grid .proof-sublabel {{ font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin-top: 0.25rem; }}
        .science-proof-grid .science-proof-cta {{ grid-column: 1 / -1; margin: 0; padding: 1rem 1.5rem; text-align: center; background: var(--warm); border-radius: 0; }}
        .science-proof-grid .science-proof-cta:hover {{ background: var(--cta); }}
        .science-berger-card .science-quote {{ margin: 0 0 1.25rem 0; padding-left: 1rem; border-left: 3px solid var(--accent); font-style: italic; color: var(--text); font-size: 1rem; line-height: 1.6; }}
        .science-creds {{ display: flex; flex-direction: column; gap: 0.5rem; }}
        .science-creds-item {{ display: flex; align-items: center; gap: 0.5rem; font-size: 0.9rem; color: var(--muted); }}
        .science-creds-dot {{ width: 6px; height: 6px; background: var(--cta); border-radius: 50%; flex-shrink: 0; }}
        .science-timeline {{ display: flex; flex-direction: column; gap: 0; margin-top: 1.5rem; }}
        .science-timeline-item {{ display: grid; grid-template-columns: 4rem 1fr; gap: 1.25rem; padding-bottom: 1.5rem; position: relative; }}
        .science-timeline-item:not(:last-child)::before {{ content: ''; position: absolute; left: 1.4rem; top: 2.2rem; bottom: 0; width: 1px; background: var(--border); }}
        .science-timeline-node {{ display: flex; flex-direction: column; align-items: center; }}
        .science-timeline-year {{ font-size: 0.8rem; color: var(--muted); letter-spacing: 0.05em; }}
        .science-timeline-dot {{ width: 10px; height: 10px; background: var(--accent); border-radius: 50%; margin-top: 0.35rem; }}
        .science-timeline-tag {{ display: inline-block; font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase; background: rgba(232,165,77,0.25); color: var(--cta-text); padding: 0.2rem 0.5rem; border-radius: 4px; margin-bottom: 0.4rem; }}
        .science-timeline-title {{ font-size: 1rem; font-weight: 600; color: var(--text); margin-bottom: 0.35rem; }}
        .science-timeline-body {{ font-size: 0.9rem; color: var(--muted); line-height: 1.55; margin: 0; }}
        .science-translate-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; margin-top: 1.5rem; align-items: start; }}
        .science-algo-block {{ margin: 0; }}
        .science-algo-code {{ margin: 0; font-size: 0.8rem; line-height: 1.7; color: var(--muted); white-space: pre-wrap; overflow-x: auto; }}
        .science-algo-code .algo-kw {{ color: var(--accent); }}
        .science-translate-list {{ display: flex; flex-direction: column; gap: 1.25rem; }}
        .science-translate-item {{ display: grid; grid-template-columns: 2.5rem 1fr; gap: 1rem; align-items: start; }}
        .science-translate-num {{ font-size: 1.5rem; font-weight: 700; color: var(--border); line-height: 1; }}
        .science-translate-title {{ font-size: 1rem; font-weight: 600; color: var(--text); margin-bottom: 0.35rem; }}
        .science-translate-body {{ font-size: 0.9rem; color: var(--muted); line-height: 1.55; margin: 0; }}
        .science-trust-closer {{ background: linear-gradient(135deg, rgba(45,74,43,0.08) 0%, rgba(232,165,77,0.06) 100%); border-radius: 16px; padding: 2.5rem 2rem; border: 1px solid var(--border); margin-top: 2rem; }}
        .science-trust-headline {{ font-size: 1.5rem; font-weight: 700; color: var(--text); margin: 0 0 0.75rem 0; line-height: 1.35; }}
        .science-trust-headline em {{ font-style: italic; color: var(--accent); }}
        .science-trust-sub {{ font-size: 1rem; color: var(--muted); line-height: 1.6; margin: 0 0 1.5rem 0; max-width: 36ch; }}
        .science-trust-ctas {{ display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: center; }}
        .science-cta-ghost {{ padding: 0.6rem 1.25rem; border: 1px solid var(--border); border-radius: 8px; background: var(--card); color: var(--text); font-size: 0.9rem; text-decoration: none; transition: border-color var(--dur), color var(--dur); }}
        .science-cta-ghost:hover {{ border-color: var(--accent); color: var(--accent); }}
        @media (max-width: 900px) {{ .science-proof-grid {{ grid-template-columns: repeat(2, 1fr); }} .science-translate-grid {{ grid-template-columns: 1fr; }} }}
        @media (max-width: 560px) {{ .science-proof-grid {{ grid-template-columns: 1fr; }} }}
        .resource-list {{ margin: 0.5rem 0 0 0; padding-left: 1.25rem; font-size: 0.9rem; color: var(--muted); line-height: 1.6; }}
        .resource-list li {{ margin-bottom: 0.4rem; }}
        .resource-list a {{ color: var(--accent); text-decoration: none; }}
        .resource-list a:hover {{ text-decoration: underline; }}
        .field-select {{ padding: 0.6rem 1rem; border-radius: var(--radius); border: 1px solid var(--border); background: var(--card); font-size: 0.9375rem; max-width: 220px; font-family: inherit; }}
        .field-controls {{ display: flex; flex-wrap: wrap; align-items: flex-end; gap: 1rem; margin-bottom: 1.5rem; }}
        .field-control-group {{ display: flex; flex-direction: column; gap: 0.35rem; }}
        .field-control-label {{ font-size: 0.625rem; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.12em; }}
        .field-share-wrap {{ margin-left: auto; display: flex; align-items: center; gap: 0.5rem; }}
        .share-dropdown {{ position: relative; }}
        .btn-share {{ padding: 0.5rem 1rem; border-radius: var(--radius); border: 1px solid var(--border); background: var(--card); color: var(--text); font-size: 0.9rem; font-weight: 600; cursor: pointer; font-family: inherit; transition: border-color 0.2s, color 0.2s; }}
        .btn-share:hover {{ border-color: var(--accent); color: var(--accent); }}
        .share-panel {{ display: none; position: absolute; top: 100%; right: 0; margin-top: 0.5rem; background: var(--card); border-radius: var(--radius); box-shadow: var(--shadow-lg); border: 1px solid var(--border); padding: 0.75rem; min-width: 140px; z-index: 200; }}
        .share-panel.share-panel-open {{ display: flex; flex-direction: column; gap: 0.35rem; }}
        .share-panel-label {{ font-size: 0.7rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }}
        .share-link {{ font-size: 0.9rem; color: var(--text); text-decoration: none; padding: 0.4rem 0.5rem; border-radius: 6px; transition: background 0.15s; }}
        .share-link:hover {{ background: var(--warm); color: var(--accent); }}
        .share-link.share-copy {{ background: none; border: none; cursor: pointer; font-family: inherit; text-align: left; width: 100%; }}
        .share-feedback {{ font-size: 0.8rem; color: var(--accent); }}
        .source-select {{ padding: 0.6rem 1rem; border-radius: var(--radius); border: 1px solid var(--border); background: var(--card); font-size: 0.9rem; font-family: inherit; }}
        .angles-wrap {{ margin-top: 0.5rem; padding-top: 0.75rem; border-top: 1px solid var(--border); }}
        .angles-label {{ font-size: 0.625rem; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; opacity: 0.88; display: block; margin-bottom: 0.35rem; }}
        .angles-list {{ margin: 0; padding-left: 1.25rem; font-size: 0.85rem; color: var(--accent); line-height: 1.5; }}
        .angles-list li {{ margin-bottom: 0.2rem; }}
        .loader-text {{ font-style: italic; }}
        .loader-spinner {{ display: inline-block; width: 20px; height: 20px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; }}
        .empty-state {{ padding: 2.5rem 1.5rem; text-align: center; }}
        .empty-state-icon {{ font-size: 2rem; margin-bottom: 1rem; opacity: 0.6; }}
        .empty-state-title {{ font-size: 1.15rem; font-weight: 600; color: var(--text); margin-bottom: 0.5rem; }}
        .empty-state-body {{ font-size: 0.95rem; color: var(--muted); margin-bottom: 1.25rem; max-width: 32ch; margin-left: auto; margin-right: auto; }}
        .empty-state-chips {{ display: flex; flex-wrap: wrap; gap: 0.5rem; justify-content: center; }}
        .empty-state-loading {{ text-align: center; padding: 2rem; }}
        .loading-overlay {{ position: fixed; inset: 0; background: rgba(250,248,245,0.92); z-index: 9999; display: flex; align-items: center; justify-content: center; }}
        .loading-overlay-content {{ text-align: center; padding: 2rem; }}
        .loading-overlay-content .loader-spinner {{ margin-bottom: 1rem; }}
        .loading-overlay-content .loading-title {{ font-size: 1.1rem; font-weight: 600; color: var(--text); margin: 0 0 0.35rem 0; }}
        .loading-overlay-content .loading-sub {{ font-size: 0.9rem; color: var(--muted); margin: 0; }}

        @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
        .lifecycle {{ font-size: 0.7rem; font-weight: 600; padding: 0.2rem 0.5rem; border-radius: 4px; text-transform: uppercase; white-space: nowrap; }}
        .lifecycle-rising {{ background: rgba(34,197,94,0.2); color: #15803d; }}
        .lifecycle-peaking {{ background: rgba(232,165,77,0.35); color: var(--cta-text); }}
        .lifecycle-fading {{ background: rgba(107,114,128,0.2); color: #6b7280; }}
        .lifecycle-wrap {{ position: relative; display: inline-block; }}
        .lifecycle-wrap .lifecycle-tooltip {{ position: absolute; left: 50%; transform: translateX(-50%) translateY(6px); bottom: 100%; margin-bottom: 0.5rem; width: 240px; padding: 0.6rem 0.75rem; background: #1e3520; color: #fff; border-radius: 10px; box-shadow: var(--shadow-lg); font-size: 0.62rem; font-weight: 400; text-transform: none; opacity: 0; visibility: hidden; pointer-events: none; transition: opacity 0.2s, transform 0.2s, visibility 0.2s; z-index: 1000; line-height: 1.4; text-align: left; white-space: normal; }}
        .lifecycle-wrap:hover .lifecycle-tooltip {{ opacity: 1; visibility: visible; transform: translateX(-50%) translateY(0); }}
        .badges {{ display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }}
        .site-header {{ display: flex; flex-direction: column; width: 100vw; max-width: 100vw; margin-left: calc(50% - 50vw); margin-right: calc(50% - 50vw); margin-bottom: 1.5rem; background: var(--bg); }}
        .header-divider {{ height: 1px; background: var(--border); width: 100%; flex-shrink: 0; }}
        .header-row {{ display: flex; align-items: center; justify-content: space-between; padding: 0.9rem 2rem; gap: 2rem; max-width: 1100px; margin: 0 auto; width: 100%; box-sizing: border-box; }}
        .header-top-left, .header-top-right, .header-bottom-right {{ flex: 0 0 auto; }}
        .header-top-center {{ flex: 1; display: flex; justify-content: center; }}
        .header-top-right, .header-bottom-right {{ display: flex; align-items: center; gap: 1.25rem; }}
        .btn-lang {{ background: none; border: none; color: var(--text); font-size: 0.9rem; cursor: pointer; font-family: inherit; display: flex; align-items: center; gap: 0.2rem; padding: 0; }}
        .btn-lang:hover {{ color: var(--accent); }}
        .logo-row {{ display: flex; align-items: center; gap: 0.5rem; text-decoration: none; }}
        .logo-row:hover .logo-text {{ color: var(--accent); }}
        .logo-text-wrap {{ display: flex; flex-direction: column; gap: 0.1rem; }}
        .logo-avatar {{ width: 36px; height: 36px; border-radius: 50%; overflow: hidden; flex-shrink: 0; display: flex; align-items: center; justify-content: center; }}
        .logo-text {{ font-size: 1.2rem; font-weight: 700; color: var(--text); letter-spacing: -0.02em; }}
        .sidebar-subtitle {{ font-size: 0.6rem; font-weight: 300; color: var(--muted); line-height: 1.2; display: block; }}
        .logo-avatar img {{ width: 100%; height: 100%; object-fit: cover; }}
        .header-icon {{ color: var(--text); text-decoration: none; font-size: 0.9rem; }}
        .header-icon:hover {{ color: var(--accent); }}
        .header-search-wrap {{ display: flex; align-items: center; flex: 1; max-width: 320px; border: 1px solid var(--border); border-radius: 10px; padding: 0.4rem 0.75rem; gap: 0.5rem; background: var(--card); box-shadow: 0 1px 4px rgba(0,0,0,0.04); }}
        .search-icon {{ color: var(--accent); font-size: 0.9rem; }}
        .header-search {{ flex: 1; border: none; background: none; color: var(--text); font-size: 0.9rem; font-family: inherit; }}
        .header-search::placeholder {{ color: var(--muted); }}
        .header-search:focus {{ outline: none; }}
        .nav-main {{ display: flex; align-items: center; gap: 1.5rem; flex: 1; justify-content: center; }}
        .nav-trigger {{ background: var(--warm); border: 1px solid var(--border); border-radius: 8px; color: var(--text); font-size: 0.9rem; cursor: pointer; font-family: inherit; padding: 0.4rem 0.75rem; display: flex; align-items: center; gap: 0.25rem; }}
        .nav-trigger:hover {{ background: var(--border); }}
        .nav-link {{ color: var(--muted); text-decoration: none; font-size: 0.95rem; }}
        .nav-link:hover, .nav-link.active {{ color: var(--accent); font-weight: 500; }}
        .nav-dropdown {{ position: relative; }}
        .nav-dropdown-panel {{ display: none; position: absolute; top: 100%; left: 0; margin-top: 0.5rem; background: var(--card); border-radius: 12px; box-shadow: 0 10px 40px rgba(0,0,0,0.12); border: 1px solid var(--border); padding: 1rem; min-width: 480px; z-index: 100; }}
        .nav-dropdown:hover .nav-dropdown-panel {{ display: block; }}
        .func-cards {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; }}
        .func-card {{ display: block; padding: 1rem; border-radius: 10px; text-decoration: none; color: var(--text); transition: background 0.15s; }}
        .func-card:hover {{ background: var(--bg); }}
        .func-icon {{ font-size: 1.5rem; display: block; margin-bottom: 0.35rem; }}
        .func-title {{ font-weight: 600; font-size: 0.95rem; display: block; margin-bottom: 0.2rem; }}
        .func-desc {{ font-size: 0.8rem; color: var(--muted); line-height: 1.4; }}
        .header-utils {{ display: flex; align-items: center; gap: 0.5rem; margin-left: auto; }}
        .btn-util {{ padding: 0.4rem 0.75rem; border-radius: 8px; font-size: 0.85rem; cursor: pointer; font-family: inherit; }}
        .btn-outline {{ border: 1px solid var(--border); background: var(--card); color: var(--text); }}
        .btn-outline:hover {{ border-color: var(--accent); color: var(--accent); }}
        .chevron {{ font-size: 0.7em; opacity: 0.8; }}
        .hero {{ display: grid; grid-template-columns: 1fr 1fr; gap: 3rem; align-items: center; margin-bottom: 3rem; padding: 2.5rem 0; min-height: 300px; position: relative; border-radius: 24px; }}
        .hero::before {{ content: ""; position: absolute; inset: 0; background: repeating-linear-gradient(transparent, transparent 29px, rgba(45,74,43,0.08) 29px, rgba(45,74,43,0.08) 30px); opacity: 0; transition: opacity 0.4s var(--ease-out); pointer-events: none; border-radius: 24px; }}
        .hero:hover::before {{ opacity: 1; }}
        .hero-left {{ max-width: 420px; position: relative; z-index: 1; }}
        .hero-greeting {{ font-size: 0.75rem; font-weight: 300; color: var(--muted); margin: 0 0 0.6rem 0; }}
        .hero-headline {{ font-size: 2.25rem; font-weight: 700; color: var(--accent); line-height: 1.2; margin: 0 0 0.5rem 0; letter-spacing: -0.02em; }}
        .hero-headline span {{ display: block; }}
        .hero-subtitle {{ font-size: 0.95rem; font-weight: 600; color: var(--accent); letter-spacing: 0.04em; text-transform: uppercase; margin: 0 0 1rem 0; opacity: 0.85; }}
        .page-header h1 {{ color: var(--ink); font-size: 1.5rem; font-weight: 800; }}
        .hero-desc {{ color: var(--muted); font-size: 1.05rem; line-height: 1.65; margin-bottom: 1.5rem; font-weight: 400; }}
        .hero-cta {{ display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.85rem 1.75rem; border-radius: var(--radius); background: var(--cta); color: var(--cta-text); font-weight: 700; text-decoration: none; font-size: 0.95rem; font-family: inherit; border: none; box-shadow: 0 4px 14px rgba(232,165,77,0.35); transition: transform var(--dur) var(--ease-out), background var(--dur) var(--ease-out), box-shadow var(--dur) var(--ease-out); }}
        .hero-cta:hover {{ transform: translateY(-2px); background: #e0963f; box-shadow: 0 8px 22px rgba(232,165,77,0.4); }}
        .page-links {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 1.25rem; margin-top: 2.5rem; }}
        .page-link-card {{ display: flex; flex-direction: column; gap: 0.35rem; padding: 1.25rem 1.5rem; background: var(--card); border-radius: var(--radius); border: 1px solid var(--border); text-decoration: none; color: var(--text); transition: transform var(--dur) var(--ease-out), border-color var(--dur) var(--ease-out), box-shadow var(--dur) var(--ease-out); box-shadow: var(--shadow); }}
        .page-link-card:hover {{ transform: translateY(-2px); border-color: var(--accent-light); box-shadow: var(--shadow-lg); }}
        .page-link-icon {{ font-size: 1.75rem; }}
        .page-link-card strong {{ font-size: 1.05rem; font-weight: 600; letter-spacing: -0.01em; line-height: 1.35; }}
        .page-link-card small {{ font-size: 0.82rem; color: var(--muted); font-weight: 400; line-height: 1.45; }}
        .hero-visual {{ display: flex; align-items: center; justify-content: center; position: relative; z-index: 1; padding: 2rem; }}
        .hero-thumbnail-wrap {{ background: var(--accent); border-radius: 45% 55% 52% 48% / 55% 45% 55% 45%; overflow: hidden; display: flex; align-items: center; justify-content: center; width: 300px; height: 300px; transition: transform 0.4s var(--ease-out), box-shadow 0.4s var(--ease-out); }}
        .hero:hover .hero-thumbnail-wrap {{ transform: scale(1.05); box-shadow: 0 12px 40px rgba(45,74,43,0.2); }}
        .hero-thumbnail {{ width: 100%; height: 100%; object-fit: cover; transition: transform 0.5s var(--ease-out); }}
        .hero:hover .hero-thumbnail {{ transform: scale(1.08); }}
        .hero-bg {{ background: transparent; }}
        .science-hero {{ margin-bottom: 2.5rem; }}
        .science-hero h2 {{ font-size: 1.85rem; font-weight: 700; color: var(--accent); margin: 0 0 0.5rem 0; letter-spacing: -0.02em; }}
        .science-hero h2 em {{ font-style: italic; color: var(--accent); }}
        .science-hero .tagline {{ font-size: 1.1rem; color: var(--muted); line-height: 1.6; margin: 0; max-width: 42ch; }}
        .berger-bio {{ background: var(--card); border-radius: var(--radius); padding: 1.75rem 2rem; border: 1px solid var(--border); box-shadow: var(--shadow); margin-bottom: 2.5rem; }}
        .berger-bio h3 {{ font-size: 1rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin: 0 0 0.75rem 0; }}
        .berger-bio p {{ font-size: 0.95rem; color: var(--text); line-height: 1.65; margin: 0; }}
        .berger-bio a {{ color: var(--accent); text-decoration: none; }}
        .berger-bio a:hover {{ text-decoration: underline; }}
        .books-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1.25rem; margin-bottom: 2.5rem; }}
        .book-card {{ background: var(--card); border-radius: var(--radius); padding: 1.25rem; border: 1px solid var(--border); box-shadow: var(--shadow); transition: transform var(--dur) var(--ease-out), box-shadow var(--dur) var(--ease-out), border-color var(--dur) var(--ease-out); text-decoration: none; color: var(--text); display: flex; flex-direction: column; align-items: center; text-align: center; }}
        .book-card:hover {{ transform: translateY(-2px); box-shadow: var(--shadow-lg); border-color: var(--accent-light); }}
        .book-cover {{ width: 100%; max-width: 120px; aspect-ratio: 2/3; object-fit: cover; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); margin-bottom: 0.85rem; }}
        .book-cover-placeholder {{ width: 100%; max-width: 120px; aspect-ratio: 2/3; background: var(--warm); border-radius: 8px; margin-bottom: 0.85rem; display: none; align-items: center; justify-content: center; font-size: 1.5rem; font-weight: 600; color: var(--muted); }}
        .book-title {{ font-size: 0.9rem; font-weight: 600; line-height: 1.35; margin: 0 0 0.25rem 0; }}
        .book-year {{ font-size: 0.75rem; color: var(--muted); }}
        .mechanism-box {{ background: linear-gradient(135deg, rgba(45,74,43,0.06) 0%, rgba(232,165,77,0.08) 100%); border-radius: var(--radius); padding: 1.75rem 2rem; border: 1px solid var(--border); margin-bottom: 2.5rem; }}
        .mechanism-box h3 {{ font-size: 1rem; font-weight: 600; color: var(--accent); margin: 0 0 1rem 0; letter-spacing: -0.01em; }}
        .mechanism-box p {{ font-size: 0.95rem; color: var(--text); line-height: 1.65; margin: 0 0 0.75rem 0; }}
        .mechanism-box p:last-child {{ margin-bottom: 0; }}
        .mechanism-box strong {{ color: var(--accent); }}
        .score-formula {{ font-size: 0.9rem; background: var(--card); padding: 1rem 1.25rem; border-radius: var(--radius); border: 1px solid var(--border); margin-top: 1rem; font-family: ui-monospace, monospace; color: var(--muted); }}
        @media (max-width: 900px) {{ .books-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
        @media (max-width: 500px) {{ .books-grid {{ grid-template-columns: 1fr; }} }}
        .onboarding-backdrop {{ position: fixed; inset: 0; background: rgba(45,74,43,0.75); backdrop-filter: blur(4px); z-index: 9999; display: flex; align-items: center; justify-content: center; padding: 1.5rem; }}
        .onboarding-modal {{ background: var(--card); max-width: 480px; width: 100%; border-radius: 16px; overflow: hidden; box-shadow: 0 24px 48px rgba(0,0,0,0.2); }}
        .onboarding-progress {{ height: 3px; background: var(--border); }}
        .onboarding-progress-fill {{ height: 100%; background: var(--accent); transition: width 0.3s ease; width: 33.33%; }}
        .onboarding-body {{ padding: 2rem 2rem 1.5rem; }}
        .onboarding-step-label {{ font-size: 0.7rem; letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); margin-bottom: 0.5rem; }}
        .onboarding-title {{ font-size: 1.35rem; font-weight: 700; color: var(--text); margin-bottom: 0.75rem; }}
        .onboarding-desc {{ font-size: 0.95rem; color: var(--muted); line-height: 1.6; margin: 0; }}
        .onboarding-footer {{ display: flex; justify-content: space-between; align-items: center; padding: 1rem 2rem 1.5rem; border-top: 1px solid var(--border); }}
        .btn-onboard-skip {{ background: none; border: none; color: var(--muted); font-size: 0.9rem; cursor: pointer; }}
        .btn-onboard-skip:hover {{ color: var(--text); }}
        .btn-onboard-next {{ background: var(--accent); color: var(--card); border: none; padding: 0.6rem 1.25rem; border-radius: 8px; font-weight: 600; font-size: 0.9rem; cursor: pointer; }}
        .btn-onboard-next:hover {{ background: var(--accent-hover); }}
        .reveal {{ opacity: 1; transform: none; transition: opacity 0.65s ease, transform 0.65s ease; }}
        .reveal.visible {{ opacity: 1; transform: none; }}
        @media (max-width: 768px) {{ .app-layout {{ flex-direction: column; }} .sidebar {{ width: 100%; height: auto; position: relative; flex-direction: row; flex-wrap: wrap; }} .sidebar-nav {{ flex-direction: row; flex-wrap: wrap; }} .sidebar-link {{ flex: 1 1 auto; }} .stats {{ grid-template-columns: 1fr; }} .cards {{ grid-template-columns: 1fr; }} footer {{ left: 0; }} }}
        @media (max-width: 640px) {{ .hero {{ grid-template-columns: 1fr; }} .hero-visual {{ order: -1; }} .hero-thumbnail-wrap {{ width: 240px; height: 240px; }} .form {{ flex-wrap: wrap; }} }}
    </style>
</head>
<body>
    <div class="app-layout">
        {_sidebar_html(active, lang)}
        <main class="main-content">
        {_header_html(active, lang)}
        {hero if hero else f'<header class="page-header"><h1>ViralLab</h1><p class="tagline">{_html_escape(_t("tagline", lang))}</p></header>'}
        {body}
        <!-- Footer: position:fixed at bottom of viewport, aligned with sidebar-footer. Do not change. -->
        <footer>
            <p class="spread">{_html_escape(_t("camp2_footer", lang))}</p>
            <p>{_html_escape(_t("camp2_footer_built", lang))} <a href="{TG_PERSONAL_URL}" target="_blank" rel="noopener">@miccakitt</a> {_html_escape(_t("camp2_footer_welcome", lang))}</p>
        </footer>
        </main>
    </div>
    <div id="loadingOverlay" class="loading-overlay" style="display:none" data-msg-search="{_html_escape(_t("loading_searching", lang))}" data-msg-search-sub="{_html_escape(_t("loading_search_sub", lang))}" data-msg-refresh="{_html_escape(_t("loading_refreshing", lang))}" data-msg-refresh-sub="{_html_escape(_t("loading_refresh_sub", lang))}">
        <div class="loading-overlay-content">
            <span class="loader-spinner"></span>
            <p class="loading-title" id="loadingTitle"></p>
            <p class="loading-sub" id="loadingSub"></p>
        </div>
    </div>
        <script>
        (function loadingOverlay() {{
            const el = document.getElementById('loadingOverlay');
            if (!el) return;
            const title = document.getElementById('loadingTitle');
            const sub = el.querySelector('.loading-sub');
            function show(mode) {{
                if (mode === 'search') {{ title.textContent = el.getAttribute('data-msg-search'); sub.textContent = el.getAttribute('data-msg-search-sub'); }}
                else {{ title.textContent = el.getAttribute('data-msg-refresh'); sub.textContent = el.getAttribute('data-msg-refresh-sub'); }}
                el.style.display = 'flex';
            }}
            document.querySelectorAll('form[action*="search-news"]').forEach(function(f) {{ f.addEventListener('submit', function() {{ show('search'); }}); }});
            document.querySelectorAll('a.refresh-link').forEach(function(a) {{
                if (!/\\/(news|daily)\\/refresh/.test(a.getAttribute('href') || '')) return;
                a.addEventListener('click', function() {{ show('refresh'); }});
            }});
        }})();
        document.getElementById('headerSearch')?.addEventListener('keydown', function(e) {{
            if (e.key === 'Enter') {{
                e.preventDefault();
                const q = this.value.trim() || 'viral trending';
                const viralInput = document.getElementById('viralQuery');
                const viralForm = document.getElementById('viralSearchForm');
                if (viralInput && viralForm) {{ viralInput.value = q; viralForm.dispatchEvent(new Event('submit')); }}
                else {{ window.location = '/viral?q=' + encodeURIComponent(q); }}
            }}
        }});
        (function scrollReveal() {{
            const reveals = document.querySelectorAll('.reveal');
            const obs = new IntersectionObserver(function(entries) {{
                entries.forEach(function(e) {{
                    if (e.isIntersecting) {{ e.target.classList.add('visible'); obs.unobserve(e.target); }}
                }});
            }}, {{ threshold: 0.1 }});
            reveals.forEach(function(el) {{ obs.observe(el); }});
        }})();
        (function() {{
            const d = new Date();
            const y = d.getFullYear(), m = String(d.getMonth()+1).padStart(2,'0'), day = String(d.getDate()).padStart(2,'0');
            const locale = document.documentElement.lang === 'zh' ? 'zh-TW' : 'en-US';
            const wd = d.toLocaleDateString(locale, {{ weekday: 'short' }});
            const el = document.getElementById('dailyNewsDate');
            if (el) el.textContent = y + '-' + m + '-' + day + ' ' + wd;
        }})();
        (function onboarding() {{
            if (localStorage.getItem('virallab-onboarding-done')) return;
            const steps = [
                {{ title: 'Pick your field.', desc: 'ViralLab tailors trends and scores to your niche. Tell us who you create for.' }},
                {{ title: 'Find what\'s spreading.', desc: 'The Viral page surfaces top videos in your niche — scored with Berger\'s STEPPS. See why each piece spreads.' }},
                {{ title: 'Score your content.', desc: 'Paste any YouTube URL into Video-to-Text. Get transcript + Berger score + fix suggestions.' }}
            ];
            let step = 0;
            const overlay = document.createElement('div');
            overlay.id = 'onboardingOverlay';
            overlay.innerHTML = '<div class="onboarding-backdrop"><div class="onboarding-modal"><div class="onboarding-progress"><div class="onboarding-progress-fill"></div></div><div class="onboarding-body"><div class="onboarding-step-label">Step ' + (step+1) + ' of 3</div><div class="onboarding-title"></div><p class="onboarding-desc"></p></div><div class="onboarding-footer"><button type="button" class="btn-onboard-skip">Skip</button><button type="button" class="btn-onboard-next">Next →</button></div></div></div>';
            overlay.querySelector('.onboarding-title').textContent = steps[0].title;
            overlay.querySelector('.onboarding-desc').textContent = steps[0].desc;
            const progressFill = overlay.querySelector('.onboarding-progress-fill');
            const titleEl = overlay.querySelector('.onboarding-title');
            const descEl = overlay.querySelector('.onboarding-desc');
            const stepLabel = overlay.querySelector('.onboarding-step-label');
            const nextBtn = overlay.querySelector('.btn-onboard-next');
            function updateStep() {{
                stepLabel.textContent = 'Step ' + (step+1) + ' of 3';
                titleEl.textContent = steps[step].title;
                descEl.textContent = steps[step].desc;
                progressFill.style.width = ((step+1)/3*100) + '%';
                nextBtn.textContent = step === 2 ? 'Start scoring →' : 'Next →';
            }}
            function done() {{ overlay.remove(); localStorage.setItem('virallab-onboarding-done', '1'); }}
            overlay.querySelector('.btn-onboard-skip').onclick = done;
            nextBtn.onclick = function() {{ if (step < 2) {{ step++; updateStep(); }} else done(); }};
            overlay.querySelector('.onboarding-backdrop').onclick = function(e) {{ if (e.target === this) done(); }};
            document.body.appendChild(overlay);
        }})();
        </script>
    </div>
</body>
</html>"""


def _list_digests():
    if not OUTPUT.exists():
        return []
    files = []
    for f in OUTPUT.glob("*.md"):
        name = f.stem
        if name == "daily_news":
            files.append({"type": "daily_news", "file": f.name})
        elif name == "daily_news_zh":
            files.append({"type": "daily_news_zh", "file": f.name})
        elif name.startswith("digest_"):
            files.append({"type": "digest", "topic": name[7:], "file": f.name})
        elif name.startswith("raw_"):
            files.append({"type": "raw", "topic": name[4:], "file": f.name})
        elif name.startswith("videos_"):
            files.append({"type": "videos", "query": name[7:], "file": f.name})
        elif name.startswith("transcript_"):
            files.append({"type": "transcript", "video_id": name[10:], "file": f.name})
    return sorted(files, key=lambda x: x["file"])


@app.route("/api/digests")
def list_digests():
    return jsonify(_list_digests())


@app.route("/api/digests/<path:name>")
def get_digest(name):
    if ".." in name or "/" in name:
        return jsonify({"error": "Invalid path"}), 400
    path = OUTPUT / name
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    return send_from_directory(OUTPUT, name, mimetype="text/markdown")


@app.route("/api/export/<path:name>")
def api_export(name):
    """Export digest as Markdown, Notion, or Obsidian format."""
    if ".." in name or "/" in name:
        return jsonify({"error": "Invalid path"}), 400
    path = OUTPUT / name
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    fmt = request.args.get("format", "markdown").lower()
    content = path.read_text(encoding="utf-8", errors="replace")
    if fmt == "obsidian":
        content = "---\ntags: [virallab, trends]\n---\n\n" + content
    elif fmt == "notion":
        content = f"# ViralLab export\n\n*Exported for Notion*\n\n---\n\n" + content
    filename = path.stem + ".md"
    from flask import Response
    return Response(content, mimetype="text/markdown", headers={
        "Content-Disposition": f"attachment; filename={filename}",
    })


@app.route("/setup")
def view_setup():
    """Serve SETUP.md for API configuration instructions."""
    path = Path(__file__).parent / "SETUP.md"
    if not path.exists():
        return "SETUP.md not found", 404
    body = path.read_text(encoding="utf-8", errors="replace")
    try:
        from markdown import markdown
        html_body = markdown(body, extensions=["fenced_code", "tables"])
    except ImportError:
        html_body = f"<pre>{_html_escape(body)}</pre>"
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>ViralLab Setup</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600&display=swap" rel="stylesheet">
<style>body{{font-family:Poppins,sans-serif;max-width:720px;margin:2rem auto;padding:1.5rem;line-height:1.6;color:#2d4a2b}}
a{{color:#2d4a2b}} code{{background:#f5f2ed;padding:0.2rem 0.4rem;border-radius:4px;font-size:0.9em}}
pre{{background:#f5f2ed;padding:1rem;border-radius:8px;overflow-x:auto}}</style>
</head><body>{html_body}</body></html>""", 200, {"Content-Type": "text/html; charset=utf-8"}


def _render_full_digest(filename: str):
    """Render daily_news.md or daily_news_zh.md as styled Buffer-style cards in main app layout."""
    lang = "zh" if "zh" in filename else "en"
    path = OUTPUT / filename
    if not path.exists():
        return None
    _, parsed = parse_file(path)
    run_type = "daily_news_zh" if lang == "zh" else "daily_news"
    parsed = add_lifecycle_to_items(run_type, parsed[:60])

    updated_at = ""
    if (OUTPUT / "daily_news_updated.txt").exists():
        updated_at = (OUTPUT / "daily_news_updated.txt").read_text(encoding="utf-8").strip()

    INITIAL_SHOW = 10
    cards_html = ""
    for i, item in enumerate(parsed, 1):
        snip = item.get("snippet", "") or ""
        angles = generate_angles("", item.get("title", ""), snip, count=2, lang=lang)
        pills = "".join(f'<span class="pill-tag">{_html_escape(a)}</span>' for a in angles)
        life = item.get("lifecycle", "peaking")
        life_label = _t(f"lifecycle_{life}", lang) if life in ("rising", "peaking", "fading") else life
        life_tt = _lifecycle_tooltip_html(lang, life)
        hidden_class = " load-more-hidden" if i > INITIAL_SHOW else ""
        src = _get_source_for_item(item)
        snip_html = f'<p class="digest-card-snippet">{_html_escape(_sanitize_snippet(snip))}</p>' if snip else ""
        src_html = f'<p class="digest-card-source">Source: {_html_escape(src)}</p>' if src else ""
        cards_html += f'''<div class="digest-card{hidden_class}" data-digest-index="{i}">
            <div class="digest-card-header">
                <span class="digest-card-num">{i}</span>
                <h3 class="digest-card-title"><a href="{_html_escape(item["url"])}" target="_blank" rel="noopener">{_html_escape(item["title"])}</a></h3>
                <span class="lifecycle-wrap"><span class="lifecycle lifecycle-{life}">{_html_escape(life_label)}</span><span class="lifecycle-tooltip">{life_tt}</span></span>
            </div>
            {snip_html}
            {src_html}
            <div class="digest-card-pills">{pills}</div>
        </div>'''

    load_more_btn = ""
    if len(parsed) > INITIAL_SHOW:
        load_more_btn = f'''
        <button type="button" class="btn-load-more" id="digestLoadMore">{_t("load_more", lang)}</button>
        <script>
        (function() {{
            var btn = document.getElementById("digestLoadMore");
            var hidden = document.querySelectorAll(".digest-card.load-more-hidden");
            if (!btn || hidden.length === 0) return;
            btn.addEventListener("click", function() {{
                var toShow = 50;
                for (var i = 0; i < toShow && hidden.length > 0; i++) {{
                    hidden[0].classList.remove("load-more-hidden");
                    hidden = document.querySelectorAll(".digest-card.load-more-hidden");
                }}
                if (hidden.length === 0) btn.style.display = "none";
            }});
        }})();
        </script>'''

    title_t = _t("daily_news_title", lang)
    back_link = f'<p class="browse-more"><a href="/daily">← {_t("nav_daily", lang)}</a></p>'
    export_links = f'<p class="sources-label">Export: <a href="/api/export/{filename}?format=markdown">Markdown</a> · <a href="/api/export/{filename}?format=notion">Notion</a> · <a href="/api/export/{filename}?format=obsidian">Obsidian</a></p>'
    refresh_url = f"/daily/refresh?next=/view/{filename}"
    refresh_options = f'<p class="sources-label"><a href="{refresh_url}" class="refresh-link">{_t("refresh_now", lang)}</a> — {_t("refresh_desc", lang)}</p>'

    body = f"""
    <section>
        <div class="section-title">📅 {title_t} · {_t("full_digest_title", lang)}</div>
        <div class="content-meta">
            {refresh_options}
            <p class="sources-label">{_t("last_updated", lang)}: {_html_escape(updated_at)}</p>
            {export_links}
        </div>
        <div class="digest-top-section">
            {back_link}
        </div>
        <div class="digest-cards">{cards_html}</div>
        {load_more_btn}
    </section>
    """
    return _base(title_t, body, "/daily", lang=lang), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/view/<path:name>")
def view_digest(name):
    if ".." in name or "/" in name:
        return "Invalid path", 400
    path = OUTPUT / name
    if not path.exists():
        return "Not found", 404

    # Styled full digest for daily news
    if name in ("daily_news.md", "daily_news_zh.md"):
        result = _render_full_digest(name)
        if result:
            return result

    body = path.read_text(encoding="utf-8", errors="replace")
    escaped = _html_escape(body)
    export_links = f'''
    <p style="margin-bottom:1rem;font-size:0.9rem;">
        Export: <a href="/api/export/{_html_escape(name)}?format=markdown">Markdown</a> ·
        <a href="/api/export/{_html_escape(name)}?format=notion">Notion</a> ·
        <a href="/api/export/{_html_escape(name)}?format=obsidian">Obsidian</a>
    </p>
    '''
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{_html_escape(name)}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
</head>
<body style="font-family:Inter,sans-serif;max-width:720px;margin:2rem auto;padding:1.5rem;white-space:pre-wrap;background:#fafafa;color:#1a1a1a;line-height:1.6">
{export_links}
{escaped}
</body></html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/api/video-to-text", methods=["POST"])
def api_video_to_text():
    url = (request.form.get("url") or request.json.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Missing url"}), 400
    vid = extract_youtube_id(url)
    if not vid:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    transcript, caption_source = _fetch_transcript_prefer_manual(vid, "en")
    if not transcript:
        return jsonify({"error": "No captions available", "hint": "Video may not have captions"}), 400

    score = score_berger(transcript)
    lang = _get_lang()
    stepps = _score_to_stepps(score.get("breakdown", {}), lang)
    title = (transcript[:80] + "…") if len(transcript) > 80 else transcript
    md = _build_markdown_export(
        url=url,
        title=title,
        score=score["total"],
        stepps=stepps,
        transcript=transcript,
        magic_words=score.get("magic_words_found", []),
    )
    OUTPUT.mkdir(exist_ok=True)
    out_file = OUTPUT / f"transcript_{vid}.md"
    out_file.write_text(md, encoding="utf-8")
    return jsonify({
        "file": out_file.name,
        "url": f"/view/{out_file.name}",
        "score": score["total"],
        "caption_source": caption_source,
    })


@app.route("/china-access")
def china_access():
    """China access guide (VPN, sources)."""
    path = Path(__file__).parent / "CHINA_ACCESS.md"
    if not path.exists():
        return "China access guide not found", 404
    body = path.read_text(encoding="utf-8", errors="replace")
    escaped = _html_escape(body)
    content = f'<section><pre style="white-space:pre-wrap;font-size:0.95rem;">{escaped}</pre></section>'
    return _base("China Access", content, ""), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/api/china-platforms")
def api_china_platforms():
    """China platform search links."""
    from src.china_sources import CHINA_PLATFORM_LINKS, get_china_search_url
    query = request.args.get("q", "viral trending").strip()
    return jsonify({
        "query": query,
        "platforms": [
            {"id": k, "name": v["name"], "url": get_china_search_url(k, query), "desc": v["desc"]}
            for k, v in CHINA_PLATFORM_LINKS.items()
        ],
    })


@app.route("/api")
def api_info():
    return jsonify({
        "name": "ViralLab API",
        "version": "1.0",
        "tagline": TAGLINE,
        "endpoints": {
            "digests": "/api/digests",
            "get": "/api/digests/<filename>",
            "export": "/api/export/<filename>?format=markdown|notion|obsidian",
            "video_to_text": "POST /api/video-to-text",
            "viral_videos": "GET /api/viral-videos?q=<query>&source=global|china",
            "health": "/api/health",
            "refresh_daily": "GET /api/refresh-daily (for cron)",
            "refresh_videos": "GET /api/refresh-videos (for cron)",
        },
    })


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "project": "virallab"})


def _run_refresh_daily():
    """Run daily news refresh (subprocess). Used by API and scheduler."""
    script = Path(__file__).parent / "scripts" / "daily_news.py"
    env = _env_no_proxy()
    env["PYTHONPATH"] = str(Path(__file__).parent)
    proc = subprocess.Popen(
        [sys.executable, str(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=Path(__file__).parent,
    )
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise
    return proc.returncode == 0


@app.route("/api/refresh-daily")
def api_refresh_daily():
    """Refresh daily news. Manual or cron. Optional: ?key=CRON_SECRET for cron."""
    import os
    key = request.args.get("key", "")
    secret = os.environ.get("CRON_SECRET", "")
    if secret and key != secret:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        _run_refresh_daily()
        return jsonify({"status": "ok", "message": "Daily news refreshed"})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timeout"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/refresh-videos")
def api_refresh_videos():
    """Refresh viral videos (videos_trending_viral.md). Optional: ?key=CRON_SECRET for cron."""
    import os
    key = request.args.get("key", "")
    secret = os.environ.get("CRON_SECRET", "")
    if secret and key != secret:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        _run_refresh_videos()
        return jsonify({"status": "ok", "message": "Viral videos refreshed"})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timeout"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/search-news", methods=["POST"])
def api_search_news():
    """Search news by topic. Runs search in background, redirects immediately (avoids timeout on Render)."""
    topic = (request.form.get("topic") or request.args.get("topic") or "").strip()
    if not topic:
        return redirect("/news")
    _record_topic_search(topic)
    safe_topic = topic.replace(" ", "_")[:30]
    range_param = request.form.get("range") or request.args.get("range") or "1d"
    if range_param not in ("60m", "1d", "7d"):
        range_param = "1d"
    redirect_url = f"/news?topic={quote(safe_topic, safe='')}&range={range_param}"

    def _run_search():
        try:
            script = Path(__file__).parent / "scripts" / "search_only.py"
            env = _env_no_proxy()
            env["PYTHONPATH"] = str(Path(__file__).parent)
            subprocess.run([sys.executable, str(script), topic], check=True, env=env, cwd=Path(__file__).parent, timeout=45)
        except Exception:
            pass

    import threading
    threading.Thread(target=_run_search, daemon=True).start()
    return redirect(redirect_url)


STEPPS_ORDER = ["social_currency", "triggers", "emotion", "public", "practical", "stories"]
STEPPS_LABELS = {"social_currency": "Social Currency", "triggers": "Triggers", "emotion": "Emotion", "public": "Public", "practical": "Practical", "stories": "Stories"}
STEPPS_LABELS_ZH = {"social_currency": "社交货币", "triggers": "触发", "emotion": "情绪", "public": "公开", "practical": "实用", "stories": "故事"}
FIX_SUGGESTIONS = {
    "triggers": "Add a time/context anchor — 'Next time you open your feed…' — to boost Triggers.",
    "stories": "Wrap your core insight in a 3-part arc: Setup → Tension → Resolution.",
    "public": "Show social proof visually — crowd, screenshot, or 'join X people' framing.",
    "social_currency": "Add insider framing — 'most people don't know…' or exclusive angle.",
    "emotion": "Raise arousal: awe, excitement, or surprise in the hook.",
    "practical": "Add actionable steps — '3 ways to…' or specific how-to.",
}
FIX_SUGGESTIONS_ZH = {
    "triggers": "加时间/情境锚 —「下次打开动态时…」— 提升触发。",
    "stories": "用三段弧包装核心洞察：铺陈 → 张力 → 解决。",
    "public": "可视化社会证明 — 人群、截图或「加入 X 人」框架。",
    "social_currency": "加内行框架 —「多数人不知道…」或独家角度。",
    "emotion": "提高唤醒：开场用敬畏、兴奋或惊喜。",
    "practical": "加可执行步骤 —「3 种方法…」或具体 how-to。",
}


def _berger_interpretation(score: dict, lang: str = "en") -> str:
    """One-line interpretation: top 2 signals, weak 1, optional fix. For tooltip."""
    labels = STEPPS_LABELS_ZH if lang == "zh" else STEPPS_LABELS
    fix_map = FIX_SUGGESTIONS_ZH if lang == "zh" else FIX_SUGGESTIONS
    bd = score.get("breakdown", {})
    if not bd:
        return ""
    sorted_sigs = sorted(((k, v) for k, v in bd.items() if v > 0), key=lambda x: -x[1])
    top = [labels.get(k, k.replace("_", " ").title()) for k, _ in sorted_sigs[:2]]
    weak_key = min((k for k in STEPPS_ORDER if bd.get(k, 0) < 15), key=lambda k: bd.get(k, 20), default=None)
    weak = labels.get(weak_key, weak_key.replace("_", " ").title()) if weak_key else None
    fix = fix_map.get(weak_key, "") if weak_key else ""
    if lang == "zh":
        if top and weak:
            return f"强 {top[0]}" + (f" + {top[1]}" if len(top) > 1 else "") + (f"。弱于 {weak}。{fix}" if fix else f"。弱于 {weak}。")
        if top:
            return f"强 {top[0]}" + (f" + {top[1]}" if len(top) > 1 else "") + "。"
        return ""
    if top and weak:
        return f"Strong {top[0]}" + (f" + {top[1]}" if len(top) > 1 else "") + (f". Weak on {weak}. {fix}" if fix else f". Weak on {weak}.")
    if top:
        return f"Strong {top[0]}" + (f" + {top[1]}" if len(top) > 1 else "") + "."
    return ""


def _berger_breakdown_list(breakdown: dict, lang: str = "en") -> list:
    """Ordered list of {letter, name, score} for STEPPS bars."""
    labels = STEPPS_LABELS_ZH if lang == "zh" else STEPPS_LABELS
    letters = ["S", "T", "E", "P", "P", "S"]
    return [{"letter": letters[i], "name": labels.get(k, k.replace("_", " ").title()), "score": breakdown.get(k, 0)} for i, k in enumerate(STEPPS_ORDER)]


@app.route("/api/viral-videos", methods=["GET"])
def api_viral_videos():
    """Fetch viral videos. Query: q (search term). Source: global (default) or china."""
    lang = _get_lang()
    query = request.args.get("q", "viral trending").strip() or "viral trending"
    source = request.args.get("source", "global").lower()
    try:
        if source == "china":
            from src.video_tools import score_berger
            # Fetch via subprocess with no-proxy (fixes SOCKS/proxy blocking Bilibili)
            script = Path(__file__).parent / "scripts" / "fetch_bilibili_json.py"
            env = _env_no_proxy()
            env["PYTHONPATH"] = str(Path(__file__).parent)
            result = subprocess.run(
                [sys.executable, str(script), query, "20"],
                capture_output=True,
                text=True,
                env=env,
                cwd=Path(__file__).parent,
                timeout=25,
            )
            if result.returncode != 0:
                err = result.stderr.strip() or result.stdout.strip()
                try:
                    data = json.loads(err)
                    err = data.get("error", err)
                except json.JSONDecodeError:
                    pass
                raise RuntimeError(err)
            videos = json.loads(result.stdout)
        else:
            from src.video_tools import score_berger, extract_youtube_id
            # Fetch via subprocess with no-proxy (fixes connection refused when proxy is down)
            max_fetch = 24 if (lang == "en" and source == "global") else 12
            script = Path(__file__).parent / "scripts" / "fetch_videos_json.py"
            env = _env_no_proxy()
            env["PYTHONPATH"] = str(Path(__file__).parent)
            result = subprocess.run(
                [sys.executable, str(script), query, str(max_fetch)],
                capture_output=True,
                text=True,
                env=env,
                cwd=Path(__file__).parent,
                timeout=25,
            )
            if result.returncode != 0:
                err = result.stderr.strip() or result.stdout.strip()
                try:
                    data = json.loads(err)
                    err = data.get("error", err)
                except json.JSONDecodeError:
                    pass
                raise RuntimeError(err)
            videos = json.loads(result.stdout)
        out = []
        for v in videos:
            # English channels: only show English content (no CJK in title/desc)
            if lang == "en" and source == "global":
                title = v.get("title", "")
                desc = v.get("description", "") or ""
                if _has_cjk(title) or _has_cjk(desc):
                    continue
            text = f"{v.get('title', '')} {v.get('description', '')}"
            score = score_berger(text)
            title = v.get("title", "")
            desc = (v.get("description") or "")[:200]
            angles = generate_angles(query, title, desc, count=3, lang=lang)
            platform = "Bilibili" if source == "china" else "YouTube"
            views_int = v.get("views_int", 0) or 0
            berger_val = score["total"]
            interpretation = _berger_interpretation(score)
            breakdown_list = _berger_breakdown_list(score.get("breakdown", {}))
            out.append({
                "title": title,
                "url": v.get("url"),
                "platform": platform,
                "views": v.get("views") or str(views_int) or "0",
                "berger": berger_val,
                "magic": ", ".join(score["magic_words_found"]) or "—",
                "desc": (v.get("description") or "")[:150],
                "angles": angles,
                "interpretation": interpretation,
                "breakdown": breakdown_list,
            })
            if len(out) >= 12:
                break
        # Lang hint when Chinese UI user searches English topic on global source
        lang_hint = None
        if lang == "zh" and source == "global" and not _has_cjk(query):
            lang_hint = _t("viral_lang_hint", lang)

        return jsonify({"query": query, "source": source, "videos": out, "lang_hint": lang_hint})
    except subprocess.TimeoutExpired:
        return jsonify({"error": _t("viral_timeout", lang)}), 504
    except Exception as e:
        err_msg = str(e)
        # When china source fails, hint user to try global
        if source == "china":
            return jsonify({
                "error": err_msg,
                "china_unavailable": True,
                "china_hint": _t("viral_china_unavailable", lang),
            }), 500
        return jsonify({"error": err_msg}), 500


STEPPS_DESCRIPTIONS = {
    "social_currency": (
        ("People share things that make them look good, smart, and ahead of the curve.", "Does sharing this make me look knowledgeable?"),
        ("人们分享让自己看起来更聪明、更领先的内容。", "分享这个会让我显得有见识吗？"),
    ),
    "triggers": (
        ("Content that connects to people at the right time and context, so they think about it when it's relevant.", "Will I remember this at the right moment?"),
        ("内容在对的时间与情境连结人们，让他们在相关时想起。", "我会在对的时刻想起这个吗？"),
    ),
    "emotion": (
        ("When we care, we share. Awe, excitement, and other emotions drive sharing.", "Does this make me feel something shareable?"),
        ("我们在乎就会分享。敬畏、兴奋等情绪驱动分享。", "这会让我产生想分享的感受吗？"),
    ),
    "public": (
        ("Visible content gets copied. Public proof of use increases adoption.", "Can others see me sharing this?"),
        ("可见的内容会被模仿。公开使用证明提升采用。", "别人能看到我在分享这个吗？"),
    ),
    "practical": (
        ("People share things they find helpful and believe will benefit others.", "Will this genuinely help someone I know?"),
        ("人们分享觉得有用、相信能帮到别人的内容。", "这会真正帮到我认识的人吗？"),
    ),
    "stories": (
        ("Content wrapped in compelling stories—information travels as idle chatter.", "Is there a story I'd naturally retell?"),
        ("包装在引人入胜故事中的内容 — 信息随闲聊传播。", "有我会自然转述的故事吗？"),
    ),
}

# Berger research timeline for "Why it works"
BERGER_TIMELINE = [
    {"year": "1996", "tag": "Foundation", "title": "Wharton Chair appointment", "body": "Berger joins Wharton School of Business, University of Pennsylvania — beginning 25+ years of word-of-mouth research."},
    {"year": "2013", "tag": "Breakthrough", "title": "Contagious published", "body": "The STEPPS framework reaches #1 on NYT Bestseller list. Apple, Google, Nike begin applying the model internally."},
    {"year": "2016", "tag": "Expansion", "title": "Invisible Influence", "body": "Berger extends the model: social conformity and hidden behavioral triggers documented across 80+ peer-reviewed studies."},
    {"year": "2020", "tag": "Algorithm", "title": "The Catalyst", "body": "Barrier-removal mechanics formalized. Resistance is shown to be a stronger predictor of inaction than lack of motivation."},
    {"year": "2023", "tag": "Language", "title": "Magic Words", "body": "Linguistic analysis at scale: specific words shown to increase compliance, sharing, and persuasion by measurable margins."},
]


# Open Library cover IDs (cover_i) — reliable image URLs
BERGER_BOOKS = [
    {"title": "Contagious", "subtitle": "Why Things Catch On", "year": "2013", "cover_id": "12130640", "url": "https://jonahberger.com/books/contagious/", "unlocks": "The 6 principles that make ideas spread—used by Fortune 500 brands."},
    {"title": "Invisible Influence", "subtitle": "The Hidden Forces That Shape Behavior", "year": "2016", "cover_id": "8869123", "url": "https://jonahberger.com/books/invisible-influence/", "unlocks": "Why people copy, conform, and share—the hidden triggers."},
    {"title": "The Catalyst", "subtitle": "How to Change Anyone's Mind", "year": "2020", "cover_id": "9295723", "url": "https://jonahberger.com/books/the-catalyst/", "unlocks": "Remove resistance. Lower friction. Make change happen."},
    {"title": "Magic Words", "subtitle": "What to Say to Get Your Way", "year": "2023", "cover_id": "13170768", "url": "https://jonahberger.com/magic-words/", "unlocks": "One word can boost compliance 50%. We surface them."},
]


@app.route("/science")
def science():
    """Jonah Berger STEPPS explainer — How we score (v2)."""
    lang = _get_lang()
    stepps_data = [
        ("S", "science_v2_stepps_S_name", "science_v2_stepps_S_desc"),
        ("T", "science_v2_stepps_T_name", "science_v2_stepps_T_desc"),
        ("E", "science_v2_stepps_E_name", "science_v2_stepps_E_desc"),
        ("P", "science_v2_stepps_P1_name", "science_v2_stepps_P1_desc"),
        ("P", "science_v2_stepps_P2_name", "science_v2_stepps_P2_desc"),
        ("S", "science_v2_stepps_S2_name", "science_v2_stepps_S2_desc"),
    ]
    stepps_html = "".join(
        f'<div class="stepps-item"><div class="stepps-letter">{letter}</div><div><div class="stepps-name">{_html_escape(_t(nk, lang))}</div><div class="stepps-desc">{_html_escape(_t(dk, lang))}</div></div></div>'
        for letter, nk, dk in stepps_data
    )
    formula_rows = [
        ("science_v2_formula_r1", "science_v2_formula_pts1"),
        ("science_v2_formula_r2", "science_v2_formula_pts2"),
        ("science_v2_formula_r3", "science_v2_formula_pts3"),
        ("science_v2_formula_r4", "science_v2_formula_pts4"),
        ("science_v2_formula_r5", "science_v2_formula_pts5"),
        ("science_v2_formula_r6", "science_v2_formula_pts6"),
    ]
    formula_html = "".join(
        f'<div class="formula-row"><span>{_t(rk, lang)}</span><span class="formula-pts">{_t(pk, lang)}</span></div>'
        for rk, pk in formula_rows
    )
    hero = f'<header class="page-header"><h1 class="science-v2-h1">{_t("science_v2_title", lang)}</h1></header>'
    body = f"""
    <div class="science-wrap">
      <p class="science-v2-p">{_t("science_v2_intro1", lang)}</p>
      <p class="science-v2-p">{_t("science_v2_intro2", lang)}</p>

      <hr class="science-hr" />

      <div class="section-title">{_t("science_v2_who_berger", lang)}</div>
      <div class="berger-block">
        <div class="berger-name">{_html_escape(_t("science_v2_berger_name", lang))}</div>
        <div class="berger-role">{_html_escape(_t("science_v2_berger_role", lang))}</div>
        <div class="berger-facts">
          <div class="berger-fact"><span>📚</span><span>{_t("science_v2_berger_f1", lang)}</span></div>
          <div class="berger-fact"><span>🔬</span><span>{_t("science_v2_berger_f2", lang)}</span></div>
          <div class="berger-fact"><span>🏛</span><span>{_t("science_v2_berger_f3", lang)}</span></div>
          <div class="berger-fact"><span>📖</span><span>{_t("science_v2_berger_f4", lang)}</span></div>
        </div>
      </div>
      <p class="science-v2-p">{_t("science_v2_berger_p", lang)}</p>

      <hr class="science-hr" />

      <div class="section-title">{_t("science_v2_stepps_title", lang)}</div>
      <p class="science-v2-p">{_t("science_v2_stepps_intro", lang)}</p>
      <div class="stepps-list">{stepps_html}</div>

      <hr class="science-hr" />

      <div class="section-title">{_t("science_v2_formula_title", lang)}</div>
      <p class="science-v2-p">{_t("science_v2_formula_intro", lang)}</p>
      <div class="formula-block">{formula_html}</div>

      <hr class="science-hr" />

      <div class="honest-note">{_t("science_v2_honest", lang)}</div>

      <div class="bottom-links">
        <a href="/viral">{_html_escape(_t("science_v2_link_score", lang))}</a>
        <a href="/video-to-text">{_html_escape(_t("science_v2_link_transcript", lang))}</a>
      </div>
    </div>
    """
    return _base(_t("science_v2_page_title", lang), body, "/science", hero=hero, lang=lang), 200, {"Content-Type": "text/html; charset=utf-8"}


STEPPS_ORDER_TUPLES = [
    ("social_currency", "S", "Social Currency", "社交货币"),
    ("triggers", "T", "Triggers", "触发"),
    ("emotion", "E", "Emotion", "情绪"),
    ("public", "P", "Public", "公开"),
    ("practical", "P", "Practical", "实用"),
    ("stories", "S", "Stories", "故事"),
]


def _get_score_tier(score: int) -> str:
    if score >= 85:
        return "Highly Viral"
    if score >= 70:
        return "Strong Signal"
    if score >= 50:
        return "Moderate Potential"
    return "Weak Signal"


def _score_to_stepps(breakdown: dict, lang: str = "en") -> list[dict]:
    """Map score_berger breakdown to STEPPS array with letter, name, score, color."""
    out = []
    for key, letter, name_en, name_zh in STEPPS_ORDER_TUPLES:
        s = breakdown.get(key, 0)
        if s >= 15:
            color = "#6a9e67"
        elif s >= 8:
            color = "#e8a54d"
        else:
            color = "#c0392b"
        name = name_zh if lang == "zh" else name_en
        out.append({"letter": letter, "name": name, "score": s, "color": color})
    return out


def _build_markdown_export(
    url: str,
    title: str,
    score: int,
    stepps: list[dict],
    transcript: str,
    magic_words: list[str],
) -> str:
    """Build AI-ready markdown string."""
    sorted_stepps = sorted(stepps, key=lambda s: s["score"], reverse=True)
    top2 = sorted_stepps[:2]
    weak = sorted_stepps[-1]
    top_names = " + ".join(s["name"] for s in top2)
    table_rows = "\n".join(
        f"| {s['name']} | {s['score']} | {round((s['score'] / 20) * 100)}% |"
        for s in stepps
    )
    remix_prompts = "\n".join([
        f'- "Rewrite as a Twitter/X thread using the top signals: {top_names}"',
        '"Extract the 5 most shareable moments from this transcript"',
        '"Write a YouTube title using Social Currency and Emotion signals"',
        '"Turn the hook into a 30-second Reels/Shorts script"',
    ])
    mw = ", ".join(magic_words) if magic_words else "None detected"
    return f"""# ViralLab Transcript Analysis

**Source:** {url}
**Title:** {title}
**Analysed by:** ViralLab · Berger STEPPS Framework

---

## Berger Score: {score}/100

| Signal | Score | /20 |
|--------|-------|-----|
{table_rows}

**Top signals:** {top_names}
**Weakest signal:** {weak["name"]}

### Fix suggestion
Add a recurring context anchor to boost {weak["name"]}:
*"Every time you sit down to plan content — think about this..."*

---

## Magic Words Detected
{mw}

---

## Transcript

{transcript}

---

## AI Remix Prompts

Use this transcript with any AI assistant:

{remix_prompts}

---
*Generated by ViralLab · Based on Jonah Berger's STEPPS framework*"""


def _fetch_transcript_prefer_manual(video_id: str, lang: str) -> tuple[str, str]:
    """Fetch transcript, preferring manual captions. Returns (transcript, caption_source)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        lang_codes = ["en", "zh", "zh-Hans", "zh-Hant"] if lang == "zh" else ["en", "en-US", "en-GB"]
        try:
            transcript_list = api.list(video_id)
            for code in lang_codes:
                try:
                    t = transcript_list.find_manually_created_transcript([code])
                    fetched = t.fetch()
                    text = " ".join(s.text for s in fetched.snippets)
                    return text, "creator-uploaded (manual)"
                except Exception:
                    pass
            for code in lang_codes:
                try:
                    t = transcript_list.find_generated_transcript([code])
                    fetched = t.fetch()
                    text = " ".join(s.text for s in fetched.snippets)
                    return text, "auto-generated"
                except Exception:
                    pass
        except Exception:
            pass
        fetched = api.fetch(video_id)
        if fetched and fetched.snippets:
            text = " ".join(s.text for s in fetched.snippets)
            return text, "unknown"
    except Exception:
        pass
    return "", ""


@app.route("/video-to-text", methods=["GET", "POST"])
def video_to_text():
    lang = _get_lang()
    msg = ""
    result = None
    if request.method == "POST":
        url = (request.form.get("url") or "").strip()
        if url:
            vid = extract_youtube_id(url)
            if vid:
                try:
                    transcript, caption_source = _fetch_transcript_prefer_manual(vid, lang)
                    if not transcript:
                        msg = "No captions available for this video."
                    else:
                        score_data = score_berger(transcript)
                        stepps = _score_to_stepps(score_data.get("breakdown", {}), lang)
                        sorted_stepps = sorted(stepps, key=lambda s: s["score"], reverse=True)
                        top2 = sorted_stepps[:2]
                        weak = sorted_stepps[-1]
                        top_names = [s["name"] for s in top2]
                        title = (transcript[:80] + "…") if len(transcript) > 80 else transcript
                        fix_suggestion = (
                            f'Add a recurring context anchor to boost {weak["name"]}: '
                            f'<em>"Every time you sit down to plan content — think about this..."</em>'
                        )
                        markdown = _build_markdown_export(
                            url=url,
                            title=title,
                            score=score_data["total"],
                            stepps=stepps,
                            transcript=transcript,
                            magic_words=score_data.get("magic_words_found", []),
                        )
                        result = {
                            "url": url,
                            "title": title,
                            "transcript": transcript,
                            "score": score_data["total"],
                            "tier": _get_score_tier(score_data["total"]),
                            "stepps": stepps,
                            "top_names": top_names,
                            "weak_name": weak["name"],
                            "fix": fix_suggestion,
                            "magic_words": score_data.get("magic_words_found", []),
                            "markdown": markdown,
                            "caption_source": caption_source,
                        }
                        OUTPUT.mkdir(exist_ok=True)
                        out_file = OUTPUT / f"transcript_{vid}.md"
                        out_file.write_text(markdown, encoding="utf-8")
                except Exception as e:
                    msg = f"Error: {e}"
            else:
                msg = "Invalid YouTube URL"
        else:
            msg = "Enter a URL"

    transcript_files = [x for x in _list_digests() if x["type"] == "transcript"]
    transcript_list = ""
    for x in transcript_files:
        transcript_list += f'<li><a href="/view/{_html_escape(x["file"])}">{_html_escape(x["file"])}</a></li>'

    v2t_styles = """
    .v2t-wrap{max-width:100%;margin:0;padding:0 0 100px;}
    .v2t-page-header{margin-bottom:32px;}
    .v2t-page-header h1{font-size:22px;font-weight:700;letter-spacing:-0.01em;margin-bottom:8px;color:var(--ink);}
    .v2t-page-header p{font-size:14px;color:var(--muted);line-height:1.65;max-width:480px;}
    .v2t-accuracy-note{font-size:13px;color:var(--muted);line-height:1.65;padding:12px 16px;background:var(--cream-dark);border-radius:var(--radius);margin-bottom:28px;}
    .v2t-accuracy-note strong{color:var(--ink);font-weight:600;}
    .v2t-form-block{margin-bottom:12px;}
    .v2t-input-row{display:flex;gap:8px;}
    .v2t-url-input{flex:1;font-family:inherit;font-size:14px;padding:11px 14px;border:1.5px solid var(--border);border-radius:var(--radius);background:var(--card);outline:none;}
    .v2t-url-input:focus{border-color:var(--accent-light);box-shadow:0 0 0 3px rgba(106,158,103,0.1);}
    .v2t-submit-btn{font-family:inherit;font-size:14px;font-weight:600;background:var(--cta);color:var(--cta-text);border:none;border-radius:var(--radius);padding:11px 22px;cursor:pointer;white-space:nowrap;}
    .v2t-submit-btn:hover{background:#f5b960;transform:translateY(-1px);}
    .v2t-form-hint{font-size:12px;color:var(--muted-light);margin-top:8px;}
    .v2t-form-hint code{font-family:monospace;font-size:11px;background:var(--cream-dark);padding:1px 5px;border-radius:3px;color:var(--muted);}
    .v2t-result-section{display:none;margin-top:28px;}
    .v2t-result-section.visible{display:block;}
    .v2t-score-summary{display:flex;align-items:center;gap:16px;padding:16px 20px;background:var(--card);border:1px solid var(--border);border-radius:var(--radius);margin-bottom:16px;}
    .v2t-score-num{font-size:36px;font-weight:800;color:var(--cta-dark);line-height:1;flex-shrink:0;}
    .v2t-score-meta{flex:1;}
    .v2t-score-tier{font-size:14px;font-weight:600;color:var(--ink);margin-bottom:3px;}
    .v2t-score-detail{font-size:13px;color:var(--muted);line-height:1.5;}
    .v2t-score-fix{font-size:12px;color:var(--muted);margin-top:6px;padding:8px 12px;background:var(--cta-pale);border-left:2px solid var(--cta);border-radius:0 var(--radius) var(--radius) 0;}
    .v2t-score-fix strong{color:var(--cta-dark);}
    .v2t-stepps-mini{display:flex;gap:3px;margin-top:10px;}
    .v2t-sm-wrap{flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;}
    .v2t-sm-bar{width:100%;height:28px;background:var(--cream-dark);border-radius:2px;position:relative;overflow:hidden;}
    .v2t-sm-fill{position:absolute;bottom:0;left:0;right:0;border-radius:2px;animation:v2tUp 0.9s cubic-bezier(.4,0,.2,1) forwards;animation-delay:var(--d,0s);}
    @keyframes v2tUp{from{height:0}to{height:var(--h)}}
    .v2t-sm-ltr{font-size:9px;font-weight:700;color:var(--muted-light);}
    .v2t-result-tabs{display:flex;gap:2px;border-bottom:1px solid var(--border);margin-bottom:0;}
    .v2t-r-tab{font-size:13px;font-weight:500;color:var(--muted);padding:9px 16px;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px;}
    .v2t-r-tab.active{color:var(--accent);border-bottom-color:var(--accent);font-weight:600;}
    .v2t-r-content{display:none;}
    .v2t-r-content.active{display:block;}
    .v2t-transcript-box{background:var(--card);border:1px solid var(--border);border-top:none;border-radius:0 0 var(--radius) var(--radius);padding:18px 20px;max-height:380px;overflow-y:auto;font-size:14px;line-height:1.8;}
    .v2t-transcript-box p{margin-bottom:6px;}
    .v2t-markdown-box{background:#1e2a1e;border:1px solid #2d4a2b;border-top:none;border-radius:0 0 var(--radius) var(--radius);padding:18px 20px;max-height:380px;overflow-y:auto;font-family:monospace;font-size:12.5px;line-height:1.8;color:#b8d4b5;white-space:pre-wrap;}
    .v2t-action-row{display:flex;justify-content:flex-end;gap:8px;padding:8px 12px;background:var(--cream-dark);border:1px solid var(--border);border-top:none;border-radius:0 0 var(--radius) var(--radius);}
    .v2t-act-btn{font-family:inherit;font-size:12px;font-weight:600;padding:6px 14px;border-radius:var(--radius);cursor:pointer;}
    .v2t-act-btn.solid{background:var(--accent);color:#fff;border:none;}
    .v2t-act-btn.solid:hover{background:var(--accent-mid);}
    .v2t-act-btn.outline{background:transparent;color:var(--muted);border:1px solid var(--border);}
    .v2t-act-btn.outline:hover{color:var(--accent);border-color:var(--accent-light);}
    .v2t-small-notes{margin-top:32px;border-top:1px solid var(--border);padding-top:20px;display:flex;flex-direction:column;gap:10px;}
    .v2t-note-item{display:grid;grid-template-columns:18px 1fr;gap:10px;font-size:13px;color:var(--muted);line-height:1.55;}
    .v2t-note-item strong{color:var(--ink);font-weight:600;}
    .v2t-bottom-links{margin-top:28px;display:flex;gap:16px;font-size:13px;}
    .v2t-bottom-links a{color:var(--accent-light);text-decoration:none;}
    .v2t-bottom-links a:hover{text-decoration:underline;}
    @media (max-width:480px){.v2t-input-row{flex-direction:column;}}
    """

    if result:
        stepps_html = "".join(
            f'<div class="v2t-sm-wrap" title="{_html_escape(s["name"])}">'
            f'<div class="v2t-sm-bar"><div class="v2t-sm-fill" style="--h:{(s["score"]/20)*100}%;--d:{i*0.08}s;background:{s["color"]}"></div></div>'
            f'<div class="v2t-sm-ltr">{s["letter"]}</div></div>'
            for i, s in enumerate(result["stepps"])
        )
        top_name = result["top_names"][0] if result["top_names"] else ""
        weak_name = result["weak_name"]
        if len(result["top_names"]) >= 2:
            detail_text = f"{top_name} + {result['top_names'][1]} firing. {weak_name} is weakest."
        else:
            detail_text = f"{top_name} is strongest · {weak_name} is weakest."
        transcript = result["transcript"]
        transcript_paras = "".join(
            f"<p>{_html_escape(p)}</p>"
            for p in transcript.split("\n") if p.strip()
        ) if "\n" in transcript else f"<p>{_html_escape(transcript)}</p>"
        markdown_escaped = _html_escape(result["markdown"])
        download_title = (result["title"] or "transcript").replace(" ", "-")[:50]
        download_title = "".join(c for c in download_title if c.isalnum() or c in "-_") or "transcript"
        fix_html = f'<strong>Quick fix:</strong> {result["fix"]}'
        result_html = f"""
        <div class="v2t-result-section visible" id="v2tResult">
            <div class="v2t-score-summary">
                <div class="v2t-score-num">{result["score"]}</div>
                <div class="v2t-score-meta">
                    <div class="v2t-score-tier">{_html_escape(result["tier"])}</div>
                    <div class="v2t-score-detail">{_html_escape(detail_text)}</div>
                    <div class="v2t-stepps-mini">{stepps_html}</div>
                </div>
            </div>
            <div class="v2t-score-fix">{fix_html}</div>
            <div style="margin-top:16px;">
                <div class="v2t-result-tabs">
                    <div class="v2t-r-tab active" data-tab="transcript" onclick="v2tSwitchTab('transcript')">Transcript</div>
                    <div class="v2t-r-tab" data-tab="markdown" onclick="v2tSwitchTab('markdown')">Markdown</div>
                </div>
                <div class="v2t-r-content active" id="v2tTabTranscript">
                    <div class="v2t-transcript-box" id="v2tTranscriptContent">{transcript_paras}</div>
                    <div class="v2t-action-row"><button class="v2t-act-btn outline" onclick="v2tCopy('v2tTranscriptContent')">Copy</button></div>
                </div>
                <div class="v2t-r-content" id="v2tTabMarkdown">
                    <div class="v2t-markdown-box" id="v2tMarkdownContent">{markdown_escaped}</div>
                    <div class="v2t-action-row">
                        <button class="v2t-act-btn outline" onclick="v2tCopyMarkdown()">Copy</button>
                        <button class="v2t-act-btn solid" onclick="v2tDownload()">Download .md</button>
                    </div>
                </div>
            </div>
            <textarea id="v2tMarkdownData" style="display:none">{_html_escape(result["markdown"])}</textarea>
            <script>window.v2tDownloadTitle={json.dumps(download_title)};</script>
        </div>"""
    else:
        result_html = '<div class="v2t-result-section" id="v2tResult"></div>'

    body = f"""
    <style>{v2t_styles}</style>
    <div class="v2t-wrap">
        <div class="v2t-page-header">
            <h1>📝 {_html_escape(_t("video2text_title", lang))}</h1>
            <p>{_html_escape(_t("video2text_tagline", lang))}</p>
        </div>
        <div class="v2t-accuracy-note">{_t("video2text_accuracy_note", lang)}</div>
        <div class="v2t-form-block">
            <form method="post">
                <div class="v2t-input-row">
                    <input type="url" name="url" class="v2t-url-input" placeholder="{_html_escape(_t("video2text_placeholder", lang))}" value="{_html_escape(result["url"]) if result else ""}" required>
                    <button type="submit" class="v2t-submit-btn">{_html_escape(_t("video2text_btn", lang))}</button>
                </div>
                <div class="v2t-form-hint">{_html_escape(_t("video2text_hint", lang))}<code>https://www.youtube.com/watch?v=dQw4w9WgXcQ</code></div>
            </form>
        </div>
        {f'<p class="muted" style="margin-bottom:1rem;">{_html_escape(msg)}</p>' if msg else ''}
        {result_html}
        <div class="v2t-small-notes">
            <div class="v2t-note-item"><span>💡</span><span>{_t("video2text_note1", lang)}</span></div>
            <div class="v2t-note-item"><span>🤖</span><span>{_t("video2text_note2", lang)}</span></div>
            <div class="v2t-note-item"><span>🌏</span><span>{_t("video2text_note3", lang)}</span></div>
        </div>
        <div class="v2t-bottom-links">
            <a href="/science">{_html_escape(_t("video2text_how_score", lang))}</a>
            <a href="/viral">{_html_escape(_t("video2text_find", lang))}</a>
        </div>
    </div>
    <script>
    function v2tSwitchTab(name){{
        document.querySelectorAll('.v2t-r-tab').forEach(function(t){{ t.classList.toggle('active', t.dataset.tab===name); }});
        document.querySelectorAll('.v2t-r-content').forEach(function(c){{ c.classList.toggle('active', c.id==='v2tTab'+name.charAt(0).toUpperCase()+name.slice(1)); }});
    }}
    function v2tCopy(id){{ navigator.clipboard.writeText(document.getElementById(id).innerText); }}
    function v2tCopyMarkdown(){{ var ta=document.getElementById('v2tMarkdownData'); if(ta) navigator.clipboard.writeText(ta.value); }}
    function v2tDownload(){{
        var ta=document.getElementById('v2tMarkdownData');
        if(!ta) return;
        var blob=new Blob([ta.value],{{type:'text/markdown'}});
        var a=document.createElement('a'); a.href=URL.createObjectURL(blob);
        a.download=(window.v2tDownloadTitle||'transcript')+'.md';
        a.click();
    }}
    var r=document.getElementById('v2tResult');
    if(r&&r.classList.contains('visible')) r.scrollIntoView({{behavior:'smooth',block:'start'}});
    </script>
    """
    return _base(_t("video2text_title", lang), body, "/video-to-text", lang=lang), 200, {"Content-Type": "text/html; charset=utf-8"}


def _load_creator_fields(lang="en", region="global"):
    base = "creator_fields_zh" if lang == "zh" else "creator_fields"
    if region != "global":
        fname = f"{base}_{region}.json"
        path = Path(__file__).parent / fname
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    fname = f"{base}.json"
    path = Path(__file__).parent / fname
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if lang == "zh":
        path = Path(__file__).parent / "creator_fields.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _render_home():
    """Landing page with hero and links to sections."""
    lang = _get_lang()
    cards = [
        ("/daily", "📅", "link_daily", "link_daily_desc"),
        ("/field", "🎯", "link_field", "link_field_desc"),
        ("/news", "📰", "link_news", "link_news_desc"),
        ("/viral", "▶️", "link_viral", "link_viral_desc"),
        ("/video-to-text", "📝", "link_video2text", "link_video2text_desc"),
        ("/science", "📊", "link_science", "link_science_desc"),
    ]
    cards_html = "".join(
        f'<a href="{href}" class="page-link-card"><span class="page-link-icon">{icon}</span>'
        f'<strong>{_html_escape(_t(title_key, lang))}</strong>'
        f'<small>{_html_escape(_t(desc_key, lang))}</small></a>'
        for href, icon, title_key, desc_key in cards
    )
    body = f'<section class="page-links">{cards_html}</section>'
    return _base(_t("home_title", lang), body, "/", hero=_hero_html(lang), lang=lang), 200, {"Content-Type": "text/html; charset=utf-8"}


def _render_daily():
    """Daily News page only. Uses lang for UI and content (EN vs ZH). Fallback to EN when ZH empty."""
    lang = _get_lang()
    items = _list_digests()
    news_type = "daily_news_zh" if lang == "zh" else "daily_news"
    daily_news_file = next((x for x in items if x["type"] == news_type), None)
    # When zh has no content, fallback to EN so page loads with something
    if lang == "zh" and daily_news_file:
        _, pre_parsed = parse_file(OUTPUT / daily_news_file["file"])
        if not pre_parsed:
            daily_news_file = next((x for x in items if x["type"] == "daily_news"), None)
            news_type = "daily_news" if daily_news_file else "daily_news_zh"
    elif lang == "zh" and not daily_news_file:
        daily_news_file = next((x for x in items if x["type"] == "daily_news"), None)
        news_type = "daily_news" if daily_news_file else "daily_news_zh"
    daily_cards = []
    if daily_news_file:
        path = OUTPUT / daily_news_file["file"]
        _, parsed = parse_file(path)
        run_type = "daily_news_zh" if lang == "zh" else "daily_news"
        parsed = add_lifecycle_to_items(run_type, parsed[:3])
        for item in parsed:
            snip = item.get("snippet", "") or ""
            angles = generate_angles("", item.get("title", ""), snip, count=2, lang=lang)
            angles_html = "".join(f'<li>{_html_escape(a)}</li>' for a in angles)
            life = item.get("lifecycle", "peaking")
            life_label = _t(f"lifecycle_{life}", lang) if life in ("rising", "peaking", "fading") else life
            life_tt = _lifecycle_tooltip_html(lang, life)
            src = _get_source_for_item(item)
            snip_html = f'<p class="card-snippet">{_html_escape(_sanitize_snippet(snip))}</p>' if snip else ""
            src_html = f'<p class="card-source">Source: {_html_escape(src)}</p>' if src else ""
            daily_cards.append(f'''<div class="card">
                <div class="card-header"><h3><a href="{_html_escape(item["url"])}" target="_blank" rel="noopener">{_html_escape(item["title"])}</a></h3><span class="lifecycle-wrap"><span class="lifecycle lifecycle-{life}">{_html_escape(life_label)}</span><span class="lifecycle-tooltip">{life_tt}</span></span></div>
                {snip_html}
                {src_html}
                <div class="angles-wrap"><span class="angles-label">{_html_escape(_t("content_angles", lang))}:</span><ul class="angles-list">{angles_html}</ul></div>
            </div>''')
    no_news_msg = f'<div class="card"><p class="muted">{_t("no_news", lang)} <code>python main.py --daily-news</code></p></div>'
    daily_html = "\n".join(daily_cards) if daily_cards else no_news_msg
    view_file = "daily_news_zh.md" if lang == "zh" else "daily_news.md"
    news_url = "/news?lang=zh" if lang == "zh" else "/news"
    browse_more = f'<p class="browse-more"><a href="/view/{view_file}">{_t("view_full_digest", lang)}</a> · <a href="{news_url}">{_t("search_by_topic", lang)}</a> — {_t("whats_happening", lang)}</p>' if daily_cards else ""
    sources_label = ""
    sources_fname = "daily_news_sources_zh.txt" if lang == "zh" else "daily_news_sources.txt"
    sources_file = OUTPUT / sources_fname
    if sources_file.exists():
        sources_text = sources_file.read_text(encoding="utf-8").strip()
        if sources_text:
            sources_label = f'<p class="sources-label">{_t("sources", lang)}: {_html_escape(sources_text)} — {_t("sources_curated", lang)}</p>'

    updated_label = ""
    updated_file = OUTPUT / "daily_news_updated.txt"
    if updated_file.exists():
        updated_label = f'<p class="sources-label">{_t("last_updated", lang)}: {_html_escape(updated_file.read_text(encoding="utf-8").strip())}</p>'

    refresh_options = f'<p class="sources-label"><a href="/daily/refresh" class="refresh-link">{_t("refresh_now", lang)}</a> — {_t("refresh_desc", lang)}</p>'

    title_t = _t("daily_news_title", lang)
    body = f"""
    <section>
        <div class="section-title">📅 {title_t}</div>
        <p class="section-desc muted">{_t("daily_news_desc", lang)}</p>
        <div class="content-meta">
            {refresh_options}
            {updated_label}
            {sources_label}
        </div>
        <div class="cards">{daily_html}</div>
        {browse_more}
    </section>
    """
    return _base(title_t, body, "/daily", lang=lang), 200, {"Content-Type": "text/html; charset=utf-8"}


def _render_field():
    """Your Field page only."""
    lang = _get_lang()
    region = _get_region()
    field_param = request.args.get("f", "").strip()
    creator_fields = _load_creator_fields(lang, region)
    cat_labels = [
        ("trends", _t("field_trends", lang)),
        ("color_forecasting", _t("field_color_forecasting", lang)),
        ("forecasting_sites", _t("field_forecasting_sites", lang)),
        ("resources", _t("field_resources", lang)),
    ]
    field_options = "".join(f'<option value="{k}"' + (' selected' if k == field_param else '') + f'>{_html_escape(v["name"])}</option>' for k, v in creator_fields.items())
    field_cards_html = ""
    if creator_fields:
        first_id = field_param if field_param in creator_fields else next(iter(creator_fields))
        first = creator_fields[first_id]
        for cat, label in cat_labels:
            items_list = first.get(cat, [])
            if items_list:
                field_cards_html += f'<div class="stepp"><h3>{_html_escape(label)}</h3><ul class="resource-list">'
                for r in items_list[:5]:
                    field_cards_html += f'<li><a href="{_html_escape(r["url"])}" target="_blank" rel="noopener">{_html_escape(r["name"])}</a> — {_html_escape(r.get("desc", ""))}</li>'
                field_cards_html += "</ul></div>"
        field_cards_html = field_cards_html or f'<p class="muted">{_t("field_select_above", lang)}</p>'

    cat_labels_js = json.dumps([[c, l] for c, l in cat_labels])
    empty_msg = _html_escape(_t("field_empty", lang))
    region_opts = [
        ("global", _t("field_region_global", lang)),
        ("americas", _t("field_region_americas", lang)),
        ("europe", _t("field_region_europe", lang)),
        ("asia", _t("field_region_asia", lang)),
    ]
    region_select = "".join(
        f'<option value="{r}"' + (' selected' if r == region else '') + f'>{_html_escape(l)}</option>'
        for r, l in region_opts
    )
    share_label = _html_escape(_t("field_share", lang))
    share_copied = _html_escape(_t("field_share_copied", lang))
    body = f"""
    <section>
        <div class="section-title">{_html_escape(_t("field_title", lang))}</div>
        <p class="section-desc muted">{_html_escape(_t("field_desc", lang))}</p>
        <div class="field-controls">
            <div class="field-control-group">
                <label class="field-control-label">{_html_escape(_t("field_region", lang))}</label>
                <select class="field-select" id="regionSelect" onchange="setRegion(this.value)">
                    {region_select}
                </select>
            </div>
            <div class="field-control-group">
                <label class="field-control-label">&nbsp;</label>
                <select class="field-select" id="fieldSelect" onchange="updateField(this.value); updateShareUrl();">
                    {field_options}
                </select>
            </div>
            <div class="field-control-group field-share-wrap">
                <div class="share-dropdown">
                    <button type="button" class="btn-share" id="shareBtn" title="{share_label}">↗ {share_label}</button>
                    <div class="share-panel" id="sharePanel">
                        <span class="share-panel-label">{_html_escape(_t("field_share_to", lang))}</span>
                        <a class="share-link" href="#" data-platform="whatsapp" target="_blank" rel="noopener">{_html_escape(_t("field_share_whatsapp", lang))}</a>
                        <a class="share-link" href="#" data-platform="telegram" target="_blank" rel="noopener">{_html_escape(_t("field_share_telegram", lang))}</a>
                        <a class="share-link" href="#" data-platform="x" target="_blank" rel="noopener">{_html_escape(_t("field_share_x", lang))}</a>
                        <a class="share-link" href="#" data-platform="linkedin" target="_blank" rel="noopener">{_html_escape(_t("field_share_linkedin", lang))}</a>
                        <button type="button" class="share-link share-copy" data-platform="copy">{_html_escape(_t("field_share_copy", lang))}</button>
                    </div>
                </div>
                <span class="share-feedback" id="shareFeedback"></span>
            </div>
        </div>
        <div id="fieldResources" class="stepps-grid">{field_cards_html}</div>
    </section>
    <script>
    const fields = {json.dumps(creator_fields)};
    const catLabels = {cat_labels_js};
    const emptyMsg = {json.dumps(empty_msg)};
    const shareCopied = {json.dumps(share_copied)};
    const baseUrl = window.location.origin + '/field';
    function updateShareUrl() {{
        const f = document.getElementById('fieldSelect').value;
        const r = document.getElementById('regionSelect').value;
        let url = baseUrl;
        const params = [];
        if (f) params.push('f=' + encodeURIComponent(f));
        if (r && r !== 'global') params.push('region=' + encodeURIComponent(r));
        if (params.length) url += '?' + params.join('&');
        return url;
    }}
    function updateField(id) {{
        const f = fields[id];
        if (!f) return;
        let html = '';
        for (const [cat, label] of catLabels) {{
            const items = f[cat] || [];
            if (items.length) {{
                html += '<div class="stepp"><h3>' + label + '</h3><ul class="resource-list">';
                items.slice(0,5).forEach(r => html += '<li><a href="' + r.url + '" target="_blank">' + r.name + '</a> — ' + (r.desc||'') + '</li>');
                html += '</ul></div>';
            }}
        }}
        document.getElementById('fieldResources').innerHTML = html || '<p class="muted">' + emptyMsg + '</p>';
    }}
    function setRegion(val) {{
        const f = document.getElementById('fieldSelect').value;
        let next = '/field';
        if (f) next += '?f=' + encodeURIComponent(f);
        if (val !== 'global') next += (next.indexOf('?') >= 0 ? '&' : '?') + 'region=' + encodeURIComponent(val);
        window.location = '/set-region?region=' + encodeURIComponent(val) + '&next=' + encodeURIComponent(next);
    }}
    const shareText = {json.dumps(_t("field_share_text", lang))};
    document.getElementById('shareBtn').addEventListener('click', function(e) {{
        e.stopPropagation();
        document.getElementById('sharePanel').classList.toggle('share-panel-open');
    }});
    document.addEventListener('click', function() {{ document.getElementById('sharePanel').classList.remove('share-panel-open'); }});
    document.getElementById('sharePanel').addEventListener('click', function(e) {{ e.stopPropagation(); }});
    document.querySelectorAll('.share-link').forEach(function(el) {{
        el.addEventListener('click', function(e) {{
            e.preventDefault();
            const url = updateShareUrl();
            const platform = el.getAttribute('data-platform');
            const text = shareText + ' ' + url;
            let shareUrl = '';
            if (platform === 'whatsapp') shareUrl = 'https://wa.me/?text=' + encodeURIComponent(text);
            else if (platform === 'telegram') shareUrl = 'https://t.me/share/url?url=' + encodeURIComponent(url) + '&text=' + encodeURIComponent(shareText);
            else if (platform === 'x') shareUrl = 'https://twitter.com/intent/tweet?url=' + encodeURIComponent(url) + '&text=' + encodeURIComponent(shareText);
            else if (platform === 'linkedin') shareUrl = 'https://www.linkedin.com/sharing/share-offsite/?url=' + encodeURIComponent(url);
            else if (platform === 'copy') {{
                navigator.clipboard.writeText(url).then(function() {{
                    document.getElementById('shareFeedback').textContent = shareCopied;
                    setTimeout(function() {{ document.getElementById('shareFeedback').textContent = ''; }}, 2000);
                }});
                document.getElementById('sharePanel').classList.remove('share-panel-open');
                return;
            }}
            if (shareUrl) {{ window.open(shareUrl, '_blank', 'noopener,noreferrer,width=600,height=500'); }}
            document.getElementById('sharePanel').classList.remove('share-panel-open');
        }});
    }});
    </script>
    """
    og_title = _t("field_title", lang)
    og_desc = _t("field_desc", lang)
    return _base(_t("nav_field", lang), body, "/field", lang=lang, og_title=og_title, og_desc=og_desc), 200, {"Content-Type": "text/html; charset=utf-8"}


def _render_news():
    """News by topic page only."""
    lang = _get_lang()
    items = _list_digests()
    news_files = [x for x in items if x["type"] == "raw"]
    topic_filter = (request.args.get("topic") or "").strip().replace(" ", "_")
    if topic_filter:
        news_files = [x for x in news_files if (x.get("topic") or "").replace(" ", "_") == topic_filter]
    if lang == "zh":
        news_files = [x for x in news_files if _has_cjk(x.get("topic", ""))]
        if topic_filter and not _has_cjk(topic_filter):
            news_html_override = True
        else:
            news_html_override = False
    else:
        news_files = [x for x in news_files if not _has_cjk(x.get("topic", ""))]
        if topic_filter and _has_cjk(topic_filter):
            news_html_override = True
        else:
            news_html_override = False
    news_cards = []
    time_range = request.args.get("range", "1d")
    if time_range not in ("60m", "1d", "7d"):
        time_range = "1d"
    range_labels = {"60m": _t("news_range_60m", lang), "1d": _t("news_range_1d", lang), "7d": _t("news_range_7d", lang)}
    search_form = f'''
        <form method="post" action="/api/search-news" class="form">
            <input type="hidden" name="range" value="{_html_escape(time_range)}">
            <input type="text" name="topic" placeholder="{_html_escape(_t("news_placeholder", lang))}" required>
            <button type="submit">{_t("search_by_topic", lang)}</button>
        </form>'''
    force_hot = request.args.get("refresh_hot") == "1"
    tip_topics, tip_source, hot_cache_age = _get_most_searched(limit=10, time_range=time_range, lang=lang, force_hot_refresh=force_hot)
    tip_chips = "".join(
        f'<form method="post" action="/api/search-news" class="tip-chip-form"><input type="hidden" name="topic" value="{_html_escape(t)}"><input type="hidden" name="range" value="{_html_escape(time_range)}"><button type="submit" class="tip-chip{" tip-chip-active" if topic_filter and t.replace(" ", "_")[:30] == topic_filter else ""}">{_html_escape(t)}</button></form>'
        for t in tip_topics[:10]
    )
    range_links = "".join(
        f'<a href="/news?range={r}" class="tip-range{" active" if r == time_range else ""}">{_html_escape(l)}</a>'
        for r, l in range_labels.items()
    )
    if tip_source == "platform":
        tip_label = _t("news_tip_platform_hot_en", lang) if lang == "en" else _t("news_tip_platform_hot", lang)
        hot_meta = ""
        if hot_cache_age is not None:
            refresh_url = "/news?refresh_hot=1" + ("&lang=en" if lang == "en" else "")
            if hot_cache_age < 60:
                hot_meta = f'<a href="{refresh_url}" class="refresh-link" title="{_t("news_refresh_hot", lang)}">↻ {_t("news_hot_just_now", lang)}</a>'
            else:
                mins = hot_cache_age // 60
                hot_meta = f'<a href="{refresh_url}" class="refresh-link" title="{_t("news_refresh_hot", lang)}">↻ {_t("news_hot_updated", lang).format(mins=mins)}</a>'
    elif tip_source == "app":
        tip_label = _t("news_tip_requested", lang).format(range=range_labels[time_range])
        hot_meta = ""
    else:
        tip_label = _t("news_tip_suggestions", lang)
        hot_meta = ""
    tip_card = f'''
        <div class="tip-card">
            <div class="tip-header">
                <span class="tip-label">{_html_escape(tip_label)}</span>
                <span class="tip-range-wrap">{range_links}{" · " + hot_meta if hot_meta else ""}</span>
            </div>
            <div class="tip-chips">{tip_chips}</div>
        </div>'''
    for x in news_files:
        path = OUTPUT / x["file"]
        _, parsed = parse_file(path)
        topic = x.get("topic", "").replace("_", " ")
        if not parsed and path.read_text(errors="replace").strip().startswith("# Search error"):
            news_cards.append(f'<div class="card card-error"><h3>{_html_escape(topic or x.get("topic", ""))}</h3><p class="muted">{_t("news_search_failed", lang)}</p></div>')
        else:
            if topic:
                news_cards.append(f'<div class="topic-label">{_t("news_topic_label", lang)}: {_html_escape(topic)}</div>')
            run_type = f"raw_{x.get('topic','')}" if x.get("topic") else "raw_unknown"
            parsed_life = add_lifecycle_to_items(run_type, parsed[:5])
            for item in parsed_life:
                snip = item.get("snippet", "") or ""
                angles = generate_angles(topic or "", item.get("title", ""), snip, count=2, lang=lang)
                angles_html = "".join(f'<li>{_html_escape(a)}</li>' for a in angles)
                life = item.get("lifecycle", "peaking")
                src = _get_source_for_item(item)
                snip_html = f'<p class="card-snippet">{_html_escape(_sanitize_snippet(snip))}</p>' if snip else ""
                src_label = _t("source", lang)
                src_html = f'<p class="card-source">{_html_escape(src_label)}: {_html_escape(src)}</p>' if src else ""
                life_label = _t(f"lifecycle_{life}", lang) if life in ("rising", "peaking", "fading") else life
                life_tt = _lifecycle_tooltip_html(lang, life)
                news_cards.append(f'''<div class="card">
                    <div class="card-header"><h3><a href="{_html_escape(item["url"])}" target="_blank" rel="noopener">{_html_escape(item["title"])}</a></h3><span class="lifecycle-wrap"><span class="lifecycle lifecycle-{life}">{_html_escape(life_label)}</span><span class="lifecycle-tooltip">{life_tt}</span></span></div>
                    {snip_html}
                    {src_html}
                    <div class="angles-wrap"><span class="angles-label">{_html_escape(_t("content_angles", lang))}:</span><ul class="angles-list">{angles_html}</ul></div>
                </div>''')

    if news_html_override:
        r = request.args.get("range", "1d")
        msg_key = "news_chinese_topic_in_en" if lang == "en" else "news_english_topic_in_zh"
        switch_url = f"/news?lang=zh&range={r}" if lang == "en" else f"/news?range={r}"
        news_html = f'<div class="card"><p class="muted">{_t(msg_key, lang)}</p><p class="browse-more"><a href="{switch_url}">{_t("news_show_all", lang)}</a></p></div>'
    else:
        if news_cards:
            news_html = "\n".join(news_cards)
        elif topic_filter:
            news_html = f'<div class="card"><p class="muted">{_t("news_searching", lang)}</p><p class="browse-more"><a href="{request.url}">↻ {_t("news_refresh_all", lang)}</a></p></div>'
        else:
            news_html = f'<div class="card"><p class="muted">{_t("news_no_results", lang)}</p></div>'

    refresh_label = _t("news_refresh_all", lang)
    refresh_interval = _t("news_refresh_interval", lang)
    refresh_meta = f'<div class="content-meta"><p class="sources-label"><a href="/news/refresh" class="refresh-link">{_html_escape(refresh_label)}</a> — {_html_escape(refresh_interval)}</p></div>'

    show_all_link = f'<p class="browse-more"><a href="/news?range={time_range}">{_html_escape(_t("news_show_all", lang))}</a></p>' if topic_filter else ""
    body = f"""
    <section>
        <div class="section-title">📰 {_html_escape(_t("news_title", lang))}</div>
        <p class="section-desc muted">{_html_escape(_t("news_desc", lang))}</p>
        {show_all_link}
        {search_form}
        {tip_card}
        {refresh_meta}
        <div class="cards">{news_html}</div>
    </section>
    """
    return _base(_t("news_title", lang), body, "/news", lang=lang), 200, {"Content-Type": "text/html; charset=utf-8"}


def _render_viral():
    """Viral Videos page only."""
    lang = _get_lang()
    items = _list_digests()
    video_files = [x for x in items if x["type"] == "videos"]
    video_cards = []
    for x in video_files:
        path = OUTPUT / x["file"]
        _, parsed = parse_file(path)
        query = x.get("query", "")
        run_type = f"videos_{query}" if query else "videos_unknown"
        parsed_life = add_lifecycle_to_items(run_type, parsed[:6])
        for item in parsed_life:
            berger_val = item.get("berger")
            berger_display = f"{berger_val}/100" if berger_val is not None else "—"
            berger_class = "high" if (berger_val or 0) >= 50 else "mid" if (berger_val or 0) >= 25 else "low"
            life = item.get("lifecycle", "peaking")
            life_label = _t(f"lifecycle_{life}", lang) if life in ("rising", "peaking", "fading") else life
            life_tt = _lifecycle_tooltip_html(lang, life)
            desc = item.get("desc", "") or ""
            url = item.get("url", "") or ""
            platform = "Bilibili" if "bilibili" in url else "YouTube"
            angles = generate_angles(query or "", item.get("title", ""), desc, count=2, lang=lang)
            angles_html = "".join(f'<li>{_html_escape(a)}</li>' for a in angles)
            video_cards.append(f'''<div class="card">
                <div class="card-header">
                    <h3><a href="{_html_escape(url)}" target="_blank" rel="noopener">{_html_escape(item["title"])}</a></h3>
                    <span class="badges"><span class="berger berger-{berger_class}" title="{_html_escape(_t("viral_berger_methodology", lang))}">{berger_display}</span><span class="lifecycle-wrap"><span class="lifecycle lifecycle-{life}">{_html_escape(life_label)}</span><span class="lifecycle-tooltip">{life_tt}</span></span></span>
                </div>
                <p class="card-source">{platform} · Views: {_html_escape(item["views"])} · Magic: {_html_escape(item["magic"]) or "—"}</p>
                <p class="card-snippet">{_html_escape(desc)}</p>
                <div class="angles-wrap"><span class="angles-label">{_html_escape(_t("content_angles", lang))}:</span><ul class="angles-list">{angles_html}</ul></div>
            </div>''')

    content_angles_label = _t("content_angles", lang)
    viral_suggestions_label = _t("viral_suggestions", lang)
    viral_loading_t = _t("viral_loading", lang)
    viral_empty_title_t = _t("viral_empty_title", lang)
    viral_empty_body_t = _t("viral_empty_body", lang)
    viral_error_t = _t("viral_error", lang)
    viral_china_hint_t = _t("viral_china_unavailable", lang)
    viral_timeout_t = _t("viral_timeout", lang)
    # When lang=zh, only show Bilibili content — never English YouTube
    if lang == "zh":
        video_cards = [c for c in video_cards if "bilibili" in c]
    video_html = "\n".join(video_cards) if video_cards else f'<div class="card empty-state-loading"><p class="muted"><span class="loader-spinner"></span> {_html_escape(viral_loading_t)}</p></div>'

    # Default source by language: zh → china, en → global
    default_source = "china" if lang == "zh" else "global"
    viral_tips = DEFAULT_VIRAL_TIPS_ZH if lang == "zh" else DEFAULT_VIRAL_TIPS
    tip_chips = "".join(
        f'<button type="button" class="tip-chip viral-tip-chip" data-query="{_html_escape(t)}">{_html_escape(t)}</button>'
        for t in viral_tips[:10]
    )

    search_form = f'''
        <form class="form" id="viralSearchForm">
            <input type="text" name="q" placeholder="{_html_escape(_t("viral_placeholder", lang))}" id="viralQuery">
            <button type="submit">{_html_escape(_t("viral_search_btn", lang))}</button>
        </form>'''
    source_select = f'''
        <label class="viral-source-label">{_html_escape(_t("viral_source_label", lang))}</label>
        <select name="source" id="viralSource" class="source-select viral-source-select">
            <option value="global"{' selected' if default_source == 'global' else ''}>{_html_escape(_t("viral_source_global", lang))}</option>
            <option value="china"{' selected' if default_source == 'china' else ''}>{_html_escape(_t("viral_source_china", lang))}</option>
        </select>'''
    tip_card = f'''
        <div class="tip-card">
            <div class="tip-header">
                <span class="tip-label">{_html_escape(viral_suggestions_label)}</span>
                <span class="tip-range-wrap viral-source-wrap">{source_select}</span>
            </div>
            <div class="tip-chips">{tip_chips}</div>
        </div>'''
    berger_methodology = _t("viral_berger_methodology", lang)
    viral_empty_suggestions = viral_tips[:6]
    source_desc = f'<p class="sources-label">{_html_escape(_t("viral_what_we_serve", lang))} {_html_escape(_t("viral_china_note", lang))}</p><p class="sources-label">{_html_escape(berger_methodology)}</p>'

    body = f"""
    <section>
        <div class="section-title">▶️ {_html_escape(_t("viral_title", lang))} · {_html_escape(_t("viral_subtitle", lang))}</div>
        <p class="section-desc muted">{_html_escape(_t("viral_desc", lang))}</p>
        {search_form}
        {tip_card}
        {source_desc}
        <div id="viralLangHint" class="card" style="display:none; margin-bottom:1rem; border-left:4px solid var(--accent);"></div>
        <div class="cards" id="viralVideos">{video_html}</div>
    </section>
    <script>
    (function initViral() {{
        const form = document.getElementById('viralSearchForm');
        const input = document.getElementById('viralQuery');
        if (!form || !input) return;
        document.body.addEventListener('click', function(e) {{
            const chip = e.target.closest('.viral-tip-chip');
            if (chip) {{
                e.preventDefault();
                e.stopPropagation();
                const q = chip.getAttribute('data-query') || '';
                input.value = q;
                form.dispatchEvent(new Event('submit', {{ bubbles: true }}));
            }}
        }}, true);
        const params = new URLSearchParams(location.search);
        const q = params.get('q');
        const isZh = document.documentElement.lang === 'zh';
        if (q) {{
            input.value = q;
            setTimeout(function() {{ form.dispatchEvent(new Event('submit', {{ bubbles: true }})); }}, 100);
        }} else {{
            input.value = isZh ? '热门' : 'viral trending';
            setTimeout(function() {{ form.dispatchEvent(new Event('submit', {{ bubbles: true }})); }}, 100);
        }}
    }})();
    document.getElementById('viralSearchForm')?.addEventListener('submit', async (e) => {{
        e.preventDefault();
        const q = document.getElementById('viralQuery').value || 'viral trending';
        const src = document.getElementById('viralSource')?.value || 'global';
        const el = document.getElementById('viralVideos');
        const hintEl = document.getElementById('viralLangHint');
        if (hintEl) {{ hintEl.style.display = 'none'; hintEl.innerHTML = ''; }}
        el.innerHTML = '<div class="card empty-state-loading"><p class="muted"><span class="loader-spinner"></span> ' + {json.dumps(viral_loading_t)} + '</p></div>';
        const FETCH_TIMEOUT = 15000;
        const ctrl = new AbortController();
        const t = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT);
        try {{
            const lang = document.documentElement.lang || 'en';
            const r = await fetch('/api/viral-videos?q=' + encodeURIComponent(q) + '&source=' + encodeURIComponent(src) + '&lang=' + encodeURIComponent(lang), {{ signal: ctrl.signal }});
            clearTimeout(t);
            const d = await r.json();
            if (d.error) {{
                const chinaHint = d.china_hint || '';
                const errHtml = chinaHint ? '<div class="card" style="border-left:4px solid var(--cta);"><p class="muted">' + chinaHint + '</p></div>' : '<p class="muted">' + {json.dumps(viral_error_t)} + ': ' + (d.error || '').replace(/</g, '&lt;') + '</p>';
                el.innerHTML = errHtml;
                return;
            }}
            if (d.lang_hint && hintEl) {{
                hintEl.innerHTML = '<p class="muted">' + d.lang_hint + '</p>';
                hintEl.style.display = 'block';
            }}
            let html = '';
            (d.videos || []).forEach(v => {{
                const bergerNum = v.berger;
                const bergerDisplay = (bergerNum != null && bergerNum !== '') ? (bergerNum + '/100') : '—';
                const bc = (bergerNum != null && bergerNum >= 50) ? 'high' : (bergerNum != null && bergerNum >= 25) ? 'mid' : 'low';
                const bergerTitle = (v.interpretation || '').trim() || {json.dumps(berger_methodology)};
                const angles = (v.angles || []).map(a => '<li>' + a + '</li>').join('');
                const anglesLabel = {json.dumps(content_angles_label)};
                const platform = v.platform || 'YouTube';
                const url = (v.url || '').trim();
                const hasUrl = url && (url.startsWith('http://') || url.startsWith('https://'));
                const titleEsc = (v.title || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                const titleEl = hasUrl ? '<a href="' + url.replace(/"/g, '&quot;') + '" target="_blank" rel="noopener">' + titleEsc + '</a>' : '<span>' + titleEsc + '</span>';
                html += '<div class="card"><div class="card-header"><h3>' + titleEl + '</h3><span class="badges"><span class="berger berger-' + bc + '" title="' + bergerTitle.replace(/"/g, '&quot;') + '">' + bergerDisplay + '</span></span></div><p class="card-source">' + platform + ' · Views: ' + (v.views || '') + ' · Magic: ' + (v.magic || '—') + '</p><p class="card-snippet">' + (v.desc || '').replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</p>' + (angles ? '<div class="angles-wrap"><span class="angles-label">' + anglesLabel + ':</span><ul class="angles-list">' + angles + '</ul></div>' : '') + '</div>';
            }});
            if (!d.videos || d.videos.length === 0) {{
                const suggestions = {json.dumps(viral_empty_suggestions)};
                const emptyTitle = {json.dumps(viral_empty_title_t)};
                const emptyBody = {json.dumps(viral_empty_body_t)};
                const emptyHtml = '<div class="empty-state"><div class="empty-state-icon">🔍</div><div class="empty-state-title">' + emptyTitle + '</div><p class="empty-state-body">' + emptyBody + '</p><div class="empty-state-chips">' + suggestions.map(s => '<button type="button" class="tip-chip viral-tip-chip" data-query="' + String(s).replace(/"/g, '&quot;') + '">' + s + '</button>').join('') + '</div></div>';
                el.innerHTML = emptyHtml;
            }} else {{
                el.innerHTML = html;
            }}
        }} catch (err) {{
            const errMsg = err.name === 'AbortError' ? {json.dumps(viral_timeout_t)} : (err.message || '');
            const chinaHint = {json.dumps(viral_china_hint_t)};
            const errHtml = (document.getElementById('viralSource')?.value === 'china') ? '<div class="card" style="border-left:4px solid var(--cta);"><p class="muted">' + chinaHint + '</p></div>' : '<p class="muted">' + {json.dumps(viral_error_t)} + ': ' + (errMsg || '').replace(/</g, '&lt;') + '</p>';
            el.innerHTML = errHtml;
        }}
    }});
    </script>
    """
    return _base(_t("viral_title", lang), body, "/viral", lang=lang), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/set-lang")
def set_lang():
    """Set language cookie and redirect. ?lang=zh|en&next=/daily"""
    lang = request.args.get("lang", "en")
    lang = "zh" if lang == "zh" else "en"
    next_url = request.args.get("next", "/")
    resp = make_response(redirect(next_url))
    resp.set_cookie("virallab-lang", lang, max_age=365 * 24 * 3600, path="/")
    return resp


@app.route("/set-region")
def set_region():
    """Set region cookie and redirect. ?region=global|americas|europe|asia&next=/field"""
    r = request.args.get("region", "global")
    r = r if r in ("global", "americas", "europe", "asia") else "global"
    next_url = request.args.get("next", "/field")
    if "//" in next_url or not next_url.startswith("/"):
        next_url = "/field"
    resp = make_response(redirect(next_url))
    resp.set_cookie("virallab-region", r, max_age=365 * 24 * 3600, path="/")
    return resp


@app.route("/", methods=["GET", "HEAD", "POST"])
def index():
    return _render_home()


@app.route("/campaign")
def campaign():
    return redirect("/")


@app.route("/daily")
def daily():
    return _render_daily()


@app.route("/daily/refresh")
def daily_refresh():
    """Manual refresh: run daily news fetch in background, redirect immediately."""
    next_url = request.args.get("next", "/daily")
    if next_url.startswith("/") and "//" not in next_url:
        pass  # safe relative path
    else:
        next_url = "/daily"
    import threading
    def _bg_refresh():
        try:
            _run_refresh_daily()
        except Exception:
            pass
    threading.Thread(target=_bg_refresh, daemon=True).start()
    return redirect(next_url)


def _run_refresh_videos():
    """Refresh trending viral videos (videos_trending_viral.md). Used by scheduler and /api/refresh-videos."""
    script = Path(__file__).parent / "scripts" / "video_trending.py"
    env = _env_no_proxy()
    env["PYTHONPATH"] = str(Path(__file__).parent)
    try:
        subprocess.run(
            [sys.executable, str(script), "trending viral"],
            capture_output=True,
            env=env,
            cwd=Path(__file__).parent,
            timeout=45,
        )
    except Exception:
        pass


def _run_refresh_news():
    """Re-search all raw topics and refresh platform hot trends. Used by /news/refresh and scheduler."""
    # Refresh platform hot topics (微博、知乎、抖音、百度)
    try:
        script = Path(__file__).parent / "scripts" / "fetch_hot_trending.py"
        env = _env_no_proxy()
        env["PYTHONPATH"] = str(Path(__file__).parent)
        subprocess.run([sys.executable, str(script)], capture_output=True, env=env, cwd=Path(__file__).parent, timeout=30)
    except Exception:
        pass
    items = _list_digests()
    raw_files = [x for x in items if x["type"] == "raw"]
    if not raw_files:
        return
    script = Path(__file__).parent / "scripts" / "search_only.py"
    env = _env_no_proxy()
    env["PYTHONPATH"] = str(Path(__file__).parent)
    for x in raw_files:
        topic = x.get("topic", "").replace("_", " ")
        if not topic:
            continue
        try:
            subprocess.run([sys.executable, str(script), topic], check=True, env=env, cwd=Path(__file__).parent, timeout=45)
        except Exception:
            pass


@app.route("/news/refresh")
def news_refresh():
    """Manual refresh: re-search all topics in background, redirect immediately."""
    import threading
    def _bg_refresh():
        try:
            _run_refresh_news()
        except Exception:
            pass
    threading.Thread(target=_bg_refresh, daemon=True).start()
    return redirect("/news")


@app.route("/field")
def field():
    return _render_field()


@app.route("/news")
def news():
    return _render_news()


@app.route("/viral")
def viral():
    return _render_viral()


if __name__ == "__main__":
    import os

    OUTPUT.mkdir(exist_ok=True)
    port = int(os.environ.get("PORT", 5001))
    host = "0.0.0.0"  # Bind all interfaces so 127.0.0.1:5001 works locally
    debug = not os.environ.get("PORT")  # Auto-reload when running locally

    # Start 60-min auto-refresh (only in the process that runs the app)
    def _start_scheduler():
        from apscheduler.schedulers.background import BackgroundScheduler
        def _job_daily():
            try:
                _run_refresh_daily()
            except Exception:
                pass
        def _job_news():
            try:
                _run_refresh_news()
            except Exception:
                pass
        def _job_videos():
            try:
                _run_refresh_videos()
            except Exception:
                pass
        sched = BackgroundScheduler()
        sched.add_job(_job_daily, "interval", minutes=60, id="daily_news")
        sched.add_job(_job_news, "interval", minutes=60, id="news_by_topic")
        sched.add_job(_job_videos, "interval", minutes=60, id="viral_videos")
        sched.start()
        print("Daily news, News by topic & Viral videos: auto-refresh every 60 mins")
        # Bootstrap: run once on startup if output is empty (fixes deploy/restart with no content)
        if not (OUTPUT / "daily_news.md").exists() or not list(OUTPUT.glob("raw_*.md")) or not (OUTPUT / "videos_trending_viral.md").exists():
            import threading
            def _bootstrap():
                try:
                    _run_refresh_daily()
                    _run_refresh_news()
                    _run_refresh_videos()
                    print("Bootstrap: news and videos content populated")
                except Exception as e:
                    print(f"Bootstrap refresh failed: {e}")
            threading.Thread(target=_bootstrap, daemon=True).start()

    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not debug:
        _start_scheduler()

    print(f"ViralLab at http://127.0.0.1:{port}" + (" (auto-reload on)" if debug else ""))
    app.run(host=host, port=port, debug=debug, use_reloader=debug)
