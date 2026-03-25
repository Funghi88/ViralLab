"""Media transcription helpers.

Strategy:
1) Keep fast YouTube caption path in server.py.
2) Fallback to VideoCaptioner CLI for broader URL/audio coverage.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

MEDIA_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".mp3", ".m4a", ".wav", ".aac", ".flac")


def looks_like_url(s: str) -> bool:
    return bool(re.match(r"^https?://", (s or "").strip(), re.IGNORECASE))


def is_supported_external_media_url(url: str) -> bool:
    """Supported via VideoCaptioner download+transcribe path."""
    u = (url or "").lower().strip()
    hosts = (
        "bilibili.com",
        "douyin.com",
        "xiaohongshu.com",
        "channels.weixin.qq.com",
        "xiaoyuzhoufm.com",
        "uxcoffee.com",
        "typlog.io",
        "youtube.com",
        "youtu.be",
        "spotify.com",
        "apple.com",
    )
    if any(h in u for h in hosts):
        return True
    return any(u.endswith(ext) for ext in MEDIA_EXTS)


def has_videocaptioner() -> bool:
    return shutil.which("videocaptioner") is not None


def _parse_srt_text(s: str) -> str:
    """Convert SRT/VTT-ish text to plain transcript."""
    out = []
    for line in (s or "").splitlines():
        t = line.strip()
        if not t:
            continue
        if t.isdigit():
            continue
        if "-->" in t:
            continue
        if re.match(r"^\d{1,2}:\d{2}(:\d{2})?([.,]\d+)?$", t):
            continue
        out.append(t)
    return " ".join(out).strip()


def _pick_transcript_file(work_dir: Path) -> Path | None:
    """Pick best transcript artifact in workspace."""
    preferred_suffixes = (".srt", ".vtt", ".txt", ".md")
    files = []
    for p in work_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in preferred_suffixes:
            files.append(p)
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


def _pick_downloaded_media(work_dir: Path) -> Path | None:
    files = []
    for p in work_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in MEDIA_EXTS:
            files.append(p)
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


def _resolve_audio_from_page(url: str) -> str:
    """Best-effort extraction of direct audio URL from a webpage."""
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        html = r.text
    except Exception:
        return ""

    patterns = [
        r'<meta[^>]+property=["\']og:audio["\'][^>]+content=["\']([^"\']+)["\']',
        r'<audio[^>]+src=["\']([^"\']+)["\']',
        r'<source[^>]+src=["\']([^"\']+)["\']',
        r'href=["\']([^"\']+\.(?:mp3|m4a|wav|aac|flac))["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, flags=re.IGNORECASE)
        if m:
            return urljoin(url, m.group(1).strip())
    return ""


def transcribe_with_videocaptioner(input_ref: str, lang: str = "en") -> tuple[str, str]:
    """Transcribe URL or local media path via VideoCaptioner CLI.

    Returns (transcript_text, source_label).
    """
    vc_bin = shutil.which("videocaptioner")
    if not vc_bin:
        return "", ""
    vc_dir = str(Path(vc_bin).resolve().parent)
    cmd_env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    cmd_env["PATH"] = vc_dir + os.pathsep + cmd_env.get("PATH", "")

    input_ref = (input_ref or "").strip()
    if not input_ref:
        return "", ""

    with tempfile.TemporaryDirectory(prefix="virallab_v2t_") as td:
        work_dir = Path(td)
        media_path: Path | None = None

        if looks_like_url(input_ref):
            # Download from supported platforms first.
            dl = subprocess.run(
                [vc_bin, "download", input_ref],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=240,
                env=cmd_env,
            )
            if dl.returncode == 0:
                media_path = _pick_downloaded_media(work_dir)
            # Fallback for podcast/web pages: resolve direct audio URL and download.
            if not media_path:
                direct_audio = _resolve_audio_from_page(input_ref)
                if direct_audio:
                    ext = Path(urlparse(direct_audio).path).suffix.lower() or ".mp3"
                    if ext not in MEDIA_EXTS:
                        ext = ".mp3"
                    media_path = work_dir / f"resolved_audio{ext}"
                    try:
                        rr = requests.get(direct_audio, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
                        rr.raise_for_status()
                        media_path.write_bytes(rr.content)
                    except Exception:
                        media_path = None
            if not media_path:
                return "", ""
        else:
            p = Path(input_ref).expanduser()
            if not p.exists() or not p.is_file():
                return "", ""
            media_path = p

        # Use free asr path when possible.
        cmd = ["videocaptioner", "transcribe", str(media_path), "--asr", "bijian"]
        cmd = [vc_bin, "transcribe", str(media_path), "--asr", "bijian"]
        tr = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=420,
            env=cmd_env,
        )
        if tr.returncode != 0:
            # Retry with default engine if bijian unavailable.
            tr2 = subprocess.run(
                [vc_bin, "transcribe", str(media_path)],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=420,
                env=cmd_env,
            )
            if tr2.returncode != 0:
                return "", ""

        transcript_file = _pick_transcript_file(work_dir)
        if not transcript_file:
            return "", ""
        raw = transcript_file.read_text(encoding="utf-8", errors="replace")
        text = _parse_srt_text(raw) if transcript_file.suffix.lower() in (".srt", ".vtt") else raw.strip()
        if not text:
            return "", ""
        source = "VideoCaptioner (ASR)"
        if lang == "zh":
            source = "VideoCaptioner（语音转文字）"
        return text, source
