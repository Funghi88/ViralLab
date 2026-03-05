"""Generate 2–3 content angles per article. Content-specific, Berger-inspired."""
import re
from typing import List


ANGLE_TEMPLATES = [
    "How to use {topic} to stand out in your niche",
    "The secret most creators miss about {topic}",
    "Why {topic} is blowing up right now (and how to ride it)",
    "3 angles on {topic} that your audience hasn't seen",
    "The {topic} trend: practical takeaway for your content",
    "{topic} — turn the buzz into a story your audience cares about",
    "What top creators know about {topic} that you don't",
    "The {topic} playbook: step-by-step for beginners",
    "{topic} — why it works and how to adapt it",
    "5 ways to leverage {topic} for more engagement",
]

ANGLE_TEMPLATES_ZH = [
    "如何用{topic}在赛道中脱颖而出",
    "多数创作者忽略的{topic}秘诀",
    "{topic}正火，如何顺势做内容",
    "从三个角度切入{topic}，观众还没看过",
    "{topic}趋势：实用内容灵感",
    "{topic} — 把热度变成观众爱看的故事",
    "头部创作者都在用的{topic}心法",
    "{topic}入门：从零到上手的完整指南",
    "{topic}为什么有效，怎么为己所用",
    "用{topic}提升互动的五个实战技巧",
]


# Stop words to skip when extracting focus (EN)
_FOCUS_STOP_EN = frozenset({"the", "a", "an", "this", "that", "these", "those", "it", "is", "are", "was", "were", "for", "with", "and", "or", "but", "blowing", "up", "how", "to", "ride", "in", "on", "at"})

# Filler prefixes to skip (ZH)
_FOCUS_SKIP_ZH = ("别傻了!", "别再", "震惊!", "重磅!", "必看!", "干货!", "收藏!", "转发!")
# Pattern: take text after this (the real subject)
_FOCUS_AFTER_ZH = ("都在用的", "都在用", "都在做", "必学的", "必读的")
# Chars that often start 2-char words — avoid ending focus with these (causes "抖角度" etc.)
_FOCUS_INCOMPLETE_TAIL_ZH = frozenset("抖微小快百红淘京视讯手书")
# Generic terms — prefer fallback (topic) when focus is one of these
_FOCUS_GENERIC_ZH = frozenset({"全国", "最新", "重磅", "独家", "必看"})


def _sanitize_focus(focus: str, fallback: str, lang: str) -> str:
    """Ensure focus is clean and readable. Avoid '抖角度' etc."""
    if not focus or len(focus) < 2:
        return fallback or "trend"
    focus = focus.strip()
    if lang == "zh":
        # Strip leading digits, quotes, punctuation
        focus = re.sub(r"^[\d\"\'\s\.\-—]+", "", focus)
        # Avoid ending with incomplete char (抖+角度 -> 抖角度)
        while len(focus) > 1 and focus[-1] in _FOCUS_INCOMPLETE_TAIL_ZH:
            focus = focus[:-1]
        # Fallback if we stripped too much or focus is too generic
        if len(focus) < 2 or focus[0] in "0123456789" or focus in _FOCUS_GENERIC_ZH:
            return fallback or "趋势"
    else:
        focus = re.sub(r"^[\d\"\'\s\.\-—]+", "", focus)
        if len(focus) < 2:
            return fallback or "trend"
    return focus.strip() or fallback or ("trend" if lang == "en" else "趋势")


def _extract_focus(title: str, snippet: str, fallback: str, lang: str, max_cjk: int = 8, max_en: int = 24) -> str:
    """Extract article-specific focus from title + snippet. Prefer title for focus."""
    text = (title or "").strip()[:100]
    if not text and snippet:
        text = (snippet or "").strip()[:80]
    if not text:
        return fallback or ("trend" if lang == "en" else "趋势")
    has_cjk = any("\u4e00" <= c <= "\u9fff" for c in text)
    if has_cjk:
        for prefix in _FOCUS_SKIP_ZH:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                break
        for pattern in _FOCUS_AFTER_ZH:
            if pattern in text:
                text = text.split(pattern, 1)[-1].strip()
                break
        focus = text[:max_cjk].strip()
        focus = _sanitize_focus(focus, fallback, "zh")
    else:
        for _ in range(4):
            lower = text.lower()
            for prefix in ("ask hn:", "show hn:", "how to ", "what is the ", "why ", "the ", "a ", "an "):
                if lower.startswith(prefix):
                    text = text[len(prefix):].strip()
                    break
            else:
                break
        # "X about Y" -> take Y (preserve case)
        t_lower = text.lower()
        if " about " in t_lower:
            idx = t_lower.find(" about ")
            text = text[idx + 7:].strip()  # len(" about ") = 7
        # "your first X" / "my first X" -> take X (2 words: "AI agent" not "AI agent 10 minutes")
        used_first_pattern = False
        for pattern in (" your first ", " my first ", " the first "):
            if pattern in t_lower:
                idx = t_lower.find(pattern)
                text = text[idx + len(pattern):].strip()
                used_first_pattern = True
                break
        words = [w for w in text.split() if len(w) > 1 and w.lower() not in _FOCUS_STOP_EN and not w.isdigit()][:6]
        n = 2 if used_first_pattern else 3
        focus = " ".join(words[:n]) if words else text[:max_en]
        focus = _sanitize_focus(focus.strip(), fallback, "en")
    return focus or fallback or ("trend" if lang == "en" else "趨勢")


def generate_angles(
    topic: str,
    title: str = "",
    snippet: str = "",
    count: int = 3,
    lang: str = "en",
) -> List[str]:
    """Generate content-specific angles per article. Uses title+snippet for variety."""
    templates = ANGLE_TEMPLATES_ZH if lang == "zh" else ANGLE_TEMPLATES
    focus = _extract_focus(title, snippet, topic, lang)
    combined = f"{topic} {title} {snippet}".strip().lower()

    # Content-based keyword matching (EN + ZH)
    angles = []
    kw_map = [
        (["how", "tip", "guide", "教程", "方法", "怎么", "如何做"], 0),
        (["secret", "first", "exclusive", "秘诀", "独家", "心法", "干货"], 1),
        (["trend", "viral", "blow", "blowing", "热门", "趋势", "爆款", "火"], 2),
        (["angle", "3", "5", "角度", "三个", "五个", "多种"], 3),
        (["practical", "easy", "simple", "实用", "简单", "轻松", "入门", "新手"], 4),
        (["story", "experience", "故事", "经验", "案例"], 5),
        (["top", "best", "pro", "头部", "顶级", "高手", "大咖"], 6),
        (["step", "playbook", "beginner", "步骤", "指南", "入门", "从零"], 7),
        (["why", "work", "adapt", "有效", "原理", "为己所用"], 8),
        (["leverage", "engagement", "互动", "技巧", "实战", "提升"], 9),
    ]
    for keywords, idx in kw_map:
        if any(k in combined for k in keywords):
            c = templates[idx].format(topic=focus)
            if c not in angles:
                angles.append(c)

    # Vary template selection per article (hash of content) so different articles get different angles
    seed = hash((title + snippet)[:80])
    for i in range(len(templates)):
        if len(angles) >= count:
            break
        idx = (seed + i) % len(templates)
        c = templates[idx].format(topic=focus)
        if c not in angles:
            angles.append(c)

    return angles[:count]
