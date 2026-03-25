"""Article rewrite lab: markdown in -> structured contagious markdown out."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from src.contagious_stepps import evaluate_contagious_article
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


def build_viral_article_markdown(md_input: str, lang: str = "en") -> tuple[str, dict[str, Any]]:
    text = markdown_to_text(md_input)
    title = infer_title(md_input, text)

    berger = score_berger(text)
    contagious = evaluate_contagious_article(title, text[:400], lang=lang)
    minto = structure_minto(text, lang=lang)

    key_points = minto.get("key_points") or []
    evidence = minto.get("evidence") or []
    top_signals = contagious.get("top_signals") or []
    top_sig_line = " + ".join(top_signals) if top_signals else ("None" if lang == "en" else "暂无")

    hook = (
        f"{minto.get('conclusion','').strip()} — This is the key shift worth sharing now."
        if lang == "en"
        else f"{minto.get('conclusion','').strip()}——这是当下最值得传播的核心变化。"
    )
    cta = (
        "If this matches your experience, share it with one person who is navigating the same transition."
        if lang == "en"
        else "如果这与你的经历一致，转给一个正在经历同样转型的人。"
    )

    body_lines = []
    for i, kp in enumerate(key_points[:5], 1):
        body_lines.append(f"### {i}. {kp}")
        rel = [e for e in evidence if e][:2]
        for ev in rel:
            body_lines.append(f"- {ev}")
        body_lines.append("")
    if not body_lines:
        body_lines = [text[:600]]

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
