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


def evaluate_stepps_llm(text: str, lang: str = "en") -> dict[str, Any]:
    """LLM-powered STEPPS evaluation with per-signal evidence and actionable diagnosis.

    Returns the same shape as evaluate_contagious_article() plus:
    - details: per-principle {score, evidence_quote, why, gap}
    - rewrite_suggestion: specific to this text (not a template)
    - llm_powered: True

    Falls back to evaluate_contagious_article() on any error.
    """
    if not text or not text.strip():
        return evaluate_contagious_article("", text, lang=lang)
    try:
        from src.llm_client import call_llm
        import json as _json

        labels = STEPPS_LABELS_ZH if lang == "zh" else STEPPS_LABELS

        if lang == "zh":
            system = (
                "你是 Jonah Berger《Contagious》STEPPS 框架专家，专门帮助内容创作者理解自己内容的传播潜力。"
                "你的评分必须基于原文内容，每条得分理由都需要引用原文中的具体句子或片段。"
                "不得凭印象打分，不得使用模板化表达。"
            )
            prompt = f"""请用 Berger STEPPS 框架对下方逐字稿进行深度评分和分析。

六个维度定义：
- social_currency（社交货币）：内容让人分享后显得有见识、有品味、有独到视角。分享这条内容让人感觉"我懂的比别人多"。
- triggers（触发）：内容与日常生活中的具体场景、习惯、时间节点绑定，让人在某个触发点自然想起并转发。
- emotion（情绪）：内容引发高唤醒情绪（敬畏、兴奋、愤怒、焦虑），而非低唤醒情绪（满足、平静）。
- public（公开可见）：内容有社会认同信号（许多人都在做/看/转），让行为可见、可被模仿。
- practical（实用价值）：内容提供可立即使用的信息、技巧、框架，让人"不得不转给需要的人"。
- stories（故事）：内容用叙事包裹核心信息，有具体人物、冲突、转折，信息藏在故事里自然传播。

评分规则：
- 每个维度 0-20 分
- evidence_quote：从原文中直接引用支撑该分数的句子或片段（必须是原文原话）
- why：一句话解释为什么这个分数（具体到本文内容）
- gap：如果分数低于12，说明具体缺什么（针对本文，不是通用建议）

最后给出：
- top2_signals：得分最高的两个维度的中文名
- weakest_signal：得分最低的维度的中文名
- rewrite_suggestion：针对本文内容的具体改写建议（50字以内，不得使用"添加XXX"等通用模板句，必须说明如何改这篇稿）

输出严格 JSON：
{{
  "social_currency": {{"score": 0, "evidence_quote": "...", "why": "...", "gap": "..."}},
  "triggers": {{"score": 0, "evidence_quote": "...", "why": "...", "gap": "..."}},
  "emotion": {{"score": 0, "evidence_quote": "...", "why": "...", "gap": "..."}},
  "public": {{"score": 0, "evidence_quote": "...", "why": "...", "gap": "..."}},
  "practical": {{"score": 0, "evidence_quote": "...", "why": "...", "gap": "..."}},
  "stories": {{"score": 0, "evidence_quote": "...", "why": "...", "gap": "..."}},
  "top2_signals": ["社交货币", "故事"],
  "weakest_signal": "触发",
  "rewrite_suggestion": "..."
}}

逐字稿原文：
{text[:4000]}"""
        else:
            system = (
                "You are a Jonah Berger STEPPS expert helping content creators understand "
                "the viral potential of their content. All scoring must be grounded in the "
                "actual text with direct quotes — no impressionistic scoring, no templates."
            )
            prompt = f"""Score the transcript below using the Berger STEPPS framework.

Six dimensions:
- social_currency: Content makes sharers look smart/insightful/in-the-know. Sharing signals identity.
- triggers: Content links to specific daily habits, routines, or recurring moments that prompt recall.
- emotion: Content triggers high-arousal emotions (awe, excitement, anger, anxiety) — not low-arousal ones.
- public: Content has social proof signals showing many people doing/watching/sharing it (visible behavior).
- practical: Content gives immediately usable information, tips, or frameworks worth passing on.
- stories: Content wraps the message in narrative — specific people, conflict, turning points.

Scoring rules:
- Each dimension 0-20
- evidence_quote: Direct quote from the transcript that supports this score
- why: One sentence explaining this score specifically for this text
- gap: If score < 12, what's concretely missing (specific to this text, not generic advice)

Then provide:
- top2_signals: Names of the two highest-scoring dimensions
- weakest_signal: Name of the lowest-scoring dimension
- rewrite_suggestion: Specific rewrite suggestion for THIS transcript (under 30 words, not a template)

Output strict JSON:
{{
  "social_currency": {{"score": 0, "evidence_quote": "...", "why": "...", "gap": "..."}},
  "triggers": {{"score": 0, "evidence_quote": "...", "why": "...", "gap": "..."}},
  "emotion": {{"score": 0, "evidence_quote": "...", "why": "...", "gap": "..."}},
  "public": {{"score": 0, "evidence_quote": "...", "why": "...", "gap": "..."}},
  "practical": {{"score": 0, "evidence_quote": "...", "why": "...", "gap": "..."}},
  "stories": {{"score": 0, "evidence_quote": "...", "why": "...", "gap": "..."}},
  "top2_signals": ["Social Currency", "Stories"],
  "weakest_signal": "Triggers",
  "rewrite_suggestion": "..."
}}

Transcript:
{text[:4000]}"""

        raw = call_llm(prompt, system=system, json_mode=True, max_tokens=2000)
        data = _json.loads(raw)

        breakdown: dict[str, int] = {}
        details: dict[str, Any] = {}
        for p in STEPPS_ORDER:
            pd = data.get(p) or {}
            score = max(0, min(20, int(pd.get("score", 0))))
            breakdown[p] = score
            details[p] = {
                "score": score,
                "evidence_quote": (pd.get("evidence_quote") or "").strip(),
                "why": (pd.get("why") or "").strip(),
                "gap": (pd.get("gap") or "").strip(),
                "name": labels[p],
            }

        active = sum(1 for p in STEPPS_ORDER if breakdown[p] >= 6)
        diversity_bonus = 4 if active >= 3 else (2 if active == 2 else 0)
        total = min(sum(breakdown.values()) + diversity_bonus, 100)

        top2_raw = data.get("top2_signals") or []
        weakest_raw = data.get("weakest_signal") or ""
        # Resolve to principle keys for top_signals display
        top_signals = top2_raw[:2] if top2_raw else [labels[p] for p in sorted(STEPPS_ORDER, key=lambda p: breakdown[p], reverse=True)[:2] if breakdown[p] > 0]

        return {
            "total": total,
            "breakdown": breakdown,
            "top_signals": top_signals,
            "details": details,
            "rewrite_suggestion": (data.get("rewrite_suggestion") or "").strip(),
            "llm_powered": True,
        }
    except Exception:
        return evaluate_contagious_article("", text, lang=lang)
