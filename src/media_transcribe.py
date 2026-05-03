"""Media transcription helpers.

Strategy:
1) Keep fast YouTube caption path in server.py.
2) Optional WhisperX (see requirements-asr.txt) when VIRALLAB_ASR_ENGINE allows.
3) Fallback to VideoCaptioner CLI for broader URL/audio coverage.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests

from src.transcription.config import get_asr_engine, get_ffmpeg_af_preset
from src.transcription.preprocess import extract_audio_for_asr
from src.transcription.whisperx_runner import has_whisperx, transcribe_audio_path
from src.video_tools import extract_youtube_id


@dataclass
class TranscribeOutcome:
    text: str
    source: str
    segments: list[dict] | None = field(default=None)

MEDIA_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".mp3", ".m4a", ".wav", ".aac", ".flac")

# Match server.py — dead local HTTP bridge (e.g. stale Quick Queue port) breaks requests + yt-dlp.
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy")


def _env_without_proxy(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    for v in _PROXY_VARS:
        env.pop(v, None)
    return env


def _session_get_trust_env_false(url: str, method: str, **kwargs):
    s = requests.Session()
    s.trust_env = False
    return s.request(method, url, **kwargs)


def _requests_get_no_proxy_fallback(url: str, **kwargs):
    """GET; retry with Session(trust_env=False) if env proxy is broken or SOCKS deps missing."""
    transient = (
        requests.exceptions.ProxyError,
        requests.exceptions.ConnectionError,
        requests.exceptions.InvalidSchema,
    )
    try:
        return requests.get(url, **kwargs)
    except transient:
        return _session_get_trust_env_false(url, "GET", **kwargs)


def _requests_head_no_proxy_fallback(url: str, **kwargs):
    transient = (
        requests.exceptions.ProxyError,
        requests.exceptions.ConnectionError,
        requests.exceptions.InvalidSchema,
    )
    try:
        return requests.head(url, **kwargs)
    except transient:
        return _session_get_trust_env_false(url, "HEAD", **kwargs)
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm")


def _find_videocaptioner_bin() -> str:
    """Locate videocaptioner executable from PATH or project venv."""
    p = shutil.which("videocaptioner")
    if p:
        return p
    project_venv = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "videocaptioner"
    if project_venv.exists():
        return str(project_venv)
    return ""


def _find_yt_dlp_bin() -> str:
    p = shutil.which("yt-dlp")
    if p:
        return p
    project_venv = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "yt-dlp"
    if project_venv.exists():
        return str(project_venv)
    return ""


def _extract_first_url(s: str) -> str:
    """Extract first URL from pasted share text."""
    txt = (s or "").strip()
    if not txt:
        return ""
    m = re.search(r"https?://[^\s]+", txt, flags=re.IGNORECASE)
    if not m:
        return txt
    u = m.group(0).strip()
    # Trim trailing punctuation often attached in copied share text.
    while u and u[-1] in ".,;:!?)]}<>":
        u = u[:-1]
    return u


def looks_like_url(s: str) -> bool:
    return bool(re.match(r"^https?://", _extract_first_url(s), re.IGNORECASE))


def _normalize_local_media_ref(ref: str) -> str:
    """Turn pasted Finder/terminal refs into a filesystem path FFmpeg/Whisper can open."""
    s = (ref or "").strip().strip("\r\n")
    if not s:
        return s
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1].strip()
    low = s.lower()
    if low.startswith("file://"):
        try:
            parsed = urlparse(s)
            path = unquote(parsed.path or "")
            if sys.platform == "win32" and len(path) >= 3 and path[0] == "/" and path[2] == ":":
                path = path.lstrip("/")
            return path or s
        except Exception:
            return s
    return s


def is_supported_external_media_url(url: str) -> bool:
    """Supported via VideoCaptioner download+transcribe path."""
    u = _extract_first_url(url).lower().strip()
    hosts = (
        "bilibili.com",
        "douyin.com",
        "v.douyin.com",
        "iesdouyin.com",
        "xiaohongshu.com",
        "xhslink.com",
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
    return bool(_find_videocaptioner_bin())


def has_yt_dlp() -> bool:
    return bool(_find_yt_dlp_bin())


def _pick_youtube_merged_file(output_dir: Path, vid: str) -> Path | None:
    """Return final merged file ``youtube_{vid}.<ext>``, not fragments ``youtube_{vid}.f251.webm``."""
    prefix = f"youtube_{vid}"
    candidates: list[Path] = []
    for p in output_dir.glob(f"{prefix}.*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in MEDIA_EXTS:
            continue
        if p.stem != prefix:
            continue
        candidates.append(p)
    if not candidates:
        return None
    # Prefer newest file first so a fresh .mkv remux beats a stale .mp4 left in output/.
    pref_order = (".mp4", ".mkv", ".webm", ".mov", ".m4a", ".mp3")
    pref_rank = {s: i for i, s in enumerate(pref_order)}

    def sort_key(p: Path) -> tuple[float, int]:
        suf = p.suffix.lower()
        return (-p.stat().st_mtime, pref_rank.get(suf, len(pref_order)))

    return sorted(candidates, key=sort_key)[0]


def download_youtube_video(url: str, output_dir: Path) -> tuple[Path | None, str]:
    """Download a single YouTube video to ``output_dir`` as ``youtube_{id}.<ext>``.

    YouTube streams are lossy; we avoid *extra* quality loss by preferring MKV merge first:
    VP9/AV1 + Opus muxes cleanly in MKV (stream copy). Forcing MP4 first often re-encodes
    audio or produces bad muxes (glitchy / ``broken-up`` sound). MP4 is tried after MKV for
    player compatibility.

    Public YouTube does not need browser cookies; skipping :func:`_yt_cookie_attempt_flags`
    avoids slow/failed ``--cookies-from-browser`` runs in headless/server environments.
    Returns ``(path, "")`` on success, or ``(None, error_detail)``.
    """
    raw = _extract_first_url((url or "").strip())
    if not raw:
        return None, "missing_url"
    vid = extract_youtube_id(raw)
    if not vid:
        return None, "not_youtube"
    ytdlp = _find_yt_dlp_bin()
    if not ytdlp:
        return None, "no_ytdlp"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(output_dir / f"youtube_{vid}.%(ext)s")
    base_head = [
        ytdlp,
        "-f",
        "bestvideo+bestaudio/best",
        "--no-playlist",
        # DASH fragments: retries reduce truncated downloads that sound like dropouts.
        "--retries",
        "10",
        "--fragment-retries",
        "10",
        "-o",
        out_template,
    ]
    cmd_env = dict(os.environ)
    attempts: list[list[str]] = [[]]
    # MKV first: remux VP9/Opus without container-forced re-encode; then MP4 for compatibility.
    merge_variants: list[list[str]] = [
        ["--merge-output-format", "mkv"],
        ["--merge-output-format", "mp4"],
        [],
    ]
    last_stderr = ""
    for merge_opt in merge_variants:
        for extra in attempts:
            cmd = base_head + merge_opt + extra + [raw]
            try:
                r = subprocess.run(
                    cmd,
                    cwd=output_dir,
                    capture_output=True,
                    text=True,
                    timeout=600,
                    env=cmd_env,
                )
                if r.returncode == 0:
                    picked = _pick_youtube_merged_file(output_dir, vid)
                    if picked is not None:
                        return picked, ""
                tail = (r.stderr or r.stdout or "").strip()
                last_stderr = tail[-2000:] if tail else "yt-dlp failed"
            except subprocess.TimeoutExpired:
                last_stderr = "timeout"
            except OSError as e:
                last_stderr = str(e)
    return None, last_stderr or "download_failed"


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


def _download_with_yt_dlp(url: str, work_dir: Path, env: dict[str, str]) -> Path | None:
    """Fallback downloader for platforms requiring browser cookies."""
    ytdlp = _find_yt_dlp_bin()
    if not ytdlp:
        return None
    base = [
        ytdlp,
        "-f",
        "bestvideo+bestaudio/best",
        "--no-playlist",
        "-o",
        str(work_dir / "%(title)s.%(ext)s"),
        url,
    ]
    attempts = _yt_cookie_attempt_flags()
    for extra in attempts:
        try:
            r = subprocess.run(
                base + extra,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=300,
                env=env,
            )
            if r.returncode == 0:
                media = _pick_downloaded_media(work_dir)
                if media:
                    return media
        except Exception:
            continue
    return None


def _yt_cookie_attempt_flags() -> list[list[str]]:
    """Cookie flag permutations for yt-dlp extraction attempts."""
    browser_pref = (os.environ.get("YTDLP_COOKIES_BROWSER", "chrome") or "chrome").strip()
    profile_pref = (os.environ.get("YTDLP_COOKIES_PROFILE", "") or "").strip()
    cookie_attempts = []
    if profile_pref:
        cookie_attempts.append([browser_pref, profile_pref])
    # Try common Chrome profiles because many users are not logged in "Default".
    cookie_attempts.extend(
        [
            [browser_pref],
            ["chrome", "Default"],
            ["chrome", "Profile 1"],
            ["chrome", "Profile 2"],
            ["chrome", "Profile 3"],
            ["safari"],
            ["edge"],
            ["firefox"],
        ]
    )
    attempts = [[]]
    for spec in cookie_attempts:
        if len(spec) == 1:
            attempts.append(["--cookies-from-browser", spec[0]])
        else:
            attempts.append(["--cookies-from-browser", f"{spec[0]}:{spec[1]}"])
    return attempts


def test_douyin_session(input_ref: str = "") -> dict:
    """Test whether current local cookie/session can access Douyin via yt-dlp."""
    ytdlp = _find_yt_dlp_bin()
    if not ytdlp:
        return {"ok": False, "message": "yt-dlp not found in environment."}
    raw = (input_ref or "").strip() or "https://v.douyin.com/hmxtL4qaTzo/"
    resolved = _expand_short_url(raw)
    if "douyin.com" not in resolved:
        return {"ok": False, "message": "Please provide a Douyin link.", "resolved_url": resolved}
    env = _env_without_proxy()
    venv_bin = str(Path(__file__).resolve().parent.parent / ".venv" / "bin")
    env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")

    reasons: list[str] = []
    for extra in _yt_cookie_attempt_flags():
        cmd = [ytdlp, "-F", resolved] + extra
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=45, env=env)
            out = (r.stdout or "") + "\n" + (r.stderr or "")
            if r.returncode == 0:
                return {
                    "ok": True,
                    "message": "Douyin session looks usable for extraction.",
                    "resolved_url": resolved,
                    "attempt": " ".join(extra) if extra else "no-cookie-flag",
                }
            s = out.lower()
            if "fresh cookies" in s or "cookies" in s or "login" in s:
                reasons.append("cookies/login required")
            elif "forbidden" in s or "429" in s or "captcha" in s:
                reasons.append("risk-control/captcha")
            else:
                reasons.append((out.strip().splitlines()[-1] if out.strip() else "unknown failure")[:140])
        except Exception as e:
            reasons.append(str(e)[:140])
    return {
        "ok": False,
        "message": "Douyin session is not usable yet. Re-open Douyin in the same browser profile and retry.",
        "resolved_url": resolved,
        "reasons": list(dict.fromkeys(reasons))[:3],
    }


def _extract_audio_ffmpeg(media_path: Path, work_dir: Path) -> Path | None:
    """Extract audio track for ASR engines that reject video container input."""
    return extract_audio_for_asr(
        media_path, work_dir, get_ffmpeg_af_preset(), "extracted_audio.wav"
    )


def _try_transcribe_candidates(
    vc_bin: str,
    media_path: Path,
    work_dir: Path,
    env: dict[str, str],
    *,
    timeout_sec: int = 420,
) -> bool:
    """Try multiple ASR engines in order. Returns True when one succeeds."""
    # Prefer free cloud engines first, keep local default as final fallback.
    engines = ["bijian", "jianying", ""]
    for eng in engines:
        cmd = [vc_bin, "transcribe", str(media_path)]
        if eng:
            cmd += ["--asr", eng]
        try:
            r = subprocess.run(
                cmd,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                env=env,
            )
            if r.returncode == 0:
                return True
        except Exception:
            continue
    return False


def _transcribe_videocaptioner_pipeline(
    media_path: Path,
    work_dir: Path,
    cmd_env: dict[str, str],
    lang: str,
) -> TranscribeOutcome:
    vc_bin = _find_videocaptioner_bin()
    if not vc_bin:
        return TranscribeOutcome("", "", None)
    ok = _try_transcribe_candidates(vc_bin, media_path, work_dir, cmd_env)
    if not ok and media_path.suffix.lower() in VIDEO_EXTS:
        audio_path = _extract_audio_ffmpeg(media_path, work_dir)
        if audio_path:
            ok = _try_transcribe_candidates(vc_bin, audio_path, work_dir, cmd_env)
    if not ok:
        return TranscribeOutcome("", "", None)
    transcript_file = _pick_transcript_file(work_dir)
    if not transcript_file:
        return TranscribeOutcome("", "", None)
    raw = transcript_file.read_text(encoding="utf-8", errors="replace")
    text = _parse_srt_text(raw) if transcript_file.suffix.lower() in (".srt", ".vtt") else raw.strip()
    if not text:
        return TranscribeOutcome("", "", None)
    source = "VideoCaptioner (ASR)"
    if lang == "zh":
        source = "VideoCaptioner（语音转文字）"
    return TranscribeOutcome(text, source, None)


def transcribe_best_effort(
    input_ref: str, lang: str = "en", *, engine: str | None = None
) -> TranscribeOutcome:
    """Download media when needed, then WhisperX (optional) and/or VideoCaptioner."""
    resolved = (engine or get_asr_engine()).strip().lower()
    if resolved not in ("auto", "whisperx", "videocaptioner"):
        resolved = "auto"

    vc_bin = _find_videocaptioner_bin()
    vc_dir = str(Path(vc_bin).resolve().parent) if vc_bin else ""
    cmd_env = _env_without_proxy()
    cmd_env["PYTHONIOENCODING"] = "utf-8"
    if vc_dir:
        cmd_env["PATH"] = vc_dir + os.pathsep + cmd_env.get("PATH", "")

    input_ref = _normalize_local_media_ref((input_ref or "").strip())
    if not input_ref:
        return TranscribeOutcome("", "", None)

    with tempfile.TemporaryDirectory(prefix="virallab_v2t_") as td:
        work_dir = Path(td)
        media_path: Path | None = None
        whisper_lang_override: str | None = None

        if looks_like_url(input_ref):
            resolved_url = _expand_short_url(input_ref)
            dl = subprocess.run(
                [vc_bin, "download", resolved_url],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=240,
                env=cmd_env,
            ) if vc_bin else subprocess.CompletedProcess([], 1)
            if vc_bin and dl.returncode == 0:
                media_path = _pick_downloaded_media(work_dir)
            if not media_path:
                media_path = _download_with_yt_dlp(resolved_url, work_dir, cmd_env)
            if not media_path:
                direct_audio = _resolve_audio_from_page(resolved_url)
                if direct_audio:
                    ext = Path(urlparse(direct_audio).path).suffix.lower() or ".mp3"
                    if ext not in MEDIA_EXTS:
                        ext = ".mp3"
                    media_path = work_dir / f"resolved_audio{ext}"
                    try:
                        rr = _requests_get_no_proxy_fallback(
                            direct_audio,
                            timeout=60,
                            headers={"User-Agent": "Mozilla/5.0"},
                        )
                        rr.raise_for_status()
                        media_path.write_bytes(rr.content)
                    except Exception:
                        media_path = None
            if not media_path:
                return TranscribeOutcome("", "", None)
        else:
            p = Path(input_ref).expanduser()
            if not p.exists() or not p.is_file():
                return TranscribeOutcome("", "", None)
            media_path = p
            whisper_lang_override = "auto"

        if resolved in ("auto", "whisperx") and has_whisperx():
            whisper_lang = whisper_lang_override if whisper_lang_override else lang
            tr = transcribe_audio_path(
                media_path,
                work_dir,
                whisper_lang,
                af_preset=get_ffmpeg_af_preset(),
            )
            if tr and tr.text:
                src = "WhisperX（语音转文字）" if lang == "zh" else "WhisperX"
                return TranscribeOutcome(tr.text, src, tr.segments)

        if not vc_bin:
            return TranscribeOutcome("", "", None)
        return _transcribe_videocaptioner_pipeline(media_path, work_dir, cmd_env, lang)


def _resolve_audio_from_page(url: str) -> str:
    """Best-effort extraction of direct audio URL from a webpage."""
    try:
        r = _requests_get_no_proxy_fallback(
            url, timeout=10, headers={"User-Agent": "Mozilla/5.0"}
        )
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


def _expand_short_url(url: str) -> str:
    """Expand short/shared links (xhslink, v.douyin, etc.) to canonical target URL."""
    u = _extract_first_url(url)
    if not looks_like_url(u):
        return u
    headers = {"User-Agent": "Mozilla/5.0"}
    # 1) Try direct redirect expansion.
    try:
        r = _requests_get_no_proxy_fallback(
            u, timeout=12, headers=headers, allow_redirects=True
        )
        if r.url and r.url.startswith("http"):
            final = r.url.strip()
            if final:
                return final
    except Exception:
        pass
    # 2) HEAD fallback for short links.
    try:
        r = _requests_head_no_proxy_fallback(
            u, timeout=12, headers=headers, allow_redirects=True
        )
        if r.url and r.url.startswith("http"):
            final = r.url.strip()
            if final:
                return final
    except Exception:
        pass
    return u


def transcribe_with_videocaptioner(input_ref: str, lang: str = "en") -> tuple[str, str]:
    """Transcribe URL or local media path via VideoCaptioner only (no WhisperX).

    Returns (transcript_text, source_label).
    """
    out = transcribe_best_effort(input_ref, lang=lang, engine="videocaptioner")
    return out.text, out.source
