"""Multi-channel publish connectors & formatters for ViralLab.

Supported platforms:
- `blog`        : GitHub Pages Jekyll blog (default: Funghi88/funghi88.github.io) via GitHub API,
                  or BLOG_PUBLISH_WEBHOOK fallback.
- `telegram`    : Direct Telegram Bot API (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`), auto-chunked.
- `wechat`      : WeChat Official Account Draft Box API (`WECHAT_APP_ID` + `WECHAT_APP_SECRET`
                  + `WECHAT_THUMB_MEDIA_ID`) + inline-CSS Rich HTML formatter for 1-click copy.
- `xiaohongshu` : Native XHS mobile formatter (<=20 char title, emoji bullets, hashtags) + optional
                  `XHS_PUBLISH_WEBHOOK` dispatch.
- `x`           : Direct X API v2 OAuth 1.0a (`X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`,
                  `X_ACCESS_TOKEN_SECRET`) with automatic threading, or `X_PUBLISH_WEBHOOK`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import os
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlparse

import requests

from src.proxy_env import requests_proxies_for

SUPPORTED_PLATFORMS = ("blog", "telegram", "wechat", "xiaohongshu", "x")

PLATFORM_META: dict[str, dict[str, str]] = {
    "blog": {
        "name_en": "Personal Blog (funghi88.github.io)",
        "name_zh": "个人博客 (funghi88.github.io)",
        "compose_url": "https://github.com/Funghi88/funghi88.github.io/tree/main/_posts",
    },
    "telegram": {
        "name_en": "Telegram Channel / Chat",
        "name_zh": "Telegram 频道 / 群组",
        "compose_url": "https://web.telegram.org/",
    },
    "wechat": {
        "name_en": "WeChat Official Account (公众号)",
        "name_zh": "微信公众号",
        "compose_url": "https://mp.weixin.qq.com/",
    },
    "xiaohongshu": {
        "name_en": "Xiaohongshu (小红书)",
        "name_zh": "小红书",
        "compose_url": "https://creator.xiaohongshu.com/publish/publish",
    },
    "x": {
        "name_en": "X (Twitter)",
        "name_zh": "X (Twitter)",
        "compose_url": "https://x.com/compose/post",
    },
}


def normalize_platform(platform: str) -> str:
    p = (platform or "x").strip().lower()
    aliases = {
        "twitter": "x",
        "xhs": "xiaohongshu",
        "red": "xiaohongshu",
        "wx": "wechat",
        "mp": "wechat",
        "tg": "telegram",
        "github": "blog",
        "jekyll": "blog",
    }
    p = aliases.get(p, p)
    return p if p in SUPPORTED_PLATFORMS else "x"


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def get_connector_statuses() -> dict[str, dict[str, Any]]:
    """Return live readiness status for all 5 publish channels (for /publish UI)."""
    gh_token = bool(_env("GITHUB_TOKEN"))
    gh_repo = _env("GITHUB_BLOG_REPO", "Funghi88/funghi88.github.io")
    blog_wh = bool(_env("BLOG_PUBLISH_WEBHOOK"))
    tg_ready = bool(_env("TELEGRAM_BOT_TOKEN") and _env("TELEGRAM_CHAT_ID"))
    wx_api = bool(_env("WECHAT_APP_ID") and _env("WECHAT_APP_SECRET"))
    wx_thumb = bool(_env("WECHAT_THUMB_MEDIA_ID"))
    wx_wh = bool(_env("WECHAT_PUBLISH_WEBHOOK"))
    xhs_wh = bool(_env("XHS_PUBLISH_WEBHOOK"))
    x_oauth = bool(
        _env("X_API_KEY")
        and _env("X_API_SECRET")
        and _env("X_ACCESS_TOKEN")
        and _env("X_ACCESS_TOKEN_SECRET")
    )
    x_wh = bool(_env("X_PUBLISH_WEBHOOK"))

    return {
        "blog": {
            "ready": gh_token or blog_wh,
            "mode": "github_api" if gh_token else ("webhook" if blog_wh else "export_only"),
            "target": gh_repo,
            "hint_en": f"Connected to {gh_repo}" if gh_token else ("Blog webhook active" if blog_wh else "Set GITHUB_TOKEN in .env to auto-commit to funghi88.github.io (or copy Jekyll .md)"),
            "hint_zh": f"已连接 {gh_repo}" if gh_token else ("已配置博客 Webhook" if blog_wh else "在 .env 配置 GITHUB_TOKEN 即可一键发布到 funghi88.github.io（或复制 Jekyll Markdown）"),
        },
        "telegram": {
            "ready": tg_ready,
            "mode": "bot_api" if tg_ready else "unconfigured",
            "target": _env("TELEGRAM_CHAT_ID"),
            "hint_en": f"Bot connected ({_env('TELEGRAM_CHAT_ID')})" if tg_ready else "Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID in .env",
            "hint_zh": f"Bot 已连接 ({_env('TELEGRAM_CHAT_ID')})" if tg_ready else "在 .env 配置 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID",
        },
        "wechat": {
            "ready": (wx_api and wx_thumb) or wx_wh,
            "mode": "draft_api" if (wx_api and wx_thumb) else ("webhook" if wx_wh else "rich_html_copy"),
            "target": "mp.weixin.qq.com",
            "hint_en": (
                "Draft Box API ready"
                if (wx_api and wx_thumb)
                else (
                    "AppID set; add WECHAT_THUMB_MEDIA_ID for API or use Copy Rich HTML"
                    if wx_api
                    else "1-click Copy WeChat Rich HTML ready (optional: WECHAT_APP_ID/SECRET for Draft API)"
                )
            ),
            "hint_zh": (
                "公众号草稿箱 API 已就绪"
                if (wx_api and wx_thumb)
                else (
                    "已配 AppID；补充 WECHAT_THUMB_MEDIA_ID 可直推草稿箱，或点「复制公众号富文本」"
                    if wx_api
                    else "支持一键「复制公众号富文本」直贴后台（可选配 WECHAT_APP_ID/SECRET 推草稿箱）"
                )
            ),
        },
        "xiaohongshu": {
            "ready": xhs_wh,
            "mode": "webhook" if xhs_wh else "format_copy",
            "target": "creator.xiaohongshu.com",
            "hint_en": "XHS webhook ready" if xhs_wh else "1-click XHS formatter + copy ready (optional: XHS_PUBLISH_WEBHOOK)",
            "hint_zh": "小红书 Webhook 已就绪" if xhs_wh else "支持一键生成小红书排版并复制（可选配 XHS_PUBLISH_WEBHOOK）",
        },
        "x": {
            "ready": x_oauth or x_wh,
            "mode": "api_v2" if x_oauth else ("webhook" if x_wh else "compose_link"),
            "target": "x.com",
            "hint_en": "X API v2 ready (threads supported)" if x_oauth else ("X webhook ready" if x_wh else "1-click X thread formatter + composer ready (optional: X_API_* or X_PUBLISH_WEBHOOK)"),
            "hint_zh": "X API v2 已就绪（支持自动串推）" if x_oauth else ("X Webhook 已就绪" if x_wh else "支持一键串推排版 + 打开 X 发布页（可选配 X_API_* 或 X_PUBLISH_WEBHOOK）"),
        },
    }


# ---------------------------------------------------------------------------
# Formatters (usable both by API connectors and 1-click UI copy buttons)
# ---------------------------------------------------------------------------


def _strip_markdown(md: str) -> str:
    s = (md or "").strip()
    s = re.sub(r"^---[\s\S]*?---\s*", "", s)
    s = re.sub(r"```[\s\S]*?```", "", s)
    s = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", s)
    s = re.sub(r"^#{1,6}\s*", "", s, flags=re.MULTILINE)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"\*([^*]+)\*", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def _slugify(title: str) -> str:
    """Create a URL/filename-safe Jekyll post slug (supports ASCII & CJK titles)."""
    s = (title or "post").strip()
    s = re.sub(r"[\\/:*?\"<>|#%&{}^~`\[\]]+", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-.")
    if not s:
        s = f"post-{secrets.token_hex(3)}"
    return s[:64]


def _yaml_quote(s: str) -> str:
    cleaned = (s or "").replace("\r", " ").replace("\n", " ").strip()
    escaped = cleaned.replace("'", "''")
    return f"'{escaped}'"


def format_for_blog_jekyll(
    title: str,
    content: str,
    *,
    category: str = "",
    excerpt: str = "",
    date_str: str = "",
) -> tuple[str, str]:
    """Return `(filename, full_jekyll_markdown)` matching funghi88.github.io `_posts/` schema."""
    body = (content or "").strip()
    now_date = date_str or datetime.now().strftime("%Y-%m-%d")
    slug = _slugify(title)
    filename = f"{now_date}-{slug}.md"

    # Preserve frontmatter if user already authored YAML frontmatter.
    if body.startswith("---\n") and "\n---" in body[4:]:
        return filename, body + ("\n" if not body.endswith("\n") else "")

    cat = category or _env("GITHUB_BLOG_CATEGORY", "Writing")
    plain = _strip_markdown(body)
    auto_excerpt = (excerpt or plain[:140]).replace("\n", " ").strip()
    if len(plain) > 140 and not excerpt:
        auto_excerpt = auto_excerpt.rstrip(".,;: ") + "…"

    frontmatter = (
        "---\n"
        "layout: post\n"
        f"title: {_yaml_quote(title or 'Untitled')}\n"
        f"date: {now_date}\n"
        f"category: {cat}\n"
        f"excerpt: {_yaml_quote(auto_excerpt)}\n"
        "---\n\n"
    )
    if not body.startswith("# "):
        body = f"# {title or 'Untitled'}\n\n{body}"
    return filename, frontmatter + body + "\n"


def format_for_telegram_html(title: str, content: str) -> list[str]:
    """Convert markdown into Telegram-safe HTML chunks (<= 3900 chars each)."""
    body = (content or "").strip()
    body = re.sub(r"^---[\s\S]*?---\s*", "", body)
    lines: list[str] = []
    if title:
        lines.append(f"<b>{html.escape(title.strip())}</b>")
        lines.append("")
    for raw in body.splitlines():
        line = raw.rstrip()
        if not line:
            lines.append("")
            continue
        if re.match(r"^#{1,6}\s+", line):
            h = re.sub(r"^#{1,6}\s+", "", line).strip()
            lines.append(f"<b>{html.escape(h)}</b>")
            continue
        # Escape HTML first, then restore safe markdown links/bold/code
        esc = html.escape(line)
        esc = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', esc)
        esc = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", esc)
        esc = re.sub(r"`([^`]+)`", r"<code>\1</code>", esc)
        lines.append(esc)

    full = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if len(full) <= 3900:
        return [full] if full else [""]

    chunks: list[str] = []
    cur = ""
    for para in full.split("\n\n"):
        if len(cur) + len(para) + 2 <= 3900:
            cur = f"{cur}\n\n{para}".strip()
        else:
            if cur:
                chunks.append(cur)
            cur = para[:3900]
    if cur:
        chunks.append(cur)
    return chunks


def format_for_wechat_html(title: str, content: str) -> str:
    """Render clean inline-CSS HTML tailored for pasting into WeChat 公众号 editor or Draft API."""
    body = re.sub(r"^---[\s\S]*?---\s*", "", (content or "").strip())
    try:
        import markdown as md_lib

        raw_html = md_lib.markdown(body, extensions=["extra", "nl2br"])
    except Exception:
        paras = [f"<p>{html.escape(p.strip())}</p>" for p in body.split("\n\n") if p.strip()]
        raw_html = "\n".join(paras)

    # Inject clean inline styles because WeChat strips <style> tags and classes.
    styled = raw_html
    styled = re.sub(
        r"<h1>",
        '<h1 style="font-size:22px;font-weight:700;color:#1a1a1a;margin:18px 0 12px;line-height:1.4;">',
        styled,
    )
    styled = re.sub(
        r"<h2>",
        '<h2 style="font-size:18px;font-weight:700;color:#1a1a1a;border-left:4px solid #c9562b;padding-left:10px;margin:20px 0 10px;line-height:1.4;">',
        styled,
    )
    styled = re.sub(
        r"<h3>",
        '<h3 style="font-size:16px;font-weight:700;color:#2c2c2c;margin:16px 0 8px;line-height:1.4;">',
        styled,
    )
    styled = re.sub(
        r"<p>",
        '<p style="font-size:15px;color:#333333;line-height:1.8;margin:0 0 14px;letter-spacing:0.02em;">',
        styled,
    )
    styled = re.sub(
        r"<blockquote>",
        '<blockquote style="border-left:3px solid #d4a373;background:#faf7f2;padding:10px 14px;margin:14px 0;color:#555555;font-size:14px;line-height:1.7;">',
        styled,
    )
    styled = re.sub(
        r"<ul>",
        '<ul style="padding-left:20px;margin:0 0 14px;font-size:15px;color:#333333;line-height:1.8;">',
        styled,
    )
    styled = re.sub(
        r"<ol>",
        '<ol style="padding-left:20px;margin:0 0 14px;font-size:15px;color:#333333;line-height:1.8;">',
        styled,
    )
    styled = re.sub(r"<li>", '<li style="margin:0 0 6px;">', styled)
    styled = re.sub(
        r"<code>",
        '<code style="background:#f3f1ec;padding:2px 5px;border-radius:3px;font-size:13px;color:#b5441c;">',
        styled,
    )

    wrapper = (
        '<section style="font-family:-apple-system,BlinkMacSystemFont,\'PingFang SC\',\'Helvetica Neue\',sans-serif;max-width:680px;margin:0 auto;">'
        + styled
        + "</section>"
    )
    return wrapper


def format_for_xiaohongshu(title: str, content: str) -> dict[str, str]:
    """Format content for Xiaohongshu: <=20-char hook title, scannable emoji body, hashtags."""
    clean_title = re.sub(r"\s*·\s*Viral Rewrite$", "", (title or "").strip())
    short_title = clean_title[:20] if len(clean_title) <= 20 else clean_title[:19] + "…"

    plain = _strip_markdown(content)
    raw_paras = [p.strip() for p in re.split(r"\n+", plain) if p.strip()]
    bullets = ["✨", "📌", "💡", "🔥", "🎯", "👉"]
    formatted_lines: list[str] = []
    for idx, p in enumerate(raw_paras[:10]):
        if len(p) > 180:
            p = p[:177].rstrip() + "…"
        icon = bullets[idx % len(bullets)] if idx > 0 else "🔥"
        formatted_lines.append(f"{icon} {p}")

    # Extract existing hashtags or generate sensible default ones.
    existing_tags = re.findall(r"#[^\s#]{2,20}", content or "")
    if not existing_tags:
        lower = f"{title} {plain}".lower()
        tags = []
        if any(k in lower for k in ("ai", "人工智能", "大模型", "openai", "claude", "gemini")):
            tags.extend(["#AI趋势", "#人工智能"])
        if any(k in lower for k in ("创业", "副业", "一人公司", "startup", "creator", "创作者")):
            tags.extend(["#创作者成长", "#个人品牌"])
        if any(k in lower for k in ("科技", "产品", "tech", "design", "设计")):
            tags.extend(["#科技观察", "#干货分享"])
        if not tags:
            tags = ["#内容创作", "#热点洞察", "#认知提升"]
        existing_tags = list(dict.fromkeys(tags))[:5]

    body = "\n\n".join(formatted_lines)
    tag_line = " ".join(existing_tags[:6])
    max_body = 960 - len(tag_line) - 4
    if len(body) > max_body:
        body = body[: max(200, max_body)].rstrip() + "…"
    full_body = f"{body}\n\n{tag_line}".strip()
    return {
        "title": short_title,
        "body": full_body,
        "combined": f"{short_title}\n\n{full_body}",
    }


def format_for_x_thread(title: str, content: str, max_tweets: int = 8) -> list[str]:
    """Split content into <=275-char X posts (single tweet or numbered thread)."""
    plain = _strip_markdown(content)
    t = (title or "").strip()
    # If title + body fits in one tweet, return single tweet.
    combined = f"{t}\n\n{plain}".strip() if (t and not plain.startswith(t)) else (plain or t)
    if len(combined) <= 275:
        return [combined] if combined else [""]

    parts: list[str] = []
    sentences = [s.strip() for s in re.split(r"(?<=[。！？.!?])\s+|\n+", combined) if s.strip()]
    cur = ""
    limit = 262  # Leave room for " 1/5" counter
    for sent in sentences:
        if len(sent) > limit:
            if cur:
                parts.append(cur)
                cur = ""
            for i in range(0, len(sent), limit):
                parts.append(sent[i : i + limit].strip())
        elif not cur:
            cur = sent
        elif len(cur) + 1 + len(sent) <= limit:
            cur = f"{cur} {sent}"
        else:
            parts.append(cur)
            cur = sent
    if cur:
        parts.append(cur)

    parts = parts[:max_tweets]
    if len(parts) <= 1:
        return parts
    n = len(parts)
    return [f"{p} ({i}/{n})" for i, p in enumerate(parts, 1)]


# ---------------------------------------------------------------------------
# Live Dispatchers
# ---------------------------------------------------------------------------


def _post_webhook(url: str, payload: dict[str, Any]) -> tuple[bool, str, str]:
    r = requests.post(url, json=payload, timeout=15, proxies=requests_proxies_for(overseas=True))
    r.raise_for_status()
    return True, f"Webhook published (HTTP {r.status_code}).", ""


def publish_to_github_blog(
    title: str,
    content: str,
    *,
    draft: bool = False,
    category: str = "",
) -> tuple[bool, str, str]:
    """Commit a Jekyll post/draft directly to GitHub Pages repo (default: Funghi88/funghi88.github.io)."""
    token = _env("GITHUB_TOKEN")
    if not token:
        webhook = _env("BLOG_PUBLISH_WEBHOOK")
        if webhook:
            return _post_webhook(webhook, {"title": title, "content": content, "platform": "blog", "draft": draft})
        return (
            False,
            "GITHUB_TOKEN not set in .env (and no BLOG_PUBLISH_WEBHOOK). Use 'Copy Jekyll .md' or add GITHUB_TOKEN.",
            "",
        )

    repo = _env("GITHUB_BLOG_REPO", "Funghi88/funghi88.github.io")
    branch = _env("GITHUB_BLOG_BRANCH", "main")
    target_dir = _env("GITHUB_BLOG_DRAFTS_DIR", "_drafts") if draft else _env("GITHUB_BLOG_POSTS_DIR", "_posts")
    filename, md_full = format_for_blog_jekyll(title, content, category=category)
    rel_path = f"{target_dir.strip('/')}/{filename}"
    api_url = f"https://api.github.com/repos/{repo}/contents/{quote(rel_path, safe='/')}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    proxies = requests_proxies_for(overseas=True)

    # Check if file already exists so updates pass `sha`.
    sha = ""
    try:
        chk = requests.get(api_url, params={"ref": branch}, headers=headers, timeout=12, proxies=proxies)
        if chk.status_code == 200:
            sha = (chk.json() or {}).get("sha") or ""
    except Exception:
        pass

    payload: dict[str, Any] = {
        "message": f"{'draft' if draft else 'post'}: {title[:72]}",
        "content": base64.b64encode(md_full.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(api_url, headers=headers, json=payload, timeout=20, proxies=proxies)
    if not r.ok:
        detail = (r.text or "").strip().replace("\n", " ")[:220]
        return False, f"GitHub API HTTP {r.status_code}: {detail}", ""
    data = r.json() or {}
    html_url = (data.get("content") or {}).get("html_url") or f"https://github.com/{repo}/blob/{branch}/{rel_path}"
    site_hint = f"https://{repo.split('/')[-1]}/" if repo.endswith(".github.io") else html_url
    kind_label = "draft" if draft else "post"
    return True, f"Committed {kind_label} `{rel_path}` to {repo} (GitHub Pages builds in ~1 min).", (html_url if draft else site_hint)


def publish_to_telegram(title: str, content: str) -> tuple[bool, str, str]:
    """Send formatted HTML post to a Telegram channel or chat via Bot API."""
    token = _env("TELEGRAM_BOT_TOKEN")
    chat_id = _env("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False, "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env to publish to Telegram.", ""

    chunks = format_for_telegram_html(title, content)
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    proxies = requests_proxies_for(overseas=True)
    last_msg_id = None
    for chunk in chunks:
        r = requests.post(
            api_url,
            json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=15,
            proxies=proxies,
        )
        if not r.ok:
            detail = (r.text or "").strip().replace("\n", " ")[:220]
            return False, f"Telegram API HTTP {r.status_code}: {detail}", ""
        res = r.json() or {}
        if not res.get("ok"):
            return False, f"Telegram error: {res.get('description', 'unknown')}", ""
        last_msg_id = (res.get("result") or {}).get("message_id")

    post_url = ""
    if chat_id.startswith("@") and last_msg_id:
        post_url = f"https://t.me/{chat_id.lstrip('@')}/{last_msg_id}"
    return True, f"Published to Telegram ({len(chunks)} msg{'s' if len(chunks) > 1 else ''}).", post_url


def publish_to_wechat_draft(title: str, content: str) -> tuple[bool, str, str]:
    """Push inline-styled HTML article to WeChat Official Account Draft Box (草稿箱)."""
    app_id = _env("WECHAT_APP_ID")
    app_secret = _env("WECHAT_APP_SECRET")
    thumb_id = _env("WECHAT_THUMB_MEDIA_ID")
    webhook = _env("WECHAT_PUBLISH_WEBHOOK")
    html_body = format_for_wechat_html(title, content)

    if not (app_id and app_secret):
        if webhook:
            return _post_webhook(
                webhook,
                {"title": title, "content": content, "html": html_body, "platform": "wechat"},
            )
        return (
            False,
            "WECHAT_APP_ID / WECHAT_APP_SECRET not set. Click 'Copy WeChat Rich HTML' to paste directly into mp.weixin.qq.com.",
            "https://mp.weixin.qq.com/",
        )
    if not thumb_id:
        return (
            False,
            "WECHAT_THUMB_MEDIA_ID is required by WeChat Draft API (permanent cover image media_id). Or use 'Copy WeChat Rich HTML'.",
            "https://mp.weixin.qq.com/",
        )

    # WeChat API is CN-domestic; bypass overseas proxy.
    tok_r = requests.get(
        "https://api.weixin.qq.com/cgi-bin/token",
        params={"grant_type": "client_credential", "appid": app_id, "secret": app_secret},
        timeout=12,
        proxies={},
    )
    tok_data = tok_r.json() or {}
    access_token = tok_data.get("access_token")
    if not access_token:
        return False, f"WeChat token failed: {tok_data.get('errmsg', tok_data)}", ""

    plain = _strip_markdown(content)
    article = {
        "title": (title or "未命名文章")[:64],
        "author": _env("WECHAT_AUTHOR", "ViralLab")[:16],
        "digest": plain[:110],
        "content": html_body,
        "thumb_media_id": thumb_id,
        "need_open_comment": 1,
        "only_fans_can_comment": 0,
    }
    draft_r = requests.post(
        "https://api.weixin.qq.com/cgi-bin/draft/add",
        params={"access_token": access_token},
        json={"articles": [article]},
        timeout=20,
        proxies={},
    )
    draft_data = draft_r.json() or {}
    if draft_data.get("media_id"):
        return (
            True,
            f"Saved to WeChat 公众号草稿箱 (media_id: {draft_data['media_id']}).",
            "https://mp.weixin.qq.com/",
        )
    return False, f"WeChat draft/add error: {draft_data.get('errmsg', draft_data)}", ""


def publish_to_xiaohongshu(title: str, content: str) -> tuple[bool, str, str]:
    """Dispatch Xiaohongshu formatted note via webhook (if set), or return formatted handoff note."""
    formatted = format_for_xiaohongshu(title, content)
    webhook = _env("XHS_PUBLISH_WEBHOOK")
    if webhook:
        return _post_webhook(
            webhook,
            {
                "title": formatted["title"],
                "content": formatted["body"],
                "raw_content": content,
                "platform": "xiaohongshu",
            },
        )
    return (
        False,
        "Xiaohongshu has no public posting API. Use 'Copy XHS Format' + 'Open Creator Studio' (or configure XHS_PUBLISH_WEBHOOK).",
        "https://creator.xiaohongshu.com/publish/publish",
    )


def _oauth1_header(
    method: str,
    url: str,
    consumer_key: str,
    consumer_secret: str,
    token: str,
    token_secret: str,
) -> str:
    """Build RFC 5849 OAuth 1.0a Authorization header (HMAC-SHA1) using stdlib only."""
    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    encoded_pairs = sorted((quote(k, safe=""), quote(v, safe="")) for k, v in oauth_params.items())
    param_str = "&".join(f"{k}={v}" for k, v in encoded_pairs)
    base_string = "&".join([method.upper(), quote(base_url, safe=""), quote(param_str, safe="")])
    signing_key = f"{quote(consumer_secret, safe='')}&{quote(token_secret, safe='')}"
    sig = base64.b64encode(
        hmac.new(signing_key.encode("utf-8"), base_string.encode("utf-8"), hashlib.sha1).digest()
    ).decode("ascii")
    oauth_params["oauth_signature"] = sig
    header_parts = [f'{quote(k, safe="")}="{quote(v, safe="")}"' for k, v in sorted(oauth_params.items())]
    return "OAuth " + ", ".join(header_parts)


def publish_to_x(title: str, content: str) -> tuple[bool, str, str]:
    """Publish single tweet or automatic thread via X API v2 (OAuth 1.0a), or X_PUBLISH_WEBHOOK."""
    ck = _env("X_API_KEY")
    cs = _env("X_API_SECRET")
    tk = _env("X_ACCESS_TOKEN")
    ts = _env("X_ACCESS_TOKEN_SECRET")
    tweets = format_for_x_thread(title, content)

    if ck and cs and tk and ts:
        url = "https://api.x.com/2/tweets"
        proxies = requests_proxies_for(overseas=True)
        first_id = ""
        prev_id = ""
        for idx, text in enumerate(tweets):
            payload: dict[str, Any] = {"text": text}
            if prev_id:
                payload["reply"] = {"in_reply_to_tweet_id": prev_id}
            auth = _oauth1_header("POST", url, ck, cs, tk, ts)
            r = requests.post(
                url,
                headers={"Authorization": auth, "Content-Type": "application/json"},
                json=payload,
                timeout=15,
                proxies=proxies,
            )
            if not r.ok:
                detail = (r.text or "").strip().replace("\n", " ")[:220]
                return False, f"X API HTTP {r.status_code} (tweet {idx + 1}/{len(tweets)}): {detail}", ""
            tid = ((r.json() or {}).get("data") or {}).get("id") or ""
            if not first_id:
                first_id = tid
            prev_id = tid
        post_url = f"https://x.com/i/web/status/{first_id}" if first_id else "https://x.com"
        return True, f"Published to X ({len(tweets)} tweet{'s' if len(tweets) > 1 else ''}).", post_url

    webhook = _env("X_PUBLISH_WEBHOOK")
    if webhook:
        return _post_webhook(
            webhook,
            {"title": title, "content": content, "tweets": tweets, "platform": "x"},
        )

    return (
        False,
        "X API keys / X_PUBLISH_WEBHOOK not set. Use 'Copy X Thread' + 'Open X Composer' or add X_API_* in .env.",
        f"https://x.com/compose/post?text={quote(tweets[0] if tweets else title)}",
    )


def dispatch_publish(
    platform: str,
    title: str,
    content: str,
    *,
    draft: bool = False,
    category: str = "",
) -> tuple[bool, str, str]:
    """Dispatch item to its target platform connector. Returns `(ok, message, published_url)`."""
    p = normalize_platform(platform)
    if p == "blog":
        return publish_to_github_blog(title, content, draft=draft, category=category)
    if p == "telegram":
        return publish_to_telegram(title, content)
    if p == "wechat":
        return publish_to_wechat_draft(title, content)
    if p == "xiaohongshu":
        return publish_to_xiaohongshu(title, content)
    return publish_to_x(title, content)
