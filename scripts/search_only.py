#!/usr/bin/env python
"""Search for news on a topic. Multi-source: DuckDuckGo, HN, NewsAPI. Outputs raw results."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def search_news(topic: str, max_results: int = 12) -> str:
    """Search multiple sources by topic. Returns formatted raw results."""
    try:
        from src.news_sources import fetch_all_topic_sources
        items, _ = fetch_all_topic_sources(topic, target_total=max_results)
    except Exception as e:
        return f"# Search error\n{str(e)}"

    if not items:
        return f"# No news found for: {topic}"

    lines = [f"# Raw news results: {topic}\n"]
    for i, r in enumerate(items, 1):
        title = r.get("title", "N/A")
        body = (r.get("snippet") or "")[:300]
        url = r.get("url", "")
        src = r.get("source", "")
        src_line = f"\nSource: {src}\n" if src else "\n"
        lines.append(f"## {i}. {title}\n\n{body}\n{src_line}URL: {url}\n")
    return "\n".join(lines)


def main():
    topic = sys.argv[1] if len(sys.argv) > 1 else "AI agents"
    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(exist_ok=True)

    raw = search_news(topic)
    safe_topic = topic.replace(" ", "_")[:30]
    out_file = output_dir / f"raw_{safe_topic}.md"
    out_file.write_text(raw, encoding="utf-8")

    # Record run for lifecycle
    try:
        from src.parse_output import parse_raw_news
        from src.run_history import record_run
        parsed = parse_raw_news(raw)
        record_run(f"raw_{safe_topic}", parsed)
    except Exception:
        pass

    print(f"Saved raw results to {out_file}")
    return out_file


if __name__ == "__main__":
    main()
