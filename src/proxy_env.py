"""Dynamic proxy resolution for ViralLab on macOS (QuickQ floating SOCKS/HTTP + TUN) & servers.

Key behaviors:
- Never blindly trust a dead proxy (e.g. stale `127.0.0.1:18080` or a rotated QuickQ port):
  every candidate proxy URL is fast-probed with a short TCP connect before use.
- On macOS, dynamically inspects `scutil --proxy` (cached briefly) for both HTTP(S) and
  SOCKS5 proxies (QuickQ floating SOCKS ports use `SOCKSEnable` / `SOCKSProxy` / `SOCKSPort`),
  automatically adapting whenever QuickQ reconnects and rotates ports.
- When QuickQ runs in TUN/VPN mode (no system proxy configured), returns `None` and cleans
  dead proxy env vars so traffic routes cleanly through the TUN interface.
- Supports `VIRALLAB_NO_DOTENV_PROXY=1` so subprocesses explicitly launched without a proxy
  do not accidentally re-inject dead proxy vars via `load_dotenv()`.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlparse

PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "http_proxy",
    "https_proxy",
    "ALL_PROXY",
    "all_proxy",
)

_PROBE_CACHE: dict[tuple[str, int], tuple[float, bool]] = {}
_PROBE_TTL_SEC = 5.0

_SCUTIL_CACHE: tuple[float, dict[str, Any]] = (0.0, {})
_SCUTIL_TTL_SEC = 4.0


def _tcp_reachable(host: str, port: int, timeout: float = 0.25) -> bool:
    """Fast cached TCP connect check to verify a local/LAN proxy is actually listening."""
    if not host or port <= 0 or port > 65535:
        return False
    now = time.monotonic()
    key = (host.lower(), port)
    cached = _PROBE_CACHE.get(key)
    if cached and (now - cached[0]) < _PROBE_TTL_SEC:
        return cached[1]
    ok = False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            ok = True
    except OSError:
        ok = False
    _PROBE_CACHE[key] = (now, ok)
    return ok


def is_proxy_url_reachable(proxy_url: str, timeout: float = 0.25) -> bool:
    """Return True if proxy_url has a valid host:port that accepts TCP connections."""
    u = (proxy_url or "").strip()
    if not u:
        return False
    if "://" not in u:
        u = "http://" + u
    try:
        parsed = urlparse(u)
        host = parsed.hostname
        port = parsed.port
        if not host:
            return False
        if port is None:
            scheme = (parsed.scheme or "http").lower()
            port = 1080 if scheme.startswith("socks") else (443 if scheme == "https" else 80)
        return _tcp_reachable(host, int(port), timeout=timeout)
    except Exception:
        return False


def parse_scutil_proxy_output(text: str) -> dict[str, Any]:
    """Parse `scutil --proxy` stdout into normalized HTTP and SOCKS proxy URLs."""
    info: dict[str, str] = {}
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        info[k.strip()] = v.strip()

    http_url = ""
    https_url = ""
    socks_url = ""

    if info.get("HTTPEnable") == "1" and info.get("HTTPProxy") and info.get("HTTPPort"):
        http_url = f"http://{info['HTTPProxy']}:{info['HTTPPort']}"
    if info.get("HTTPSEnable") == "1" and info.get("HTTPSProxy") and info.get("HTTPSPort"):
        https_url = f"http://{info['HTTPSProxy']}:{info['HTTPSPort']}"
    elif http_url:
        https_url = http_url

    if info.get("SOCKSEnable") == "1" and info.get("SOCKSProxy") and info.get("SOCKSPort"):
        # socks5h resolves DNS remotely through the VPN/proxy (prevents DNS poisoning in CN).
        socks_url = f"socks5h://{info['SOCKSProxy']}:{info['SOCKSPort']}"

    return {
        "http": http_url,
        "https": https_url,
        "socks": socks_url,
        "raw": info,
    }


def read_macos_system_proxy(*, force: bool = False) -> dict[str, Any]:
    """Read live macOS system proxy settings via `scutil --proxy` (cached briefly)."""
    global _SCUTIL_CACHE
    if sys.platform != "darwin":
        return {"http": "", "https": "", "socks": "", "raw": {}}
    now = time.monotonic()
    if not force and (now - _SCUTIL_CACHE[0]) < _SCUTIL_TTL_SEC:
        return _SCUTIL_CACHE[1]
    result = {"http": "", "https": "", "socks": "", "raw": {}}
    try:
        r = subprocess.run(
            ["scutil", "--proxy"],
            capture_output=True,
            text=True,
            timeout=1.5,
        )
        if r.returncode == 0 and r.stdout:
            result = parse_scutil_proxy_output(r.stdout)
    except Exception:
        pass
    _SCUTIL_CACHE = (now, result)
    return result


def resolve_active_proxy(
    env: dict[str, str] | None = None,
    *,
    force_scutil: bool = False,
) -> dict[str, str]:
    """Resolve currently reachable proxy URLs.

    Returns a dict with optional keys `http`, `https`, `all`, `mode` (`env`, `scutil_http`,
    `scutil_socks`, or `direct`). Dead/unreachable proxies are automatically skipped so
    floating QuickQ ports or TUN-mode VPN never stall requests.
    """
    src = env if env is not None else os.environ

    # 1. Explicit env proxy (only if actually reachable right now)
    env_http = (src.get("HTTP_PROXY") or src.get("http_proxy") or "").strip()
    env_https = (src.get("HTTPS_PROXY") or src.get("https_proxy") or "").strip()
    env_all = (src.get("ALL_PROXY") or src.get("all_proxy") or "").strip()

    live_http = env_http if is_proxy_url_reachable(env_http) else ""
    live_https = env_https if is_proxy_url_reachable(env_https) else ""
    live_all = env_all if is_proxy_url_reachable(env_all) else ""

    if live_http or live_https or live_all:
        h = live_http or live_https or live_all
        hs = live_https or live_http or live_all
        out = {"http": h, "https": hs, "mode": "env"}
        if live_all:
            out["all"] = live_all
        return out

    # 2. macOS dynamic system proxy (QuickQ / Clash / Surge floating HTTP or SOCKS5)
    sc = read_macos_system_proxy(force=force_scutil)
    sc_http = sc.get("http") or ""
    sc_https = sc.get("https") or ""
    sc_socks = sc.get("socks") or ""

    if sc_http and is_proxy_url_reachable(sc_http):
        hs = sc_https if (sc_https and is_proxy_url_reachable(sc_https)) else sc_http
        return {"http": sc_http, "https": hs, "mode": "scutil_http"}

    if sc_https and is_proxy_url_reachable(sc_https):
        return {"http": sc_https, "https": sc_https, "mode": "scutil_http"}

    if sc_socks and is_proxy_url_reachable(sc_socks):
        return {"http": sc_socks, "https": sc_socks, "all": sc_socks, "mode": "scutil_socks"}

    # 3. Direct / TUN VPN interface (e.g. QuickQ utun)
    return {"mode": "direct"}


def strip_proxy_vars(env: dict[str, str]) -> dict[str, str]:
    """Return a copy of `env` with all proxy vars removed and dotenv proxy disabled."""
    out = dict(env)
    for k in PROXY_ENV_VARS:
        out.pop(k, None)
    out["VIRALLAB_NO_DOTENV_PROXY"] = "1"
    return out


def env_for_overseas(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Build subprocess env for overseas targets (YouTube, Google, DDG, OpenAI, X, TikTok).

    Uses the currently reachable env or macOS system proxy (HTTP or floating SOCKS5).
    If no local proxy is active (e.g., QuickQ TUN mode or direct internet), strips dead
    proxy vars so requests flow cleanly without ConnectionRefusedError.
    """
    out = dict(base_env if base_env is not None else os.environ)
    active = resolve_active_proxy(out)
    for k in PROXY_ENV_VARS:
        out.pop(k, None)
    if active.get("http"):
        out["HTTP_PROXY"] = active["http"]
        out["http_proxy"] = active["http"]
    if active.get("https"):
        out["HTTPS_PROXY"] = active["https"]
        out["https_proxy"] = active["https"]
    if active.get("all"):
        out["ALL_PROXY"] = active["all"]
        out["all_proxy"] = active["all"]
    else:
        # Prevent child scripts from re-injecting a dead .env proxy when running in direct/TUN mode.
        if active.get("mode") == "direct":
            out["VIRALLAB_NO_DOTENV_PROXY"] = "1"
    return out


def env_for_domestic(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Build subprocess env for China-domestic targets (Douyin, XHS, Bilibili direct)."""
    return strip_proxy_vars(dict(base_env if base_env is not None else os.environ))


def apply_runtime_proxy_hygiene() -> dict[str, str]:
    """Sanitize `os.environ` in-place after `load_dotenv()`.

    - If `VIRALLAB_NO_DOTENV_PROXY=1` was set by parent process, ensures proxy vars stay stripped.
    - Otherwise removes any dead/unreachable proxy vars (like stale `127.0.0.1:18080`) and
      populates live macOS `scutil --proxy` HTTP/SOCKS5 settings if active.
    """
    if (os.environ.get("VIRALLAB_NO_DOTENV_PROXY") or "").strip().lower() in ("1", "true", "yes"):
        for k in PROXY_ENV_VARS:
            os.environ.pop(k, None)
        return {"mode": "direct"}

    active = resolve_active_proxy(os.environ, force_scutil=True)
    for k in PROXY_ENV_VARS:
        os.environ.pop(k, None)
    if active.get("http"):
        os.environ["HTTP_PROXY"] = active["http"]
        os.environ["http_proxy"] = active["http"]
    if active.get("https"):
        os.environ["HTTPS_PROXY"] = active["https"]
        os.environ["https_proxy"] = active["https"]
    if active.get("all"):
        os.environ["ALL_PROXY"] = active["all"]
        os.environ["all_proxy"] = active["all"]
    return active


def load_dotenv_safe(dotenv_path: Any = None) -> dict[str, str]:
    """Load `.env` and immediately apply proxy hygiene so dead proxies are never re-injected."""
    try:
        from dotenv import load_dotenv
        if dotenv_path is not None:
            load_dotenv(dotenv_path)
        else:
            load_dotenv()
    except ImportError:
        pass
    return apply_runtime_proxy_hygiene()


def requests_proxies_for(*, overseas: bool = True) -> dict[str, str] | None:
    """Return a fresh `proxies=` dict for `requests` (adapts dynamically to QuickQ port changes).

    Returns `{}` when running direct/TUN or domestic so `requests` never uses a stale env proxy.
    """
    if not overseas:
        return {}
    active = resolve_active_proxy(os.environ)
    if active.get("http") or active.get("https"):
        return {
            "http": active.get("http") or active.get("https") or "",
            "https": active.get("https") or active.get("http") or "",
        }
    return {}


def clear_caches() -> None:
    """Reset probe and scutil caches (for tests)."""
    global _SCUTIL_CACHE
    _PROBE_CACHE.clear()
    _SCUTIL_CACHE = (0.0, {})
