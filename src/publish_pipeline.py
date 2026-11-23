"""Multi-channel publish queue & scheduler for ViralLab.

Flow: queue draft -> approve/publish now (or auto-dispatch at schedule_at) -> connector dispatch.
Supports: blog (funghi88.github.io Jekyll/GitHub API), telegram, wechat, xiaohongshu, x.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.publish_connectors import (
    dispatch_publish,
    normalize_platform,
)

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


def parse_schedule_time(schedule_at: str) -> datetime | None:
    """Parse `schedule_at` into an aware datetime (local timezone when tz is omitted)."""
    s = (schedule_at or "").strip()
    if not s:
        return None
    local_tz = datetime.now().astimezone().tzinfo
    try:
        iso = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=local_tz)
        return dt
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=local_tz)
        except ValueError:
            continue
    return None


def list_publish_items(limit: int = 40) -> list[dict[str, Any]]:
    items = _read_queue()
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items[: max(1, min(limit, 200))]


def queue_publish_item(
    *,
    title: str,
    content: str,
    platform: str = "blog",
    source_file: str = "",
    schedule_at: str = "",
    draft: bool = False,
    category: str = "",
) -> dict[str, Any]:
    platform_norm = normalize_platform(platform)
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
        "draft": bool(draft),
        "category": (category or "").strip()[:40],
        "source_file": (source_file or "").strip(),
        "fingerprint": fp,
        "created_at": _now_iso(),
        "schedule_at": (schedule_at or "").strip(),
        "published_at": "",
        "published_url": "",
        "publish_result": "",
    }
    items.append(item)
    _write_queue(items)
    _append_event("queue_add", {"id": item["id"], "platform": item["platform"], "draft": item["draft"]})
    return item


def publish_item_now(item_id: str, *, force_draft: bool | None = None) -> tuple[bool, str, dict[str, Any] | None]:
    items = _read_queue()
    idx = next((i for i, x in enumerate(items) if x.get("id") == item_id), -1)
    if idx < 0:
        _append_event("publish_missing", {"id": item_id})
        return False, "Item not found.", None
    item = items[idx]
    if not (item.get("content") or "").strip():
        _append_event("publish_invalid", {"id": item_id, "reason": "empty_content"})
        return False, "Content is empty.", item

    platform = normalize_platform(item.get("platform", "x"))
    is_draft = bool(item.get("draft")) if force_draft is None else bool(force_draft)
    category = (item.get("category") or "").strip()

    try:
        ok, result, pub_url = dispatch_publish(
            platform,
            item.get("title", ""),
            item.get("content", ""),
            draft=is_draft,
            category=category,
        )
        if ok:
            item["status"] = "published"
            item["published_at"] = _now_iso()
            item["published_url"] = pub_url
            item["publish_result"] = result
            items[idx] = item
            _write_queue(items)
            _append_event("publish_success", {"id": item.get("id"), "platform": platform, "url": pub_url})
            return True, result, item

        item["status"] = "failed"
        item["published_url"] = pub_url
        item["publish_result"] = result
        items[idx] = item
        _write_queue(items)
        _append_event("publish_needs_setup", {"id": item.get("id"), "platform": platform, "reason": result})
        return False, result, item
    except Exception as e:
        msg = f"Publish failed: {e}"
        item["status"] = "failed"
        item["publish_result"] = msg
        items[idx] = item
        _write_queue(items)
        _append_event("publish_failed", {"id": item.get("id"), "platform": platform, "error": str(e)})
        return False, msg, item


def process_due_scheduled_items(*, now: datetime | None = None) -> list[dict[str, Any]]:
    """Dispatch any `queued` items whose `schedule_at` timestamp is <= now."""
    ref_now = now or datetime.now().astimezone()
    items = _read_queue()
    due_ids: list[str] = []
    for it in items:
        if it.get("status") != "queued":
            continue
        sched = parse_schedule_time(it.get("schedule_at") or "")
        if sched is not None and sched <= ref_now:
            due_ids.append(str(it.get("id") or ""))

    dispatched: list[dict[str, Any]] = []
    for item_id in due_ids:
        if not item_id:
            continue
        ok, msg, updated = publish_item_now(item_id)
        dispatched.append({"id": item_id, "ok": ok, "message": msg, "item": updated})
    return dispatched


def delete_publish_item(item_id: str) -> tuple[bool, str]:
    items = _read_queue()
    new_items = [x for x in items if x.get("id") != item_id]
    if len(new_items) == len(items):
        return False, "Item not found."
    _write_queue(new_items)
    _append_event("queue_delete", {"id": item_id})
    return True, "Removed from publish queue."


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
