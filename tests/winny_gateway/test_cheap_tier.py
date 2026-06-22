"""The cheap-classify tier: high-volume classification routes to a local
OpenAI-compatible model (llama.cpp/Ollama) when LOCAL_LLM_BASE is set, and falls
back safely to the primary council worker otherwise — so it's a no-op by default.
"""
from __future__ import annotations

import asyncio

import winny.council.providers as P
from winny.council import registry as R
from winny.council.registry import cheap_pool, cheap_worker, worker_registry


def test_cheap_worker_falls_back_to_primary_when_unset(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_BASE", raising=False)
    assert cheap_worker() == worker_registry()["primary"]


def test_cheap_worker_uses_local_when_configured(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_BASE", "http://127.0.0.1:8080/v1")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "qwen2.5-3b-instruct")
    w = cheap_worker()
    assert w["family"] == "local"
    assert w["model"] == "qwen2.5-3b-instruct"


def test_local_family_is_recognised_by_ask(monkeypatch):
    # No server running → ask() degrades to a stub rather than raising, proving the
    # 'local' family is wired through the provider dispatch (not an "unknown family").
    import asyncio
    from winny.council.providers import ask
    monkeypatch.setenv("LOCAL_LLM_BASE", "http://127.0.0.1:59999/v1")  # nothing listening
    out = asyncio.run(ask({"family": "local", "model": "local-model"}, "ping", max_tokens=8))
    assert out.get("stub") is True
    assert "unknown family" not in (out.get("output") or "")


def test_cheap_pool_respects_env(monkeypatch):
    monkeypatch.setenv("CHEAP_POOL", "local,hf:openai/gpt-oss-20b")
    pool = cheap_pool()
    assert [w["family"] for w in pool] == ["local", "huggingface"]
    assert pool[1]["model"] == "openai/gpt-oss-20b"


def test_cheap_pool_default_has_paid_fallback(monkeypatch):
    monkeypatch.delenv("CHEAP_POOL", raising=False)
    monkeypatch.delenv("LOCAL_LLM_BASE", raising=False)
    pool = cheap_pool()
    assert pool and pool[-1]["family"] == "huggingface"   # always a working tier


def test_ask_cheap_fails_over_past_a_stubbing_provider(monkeypatch):
    wa = {"family": "local", "model": "a"}
    wb = {"family": "huggingface", "model": "b"}
    monkeypatch.setattr(R, "cheap_pool", lambda: [wa, wb])
    calls = []

    async def fake_ask(w, prompt, **kw):
        calls.append(w["model"])
        if w["model"] == "a":
            return {"output": "", "stub": True, "cost_usd": 0.0}
        return {"output": "ok", "stub": False, "cost_usd": 0.0}
    monkeypatch.setattr(P, "ask", fake_ask)
    P._cheap_cooldowns.clear()

    res = asyncio.run(P.ask_cheap("classify this"))
    assert res["stub"] is False and res["output"] == "ok"
    assert calls == ["a", "b"]                      # tried a (stub) → failed over to b
    assert P._cheap_cooldowns.get("local:a", 0) > 0  # a parked on cooldown
