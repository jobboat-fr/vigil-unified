"""Verrou d'origine : sans le secret de la bordure, la passerelle refuse (enforce) ou note (observe)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from winny_gateway.edge_lock import EdgeLockMiddleware


@pytest.fixture
def client():
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/v1/x")
    def x():
        return {"ok": True}

    app.add_middleware(EdgeLockMiddleware)
    return TestClient(app)


def test_enforce_refuse_sans_secret(client, monkeypatch):
    monkeypatch.setenv("ORIGIN_LOCK_MODE", "enforce")
    monkeypatch.setenv("ORIGIN_EDGE_SECRET", "s3cret-de-bordure")
    r = client.get("/v1/x")
    assert r.status_code == 403 and r.json()["error"] == "acces_direct_refuse"
    assert client.get("/v1/x", headers={"x-vtlvs-edge": "faux"}).status_code == 403


def test_enforce_accepte_avec_secret(client, monkeypatch):
    monkeypatch.setenv("ORIGIN_LOCK_MODE", "enforce")
    monkeypatch.setenv("ORIGIN_EDGE_SECRET", "s3cret-de-bordure")
    assert client.get("/v1/x", headers={"x-vtlvs-edge": "s3cret-de-bordure"}).status_code == 200


def test_health_toujours_libre(client, monkeypatch):
    monkeypatch.setenv("ORIGIN_LOCK_MODE", "enforce")
    monkeypatch.setenv("ORIGIN_EDGE_SECRET", "s3cret-de-bordure")
    assert client.get("/health").status_code == 200


def test_observe_laisse_passer(client, monkeypatch):
    monkeypatch.setenv("ORIGIN_LOCK_MODE", "observe")
    monkeypatch.setenv("ORIGIN_EDGE_SECRET", "s3cret-de-bordure")
    assert client.get("/v1/x").status_code == 200


def test_enforce_sans_secret_configure_ne_ferme_pas_le_service(client, monkeypatch):
    monkeypatch.setenv("ORIGIN_LOCK_MODE", "enforce")
    monkeypatch.delenv("ORIGIN_EDGE_SECRET", raising=False)
    assert client.get("/v1/x").status_code == 200
