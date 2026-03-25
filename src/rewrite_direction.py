"""Rewrite directions from STEPPS + Minto. No external APIs; our own framework only."""

from __future__ import annotations

STEPPS_ORDER = [
    "social_currency",
    "triggers",
    "emotion",
    "public",
    "practical",
    "stories",
]

# 改写建议：弱项 → 具体方向（中英）
REWRITE_STEPPS_ZH = {
    "social_currency": "强化社交货币：加入独家/秘诀/首发/内行视角，让读者觉得「先知道」。",
    "triggers": "强化触发：绑定日常场景或时间点（如「每次…就想到」「早上刷手机时」），提高被想起的概率。",
    "emotion": "强化情绪：加入高唤醒词（震惊、绝了、必看、没想到），提高转发冲动。",
    "public": "强化公开：加入社会证明（多少人已用、截图、案例），或明确的「分享给…」话术。",
    "practical": "强化实用：突出干货、步骤、可操作清单（如 3 步、5 个方法），便于收藏转发。",
    "stories": "强化故事：用经历/故事包装信息（起因→转折→结果），信息更易被复述。",
}
REWRITE_STEPPS_EN = {
    "social_currency": "Boost Social Currency: add insider/exclusive/first-to-know framing.",
    "triggers": "Boost Triggers: tie to a daily moment or cue so people recall it later.",
    "emotion": "Boost Emotion: add high-arousal words (awe, must-see, surprising).",
    "public": "Boost Public: add social proof or visible 'share with…' framing.",
    "practical": "Boost Practical: add clear steps, list, or how-to so it's worth saving.",
    "stories": "Boost Stories: wrap the point in a 3-part arc (setup → tension → resolution).",
}

MINTO_REWRITE_ZH = {
    "no_conclusion": "结论前置：开头一句点明核心观点或结论，再展开理由。",
    "few_points": "归纳要点：用 3–5 个关键句作为小标题或首句，便于扫读。",
    "scattered_evidence": "论据归类：把论据归到各要点下，避免堆在一起。",
}
MINTO_REWRITE_EN = {
    "no_conclusion": "Lead with the answer: state the main conclusion in the first sentence.",
    "few_points": "Add 3–5 key points or subheads so the structure is scannable.",
    "scattered_evidence": "Group evidence under each key point instead of one long block.",
}


def rewrite_directions(
    score_result: dict,
    minto_result: dict | None = None,
    lang: str = "zh",
) -> list[str]:
    """Build rewrite directions from STEPPS breakdown and optional Minto structure.

    score_result: from score_berger() (total, breakdown, ...).
    minto_result: from structure_minto() (conclusion, key_points, evidence).
    lang: 'zh' or 'en'.
    Returns list of actionable rewrite suggestions.
    """
    out: list[str] = []
    breakdown = score_result.get("breakdown") or {}
    stepps_map = REWRITE_STEPPS_ZH if lang == "zh" else REWRITE_STEPPS_EN

    # Weak STEPPS: suggest for dimensions with score < 10, or bottom 2
    scored = [(k, breakdown.get(k, 0)) for k in STEPPS_ORDER]
    scored.sort(key=lambda x: x[1])
    weak_keys = [k for k, v in scored if v < 10][:2]
    if not weak_keys:
        weak_keys = [scored[0][0], scored[1][0]] if len(scored) >= 2 else [scored[0][0]] if scored else []
    for k in weak_keys:
        if k in stepps_map and stepps_map[k] not in out:
            out.append(stepps_map[k])

    # Minto-based suggestions
    if minto_result:
        minto_map = MINTO_REWRITE_ZH if lang == "zh" else MINTO_REWRITE_EN
        conclusion = (minto_result.get("conclusion") or "").strip()
        key_points = minto_result.get("key_points") or []
        evidence = minto_result.get("evidence") or []

        if len(conclusion) < 15 and (key_points or evidence):
            out.append(minto_map["no_conclusion"])
        if len(key_points) < 2 and (conclusion or evidence):
            out.append(minto_map["few_points"])
        if len(evidence) > 3 and len(key_points) < 2:
            out.append(minto_map["scattered_evidence"])

    return out
