"""Parse output markdown files into structured data."""
import re
from pathlib import Path
from typing import Any


def parse_raw_news(content: str) -> list[dict[str, Any]]:
    """Parse raw_*.md format: ## N. Title, snippet, Source:, URL."""
    items = []
    blocks = re.split(r"\n## \d+\. ", content)
    if not blocks:
        return items
    blocks = blocks[1:]  # skip header
    for block in blocks:
        lines = block.strip().split("\n")
        if not lines:
            continue
        title = lines[0].strip()
        if title.startswith("Search error"):
            continue
        url = ""
        snippet = ""
        source = ""
        for line in lines[1:]:
            s = line.strip()
            if s.startswith("URL:"):
                url = s[4:].strip()
                break
            if s.startswith("Source:"):
                source = s[7:].strip()
            elif s:
                snippet = s[:200]
        items.append({"title": title, "url": url, "snippet": snippet, "source": source})
    return items


def parse_videos(content: str) -> list[dict[str, Any]]:
    """Parse videos_*.md format: ## N. Title, URL, Views, Berger score, Magic words, desc."""
    items = []
    blocks = re.split(r"\n## \d+\. ", content)
    if not blocks:
        return items
    blocks = blocks[1:]
    for block in blocks:
        lines = block.strip().split("\n")
        if not lines:
            continue
        title = lines[0].strip()
        url = ""
        views = "N/A"
        berger = 0
        magic = ""
        desc = ""
        past_magic = False
        for line in lines[1:]:
            s = line.strip().lstrip("- ").strip()  # handle "- URL: ..." format
            if s.startswith("URL:"):
                url = s[4:].strip()
            elif s.startswith("Views:"):
                views = s[7:].strip()
            elif "Berger score:" in s:
                m = re.search(r"(\d+)/100", s)
                berger = int(m.group(1)) if m else 0
            elif "Magic words:" in s:
                magic = s.split("Magic words:")[-1].strip()
                past_magic = True
            elif past_magic and s and not s.startswith("Magic words:"):
                desc = s.lstrip("- ")[:150]
                past_magic = False
        if title:
            items.append({
                "title": title, "url": url, "views": views,
                "berger": berger, "magic": magic, "desc": desc,
            })
    return items


def _infer_source_from_url(url: str) -> str:
    """Infer source from URL for legacy items without Source line."""
    if not url:
        return ""
    url_lower = url.lower()
    if "news.ycombinator.com" in url_lower:
        return "Hacker News front page"
    if "theverge.com" in url_lower:
        return "The Verge"
    if "techcrunch.com" in url_lower:
        return "TechCrunch"
    if "producthunt.com" in url_lower:
        return "Product Hunt"
    if "youtube.com" in url_lower:
        return "YouTube Trending"
    return ""


def parse_daily_news(content: str) -> list[dict[str, Any]]:
    """Parse daily_news.md format: ## N. Title, snippet, Source:, URL."""
    items = []
    blocks = re.split(r"\n## \d+\. ", content)
    if not blocks:
        return items
    blocks = blocks[1:]
    for block in blocks:
        lines = block.strip().split("\n")
        if not lines:
            continue
        title = lines[0].strip()
        url = ""
        snippet = ""
        source = ""
        for line in lines[1:]:
            s = line.strip()
            if s.startswith("URL:"):
                url = s[4:].strip()
                break
            if s.startswith("Source:"):
                source = s[7:].strip()
            elif s and not s.startswith("---"):
                snippet = s[:200]
        if not source and url:
            source = _infer_source_from_url(url)
        if title:
            items.append({"title": title, "url": url, "snippet": snippet, "source": source})
    return items


def parse_file(path: Path) -> tuple[str, list[dict]]:
    """Parse file by type. Returns (type, items)."""
    content = path.read_text(encoding="utf-8", errors="replace")
    name = path.stem
    if name == "daily_news" or name == "daily_news_zh":
        items = parse_daily_news(content)
        return ("daily_news" if name == "daily_news" else "daily_news_zh", items)
    if name.startswith("raw_"):
        items = parse_raw_news(content)
        return ("news", items)
    if name.startswith("videos_"):
        items = parse_videos(content)
        return ("videos", items)
    return ("unknown", [])
