"""The cheap-classify tier: high-volume classification routes to a local
OpenAI-compatible model (llama.cpp/Ollama) when LOCAL_LLM_BASE is set, and falls
back safely to the primary council worker otherwise — so it's a no-op by default.
"""
from __future__ import annotations

from winny.council.registry import cheap_worker, worker_registry


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
