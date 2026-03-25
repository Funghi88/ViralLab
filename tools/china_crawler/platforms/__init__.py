"""Platform-specific fetchers.

Each platform module exposes fetch_*_search and returns raw list of dicts.
"""

from . import bilibili, douyin, shipinhao, xhs, zhihu

PLATFORMS = {
    "xhs": xhs,
    "douyin": douyin,
    "shipinhao": shipinhao,
    "zhihu": zhihu,
    "bilibili": bilibili,
}
