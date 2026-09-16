"""Coupe-circuit IA (phase 0.5) : les pages survivent à un fournisseur en panne."""
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from winny.council import guard, providers
from winny_gateway import ai_guard

W = {"family": "together", "model": "zai-org/GLM-5.3"}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    guard.reset()
    for k in ("AI_ENABLED", "AI_DISABLED_FEATURES", "AI_TIMEOUT_S", "AI_BREAKER_FAILURES", "AI_BREAKER_COOLDOWN_S"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TOGETHER_API_KEY", "test-key")
    yield
    guard.reset()


def _ask():
    return asyncio.run(providers.ask(W, "bonjour"))


def _fail_with(monkeypatch, status_code=402):
    calls = {"n": 0}

    async def boom(*_a, **_k):
        calls["n"] += 1
        req = httpx.Request("POST", "https://api.together.xyz/v1/chat/completions")
        raise httpx.HTTPStatusError("x", request=req, response=httpx.Response(status_code, request=req, text="credits"))

    monkeypatch.setattr(providers, "_call_openai", boom)
    return calls


def test_trois_echecs_ouvrent_le_circuit_et_coupent_les_appels(monkeypatch):
    calls = _fail_with(monkeypatch)
    for _ in range(3):
        r = _ask()
        assert r["stub"] and r["ai_unavailable"]
    assert calls["n"] == 3
    r = _ask()
    assert r["unavailable_reason"] == "circuit_open"
    assert calls["n"] == 3  # plus aucun appel réseau tant que le circuit est ouvert
    assert guard.health()["providers"]["together"]["state"] == "open"


def test_essai_apres_delai_puis_fermeture(monkeypatch):
    monkeypatch.setenv("AI_BREAKER_COOLDOWN_S", "0")
    _fail_with(monkeypatch)
    for _ in range(3):
        _ask()

    async def ok(*_a, **_k):
        return {"model": "m", "output": "{}", "usage": {}, "latency_ms": 1, "cost_usd": 0, "finish_reason": "stop", "stub": False}

    monkeypatch.setattr(providers, "_call_openai", ok)
    r = _ask()
    assert r["stub"] is False
    assert guard.health()["providers"]["together"]["state"] == "closed"


def test_interrupteur_general(monkeypatch):
    monkeypatch.setenv("AI_ENABLED", "false")
    calls = _fail_with(monkeypatch)
    assert _ask()["unavailable_reason"] == "ai_disabled"
    assert calls["n"] == 0


def test_cle_absente_signalee(monkeypatch):
    monkeypatch.delenv("TOGETHER_API_KEY")
    r = _ask()
    assert r["ai_unavailable"]
    assert guard.health()["providers"]["together"]["state"] == "not_configured"


def test_delai_plafonne(monkeypatch):
    monkeypatch.setenv("AI_TIMEOUT_S", "12")
    seen = {}

    async def spy(url, key, label, model, messages, temperature, max_tokens, timeout, extra_headers=None):
        seen["timeout"] = timeout
        return {"model": model, "output": "", "usage": {}, "latency_ms": 0, "cost_usd": 0, "finish_reason": "stop", "stub": False}

    monkeypatch.setattr(providers, "_call_openai", spy)
    asyncio.run(providers.ask(W, "x", timeout=90))
    assert seen["timeout"] == 12


def test_fonction_coupee_via_la_dependance_de_routeur(monkeypatch):
    """La fonction nommée par la dépendance est bien vue par `ask` dans l'endpoint."""
    monkeypatch.setenv("AI_DISABLED_FEATURES", "meeting")
    calls = _fail_with(monkeypatch)
    r = APIRouter()

    @r.get("/x")
    async def endpoint():
        return await providers.ask(W, "x")

    app = FastAPI()
    app.include_router(r, dependencies=[Depends(ai_guard.feature("meeting"))])
    body = TestClient(app).get("/x").json()
    assert body["unavailable_reason"] == "feature_disabled:meeting"
    assert calls["n"] == 0


def test_etat_expose_a_l_app(monkeypatch):
    monkeypatch.delenv("COUNCIL_PROVIDER", raising=False)
    _fail_with(monkeypatch)
    for _ in range(3):
        _ask()
    s = ai_guard.status()
    assert s["provider"] == "together"
    assert s["available"] is False
    assert s["features"]["mail"] is False
