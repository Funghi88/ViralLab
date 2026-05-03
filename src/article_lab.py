"""Article rewrite lab: markdown in -> structured contagious markdown out.

Output strictly follows:
- Minto Pyramid SKILL: Conclusion first, grouped key points, evidence per point, logic order stated.
- Berger STEPPS SKILL: Full 6-signal breakdown, top 2 strongest, weakest signal + rewrite action.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from src.contagious_stepps import STEPPS_LABELS, STEPPS_LABELS_ZH, STEPPS_ORDER, evaluate_contagious_article
from src.minto_pyramid import minto_to_markdown, structure_minto
from src.video_tools import score_berger


def markdown_to_text(md: str) -> str:
    """Light markdown cleanup to plain text for scoring/structuring."""
    if not md:
        return ""
    s = md
    s = re.sub(r"```[\s\S]*?```", " ", s)
    s = re.sub(r"`[^`]*`", " ", s)
    s = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"^#{1,6}\s*", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s*[-*+]\s+", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s*\d+\.\s+", "", s, flags=re.MULTILINE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def infer_title(md: str, text: str) -> str:
    for line in (md or "").splitlines():
        m = re.match(r"^\s*#\s+(.+?)\s*$", line)
        if m:
            return m.group(1).strip()
    if text:
        return text[:80] + ("…" if len(text) > 80 else "")
    return "Untitled"


def _stepps_diagnosis(breakdown: dict, lang: str) -> str:
    """Build a STEPPS diagnosis block: strongest 2, weakest 1 + rewrite action."""
    labels = STEPPS_LABELS_ZH if lang == "zh" else STEPPS_LABELS
    sorted_principles = sorted(STEPPS_ORDER, key=lambda p: breakdown.get(p, 0), reverse=True)
    top2 = [labels[p] for p in sorted_principles[:2] if breakdown.get(p, 0) > 0]
    weakest = sorted_principles[-1]
    weakest_label = labels[weakest]

    # Rewrite actions per weakest signal
    rewrite_actions = {
        "social_currency": (
            "Add a status hook: frame this as insider knowledge or a rare insight the reader can share to look smart.",
            "添加地位钩子：将内容定位为内幕知识或稀缺洞察，让读者分享后显得有见识。",
        ),
        "triggers": (
            "Tie the content to a daily ritual or recurring event so it surfaces naturally in memory.",
            "将内容与日常场景或周期性事件绑定，让它在记忆中自然触发。",
        ),
        "emotion": (
            "Raise the emotional stakes: surface the specific anxiety, excitement, or surprise at the core of this topic.",
            "提升情绪强度：挖掘话题核心的焦虑感、兴奋感或惊喜感，直接命名情绪。",
        ),
        "public": (
            "Add a social proof signal: mention how many people are already experiencing this trend.",
            "加入社会认同信号：说明有多少人正在经历这一趋势，让行为可见。",
        ),
        "practical": (
            "Add one actionable takeaway the reader can apply today — a checklist, formula, or single next step.",
            "增加一个今天就能执行的行动项——清单、公式或下一步具体动作。",
        ),
        "stories": (
            "Open with a specific person's concrete experience before zooming out to the broader point.",
            "用一个具体人物的真实经历开头，再展开到更广泛的核心观点。",
        ),
    }
    action_en, action_zh = rewrite_actions.get(weakest, ("Strengthen the weakest signal.", "加强最弱信号。"))
    action = action_zh if lang == "zh" else action_en

    if lang == "zh":
        top_line = " + ".join(top2) if top2 else "暂无强信号"
        return (
            f"- **最强信号:** {top_line}\n"
            f"- **最弱信号:** {weakest_label}\n"
            f"- **改写建议:** {action}"
        )
    else:
        top_line = " + ".join(top2) if top2 else "None active"
        return (
            f"- **Strongest:** {top_line}\n"
            f"- **Weakest:** {weakest_label}\n"
            f"- **Rewrite action:** {action}"
        )


def build_viral_article_markdown(md_input: str, lang: str = "en") -> tuple[str, dict[str, Any]]:
    text = markdown_to_text(md_input)
    title = infer_title(md_input, text)

    berger = score_berger(text)
    contagious = evaluate_contagious_article(title, text[:400], lang=lang)
    minto = structure_minto(text, lang=lang)

    key_points = minto.get("key_points") or []
    groups = minto.get("groups") or []
    # Flat evidence fallback for when groups is not populated
    flat_evidence = minto.get("evidence") or []
    breakdown = contagious.get("breakdown") or {}
    top_signals = contagious.get("top_signals") or []
    top_sig_line = " + ".join(top_signals) if top_signals else ("None" if lang == "en" else "暂无")

    hook = (
        f"{minto.get('conclusion','').strip()} — This is the key shift worth sharing now."
        if lang == "en"
        else f"{minto.get('conclusion','').strip()}——这是当下最值得传播的核心变化。"
    )
    cta = (
        "If this matches your experience, share it with one person navigating the same transition."
        if lang == "en"
        else "如果这与你的经历一致，转给一个正在经历同样转型的人。"
    )

    # Body: key points with their own evidence drawn from groups (not a shared flat list)
    body_lines = []
    for i, kp in enumerate(key_points[:5], 1):
        body_lines.append(f"### {i}. {kp}")
        # Use group-level evidence if available for this point index
        if i <= len(groups):
            point_evidence = (groups[i - 1].get("evidence") or [])[:3]
        else:
            # Fall back to cycling through flat evidence
            point_evidence = flat_evidence[(i - 1) * 2 : (i - 1) * 2 + 2]
        for ev in point_evidence:
            if ev:
                body_lines.append(f"- {ev}")
        body_lines.append("")
    if not body_lines:
        body_lines = [text[:600]]

    stepps_diag = _stepps_diagnosis(breakdown, lang)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    out = f"""# {title} · Viral Rewrite

**Generated:** {now}
**Berger STEPPS:** {berger.get('total', 0)}/100
**Contagious (article):** {contagious.get('total', 0)}/100
**Top signals:** {top_sig_line}

---

## Hook
{hook}

## Article (Minto-first)

{chr(10).join(body_lines)}
## CTA
{cta}

---

## STEPPS Diagnosis
{stepps_diag}

---

## Minto Structure
{minto_to_markdown(minto, lang=lang)}
"""
    meta = {
        "title": title,
        "berger_total": berger.get("total", 0),
        "contagious_total": contagious.get("total", 0),
        "top_signals": top_signals,
        "minto": minto,
    }
    return out, meta
