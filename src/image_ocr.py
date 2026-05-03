"""Image OCR (Chinese + Latin) via RapidOCR + ONNX — no cloud keys.

Use for picture-heavy notes/articles when you have image URLs or raw bytes.
Does not log into Xiaohongshu/WeChat; public image URLs and many mp.weixin.qq.com
article pages still work for fetching <img> URLs.
"""
from __future__ import annotations

import io
import ipaddress
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import numpy as np
import requests
from PIL import Image, UnidentifiedImageError

_MAX_IMAGE_BYTES = 12 * 1024 * 1024
_DEFAULT_TIMEOUT = 25
_IMG_EXT_RE = re.compile(r"\.(jpe?g|png|webp|gif)(\?|#|$)", re.I)
# img src= / data-src= / data-original=
_IMG_URL_RE = re.compile(
    r"""<img[^>]+?(?:data-src|data-original|src)\s*=\s*['"]([^'"]+)['"]""",
    re.IGNORECASE | re.DOTALL,
)

_rapid_ocr: Any = None


def _get_ocr_engine() -> Any:
    global _rapid_ocr
    if _rapid_ocr is None:
        from rapidocr_onnxruntime import RapidOCR

        _rapid_ocr = RapidOCR()
    return _rapid_ocr


def host_is_blocked(hostname: str) -> bool:
    h = (hostname or "").lower().strip()
    if not h:
        return True
    if h == "localhost" or h.endswith(".local"):
        return True
    if h in ("metadata.google.internal", "metadata.goog"):
        return True
    if h.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(h)
        return not ip.is_global
    except ValueError:
        pass
    parts = h.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        a, b, c, d = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        if a == 10 or a == 127 or a == 0:
            return True
        if a == 192 and b == 168:
            return True
        if a == 172 and 16 <= b <= 31:
            return True
        if a == 169 and b == 254:
            return True
        if a == 100 and 64 <= b <= 127:
            return True
    if h.startswith("fc00:") or h.startswith("fe80:"):
        return True
    return False


def url_allowed_for_fetch(url: str) -> bool:
    p = urlparse((url or "").strip())
    if p.scheme not in ("http", "https"):
        return False
    return not host_is_blocked(p.hostname or "")


def looks_like_direct_image_url(url: str) -> bool:
    path = urlparse(url).path or ""
    return bool(_IMG_EXT_RE.search(path))


def normalize_page_url(url: str) -> str:
    u = (url or "").strip()
    if u.startswith("//"):
        return "https:" + u
    return u


def extract_image_urls_from_html(html: str, base_url: str) -> list[str]:
    base = normalize_page_url(base_url)
    seen: set[str] = set()
    out: list[str] = []
    for m in _IMG_URL_RE.finditer(html or ""):
        raw = (m.group(1) or "").strip()
        if not raw or raw.startswith("data:"):
            continue
        if raw.startswith("//"):
            raw = "https:" + raw
        elif raw.startswith("/"):
            raw = urljoin(base, raw)
        elif not raw.startswith("http"):
            raw = urljoin(base, raw)
        if not url_allowed_for_fetch(raw):
            continue
        if raw not in seen:
            seen.add(raw)
            out.append(raw)
    return out


def _pil_to_rgb_ndarray(im: Image.Image) -> np.ndarray:
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    return np.array(im)


def ocr_pil_image(im: Image.Image) -> tuple[list[dict[str, Any]], str]:
    """Run OCR on a PIL image. Returns (lines_detail, full_text)."""
    arr = _pil_to_rgb_ndarray(im)
    engine = _get_ocr_engine()
    result, _elapse = engine(arr)
    lines: list[dict[str, Any]] = []
    parts: list[str] = []
    if not result:
        return lines, ""
    for item in result:
        if not item or len(item) < 2:
            continue
        text = (item[1] or "").strip()
        score = float(item[2]) if len(item) > 2 else None
        if text:
            lines.append({"text": text, "score": score})
            parts.append(text)
    return lines, "\n".join(parts)


def ocr_image_bytes(data: bytes) -> tuple[list[dict[str, Any]], str]:
    if not data:
        return [], ""
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except (UnidentifiedImageError, OSError):
        return [], ""
    return ocr_pil_image(im)


def fetch_url_bytes(url: str, timeout: float = _DEFAULT_TIMEOUT) -> tuple[bytes, str]:
    cur = normalize_page_url(url)
    headers = {"User-Agent": "ViralLab-ImageOCR/1.0"}
    try:
        for _ in range(8):
            if not url_allowed_for_fetch(cur):
                return b"", "url_not_allowed"
            r = requests.get(cur, timeout=timeout, allow_redirects=False, headers=headers)
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                cur = urljoin(cur, r.headers["Location"].strip())
                continue
            if r.status_code >= 400:
                return b"", f"http_{r.status_code}"
            if len(r.content) > _MAX_IMAGE_BYTES:
                return b"", "response_too_large"
            return r.content, ""
    except requests.RequestException as e:
        return b"", f"fetch_error:{e!s}"
    return b"", "too_many_redirects"


def ocr_image_url(url: str, timeout: float = _DEFAULT_TIMEOUT) -> dict[str, Any]:
    url = normalize_page_url(url)
    err: str | None = None
    if not url_allowed_for_fetch(url):
        return {"ok": False, "source": url, "text": "", "lines": [], "error": "url_not_allowed"}
    data, e = fetch_url_bytes(url, timeout=timeout)
    if e:
        return {"ok": False, "source": url, "text": "", "lines": [], "error": e}
    lines, text = ocr_image_bytes(data)
    if not lines and not text and data:
        err = "unrecognized_image_or_no_text"
    return {"ok": err is None, "source": url, "text": text, "lines": lines, "error": err}


def ocr_webpage_images(
    page_url: str,
    *,
    max_images: int = 20,
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Fetch HTML, collect img URLs, OCR each (best-effort for public pages)."""
    page_url = normalize_page_url(page_url)
    if not url_allowed_for_fetch(page_url):
        return {"ok": False, "page_url": page_url, "error": "url_not_allowed", "results": []}
    html, e = fetch_url_bytes(page_url, timeout=timeout)
    if e:
        return {"ok": False, "page_url": page_url, "error": e, "results": []}
    try:
        text = html.decode("utf-8", errors="replace")
    except Exception:
        text = str(html)
    img_urls = extract_image_urls_from_html(text, page_url)[:max_images]
    if not img_urls:
        return {"ok": True, "page_url": page_url, "error": None, "results": [], "note": "no_images_found"}
    results: list[dict[str, Any]] = []
    for u in img_urls:
        results.append(ocr_image_url(u, timeout=timeout))
    return {"ok": True, "page_url": page_url, "error": None, "results": results}


def ocr_job_for_url(url: str, *, mode: str = "auto", timeout: float = _DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Single entry: ``mode`` auto | image | page."""
    url = normalize_page_url(url.strip())
    m = (mode or "auto").lower().strip()
    if m == "page":
        return ocr_webpage_images(url, timeout=timeout)
    if m == "image":
        r = ocr_image_url(url, timeout=timeout)
        return {"ok": r.get("ok"), "mode": "image", "results": [r]}
    # auto
    if looks_like_direct_image_url(url):
        r = ocr_image_url(url, timeout=timeout)
        return {"ok": r.get("ok"), "mode": "image", "results": [r]}
    return ocr_webpage_images(url, timeout=timeout)
