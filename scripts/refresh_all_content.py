#!/usr/bin/env python
"""Refresh all ViralLab crawled content (hot list, daily, AI authority, longform, videos, topic news, optional China crawl)."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.proxy_env import env_for_overseas, load_dotenv_safe

load_dotenv_safe(ROOT / ".env")


def _step(name: str) -> float:
    print(f"\n=== {name} ===", flush=True)
    t0 = time.time()
    return t0


def _done(t0: float) -> None:
    print(f"done in {time.time() - t0:.1f}s", flush=True)


def main() -> int:
    py = sys.executable
    env = env_for_overseas(os.environ.copy())
    env["PYTHONPATH"] = str(ROOT)

    t = _step("1/6 Platform hot list (fetch_hot_trending.py)")
    r = subprocess.run([py, str(ROOT / "scripts" / "fetch_hot_trending.py")], cwd=ROOT, env=env, timeout=120)
    if r.returncode != 0:
        print(f"WARN: hot list exit {r.returncode}", flush=True)
    _done(t)

    t = _step("2/6 Daily news EN+ZH (daily_news.py)")
    r = subprocess.run([py, str(ROOT / "scripts" / "daily_news.py")], cwd=ROOT, env=env, timeout=int(os.environ.get("DAILY_REFRESH_TIMEOUT_SEC", "420")))
    if r.returncode != 0:
        print(f"ERROR: daily_news exit {r.returncode}", flush=True)
        return r.returncode
    _done(t)

    t = _step("3/6 Longform + podcast RSS (en + zh)")
    from server import _refresh_longform_cache

    _refresh_longform_cache("en", max_per_feed=6)
    _refresh_longform_cache("zh", max_per_feed=6)
    _done(t)

    t = _step("4/6 Viral videos (video_trending.py)")
    r = subprocess.run(
        [py, str(ROOT / "scripts" / "video_trending.py"), "trending viral"],
        cwd=ROOT,
        env=env,
        timeout=120,
    )
    if r.returncode != 0:
        print(f"WARN: videos exit {r.returncode}", flush=True)
    _done(t)

    t = _step("5/6 Topic news (hot tags → search_only.py)")
    from server import _run_refresh_news

    _run_refresh_news()
    _done(t)

    china_min = 0
    try:
        china_min = int(os.environ.get("CHINA_SCHEDULED_CRAWL_MINUTES", "0"))
    except ValueError:
        china_min = 0
    if china_min > 0 or os.environ.get("VIRALLAB_REFRESH_CHINA_CRAWL", "").strip().lower() in ("1", "true", "yes"):
        t = _step("6/6 China crawler (B站 + 知乎 热门)")
        from server import _run_scheduled_china_crawl

        _run_scheduled_china_crawl()
        _done(t)
    else:
        print("\n=== 6/6 China crawler skipped (set VIRALLAB_REFRESH_CHINA_CRAWL=1 to include) ===", flush=True)

    print("\nAll content refresh steps finished.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
