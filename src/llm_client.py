"""Lightweight LLM client for ViralLab with automatic multi-provider fallback & proxy support.

Provider order: OpenAI -> Anthropic -> Gemini.
If the primary configured provider fails (network, quota, auth, model error), automatically
falls back to the next configured key instead of aborting immediately.

Model env overrides:
- VIRALLAB_OPENAI_MODEL    (default: gpt-4.1-mini)
- VIRALLAB_ANTHROPIC_MODEL (default: claude-haiku-4-5)
- VIRALLAB_GEMINI_MODEL    (default: gemini-2.5-flash)
"""
from __future__ import annotations

import os
from typing import Any, Callable

import requests

from src.proxy_env import load_dotenv_safe, requests_proxies_for

_PLACEHOLDER_KEYS = {"", "sk-...", "your-key-here", "sk-ant-..."}


def _load_env() -> None:
    load_dotenv_safe()


def _valid_key(val: str | None) -> str:
    k = (val or "").strip()
    return "" if k in _PLACEHOLDER_KEYS else k


def _post_json(url: str, *, headers: dict[str, str], payload: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
    proxies = requests_proxies_for(overseas=True)
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout, proxies=proxies)
    except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError):
        if not proxies:
            raise
        r = requests.post(url, headers=headers, json=payload, timeout=timeout, proxies={})
    if not r.ok:
        detail = (r.text or "").strip().replace("\n", " ")[:240]
        raise RuntimeError(f"HTTP {r.status_code} ({detail or r.reason})")
    return r.json()


def call_llm(
    prompt: str,
    system: str = "",
    json_mode: bool = False,
    max_tokens: int = 2000,
) -> str:
    """Return LLM text response, trying each configured provider in order until one succeeds."""
    _load_env()
    providers: list[tuple[str, str, Callable[..., str]]] = []
    openai_key = _valid_key(os.getenv("OPENAI_API_KEY"))
    if openai_key:
        providers.append(("OpenAI", openai_key, _openai))
    anthropic_key = _valid_key(os.getenv("ANTHROPIC_API_KEY"))
    if anthropic_key:
        providers.append(("Anthropic", anthropic_key, _anthropic))
    gemini_key = _valid_key(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    if gemini_key:
        providers.append(("Gemini", gemini_key, _gemini))

    if not providers:
        raise RuntimeError(
            "No LLM API key. Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or GEMINI_API_KEY in .env"
        )

    errors: list[str] = []
    for name, key, fn in providers:
        try:
            text = fn(key, prompt, system, json_mode, max_tokens)
            if text and text.strip():
                return text
            errors.append(f"{name}: empty response")
        except Exception as e:
            errors.append(f"{name}: {e}")
            continue
    raise RuntimeError("All configured LLM providers failed: " + " | ".join(errors))


def _openai(key: str, prompt: str, system: str, json_mode: bool, max_tokens: int) -> str:
    model = (os.getenv("VIRALLAB_OPENAI_MODEL") or "gpt-4.1-mini").strip()
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = _post_json(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        payload=body,
    )
    return r["choices"][0]["message"]["content"]


def _anthropic(key: str, prompt: str, system: str, json_mode: bool, max_tokens: int) -> str:
    model = (os.getenv("VIRALLAB_ANTHROPIC_MODEL") or "claude-haiku-4-5").strip()
    user_prompt = (
        f"{prompt}\n\nRespond with valid JSON only, without markdown code fences."
        if json_mode
        else prompt
    )
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    if system:
        body["system"] = system
    r = _post_json(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        payload=body,
    )
    return r["content"][0]["text"]


def _gemini(key: str, prompt: str, system: str, json_mode: bool, max_tokens: int) -> str:
    model = (os.getenv("VIRALLAB_GEMINI_MODEL") or "gemini-2.5-flash").strip()
    full = f"{system}\n\n{prompt}" if system else prompt
    body: dict[str, Any] = {
        "contents": [{"parts": [{"text": full}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2},
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    r = _post_json(
        url,
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        payload=body,
    )
    return r["candidates"][0]["content"]["parts"][0]["text"]
