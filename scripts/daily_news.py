#!/usr/bin/env python
"""Fetch today's top creator-focused news. 10 on dashboard, 60 in full digest (load more). EN + ZH."""
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env for API keys
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass


def _write_digest(output_dir: Path, lang: str, items: list, sources_used: list, updated_at: str) -> Path:
    top10, all60 = items[:10], items[:60]

    if lang == "zh":
        mechanism = "前 3 条为当下最热话题。小红书、抖音创作者可参考"
        header = "# 每日新闻\n"
        header += f"**最后更新：** {updated_at}\n"
        header += f"创作者最相关新闻。主页 10 条，载入更多。\n\n{mechanism}\n\n---\n"
        footer = "\n---\n*[按主题搜索](/news?lang=zh) — 了解 X 领域动态*\n"
    else:
        mechanism = "Top 3 = most talked about right now. Xiaohongshu and Douyin creators can reference."
        header = "# Daily News\n"
        header += f"**Last updated:** {updated_at}\n"
        header += f"Top news for creators. Items 1–10 on main page, load more.\n\n{mechanism}\n\n---\n"
        footer = "\n---\n*[Search by topic](/news) — what's happening around X*\n"

    lines = [header]
    for i, item in enumerate(all60, 1):
        src = item.get("source", "")
        src_line = f"\nSource: {src}\n" if src else "\n"
        lines.append(f"## {i}. {item['title']}\n\n{item.get('snippet', '')}\n{src_line}URL: {item['url']}\n")
    lines.append(footer)

    filename = "daily_news_zh.md" if lang == "zh" else "daily_news.md"
    out_file = output_dir / filename
    out_file.write_text("\n".join(lines), encoding="utf-8")
    return out_file


def main():
    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(exist_ok=True)

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    weekday = now.strftime("%a")
    updated_at = now.strftime("%Y-%m-%d %H:%M UTC")

    from src.news_sources import fetch_all_sources

    print(f"Fetching daily news for {today} ({weekday})...")
    items_en, sources_en = fetch_all_sources(target_total=60, lang="en")
    items_zh, sources_zh = fetch_all_sources(target_total=60, lang="zh")

    _write_digest(output_dir, "en", items_en, sources_en, updated_at)
    _write_digest(output_dir, "zh", items_zh, sources_zh, updated_at)

    # Save sources and timestamp for UI (EN default)
    (output_dir / "daily_news_sources.txt").write_text(
        ", ".join(sources_en) if sources_en else "DuckDuckGo News", encoding="utf-8"
    )
    (output_dir / "daily_news_sources_zh.txt").write_text(
        ", ".join(sources_zh) if sources_zh else "DuckDuckGo 新闻", encoding="utf-8"
    )
    (output_dir / "daily_news_updated.txt").write_text(updated_at, encoding="utf-8")

    # Record run for lifecycle (rising/peaking/fading)
    try:
        from src.run_history import record_run
        record_run("daily_news", items_en[:3])
        record_run("daily_news_zh", items_zh[:3])
    except Exception:
        pass

    print(f"Saved EN (sources: {', '.join(sources_en)}) and ZH (sources: {', '.join(sources_zh)})")
    return output_dir / "daily_news.md"


if __name__ == "__main__":
    main()
