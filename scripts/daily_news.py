#!/usr/bin/env python
"""Fetch today's top creator-focused news. 10 on dashboard, 60 in full digest (load more). EN + ZH."""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.proxy_env import load_dotenv_safe

load_dotenv_safe(PROJECT_ROOT / ".env")


def _file_has_articles(path: Path) -> bool:
    """Return True if an existing digest file contains at least one rendered item."""
    if not path.is_file():
        return False
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
        return "\n## 1. " in txt or txt.startswith("## 1. ")
    except OSError:
        return False


def _write_digest(output_dir: Path, lang: str, items: list, sources_used: list, updated_at: str, snapshot_md: str = "") -> Path:
    top10, all60 = items[:10], items[:60]

    if lang == "zh":
        mechanism = (
            "头条优先 **AI/科技与大模型**，然后是 **中美关系与政经**，再单列 **经济与公众情绪／疗愈玄学等文化报道（参考语气与热点）**，最后是 **影视娱乐（轻量）**。"
            "打开 [/news](/news?lang=zh) 可按「科技 / 中美政经 / 创业 / 创作者」查看带搜索次数的热门话题。"
        )
        header = "# 每日新闻\n"
        header += f"**最后更新：** {updated_at}\n"
        header += f"精选信息流：主页展示前 10 条，可载入更多（至多 60 条）。\n\n{mechanism}\n\n---\n"
        footer = "\n---\n*[按主题搜索](/news?lang=zh) — 分领域热度与长文播客]*\n"
    else:
        mechanism = (
            "**AI & tech first**, then **US–China business/politics**, then **economy × public mood** (stress, downturn, belief/sensation stories to study tone)—then **light Hollywood/entertainment**. "
            "On [/news](/news), switch audience pills to see per-field hot topics with in-app search counts."
        )
        header = "# Daily News\n"
        header += f"**Last updated:** {updated_at}\n"
        header += f"Editorial mix: items 1–10 on the home digest, up to 60 with load more.\n\n{mechanism}\n\n---\n"
        footer = "\n---\n*[News by topic](/news) — field heat, long-form & podcasts]*\n"

    lines = [header]
    if snapshot_md:
        lines.append(snapshot_md.strip() + "\n\n---\n")
    for i, item in enumerate(all60, 1):
        src = item.get("source", "")
        src_line = f"\nSource: {src}\n" if src else "\n"
        lines.append(f"## {i}. {item['title']}\n\n{item.get('snippet', '')}\n{src_line}URL: {item['url']}\n")
    lines.append(footer)

    filename = "daily_news_zh.md" if lang == "zh" else "daily_news.md"
    out_file = output_dir / filename
    if not all60 and _file_has_articles(out_file):
        print(f"[daily_news] WARN: 0 items fetched for {lang}; keeping existing {filename}")
        return out_file
    out_file.write_text("\n".join(lines), encoding="utf-8")
    return out_file


def _write_ai_authority_digest(output_dir: Path, lang: str, items: list, updated_at: str) -> Path:
    from src.news_sources import AI_INTEL_LAYER_ORDER, classify_ai_authority_item, summarize_ai_authority_items

    summary = summarize_ai_authority_items(items)
    layer_line = " · ".join(
        f"{layer}: {summary['layers'].get(layer, 0)}" for layer in AI_INTEL_LAYER_ORDER
    )
    if lang == "zh":
        lines = [
            "# AI 权威简报\n"
            f"**最后更新：** {updated_at}\n"
            "中文权威流：优先中文来源，并按战略层聚合一手 AI 信号。\n\n"
            f"**层分布：** {layer_line}\n\n"
            "---\n"
        ]
    else:
        lines = [
            "# AI Authority Brief\n"
            f"**Last updated:** {updated_at}\n"
            "Signal-first stream from official labs, research institutes, and high-credibility AI publications.\n\n"
            f"**Layer mix:** {layer_line}\n\n"
            "---\n"
        ]
    grouped: dict[str, list[dict]] = {k: [] for k in AI_INTEL_LAYER_ORDER}
    for item in items[:40]:
        cls = classify_ai_authority_item(item)
        enriched = dict(item)
        enriched["layer"] = cls["layer"]
        enriched["cadence"] = cls["cadence"]
        grouped.setdefault(cls["layer"], []).append(enriched)

    idx = 1
    for layer in AI_INTEL_LAYER_ORDER:
        bucket = grouped.get(layer, [])
        if not bucket:
            continue
        lines.append(f"### {layer}\n")
        for item in bucket:
            src = item.get("source", "")
            src_line = f"\nSource: {src}\n" if src else "\n"
            if lang == "zh":
                lines.append(
                    f"## {idx}. {item.get('title', 'N/A')}\n\n"
                    f"{item.get('snippet', '')}\n"
                    f"Layer: {item.get('layer', 'Industry')}\n"
                    f"Cadence: {item.get('cadence', 'Weekly')}\n"
                    f"{src_line}URL: {item.get('url', '')}\n"
                )
            else:
                lines.append(
                    f"## {idx}. {item.get('title', 'N/A')}\n\n"
                    f"{item.get('snippet', '')}\n"
                    f"Layer: {item.get('layer', 'Industry')}\n"
                    f"Cadence: {item.get('cadence', 'Weekly')}\n"
                    f"{src_line}URL: {item.get('url', '')}\n"
                )
            idx += 1
    if lang == "zh":
        lines.append("\n---\n*Founder 视角：能力边界 · 产业重构 · 资本流向 · 个人杠杆*\n")
    else:
        lines.append("\n---\n*Founder lens: capability frontier · industry reset · capital flow · personal leverage*\n")
    out_file = output_dir / ("daily_ai_authority_zh.md" if lang == "zh" else "daily_ai_authority.md")
    if not items and _file_has_articles(out_file):
        print(f"[daily_news] WARN: 0 AI authority items for {lang}; keeping existing {out_file.name}")
        return out_file
    out_file.write_text("\n".join(lines), encoding="utf-8")
    return out_file


def _write_ai_longform_digest(output_dir: Path, lang: str, items: list, updated_at: str) -> Path:
    if lang == "zh":
        header = (
            "# AI 长文与报告\n"
            f"**最后更新：** {updated_at}\n"
            "来自研究机构、智库与深度媒体的长文/报告信号。\n\n---\n"
        )
        filename = "longform_ai_authority_zh.md"
    else:
        header = (
            "# AI Long-form Signals\n"
            f"**Last updated:** {updated_at}\n"
            "Long-form and report-oriented signals from labs, institutes, and deep-analysis outlets.\n\n---\n"
        )
        filename = "longform_ai_authority.md"
    lines = [header]
    for i, item in enumerate(items[:40], 1):
        src = item.get("source", "")
        src_line = f"\nSource: {src}\n" if src else "\n"
        lines.append(
            f"## {i}. {item.get('title', 'N/A')}\n\n"
            f"{item.get('snippet', '')}\n"
            f"{src_line}URL: {item.get('url', '')}\n"
        )
    out_file = output_dir / filename
    if not items and _file_has_articles(out_file):
        print(f"[daily_news] WARN: 0 AI longform items for {lang}; keeping existing {filename}")
        return out_file
    out_file.write_text("\n".join(lines), encoding="utf-8")
    return out_file


def main(authority_only: bool = False):
    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(exist_ok=True)

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    weekday = now.strftime("%a")
    updated_at = now.strftime("%Y-%m-%d %H:%M UTC")

    from src.news_sources import fetch_ai_authority_sources, fetch_all_sources
    from src.news_topic_stats import daily_snapshot_markdown

    if not authority_only:
        print(f"Fetching daily news for {today} ({weekday})...")
        items_en, sources_en = fetch_all_sources(target_total=60, lang="en")
        items_zh, sources_zh = fetch_all_sources(target_total=60, lang="zh")

        snap_en = daily_snapshot_markdown("en", "1d")
        snap_zh = daily_snapshot_markdown("zh", "1d")

        _write_digest(output_dir, "en", items_en, sources_en, updated_at, snapshot_md=snap_en)
        _write_digest(output_dir, "zh", items_zh, sources_zh, updated_at, snapshot_md=snap_zh)

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

    from src.news_sources import classify_ai_authority_item
    from src.podcast_rss_sources import classify_source_type

    authority_en, authority_sources_en = fetch_ai_authority_sources(
        target_total=20,
        max_per_feed=2,
        lang="en",
        news_only=False,
    )
    authority_zh, authority_sources_zh = fetch_ai_authority_sources(
        target_total=12,
        max_per_feed=2,
        lang="zh",
        news_only=False,
    )

    def _split_news_vs_longform(items: list[dict]) -> tuple[list[dict], list[dict]]:
        news_items: list[dict] = []
        longform_items: list[dict] = []
        for item in items:
            cls = classify_ai_authority_item(item)
            cadence = cls.get("cadence", "Weekly")
            source_type = classify_source_type((item.get("source") or "").strip())
            if source_type != "news" or cadence in ("Monthly", "Quarterly"):
                longform_items.append(item)
            else:
                news_items.append(item)
        return news_items, longform_items

    authority_en_news, authority_en_longform = _split_news_vs_longform(authority_en)
    authority_zh_news, authority_zh_longform = _split_news_vs_longform(authority_zh)

    _write_ai_authority_digest(output_dir, "en", authority_en_news, updated_at)
    _write_ai_authority_digest(output_dir, "zh", authority_zh_news, updated_at)
    _write_ai_longform_digest(output_dir, "en", authority_en_longform, updated_at)
    _write_ai_longform_digest(output_dir, "zh", authority_zh_longform, updated_at)
    (output_dir / "daily_ai_authority_sources.txt").write_text(
        ", ".join(authority_sources_en) if authority_sources_en else "OpenAI Blog, Google AI Blog, Hugging Face Blog",
        encoding="utf-8",
    )
    (output_dir / "daily_ai_authority_sources_zh.txt").write_text(
        ", ".join(authority_sources_zh) if authority_sources_zh else "量子位, 腾讯研究院, 机器之心",
        encoding="utf-8",
    )
    (output_dir / "daily_ai_authority_updated.txt").write_text(updated_at, encoding="utf-8")
    (output_dir / "daily_ai_authority_updated_zh.txt").write_text(updated_at, encoding="utf-8")
    print(
        f"Saved AI Authority EN/ZH + longform EN/ZH "
        f"(sources EN: {', '.join(authority_sources_en)} | ZH: {', '.join(authority_sources_zh)})"
    )

    try:
        from src.output_cleanup import cleanup_ephemeral_output

        removed = cleanup_ephemeral_output(output_dir)
        if removed:
            print(f"Cleaned {len(removed)} file(s) older than retention (OUTPUT_RETENTION_DAYS): {', '.join(removed[:8])}{'…' if len(removed) > 8 else ''}")
    except Exception as e:
        print(f"[daily_news] output cleanup skipped: {e}")

    return output_dir / ("daily_ai_authority.md" if authority_only else "daily_news.md")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build ViralLab daily digests.")
    parser.add_argument(
        "--authority-only",
        action="store_true",
        help="Only refresh AI authority digest and skip the main EN/ZH daily digest.",
    )
    args = parser.parse_args()
    main(authority_only=args.authority_only)
