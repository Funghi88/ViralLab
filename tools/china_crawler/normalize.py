"""Normalize crawler results to the same shape as Bilibili (title, url, description, views, platform, content_type)."""

from typing import Union


def normalize_item(
    *,
    title: str,
    url: str,
    description: str = "",
    views: Union[str, int] = "N/A",
    platform: str,
    content_type: str = "video",
) -> dict:
    """One item in the shape ViralLab uses. content_type: video, post, article, etc."""
    views_int = 0
    if isinstance(views, int):
        views_int = views
    elif isinstance(views, str) and views.isdigit():
        views_int = int(views)
    views_str = str(views) if views else "N/A"
    ct = (content_type or "video").lower()
    if ct not in ("video", "post", "article", "note"):
        ct = "video"
    return {
        "title": (title or "").strip(),
        "url": (url or "").strip(),
        "description": (description or "")[:500],
        "views": views_str,
        "views_int": views_int,
        "platform": (platform or "").lower(),
        "content_type": ct,
    }
