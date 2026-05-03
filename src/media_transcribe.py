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
from urllib.parse import parse_qs, unquote, urljoin, urlparse

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
    #: Download/ASR diagnostics when ``text`` is empty (e.g. yt-dlp stderr tail).
    detail: str | None = field(default=None)

MEDIA_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".mp3", ".m4a", ".wav", ".aac", ".flac")

# Match server.py — dead local HTTP bridge (e.g. stale Quick Queue port) breaks requests + yt-dlp.
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy")


def _env_without_proxy(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    for v in _PROXY_VARS:
        env.pop(v, None)
    return env


def _cmd_env_for_media_subprocess() -> dict[str, str]:
    """Subprocess env for videocaptioner / yt-dlp. Strips proxy by default (domestic CDNs)."""
    v = (os.environ.get("VIRALLAB_MEDIA_DOWNLOAD_USE_ENV_PROXY") or "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return dict(os.environ)
    return _env_without_proxy()


def _douyin_restore_parent_http_proxy(cmd_env: dict[str, str]) -> dict[str, str]:
    """Copy process HTTP(S)_PROXY into Douyin yt-dlp subprocess (default subprocess env strips them).

    Aligns egress with browsers using local gost/QuickQ when the server inherits those vars.
    Opt out: ``VIRALLAB_DOUYIN_SKIP_PROXY_RESTORE=1``.
    """
    if (os.environ.get("VIRALLAB_MEDIA_DOWNLOAD_USE_ENV_PROXY") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return cmd_env
    if (os.environ.get("VIRALLAB_DOUYIN_SKIP_PROXY_RESTORE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return cmd_env
    out = dict(cmd_env)
    restored: list[str] = []
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        v = (os.environ.get(k) or "").strip()
        if v:
            out[k] = v
            restored.append(k)
    return out


def _yt_dlp_verbose() -> bool:
    """When True, yt-dlp runs with ``-v`` (proxy map, extractor debug). Omit ``--print-traffic`` to avoid cookie dumps."""
    raw = os.environ.get("VIRALLAB_YTDLP_VERBOSE")
    if raw is not None and str(raw).strip():
        return str(raw).strip().lower() not in ("0", "false", "no", "off")
    for k in ("VIRALLAB_DEBUG_MEDIA", "VIRALLAB_DEBUG", "FLASK_DEBUG"):
        if (os.environ.get(k) or "").strip().lower() in ("1", "true", "yes", "on"):
            return True
    return False


def _yt_dlp_stderr_tail_max() -> int:
    return 16000 if _yt_dlp_verbose() else 2800


def _stderr_tail(proc: subprocess.CompletedProcess[str], max_len: int = 1800) -> str:
    combined = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
    if len(combined) <= max_len:
        return combined
    return "…" + combined[-max_len:]


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
    """Locate videocaptioner executable from PATH, env override, or project venv."""
    override = (os.environ.get("VIRALLAB_VIDEOCAPTIONER_BIN") or "").strip()
    if override:
        cand = Path(override).expanduser()
        if cand.is_file():
            return str(cand.resolve())
    p = shutil.which("videocaptioner")
    if p:
        return p
    project_venv = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "videocaptioner"
    if project_venv.exists():
        return str(project_venv)
    return ""


def _find_yt_dlp_bin() -> str:
    override = (os.environ.get("VIRALLAB_YTDLP_BIN") or "").strip()
    if override:
        cand = Path(override).expanduser()
        if cand.is_file():
            return str(cand.resolve())
    project_venv = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "yt-dlp"
    if project_venv.is_file():
        return str(project_venv.resolve())
    p = shutil.which("yt-dlp")
    if p:
        return p
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

    Public YouTube does not need browser cookies; skipping yt-dlp cookie flags.
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


def _download_with_yt_dlp(url: str, work_dir: Path, env: dict[str, str]) -> tuple[Path | None, str]:
    """Fallback downloader for platforms requiring browser cookies."""
    ytdlp = _find_yt_dlp_bin()
    if not ytdlp:
        return None, "yt-dlp executable not found (install yt-dlp or add to PATH)."
    attempts = _yt_dlp_attempt_extras(url)
    base: list[str] = [ytdlp]
    if _yt_dlp_verbose():
        base.append("-v")
    base += [
        "-f",
        "bestvideo+bestaudio/best",
        "--no-playlist",
        "-o",
        str(work_dir / "%(title)s.%(ext)s"),
        url,
    ]
    last_err = ""
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
                    return media, ""
            last_err = _stderr_tail(r, _yt_dlp_stderr_tail_max())
        except Exception as e:
            last_err = str(e)[:800]
            continue
    return None, last_err or "yt-dlp failed (no stderr captured)."


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _looks_like_douyin_url(url: str) -> bool:
    u = (url or "").lower()
    return "douyin.com" in u or "v.douyin.com" in u or "iesdouyin.com" in u


def _normalize_douyin_watch_url(url: str) -> str:
    """Rewrite Douyin feed URLs so yt-dlp's Douyin extractor matches ``/video/<id>``.

    ``/jingxuan?modal_id=<aweme_id>`` uses the same id as ``https://www.douyin.com/video/<id>``.
    Otherwise yt-dlp uses the **generic** extractor and returns **Unsupported URL**.
    """
    u = (url or "").strip()
    if not u or not _looks_like_douyin_url(u):
        return u
    try:
        parsed = urlparse(u)
        host = (parsed.netloc or "").lower()
        if "douyin.com" not in host:
            return u
        path = (parsed.path or "").strip().rstrip("/")
        qs = parse_qs(parsed.query, keep_blank_values=False)

        mids = qs.get("modal_id") or []
        if len(mids) != 1 or not str(mids[0]).isdigit():
            return u

        vid = str(mids[0])
        if "/video/" in (parsed.path or ""):
            return u

        if path.endswith("/jingxuan") or path == "/jingxuan":
            return f"https://www.douyin.com/video/{vid}"

        for prefix in ("/discover", "/follow", "/user", "/root", "/search", "/recommend"):
            if path == prefix or path.startswith(prefix + "/"):
                return f"https://www.douyin.com/video/{vid}"
    except Exception:
        return u
    return u


def _virallab_optional_cookie_txt_files() -> list[Path]:
    """Optional Netscape cookies.txt locations (never committed — see `.gitignore`)."""
    root = _repo_root()
    out: list[Path] = []
    for rel in ("config/ytdlp_cookies.txt", ".local/ytdlp_cookies.txt"):
        p = (root / rel).resolve()
        if p.is_file() and _netscape_cookie_txt_has_entries(p):
            out.append(p)
    return out


def _netscape_cookie_txt_has_entries(path: Path) -> bool:
    """True when ``path`` contains at least one Netscape-format cookie row (7+ tab fields).

    Comment-only placeholders are ignored so Douyin still tries ``--cookies-from-browser`` until
    you paste a real export into ``config/ytdlp_cookies.txt``.
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if len(line.split("\t")) >= 7:
            return True
    return False


def _netscape_cookie_names_in_file(path: Path) -> set[str]:
    """Cookie **names** from Netscape rows (never values); for diagnostics only."""
    out: set[str] = set()
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            out.add(parts[5].strip())
    return out


def _douyin_cookie_file_runtime_status() -> dict:
    """Counts / flags only — no secrets (NDJSON-safe)."""
    root = _repo_root()
    names: set[str] = set()
    seen_resolved: set[str] = set()
    n_real = 0
    cfg = root / "config/ytdlp_cookies.txt"
    placeholder = cfg.is_file() and not _netscape_cookie_txt_has_entries(cfg)

    def ingest(p: Path) -> None:
        nonlocal n_real, names
        if not p.is_file() or not _netscape_cookie_txt_has_entries(p):
            return
        key = str(p.resolve())
        if key in seen_resolved:
            return
        seen_resolved.add(key)
        n_real += 1
        names |= _netscape_cookie_names_in_file(p)

    ingest(cfg)
    ingest(root / ".local/ytdlp_cookies.txt")
    env_file = (os.environ.get("YTDLP_COOKIES_FILE") or "").strip()
    if env_file:
        ingest(Path(env_file).expanduser())

    return {
        "n_cookie_files_with_netscape_rows": n_real,
        "has_s_v_web_id_cookie_name": "s_v_web_id" in names,
        "config_ytdlp_cookies_placeholder_only": placeholder,
        "distinct_cookie_name_count": len(names),
    }


def _douyin_failure_diagnosis_block(st: dict) -> str:
    """Short runtime diagnosis when Douyin download failed (no secrets)."""
    n = int(st.get("n_cookie_files_with_netscape_rows") or 0)
    has_sv = bool(st.get("has_s_v_web_id_cookie_name"))
    ph = bool(st.get("config_ytdlp_cookies_placeholder_only"))
    zh_a = (
        "\n\n【运行时诊断 / Runtime diagnosis】\n"
        "• **未发现带有效 Cookie 行的配置文件** — `yt-dlp` **没有**传入 `--cookies /path`**，只能依赖 `--cookies-from-browser`（易出现钥匙串，且抖音仍可能返回空 JSON）。\n"
    )
    if ph:
        zh_a += (
            "• **`config/ytdlp_cookies.txt` 仍存在但只剩说明文字**：请用 Chrome 登录 **`douyin.com`** 后用扩展导出 **Netscape** 全文，"
            "**整份替换**该文件并重启 `./scripts/dev-server.sh`。\n"
        )
    else:
        zh_a += (
            "• **下一步**：导出 Netscape **`douyin.com`** → **`config/ytdlp_cookies.txt`** 或 **`.local/ytdlp_cookies.txt`** / **`YTDLP_COOKIES_FILE`**。\n"
        )
    en_a = (
        "---\n"
        "**No** Netscape cookie file with data rows is active → yt-dlp runs **without** `--cookies …`. Export while logged in "
        "and restart the server, or transcribe from a **local downloaded file** instead.\n"
    )

    zh_b = (
        "\n\n【运行时诊断 / Runtime diagnosis】\n"
        "• 检测到 Cookie 文件，但在 **Cookie 名**中未见 **`s_v_web_id`**（抖音 Web 常见项）。请 **重新导出** "
        "**已登录网页**状态下的 `douyin.com` Cookie，或使用另一扩展试一次。\n"
        "---\n"
        "**Cookie file present** but **no `s_v_web_id`** cookie **name** in file rows; re-export from Chrome on douyin.com.\n"
    )

    zh_c = (
        "\n\n【运行时诊断 / Runtime diagnosis】\n"
        "• 已检测到 **有效 Cookie 文件**（且含 **`s_v_web_id`** Cookie 名），但接口仍为 **JSON 正文为空**："
        "多为抖音 **服务端风控**，需 **本地下载或录屏** 后走本地音视频路径逐字稿，或等待 **`yt-dlp`** 适配。\n"
        "---\n"
        "**Valid cookie file names look OK** (`s_v_web_id` present) but Douyin still returns empty API body — likely **anti-bot**; transcribe via **local file** or monitor yt-dlp updates.\n"
    )

    if n == 0:
        return zh_a + en_a
    if not has_sv:
        return zh_b
    return zh_c


def _douyin_recommended_local_first_blurb() -> str:
    """Product guidance: Douyin URLs are flaky; transcribe downloaded files."""
    return (
        "\n\n【推荐 / Recommended（抖音）】\n"
        "• **不要用抖音网页链接当主路径。** 请先在本机准备好 **MP4/MOV/M4A** 等音视频，在下面输入框粘贴 **完整路径**"
        "（macOS：**Finder 按住 Option 可复制路径**，或直接把文件拖到终端/Cursor里出现的路径）。再用「获取逐字稿」。\n"
        "• **Do not rely on Douyin URLs.** Paste a **local file path** of the downloaded clip, then transcribe.\n\n"
        "──── 以下为可选：**仍想尝试用链接在线拉取**（需 Cookie / 易被风控）。────\n"
    )


def _yt_browser_cookie_fragments_douyin_minimal() -> list[list[str]]:
    """At most **one** ``--cookies-from-browser`` variant for Douyin (limits Keychain prompts).

    Use ``YTDLP_COOKIES_BROWSER`` / ``YTDLP_COOKIES_PROFILE`` like the generic ladder.
    Opt into the legacy multi-browser probe with ``VIRALLAB_YTDLP_DOUYIN_WIDE_BROWSER=1``.
    """
    browser_pref = (os.environ.get("YTDLP_COOKIES_BROWSER", "chrome") or "chrome").strip()
    profile_pref = (os.environ.get("YTDLP_COOKIES_PROFILE", "") or "").strip()
    if profile_pref:
        return [["--cookies-from-browser", f"{browser_pref}:{profile_pref}"]]
    return [["--cookies-from-browser", browser_pref]]


def _douyin_wide_browser_env_on() -> bool:
    return (os.environ.get("VIRALLAB_YTDLP_DOUYIN_WIDE_BROWSER") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _effective_browser_fragments(url: str | None) -> list[list[str]]:
    """Full multi-browser ladder except Douyin URLs, where we default to a single browser try."""
    is_dy = bool(url and _looks_like_douyin_url(url))
    if is_dy and not _douyin_wide_browser_env_on():
        return _yt_browser_cookie_fragments_douyin_minimal()
    return _yt_browser_cookie_fragments()


def _yt_browser_cookie_fragments() -> list[list[str]]:
    """Fragments using ``--cookies-from-browser`` (may trigger repeated macOS Keychain prompts)."""
    out: list[list[str]] = []
    browser_pref = (os.environ.get("YTDLP_COOKIES_BROWSER", "chrome") or "chrome").strip()
    profile_pref = (os.environ.get("YTDLP_COOKIES_PROFILE", "") or "").strip()
    cookie_attempts: list[list[str]] = []
    if profile_pref:
        cookie_attempts.append([browser_pref, profile_pref])
    cookie_attempts.extend(
        [
            [browser_pref],
            ["chrome", "Default"],
            ["chrome", "Profile 1"],
            ["chrome", "Profile 2"],
            ["chrome", "Profile 3"],
            ["chromium"],
            ["brave"],
            ["safari"],
            ["edge"],
            ["firefox"],
            ["vivaldi"],
        ]
    )
    for spec in cookie_attempts:
        if len(spec) == 1:
            out.append(["--cookies-from-browser", spec[0]])
        else:
            out.append(["--cookies-from-browser", f"{spec[0]}:{spec[1]}"])
    return out


def _yt_cookie_file_fragments() -> list[list[str]]:
    """``--cookies /path/to/cookies.txt`` entries (does not trigger Keychain)."""
    frags: list[list[str]] = []
    seen: set[str] = set()

    def append_cookie_file(p: Path) -> None:
        if not p.is_file() or not _netscape_cookie_txt_has_entries(p):
            return
        key = str(p.resolve())
        if key in seen:
            return
        seen.add(key)
        frags.append(["--cookies", key])

    env_file = (os.environ.get("YTDLP_COOKIES_FILE") or "").strip()
    if env_file:
        append_cookie_file(Path(env_file).expanduser())
    for p in _virallab_optional_cookie_txt_files():
        append_cookie_file(p)
    return frags


def _yt_cookie_extras_nonempty(url: str | None = None) -> list[list[str]]:
    """Cookie-related argv fragments for yt-dlp (never includes the no-extra empty list).

    When a Netscape cookies file is configured, **Douyin** URLs skip ``--cookies-from-browser``
    by default (avoids repeated macOS Keychain prompts). Other hosts still get browser fallbacks
    unless ``VIRALLAB_YTDLP_SKIP_BROWSER_COOKIES`` is set.
    """
    files = _yt_cookie_file_fragments()
    browsers = _effective_browser_fragments(url)

    skip_all_browser = (os.environ.get("VIRALLAB_YTDLP_SKIP_BROWSER_COOKIES") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    force_browser = (os.environ.get("VIRALLAB_YTDLP_USE_BROWSER_COOKIES") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    if skip_all_browser:
        return files
    is_dy = bool(url and _looks_like_douyin_url(url))
    if files and not force_browser and is_dy:
        return files
    return files + browsers


def _douyin_download_help_zh_en() -> str:
    """Optional advance notes when user still wants URL-based Douyin fetch."""
    return (
        "\n\n【可选：链接拉取 / Optional: URL fetch】\n"
        "• **链接形态**：`/jingxuan?modal_id=` 会规范为 `https://www.douyin.com/video/<id>`。\n"
        "• **Cookie（进阶）**：见 **`config/README-ytdlp-cookies.md`**；有效 **`config/ytdlp_cookies.txt`** 可减少钥匙串弹窗。"
        "仍可能遇 **空 JSON 风控**，只能改走本地文件。\n"
        "• **代理**：Douyin 子进程会继承你在启动 `dev-server` 时的 HTTP(S) 代理；异常见 **`VIRALLAB_DOUYIN_SKIP_PROXY_RESTORE`**、"
        "**`VIRALLAB_MEDIA_DOWNLOAD_USE_ENV_PROXY`**。\n"
        "• **`pip install -U yt-dlp`**；详细日志 **`VIRALLAB_YTDLP_VERBOSE`**（勿用 **`--print-traffic`**）。\n"
        "---\n"
        "**Optional URL path:** Cookie file → **`config/README-ytdlp-cookies.md`**; yt-dlp may still see **empty API bodies** "
        "**(anti-bot)** — use **local path** transcript.\n"
    )


def _yt_dlp_attempt_extras(url: str) -> list[list[str]]:
    """Order attempts: Douyin prefers cookie-aware tries before an unauthenticated last resort."""
    u = (url or "").lower()
    is_dy = "douyin.com" in u or "v.douyin.com" in u or "iesdouyin.com" in u
    core = _yt_cookie_extras_nonempty(url)
    if is_dy:
        return core + [[]] if core else [[]]
    return [[]] + core


def _yt_cookie_attempt_flags() -> list[list[str]]:
    """Compat: full attempt list including no-cookie first (non-Douyin order). Deprecated for downloads; use :func:`_yt_dlp_attempt_extras`."""
    return _yt_dlp_attempt_extras("")


def test_douyin_session(input_ref: str = "") -> dict:
    """Test whether current local cookie/session can access Douyin via yt-dlp."""
    ytdlp = _find_yt_dlp_bin()
    if not ytdlp:
        return {"ok": False, "message": "yt-dlp not found in environment."}
    raw = (input_ref or "").strip() or "https://v.douyin.com/hmxtL4qaTzo/"
    resolved = _normalize_douyin_watch_url(_expand_short_url(raw))
    if "douyin.com" not in resolved:
        return {"ok": False, "message": "Please provide a Douyin link.", "resolved_url": resolved}
    env = _douyin_restore_parent_http_proxy(dict(_cmd_env_for_media_subprocess()))
    venv_bin = str(Path(__file__).resolve().parent.parent / ".venv" / "bin")
    env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")

    reasons: list[str] = []
    for extra in _yt_dlp_attempt_extras(resolved):
        cmd = [ytdlp] + (["-v"] if _yt_dlp_verbose() else []) + ["-F", resolved] + extra
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=45, env=env)
            out = (r.stdout or "") + "\n" + (r.stderr or "")
            if r.returncode == 0:
                return {
                    "ok": True,
                    "message": "Douyin session looks usable for extraction.",
                    "resolved_url": resolved,
                    "effective_url": resolved,
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
        "effective_url": resolved,
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
    cmd_env = _cmd_env_for_media_subprocess()
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
            resolved_url = _normalize_douyin_watch_url(_expand_short_url(input_ref))
            vc_err = ""
            ytdl_err = ""
            is_dy = _looks_like_douyin_url(resolved_url)

            if is_dy:
                dy_env = _douyin_restore_parent_http_proxy(cmd_env)
                media_path, ytdl_err = _download_with_yt_dlp(resolved_url, work_dir, dy_env)
                if not media_path and vc_bin:
                    dl_vc = subprocess.run(
                        [vc_bin, "download", resolved_url],
                        cwd=work_dir,
                        capture_output=True,
                        text=True,
                        timeout=240,
                        env=dy_env,
                    )
                    if dl_vc.returncode == 0:
                        media_path = _pick_downloaded_media(work_dir)
                    else:
                        vc_err = _stderr_tail(dl_vc, 1400)
            elif vc_bin:
                dl_vc = subprocess.run(
                    [vc_bin, "download", resolved_url],
                    cwd=work_dir,
                    capture_output=True,
                    text=True,
                    timeout=240,
                    env=cmd_env,
                )
                if dl_vc.returncode == 0:
                    media_path = _pick_downloaded_media(work_dir)
                else:
                    vc_err = _stderr_tail(dl_vc, 1400)
                if not media_path:
                    media_path, ytdl_err = _download_with_yt_dlp(resolved_url, work_dir, cmd_env)
            else:
                media_path, ytdl_err = _download_with_yt_dlp(resolved_url, work_dir, cmd_env)

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
                blocks: list[str] = []
                if is_dy:
                    blocks.append(f"yt-dlp (preferred for Douyin; includes cookie ladder):\n{ytdl_err or '(no stderr)'}")
                    if vc_bin and vc_err:
                        blocks.append(f"VideoCaptioner download fallback:\n{vc_err}")
                else:
                    if vc_bin:
                        blocks.append(f"VideoCaptioner download ({vc_bin}):\n{vc_err or '(no stderr)'}")
                    blocks.append(f"yt-dlp:\n{ytdl_err or '(no stderr)'}")
                detail = "\n\n".join(blocks)
                if _looks_like_douyin_url(resolved_url):
                    dy_st = _douyin_cookie_file_runtime_status()
                    detail += _douyin_recommended_local_first_blurb()
                    detail += _douyin_failure_diagnosis_block(dy_st)
                    detail += _douyin_download_help_zh_en()
                return TranscribeOutcome("", "", None, detail=detail)
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
