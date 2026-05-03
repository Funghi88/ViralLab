"""Structured diagnostics helpers for fetch/search failures."""

from __future__ import annotations


def classify_error_message(message: str, context: str = "general") -> dict[str, object]:
    """Map free-form error text to stable diagnostic fields."""
    msg = (message or "").strip()
    lower = msg.lower()

    code = "unknown_error"
    category = "unknown"
    hint = "Please try again later."
    retryable = True

    if not msg:
        code = "empty_error"
        category = "unknown"
        hint = "Operation failed without details."
    elif "ratelimit" in lower or "rate limit" in lower or "too many requests" in lower or "429" in lower or "202 ratelimit" in lower:
        code = "rate_limited"
        category = "throttle"
        hint = "Rate limited by upstream source. Retry in 1-2 minutes."
    elif "timeout" in lower or "timed out" in lower:
        code = "timeout"
        category = "network"
        hint = "Upstream timed out. Retry shortly."
    elif "connection refused" in lower or "name or service not known" in lower or "temporary failure in name resolution" in lower or "failed to establish a new connection" in lower:
        code = "network_unavailable"
        category = "network"
        hint = "Network path to source failed. Check proxy/VPN and retry."
    elif "json" in lower and ("decode" in lower or "parse" in lower):
        code = "parse_error"
        category = "response"
        hint = "Source returned malformed data. Retry with a different query."
    elif "unauthorized" in lower or "forbidden" in lower or "401" in lower or "403" in lower:
        code = "auth_error"
        category = "auth"
        hint = "Source rejected request. Credentials or access may be required."
        retryable = False
    elif "api key" in lower or "token" in lower:
        code = "missing_credentials"
        category = "config"
        hint = "Missing API credentials for optional source."
        retryable = False

    if context == "news" and code == "unknown_error":
        hint = "News sources may be temporarily unavailable. Try another topic."
    if context == "video" and code == "unknown_error":
        hint = "Video source unavailable. Try another query or switch source."
    if context == "china_video" and code == "unknown_error":
        hint = "China source may need direct network path or platform login."

    return {
        "code": code,
        "category": category,
        "message": msg,
        "hint": hint,
        "retryable": retryable,
    }
