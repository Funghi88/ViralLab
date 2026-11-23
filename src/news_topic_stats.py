"""Aggregate topic popularity for /news labels and daily digest snapshot."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OUTPUT = Path(__file__).parent.parent / "output"
NEWS_SEARCHES_FILE = OUTPUT / "news_searches.json"


def _parse_ts(s: str | None) -> float:
    if not s:
        return 0.0
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")[:26]).timestamp()
    except Exception:
        return 0.0


def _has_cjk(s: str) -> bool:
    for c in s:
        if "\u4e00" <= c <= "\u9fff" or "\u3000" <= c <= "\u303f" or "\uac00" <= c <= "\ud7af":
            return True
    return False


def _matches_lang(topic: str, lang: str) -> bool:
    has_cjk = _has_cjk(topic)
    return (lang == "zh" and has_cjk) or (lang == "en" and not has_cjk)


def search_counts_for_range(lang: str, time_range: str = "1d") -> dict[str, int]:
    """In-app topic search counts in the given window (from news_searches.json)."""
    if not NEWS_SEARCHES_FILE.exists():
        return {}
    now = datetime.now(timezone.utc).timestamp()
    if time_range == "60m":
        cutoff = now - 3600
    elif time_range == "7d":
        cutoff = now - (7 * 24 * 3600)
    else:
        cutoff = now - (24 * 3600)
    try:
        data: dict[str, Any] = json.loads(NEWS_SEARCHES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    searches = data.get("searches", [])
    counts: dict[str, int] = {}
    for s in searches:
        if _parse_ts(s.get("ts", "")) < cutoff:
            continue
        t = (s.get("topic") or "").strip()
        if t and _matches_lang(t, lang):
            counts[t] = counts.get(t, 0) + 1
    return counts


def topics_per_segment_with_counts(
    lang: str,
    time_range: str = "1d",
    limit_per: int = 5,
    *,
    segments: tuple[str, ...] = ("tech", "geopolitics", "entrepreneurs", "creator"),
) -> list[tuple[str, str, list[tuple[str, int]]]]:
    """
    Each row: (segment_id, segment_label, [(topic, search_count), ...]).
    Topics are platform hot-list order re-ranked for that segment; counts are app searches only.
    """
    try:
        from src.hot_trending import AUDIENCE_SEGMENTS, get_cached_or_fetch, rerank_topics_by_segment

        lang_fetch = "zh" if lang == "zh" else "en"
        lang_key = "zh" if lang == "zh" else "en"
        topics, _ = get_cached_or_fetch(lang_fetch)
        counts = search_counts_for_range(lang, time_range)
        rows: list[tuple[str, str, list[tuple[str, int]]]] = []
        for seg_id in segments:
            if seg_id not in AUDIENCE_SEGMENTS:
                continue
            ranked = rerank_topics_by_segment(list(topics), lang, seg_id)
            seen: set[str] = set()
            picks: list[tuple[str, int]] = []
            for t in ranked:
                tl = t.strip()
                if not tl or tl in seen:
                    continue
                seen.add(tl)
                picks.append((t, counts.get(tl, 0)))
                if len(picks) >= limit_per:
                    break
            label = AUDIENCE_SEGMENTS[seg_id][f"name_{lang_key}"]
            rows.append((seg_id, label, picks))
        return rows
    except Exception:
        return []


def daily_snapshot_markdown(lang: str, time_range: str = "1d") -> str:
    """Short markdown block for daily_news.md — topic heat by focus area."""
    rows = topics_per_segment_with_counts(lang, time_range, limit_per=6)
    if not rows:
        return ""
    if lang == "zh":
        lines = ["## 各域热门参考（热榜 × 站内搜索次数）", ""]
    else:
        lines = ["## Topic heat by focus (hot list × in-app search counts)", ""]
    for _seg_id, name, picks in rows:
        lines.append(f"### {name}")
        for t, c in picks:
            suffix = f" ×{c}" if c else ""
            lines.append(f"- {t}{suffix}")
        lines.append("")
    return "\n".join(lines)
