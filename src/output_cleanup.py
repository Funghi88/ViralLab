"""Remove stale generated files under output/ (rolling retention by mtime)."""
from __future__ import annotations

import os
import time
from pathlib import Path

# Never delete these — current digests, indices, queues.
_PROTECTED_NAMES = frozenset(
    {
        "daily_news.md",
        "daily_news_zh.md",
        "daily_news_sources.txt",
        "daily_news_sources_zh.txt",
        "daily_news_updated.txt",
        "runs.json",
        "hot_trending.json",
        "news_searches.json",
        "publish_queue.json",
        "publish_events.jsonl",
    }
)

# Delete when older than retention if stem matches (topic raw files, digests, media artifacts).
_EPHEMERAL_PREFIXES = (
    "raw_",
    "digest_",
    "videos_",
    "transcript_",
    "article_rewrite_",
)


def _should_prune_file(name: str) -> bool:
    if name in _PROTECTED_NAMES:
        return False
    stem = Path(name).stem
    return any(stem.startswith(p) for p in _EPHEMERAL_PREFIXES)


def cleanup_ephemeral_output(
    output_dir: Path | None = None,
    *,
    retention_days: int | None = None,
) -> list[str]:
    """
    Unlink ephemeral markdown (and same-pattern files) under output/ when mtime is older than retention.

    Returns list of deleted filenames (basename only).
    """
    if os.environ.get("OUTPUT_CLEANUP", "1").strip().lower() in ("0", "false", "no"):
        return []

    out = output_dir or (Path(__file__).resolve().parent.parent / "output")
    if not out.is_dir():
        return []

    if retention_days is None:
        try:
            retention_days = int(os.environ.get("OUTPUT_RETENTION_DAYS", "3"))
        except ValueError:
            retention_days = 3
    retention_days = max(1, min(retention_days, 365))

    max_age_sec = retention_days * 86400
    now = time.time()
    deleted: list[str] = []

    for path in out.iterdir():
        if not path.is_file():
            continue
        if not _should_prune_file(path.name):
            continue
        try:
            age = now - path.stat().st_mtime
        except OSError:
            continue
        if age <= max_age_sec:
            continue
        try:
            path.unlink()
            deleted.append(path.name)
        except OSError:
            pass

    return deleted
