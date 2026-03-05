"""Store and compare runs for trend lifecycle (rising/peaking/fading)."""
import json
from datetime import datetime
from pathlib import Path
from typing import Any

RUNS_FILE = Path(__file__).parent.parent / "output" / "runs.json"
MAX_RUNS = 7


def _load_runs() -> dict:
    if not RUNS_FILE.exists():
        return {}
    try:
        return json.loads(RUNS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_runs(data: dict) -> None:
    RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RUNS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_key(item: dict) -> str:
    """Unique key for matching items across runs."""
    return (item.get("url") or "") + "|" + (item.get("title") or "")[:80]


def record_run(run_type: str, items: list[dict]) -> None:
    """Record a run. run_type: daily_news, videos_<query>."""
    data = _load_runs()
    today = datetime.now().strftime("%Y-%m-%d")
    entry = {"date": today, "items": items}
    if run_type not in data:
        data[run_type] = []
    data[run_type] = [e for e in data[run_type] if e["date"] != today] + [entry]
    data[run_type] = sorted(data[run_type], key=lambda x: x["date"], reverse=True)[:MAX_RUNS]
    _save_runs(data)


def get_lifecycle(run_type: str, items: list[dict]) -> dict[str, str]:
    """Return {item_key: "rising"|"peaking"|"fading"} for each item."""
    data = _load_runs()
    runs = data.get(run_type, [])
    if len(runs) < 2:
        return {_run_key(it): "peaking" for it in items}

    prev_keys = {_run_key(it) for it in runs[1]["items"]}
    prev_ranks = {_run_key(it): i for i, it in enumerate(runs[1]["items"])}

    result = {}
    for i, it in enumerate(items):
        key = _run_key(it)
        if key not in prev_keys:
            result[key] = "rising"
        else:
            prev_rank = prev_ranks.get(key, 99)
            result[key] = "fading" if i > prev_rank else "peaking"
    return result


def add_lifecycle_to_items(run_type: str, items: list[dict]) -> list[dict]:
    """Add lifecycle badge to each item."""
    lifecycle = get_lifecycle(run_type, items)
    for it in items:
        key = _run_key(it)
        it["lifecycle"] = lifecycle.get(key, "peaking")
    return items
