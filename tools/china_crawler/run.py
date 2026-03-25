"""CLI entry for China crawler. Platforms: xhs, douyin, shipinhao, zhihu, bilibili."""

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
_PLATFORM_IDS = {
    "xhs": "xiaohongshu",
    "douyin": "douyin",
    "shipinhao": "shipinhao",
    "zhihu": "zhihu",
    "bilibili": "bilibili",
}
_FETCH_FUNCS = {
    "xhs": "fetch_xhs_search",
    "douyin": "fetch_douyin_search",
    "shipinhao": "fetch_shipinhao_search",
    "zhihu": "fetch_zhihu_search",
    "bilibili": "fetch_bilibili_search",
}

# Login URLs for saving session (user logs in in browser, we save storage state)
_LOGIN_URLS = {
    "xhs": "https://www.xiaohongshu.com",
    "douyin": "https://www.douyin.com",
    "zhihu": "https://www.zhihu.com",
    "shipinhao": "https://channels.weixin.qq.com",
}


def _storage_state_path(platform: str) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR / f"china_crawler_{platform}_state.json"


def login_cmd(args: argparse.Namespace) -> int:
    """Open browser for user to log in; save session to config/ for later crawls."""
    platform = (args.platform or "xhs").lower()
    if platform not in _LOGIN_URLS:
        print(
            f"Error: unsupported platform {platform}. Use: xhs, douyin, shipinhao, zhihu "
            "(bilibili does not require login)",
            file=sys.stderr,
        )
        return 1
    url = _LOGIN_URLS[platform]
    state_path = _storage_state_path(platform)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright required. Run: pip install playwright && playwright install chromium", file=sys.stderr)
        return 1
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Opening browser for {platform}. Log in there, then return here and press Enter.", file=sys.stderr)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        input("After you have logged in, press Enter to save session (or Ctrl+C to cancel)... ")
        context.storage_state(path=str(state_path))
        browser.close()
    print(f"Session saved to {state_path}. Future crawls for {platform} will use it.", file=sys.stderr)
    return 0


def _output_path(platform: str) -> Path:
    if os.environ.get("CHINA_CRAWLER_OUTPUT_DIR"):
        return Path(os.environ["CHINA_CRAWLER_OUTPUT_DIR"]) / f"china_crawler_{platform}.json"
    if os.environ.get("CHINA_CRAWLER_OUTPUT"):
        return Path(os.environ["CHINA_CRAWLER_OUTPUT"])
    return PROJECT_ROOT / "output" / "china_crawler_results.json"


def run(args: argparse.Namespace) -> int:
    platform = (args.platform or "xhs").lower()
    crawl_type = (args.type or "search").lower()
    keywords = (args.keywords or "").strip()
    if not keywords:
        print("Error: --keywords is required.", file=sys.stderr)
        return 1

    if platform not in _PLATFORM_IDS:
        print(f"Error: unsupported platform {platform}. Use: xhs, douyin, shipinhao, zhihu, bilibili", file=sys.stderr)
        return 1
    if crawl_type != "search":
        print(f"Error: unsupported type {crawl_type}. Use: search", file=sys.stderr)
        return 1

    from . import platforms
    from .normalize import normalize_item

    mod = platforms.PLATFORMS.get(platform)
    fetch_fn = getattr(mod, _FETCH_FUNCS.get(platform, "fetch_xhs_search"), None) if mod else None
    if not fetch_fn:
        return 1

    max_results = min(int(args.max or 20), 50)
    headless = not getattr(args, "no_headless", False)

    print(f"Running: platform={platform}, type={crawl_type}, keywords={keywords!r}, max={max_results}", file=sys.stderr)
    raw = fetch_fn(keywords, max_results=max_results, headless=headless)
    print(f"Fetched {len(raw)} raw items.", file=sys.stderr)

    platform_id = _PLATFORM_IDS[platform]
    normalized = [
        normalize_item(
            title=item.get("title", ""),
            url=item.get("url", ""),
            description=item.get("description", ""),
            views=item.get("views", "N/A"),
            platform=platform_id,
            content_type=item.get("content_type", "video"),
        )
        for item in raw
    ]

    out_path = _output_path(platform)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "platform": platform,
        "type": crawl_type,
        "keywords": keywords,
        "count": len(normalized),
        "items": normalized,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(normalized)} items to {out_path}", file=sys.stderr)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="China crawler (multi-platform search).")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="Run a crawl job")
    run_parser.add_argument("--platform", "-p", default="xhs", help="Platform: xhs, douyin, shipinhao, zhihu, bilibili")
    run_parser.add_argument("--type", "-t", default="search", help="Crawl type: search")
    run_parser.add_argument("--keywords", "-k", required=True, help="Search keywords")
    run_parser.add_argument("--max", "-n", default="20", help="Max results (default 20, max 50)")
    run_parser.add_argument("--no-headless", action="store_true", help="Show browser window")
    run_parser.set_defaults(func=run)

    login_parser = sub.add_parser("login", help="Open browser to log in; save session to config/ for later crawls")
    login_parser.add_argument("--platform", "-p", default="xhs", help="Platform: xhs, douyin, shipinhao, zhihu (bilibili not needed)")
    login_parser.set_defaults(func=login_cmd)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
