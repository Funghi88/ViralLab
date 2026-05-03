"""Simple publish queue for ViralLab.

Flow: queue draft -> approve/publish action -> optional webhook dispatch.
"""

from __future__ import annotations

import json
import os
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

OUTPUT = Path(__file__).resolve().parent.parent / "output"
QUEUE_FILE = OUTPUT / "publish_queue.json"
EVENTS_FILE = OUTPUT / "publish_events.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_queue() -> list[dict[str, Any]]:
    if not QUEUE_FILE.exists():
        return []
    try:
        data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data["items"]
    except Exception:
        pass
    return []


def _write_queue(items: list[dict[str, Any]]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(
        json.dumps({"updated_at": _now_iso(), "items": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _append_event(event_type: str, payload: dict[str, Any]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rec = {"ts": _now_iso(), "event": event_type, "payload": payload}
    with EVENTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _fingerprint(title: str, content: str, platform: str) -> str:
    basis = f"{(title or '').strip().lower()}|{(content or '').strip().lower()}|{platform}"
    return hashlib.sha256(basis.encode("utf-8", errors="replace")).hexdigest()[:16]


def validate_publish_content(content: str) -> list[str]:
    warnings: list[str] = []
    text = (content or "").strip()
    if len(text) < 80:
        warnings.append("Content is short (<80 chars).")
    if text.count("\n") < 1:
        warnings.append("Consider adding line breaks for readability.")
    if "http" not in text and "#" not in text:
        warnings.append("No link/hashtag found; add one if needed for distribution.")
    return warnings


def list_publish_items(limit: int = 40) -> list[dict[str, Any]]:
    items = _read_queue()
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items[: max(1, min(limit, 200))]


def queue_publish_item(
    *,
    title: str,
    content: str,
    platform: str = "x",
    source_file: str = "",
    schedule_at: str = "",
) -> dict[str, Any]:
    platform_norm = "blog" if platform == "blog" else "x"
    fp = _fingerprint(title, content, platform_norm)
    items = _read_queue()
    for old in items:
        if old.get("fingerprint") == fp and old.get("status") in ("queued", "published"):
            old["duplicate"] = True
            _append_event("queue_duplicate", {"id": old.get("id"), "fingerprint": fp})
            return old

    item = {
        "id": uuid.uuid4().hex[:12],
        "title": (title or "Untitled post").strip()[:180],
        "content": (content or "").strip(),
        "platform": platform_norm,
        "status": "queued",
        "source_file": (source_file or "").strip(),
        "fingerprint": fp,
        "created_at": _now_iso(),
        "schedule_at": (schedule_at or "").strip(),
        "published_at": "",
        "publish_result": "",
    }
    items.append(item)
    _write_queue(items)
    _append_event("queue_add", {"id": item["id"], "platform": item["platform"]})
    return item


def _publish_webhook_for_platform(platform: str) -> str:
    if platform == "blog":
        return os.environ.get("BLOG_PUBLISH_WEBHOOK", "").strip()
    return os.environ.get("X_PUBLISH_WEBHOOK", "").strip()


def publish_item_now(item_id: str) -> tuple[bool, str, dict[str, Any] | None]:
    items = _read_queue()
    idx = next((i for i, x in enumerate(items) if x.get("id") == item_id), -1)
    if idx < 0:
        _append_event("publish_missing", {"id": item_id})
        return False, "Item not found.", None
    item = items[idx]
    if not (item.get("content") or "").strip():
        _append_event("publish_invalid", {"id": item_id, "reason": "empty_content"})
        return False, "Content is empty.", item

    webhook = _publish_webhook_for_platform(item.get("platform", "x"))
    payload = {
        "id": item.get("id"),
        "title": item.get("title", ""),
        "content": item.get("content", ""),
        "platform": item.get("platform", "x"),
        "source_file": item.get("source_file", ""),
        "schedule_at": item.get("schedule_at", ""),
        "created_at": item.get("created_at", ""),
    }
    try:
        if webhook:
            r = requests.post(webhook, json=payload, timeout=12)
            r.raise_for_status()
            result = f"Webhook published ({r.status_code})."
        else:
            # Safe local fallback when webhook is not configured.
            result = "No webhook configured; marked as published locally."
        item["status"] = "published"
        item["published_at"] = _now_iso()
        item["publish_result"] = result
        items[idx] = item
        _write_queue(items)
        _append_event("publish_success", {"id": item.get("id"), "platform": item.get("platform")})
        return True, result, item
    except Exception as e:
        msg = f"Publish failed: {e}"
        item["status"] = "failed"
        item["publish_result"] = msg
        items[idx] = item
        _write_queue(items)
        _append_event("publish_failed", {"id": item.get("id"), "error": str(e)})
        return False, msg, item


def load_markdown_from_output(filename: str) -> tuple[str, str]:
    safe = Path(filename or "").name
    if not safe:
        return "", ""
    path = OUTPUT / safe
    if not path.exists() or not path.is_file():
        return "", ""
    text = path.read_text(encoding="utf-8", errors="replace")
    title = "Untitled"
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            title = s[2:].strip()[:180] or "Untitled"
            break
    return title, text
