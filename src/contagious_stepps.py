"""Strict-ish STEPPS evaluation for article/news cards.

Designed for consistent, explainable scoring aligned with Jonah Berger's
STEPPS principles (Social Currency, Triggers, Emotion, Public, Practical, Stories).
"""
from __future__ import annotations

import re
from typing import Any

STEPPS_ORDER = (
    "social_currency",
    "triggers",
    "emotion",
    "public",
    "practical",
    "stories",
)

STEPPS_LABELS = {
    "social_currency": "Social Currency",
    "triggers": "Triggers",
    "emotion": "Emotion",
    "public": "Public",
    "practical": "Practical Value",
    "stories": "Stories",
}
STEPPS_LABELS_ZH = {
    "social_currency": "社交货币",
    "triggers": "触发",
    "emotion": "情绪",
    "public": "公开",
    "practical": "实用价值",
    "stories": "故事",
}

STEPPS_KWS_EN = {
    "social_currency": ("exclusive", "secret", "insider", "rare", "first", "premium"),
    "triggers": ("daily", "every day", "every time", "routine", "habit", "when"),
    "emotion": ("amazing", "shocking", "anxious", "fear", "excited", "surprising"),
    "public": ("viral", "trending", "everyone", "people are", "shared", "popular"),
    "practical": ("how to", "guide", "tips", "checklist", "step", "framework"),
    "stories": ("story", "journey", "case", "example", "experience", "what happened"),
}
STEPPS_KWS_ZH = {
    "social_currency": ("独家", "内幕", "秘诀", "首发", "稀缺", "高端"),
    "triggers": ("每天", "每次", "一到", "习惯", "场景", "日常"),
    "emotion": ("焦虑", "震惊", "兴奋", "愤怒", "恐惧", "惊喜"),
    "public": ("爆款", "热门", "全网", "大家都在", "疯传", "热搜"),
    "practical": ("如何", "指南", "步骤", "清单", "方法", "实践"),
    "stories": ("故事", "经历", "案例", "复盘", "实录", "发生了什么"),
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def _kw_count(text: str, kws: tuple[str, ...]) -> int:
    t = _norm(text)
    return sum(1 for kw in kws if kw.lower() in t)


def evaluate_contagious_article(
    title: str,
    snippet: str = "",
    lang: str = "en",
) -> dict[str, Any]:
    """Return a strict, auditable STEPPS score for article-like text.

    Scoring:
    - 6 principles * max 16 = 96
    - diversity bonus up to 4 when >=3 principles activate
    - total capped at 100
    """
    text = f"{title or ''} {snippet or ''}".strip()
    if not text:
        return {"total": 0, "breakdown": {}, "top_signals": []}

    kws_map = STEPPS_KWS_ZH if lang == "zh" else STEPPS_KWS_EN
    labels = STEPPS_LABELS_ZH if lang == "zh" else STEPPS_LABELS

    breakdown: dict[str, int] = {}
    for p in STEPPS_ORDER:
        c = _kw_count(text, kws_map[p])
        # stronger than keyword presence but still bounded
        pts = min(c * 6, 16)
        breakdown[p] = pts

    active = sum(1 for p in STEPPS_ORDER if breakdown[p] >= 6)
    diversity_bonus = 4 if active >= 3 else (2 if active == 2 else 0)
    total = min(sum(breakdown.values()) + diversity_bonus, 100)

    top = sorted(STEPPS_ORDER, key=lambda p: breakdown[p], reverse=True)
    top_signals = [labels[p] for p in top[:2] if breakdown[p] > 0]
    return {
        "total": total,
        "breakdown": breakdown,
        "top_signals": top_signals,
    }
