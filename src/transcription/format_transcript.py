"""Lightweight transcript cleanup for display and downstream scoring."""
from __future__ import annotations

import re


def format_transcript_text(text: str, lang: str) -> str:
    """Normalize whitespace; Latin languages get light spacing fixes. Chinese: no Title Case."""
    t = (text or "").strip()
    if not t:
        return ""
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    if lang == "zh":
        t = re.sub(r"\s+([，。！？、；：])", r"\1", t)
        return t.strip()
    t = re.sub(r"\s+([.,;:!?])", r"\1", t)
    return t.strip()
