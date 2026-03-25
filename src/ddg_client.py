"""DuckDuckGo client compatibility helper.

Prefer the new `ddgs` package, with fallback to `duckduckgo_search`
for environments that have not migrated yet.
"""


def get_ddgs_class():
    """Return DDGS class from available package."""
    try:
        from ddgs import DDGS
        return DDGS
    except ImportError:
        from duckduckgo_search import DDGS
        return DDGS
