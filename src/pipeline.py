"""Shared content pipeline primitives for ViralLab.

This module keeps the first pass simple:
- one normalized content schema (ContentItem)
- reusable transform stages (normalize, dedupe, sort)
- tiny pipeline runner for predictable stage chaining
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable


def _parse_date_ts(value: str) -> float:
    """Best-effort ISO timestamp parsing; returns 0 on failure."""
    if not value:
        return 0.0
    try:
        normalized = value.replace("Z", "+00:00")[:26]
        return datetime.fromisoformat(normalized).timestamp()
    except Exception:
        return 0.0


@dataclass(frozen=True)
class ContentItem:
    title: str
    snippet: str
    url: str
    date: str
    source: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContentItem | None":
        """Build a normalized item from loosely-shaped dict input."""
        if not isinstance(data, dict):
            return None
        title = str(data.get("title", "") or "").strip()
        if not title:
            return None
        return cls(
            title=title,
            snippet=str(data.get("snippet", "") or "").strip(),
            url=str(data.get("url", "") or "").strip(),
            date=str(data.get("date", "") or "").strip(),
            source=str(data.get("source", "") or "").strip(),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "title": self.title,
            "snippet": self.snippet,
            "url": self.url,
            "date": self.date,
            "source": self.source,
        }

    def dedupe_key(self) -> str:
        return self.title.lower().strip()


def stage_normalize(items: list[dict[str, Any]]) -> list[ContentItem]:
    """Drop malformed records and normalize keys/types."""
    out: list[ContentItem] = []
    for raw in items:
        normalized = ContentItem.from_dict(raw)
        if normalized:
            out.append(normalized)
    return out


def stage_dedupe(items: list[ContentItem]) -> list[ContentItem]:
    """Dedupe by normalized title, keeping first occurrence."""
    seen: set[str] = set()
    unique: list[ContentItem] = []
    for item in items:
        key = item.dedupe_key()
        if key and key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def stage_sort_by_date_desc(items: list[ContentItem]) -> list[ContentItem]:
    """Sort newest first. Items with unparseable dates sink to end."""
    return sorted(items, key=lambda item: _parse_date_ts(item.date), reverse=True)


def run_pipeline(
    items: list[dict[str, Any]],
    stages: list[Callable[[Any], Any]] | None = None,
) -> list[dict[str, str]]:
    """Run a linear pipeline over list-of-dict records."""
    active_stages = stages or [stage_normalize, stage_dedupe, stage_sort_by_date_desc]
    current: Any = items
    for stage in active_stages:
        current = stage(current)
    return [item.to_dict() for item in current]
