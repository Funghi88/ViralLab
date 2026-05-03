"""Minto Pyramid (Pyramid Principle) structure extraction for content.

Goal:
- Conclusion first (single governing thought)
- Grouped key points (MECE-ish buckets)
- Evidence under each point
"""
import re
from collections import defaultdict
from typing import Any


def _sentences(text: str) -> list[str]:
    """Split text into sentence-like chunks for EN/ZH."""
    if not text or not text.strip():
        return []
    t = text.strip()
    # Keep paragraph/newline boundaries from ASR output, then split by punctuation.
    blocks = re.split(r"[\r\n]+", t)
    out: list[str] = []
    for block in blocks:
        b = re.sub(r"\s+", " ", block.strip())
        if not b:
            continue
        parts = re.split(r"[。！？!?\.]+", b)
        for part in parts:
            p = part.strip().strip("。.!?！？")
            if not p:
                continue
            # ASR sometimes emits very long lines without punctuation; chunk by commas/pauses.
            if len(p) > 180:
                chunks = re.split(r"[，,;；:：]+", p)
                for c in chunks:
                    cc = c.strip()
                    if len(cc) >= 8:
                        out.append(cc)
            else:
                out.append(p)
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _contains_any(s: str, kws: tuple[str, ...]) -> int:
    s = _norm(s)
    return sum(1 for k in kws if k.lower() in s)


def _score_conclusion_candidate(s: str, lang: str) -> int:
    """Score sentence for being a governing thought."""
    if not s:
        return -999
    n = len(s)
    score = 0
    if 18 <= n <= 120:
        score += 3
    elif 10 <= n <= 180:
        score += 1
    else:
        score -= 2

    abstract_en = ("core", "key", "shift", "value", "must", "needs", "future", "not", "but", "because")
    abstract_zh = ("核心", "关键", "本质", "转向", "价值", "必须", "需要", "不是", "而是", "因为")
    score += _contains_any(s, abstract_zh if lang == "zh" else abstract_en) * 2

    # Penalize pure narrative lines.
    narrative_en = ("then", "and then", "i ", "we ", "today i", "he said")
    narrative_zh = ("然后", "我", "我们", "他说", "她说", "有一天")
    score -= _contains_any(s, narrative_zh if lang == "zh" else narrative_en)
    return score


def _theme_buckets(lang: str) -> dict[str, tuple[str, ...]]:
    if lang == "zh":
        return {
            "why": ("因为", "导致", "原因", "本质", "变化", "转向", "替代", "效率", "门槛"),
            "impact": ("焦虑", "压力", "失业", "裁员", "分化", "危机", "困境", "不确定"),
            "path": ("路径", "方法", "实践", "策略", "建议", "如何", "应该", "可以", "步骤"),
        }
    return {
        "why": ("because", "driver", "reason", "shift", "change", "commoditize", "replace"),
        "impact": ("anxiety", "pressure", "layoff", "risk", "identity", "crisis", "uncertainty"),
        "path": ("path", "playbook", "how to", "should", "can", "strategy", "practice", "steps"),
    }


def _bucket_sentence(s: str, lang: str) -> str:
    buckets = _theme_buckets(lang)
    # Prefer explicit path cues first so "how to do it" does not get swallowed by cause terms.
    if _contains_any(s, ("路径", "方法", "如何", "步骤", "playbook", "how to", "strategy", "steps")) > 0:
        return "path"
    if _contains_any(s, buckets["impact"]) > 0:
        return "impact"
    if _contains_any(s, buckets["why"]) > 0:
        return "why"
    if _contains_any(s, buckets["path"]) > 0:
        return "path"
    return "why"


def _build_key_point(label: str, s: str, lang: str) -> str:
    labels = {
        "en": {
            "why": "Why",
            "impact": "Impact",
            "path": "Path",
        },
        "zh": {
            "why": "为什么",
            "impact": "结果",
            "path": "路径",
        },
    }
    prefix = labels["zh" if lang == "zh" else "en"][label]
    return f"{prefix}: {s.strip()}"


def _fallback_point(label: str, sents: list[str], lang: str) -> str:
    """Generate deterministic fallback key point when a bucket is sparse."""
    if lang == "zh":
        fallback = {
            "why": "为什么: 内容环境变化导致执行优势被快速压缩，价值重心转向判断与定位。",
            "impact": "结果: 从业者会感到增长压力与角色焦虑，原有经验需要重构。",
            "path": "路径: 用可复用方法把结论前置、要点分组、证据挂钩，并持续迭代。",
        }
    else:
        fallback = {
            "why": "Why: The content environment is shifting, so execution alone no longer creates durable advantage.",
            "impact": "Impact: Creators face higher pressure and role uncertainty as old playbooks decay faster.",
            "path": "Path: Lead with a clear claim, group key points, attach evidence, and iterate with feedback.",
        }
    # Prefer a real sentence if we can find one with minimal overlap.
    for s in sents:
        if len(s) >= 12:
            return _build_key_point(label, s, lang)
    return fallback[label]


def structure_minto(text: str, lang: str = "en", max_key_points: int = 5) -> dict[str, Any]:
    """Extract a stricter Minto structure.

    Returns:
    - conclusion: single governing thought
    - key_points: grouped points (Why/Impact/Path)
    - evidence: support bullets grouped from raw sentences
    - groups: structured groups for richer downstream UI/markdown
    """
    if not text or not text.strip():
        return {"conclusion": "", "key_points": [], "evidence": [], "groups": [], "logic_order": ""}

    sents = _sentences(text)
    if not sents:
        return {"conclusion": "", "key_points": [], "evidence": [], "groups": [], "logic_order": ""}

    # 1) Governing thought: best-scored sentence from early context.
    head = sents[: min(14, len(sents))]
    conclusion = max(head, key=lambda s: _score_conclusion_candidate(s, lang)).strip()
    if len(conclusion) > 160:
        conclusion = conclusion[:160].rstrip(" ,，;；:：") + "..."

    # 2) Grouping: Why -> Impact -> Path
    grouped: dict[str, list[str]] = defaultdict(list)
    for s in sents:
        if _norm(s) == _norm(conclusion):
            continue
        b = _bucket_sentence(s, lang)
        if len(s) >= 8 and len(grouped[b]) < 8:
            grouped[b].append(s.strip())

    order = ("why", "impact", "path")
    key_points: list[str] = []
    evidence: list[str] = []
    groups: list[dict[str, Any]] = []
    for b in order[: max(3, min(max_key_points, 5))]:
        arr = grouped.get(b, [])
        kp = _build_key_point(b, arr[0], lang) if arr else _fallback_point(b, sents, lang)
        key_points.append(kp)
        ev = arr[1:4] if len(arr) > 1 else []
        for e in ev:
            evidence.append(f"[{b}] {e}")
        groups.append({"group": b, "point": kp, "evidence": ev})

    # 3) Fallback evidence per point to keep strict structure usable.
    if not evidence:
        tail = [s for s in sents if _norm(s) != _norm(conclusion)]
        evidence = [e[:280] + ("…" if len(e) > 280 else "") for e in tail[:6]]
        if groups:
            per_group = [evidence[i * 2 : (i + 1) * 2] for i in range(len(groups))]
            groups = [
                {"group": g["group"], "point": g["point"], "evidence": per_group[idx]}
                for idx, g in enumerate(groups)
            ]

    logic_order = (
        "Cause-Effect" if lang != "zh" else "因果"
    )
    return {
        "conclusion": conclusion,
        "key_points": key_points[: max(3, min(max_key_points, 5))],
        "evidence": evidence[:10],
        "groups": groups,
        "logic_order": logic_order,
    }


def minto_to_markdown(m: dict[str, Any], lang: str = "en") -> str:
    """Format Minto structure as markdown."""
    labels = (
        {
            "conclusion": "Conclusion (answer first)",
            "key_points": "Key points (grouped)",
            "evidence": "Supporting evidence",
            "logic": "Logic order",
        }
        if lang == "en"
        else {
            "conclusion": "结论（先给答案）",
            "key_points": "要点（分组）",
            "evidence": "支撑论据",
            "logic": "逻辑顺序",
        }
    )
    out = [f"## {labels['conclusion']}\n", (m.get("conclusion") or "").strip(), "\n"]
    point_prefix = "For point" if lang == "en" else "对应要点"
    if m.get("logic_order"):
        out.append(f"\n**{labels['logic']}:** {m.get('logic_order')}\n")
    if m.get("key_points"):
        out.append(f"\n## {labels['key_points']}\n")
        for i, p in enumerate(m["key_points"], 1):
            out.append(f"{i}. {p}\n")
    groups = m.get("groups") or []
    if groups:
        out.append(f"\n## {labels['evidence']}\n")
        for i, g in enumerate(groups, 1):
            out.append(f"### {point_prefix} {i}\n")
            ev = g.get("evidence") or []
            if not ev:
                out.append("- (No direct evidence extracted)\n")
            for e in ev[:3]:
                out.append(f"- {e}\n")
            out.append("\n")
    elif m.get("evidence"):
        out.append(f"\n## {labels['evidence']}\n")
        for e in m["evidence"]:
            out.append(f"- {e}\n")
    return "".join(out).strip()
