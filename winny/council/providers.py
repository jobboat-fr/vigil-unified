"""Multi-provider LLM client for the AI council — Python port of VIGIL's
multi_provider_client.js (Anthropic Messages, OpenAI Chat, Gemini
generateContent, plus OpenAI-compatible Groq/Mistral/DeepSeek/Together).

Differences from the Node original, by design:
  * Async (httpx.AsyncClient) — the gateway is async.
  * **Graceful offline mode:** when a provider's API key is unset, ``ask`` does
    NOT raise; it returns a ``stub`` response whose ``output`` is valid JSON so
    the council still produces a (clearly-labelled) verdict locally without
    keys. With keys present it makes the real call. This keeps the meeting room
    usable in dev and degrades cleanly in prod.

Return shape matches the orchestrator's expectations:
    {model, output, usage{prompt_tokens, completion_tokens, total_tokens},
     latency_ms, cost_usd, finish_reason, stub: bool}
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_TIMEOUT = 90.0

# Minimal price table (USD per 1M tokens: input, output). Unknown models → 0.0
# so cost telemetry never blocks a run. Extend as needed.
_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4.5": (3.0, 15.0),
    "claude-3.5-sonnet": (3.0, 15.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
    "gemini-2.5-flash": (0.30, 2.5),
    "gemini-2.5-pro": (1.25, 10.0),
    # HuggingFace router models (ports AZZCO's TOKEN_PRICES table)
    "gpt-oss-120b": (0.15, 0.60),
    "gpt-oss-20b": (0.05, 0.20),
    "kimi-k2": (0.50, 2.80),
    "qwen": (0.10, 0.15),
}

_OAI_COMPAT = {
    "groq": ("GROQ_BASE_URL", "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "mistral": ("MISTRAL_BASE_URL", "https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
    "deepseek": ("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    "together": ("TOGETHER_BASE_URL", "https://api.together.xyz/v1", "TOGETHER_API_KEY"),
}


def _price_key(model: str) -> str:
    m = model.lower()
    if m.startswith("claude-sonnet-4") or "sonnet-4.5" in m:
        return "claude-sonnet-4.5"
    if "claude-3-5-sonnet" in m or "claude-3.5-sonnet" in m:
        return "claude-3.5-sonnet"
    if "gemini-2.5-pro" in m:
        return "gemini-2.5-pro"
    if "gemini-2.5-flash" in m:
        return "gemini-2.5-flash"
    if "gpt-oss-120b" in m:
        return "gpt-oss-120b"
    if "gpt-oss-20b" in m:
        return "gpt-oss-20b"
    if "kimi" in m:
        return "kimi-k2"
    if "qwen" in m:
        return "qwen"
    return m


def _cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    inp, out = _PRICING.get(_price_key(model), (0.0, 0.0))
    return round((prompt_tokens / 1_000_000) * inp + (completion_tokens / 1_000_000) * out, 6)


def _stub(model: str, family: str, reason: str) -> dict[str, Any]:
    """Offline response: valid JSON output so downstream parsing stays sane."""
    payload = {
        "should_intervene": False,
        "intervention_text": f"[council offline] {family} model {model} unavailable: {reason}",
        "category": "other",
        "confidence": 0,
        "reasoning": f"No API key for {family}; returned a neutral stub so the council can complete.",
        # neutral reviewer scores in case this stub is a reviewer
        "accuracy": 70, "relevance": 70, "completeness": 70,
        "tone": 70, "harm_risk": 70, "timing": 70, "overall": 70,
    }
    return {
        "model": model,
        "output": json.dumps(payload),
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "latency_ms": 0,
        "cost_usd": 0.0,
        "finish_reason": "stub",
        "stub": True,
    }


async def ask(
    worker: dict[str, Any],
    user_prompt: str,
    *,
    system: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Single-shot completion for a council worker. Never raises on missing key."""
    family = str(worker.get("family", "")).lower()
    model = worker.get("model", "")
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_prompt})

    try:
        if family == "anthropic":
            return await _call_anthropic(model, messages, temperature, max_tokens, timeout)
        if family == "openai":
            return await _call_openai(OPENAI_URL, os.getenv("OPENAI_API_KEY"), "OpenAI", model, messages, temperature, max_tokens, timeout)
        if family == "google":
            return await _call_gemini(model, messages, temperature, max_tokens, timeout)
        if family in ("huggingface", "hf"):
            # HuggingFace Inference Router — OpenAI-compatible. The x-hf-bill-to
            # header routes inference cost to the configured org (ports AZZCO's
            # HuggingFaceChatProvider). Token: HF_TOKEN; model slug as-is
            # (e.g. "openai/gpt-oss-120b").
            base = (os.getenv("HUGGINGFACE_CHAT_BASE") or "https://router.huggingface.co/v1").rstrip("/")
            # Bill inference to the org that holds the credits. Defaults to
            # "azzetco" (the real HF org for this token — the handoff's "jobboat"
            # was a wrong guess and 403s); override via HF_BILL_TO.
            extra: dict[str, str] = {
                "x-hf-bill-to": os.getenv("HF_BILL_TO") or os.getenv("HUGGINGFACE_BILL_TO") or "azzetco"
            }
            return await _call_openai(
                f"{base}/chat/completions",
                os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_API_TOKEN"),
                "HuggingFace", model, messages, temperature, max_tokens, timeout,
                extra_headers=extra,
            )
        if family in _OAI_COMPAT:
            base_env, base_default, key_env = _OAI_COMPAT[family]
            base = (os.getenv(base_env) or base_default).rstrip("/")
            return await _call_openai(f"{base}/chat/completions", os.getenv(key_env), family, model, messages, temperature, max_tokens, timeout)
        return _stub(model, family or "unknown", f"unknown family '{family}'")
    except _MissingKey as exc:
        return _stub(model, family, str(exc))
    except httpx.HTTPError as exc:
        # Transport/timeout — degrade rather than crash the council.
        return _stub(model, family, f"transport error: {exc}")


class _MissingKey(RuntimeError):
    pass


async def _call_anthropic(model, messages, temperature, max_tokens, timeout) -> dict[str, Any]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise _MissingKey("ANTHROPIC_API_KEY not set")
    system_msg = next((m["content"] for m in messages if m["role"] == "system"), None)
    user_msgs = [m for m in messages if m["role"] != "system"]
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user" if m["role"] != "assistant" else "assistant", "content": m["content"]} for m in user_msgs],
    }
    if system_msg:
        body["system"] = system_msg
    t0 = time.time()
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            ANTHROPIC_URL,
            headers={"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION, "Content-Type": "application/json"},
            json=body,
        )
    latency_ms = int((time.time() - t0) * 1000)
    resp.raise_for_status()
    data = resp.json()
    output = "".join(c.get("text", "") for c in data.get("content", []) if c.get("type") == "text")
    usage = {
        "prompt_tokens": data.get("usage", {}).get("input_tokens", 0),
        "completion_tokens": data.get("usage", {}).get("output_tokens", 0),
    }
    usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    return {
        "model": model, "output": output, "usage": usage, "latency_ms": latency_ms,
        "cost_usd": _cost(model, usage["prompt_tokens"], usage["completion_tokens"]),
        "finish_reason": data.get("stop_reason", "unknown"), "stub": False,
    }


async def _call_openai(url, api_key, label, model, messages, temperature, max_tokens, timeout, extra_headers=None) -> dict[str, Any]:
    if not api_key:
        raise _MissingKey(f"{label} API key not set")
    body = {
        "model": model,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    t0 = time.time()
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=body)
    latency_ms = int((time.time() - t0) * 1000)
    resp.raise_for_status()
    data = resp.json()
    choice = (data.get("choices") or [{}])[0]
    output = (choice.get("message") or {}).get("content", "")
    usage = {
        "prompt_tokens": data.get("usage", {}).get("prompt_tokens", 0),
        "completion_tokens": data.get("usage", {}).get("completion_tokens", 0),
        "total_tokens": data.get("usage", {}).get("total_tokens", 0),
    }
    return {
        "model": model, "output": output, "usage": usage, "latency_ms": latency_ms,
        "cost_usd": _cost(model, usage["prompt_tokens"], usage["completion_tokens"]),
        "finish_reason": choice.get("finish_reason", "unknown"), "stub": False,
    }


async def _call_gemini(model, messages, temperature, max_tokens, timeout) -> dict[str, Any]:
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise _MissingKey("GOOGLE_API_KEY (or GEMINI_API_KEY) not set")
    system_msg = next((m["content"] for m in messages if m["role"] == "system"), None)
    user_msgs = [m for m in messages if m["role"] != "system"]
    body: dict[str, Any] = {
        "contents": [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in user_msgs],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "thinkingConfig": {"thinkingBudget": 0},
        },
        "safetySettings": [
            {"category": c, "threshold": "BLOCK_ONLY_HIGH"}
            for c in ("HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")
        ],
    }
    if system_msg:
        body["systemInstruction"] = {"parts": [{"text": system_msg}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    t0 = time.time()
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers={"Content-Type": "application/json"}, json=body)
    latency_ms = int((time.time() - t0) * 1000)
    resp.raise_for_status()
    data = resp.json()
    candidate = (data.get("candidates") or [{}])[0]
    output = "".join(p.get("text", "") for p in (candidate.get("content") or {}).get("parts", []))
    md = data.get("usageMetadata", {})
    usage = {
        "prompt_tokens": md.get("promptTokenCount", 0),
        "completion_tokens": md.get("candidatesTokenCount", 0),
        "total_tokens": md.get("totalTokenCount", 0),
    }
    return {
        "model": model, "output": output, "usage": usage, "latency_ms": latency_ms,
        "cost_usd": _cost(model, usage["prompt_tokens"], usage["completion_tokens"]),
        "finish_reason": candidate.get("finishReason", "unknown"), "stub": False,
    }
