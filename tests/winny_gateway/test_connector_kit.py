"""Connector kit (Phase 0) — generic per-tenant connect/sync/disconnect.

Proves the kit hermetically with the GitHub connector's network calls monkeypatched:
token verified → stored ENCRYPTED per tenant → sync writes metadata → status masks the
token → disconnect removes it → multi-tenant isolation holds.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import winny_gateway.db as db_mod
from winny_gateway.auth import get_current_user
from winny_gateway.integrations import connector as conn_mod
from winny_gateway.integrations import github as gh_mod
from winny_gateway.routes.vigil import connect as connect_mod


class FakeDB:
    def __init__(self): self.tables: dict[str, list[dict[str, Any]]] = {}
    def _t(self, n): return self.tables.setdefault(n, [])
    @staticmethod
    def _m(r, f): return all(r.get(k) == v for k, v in (f or {}).items())

    async def insert(self, table, data, **_k):
        row = dict(data); row.setdefault("id", str(uuid.uuid4()))
        self._t(table).append(row); return dict(row)

    async def select(self, table, *, filters=None, limit=None, order_by=None, **_k):
        rows = [dict(r) for r in self._t(table) if self._m(r, filters)]
        return rows[:limit] if limit else rows

    async def update(self, table, data, *, filters, **_k):
        out = []
        for r in self._t(table):
            if self._m(r, filters):
                r.update(data); out.append(dict(r))
        return out

    async def delete(self, table, *, filters, **_k):
        self.tables[table] = [r for r in self._t(table) if not self._m(r, filters)]
        return True


@pytest.fixture
def client(monkeypatch):
    db = FakeDB()
    for mod in (conn_mod, db_mod):
        monkeypatch.setattr(mod, "db_insert", db.insert, raising=False)
        monkeypatch.setattr(mod, "db_select", db.select, raising=False)
        monkeypatch.setattr(mod, "db_update", db.update, raising=False)
        monkeypatch.setattr(mod, "db_delete", db.delete, raising=False)

    # Monkeypatch the GitHub connector's network calls (no real GitHub).
    gh = conn_mod.get_connector("github")

    async def verify(_token): return {"external_account": "octocat", "github_id": 1}
    async def sync(_uid, _conn, _token): return {"metadata": {"repos": 3, "open_issues": 7}, "repos": 3, "open_issues": 7}
    monkeypatch.setattr(gh, "verify_token", verify)
    monkeypatch.setattr(gh, "sync", sync)

    app = FastAPI()
    app.include_router(connect_mod.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "u1", "email": "a@x.com"}
    c = TestClient(app)
    c.db = db  # type: ignore[attr-defined]
    return c


def _data(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_status_lists_registered_providers(client):
    data = _data(client.get("/v1/connect/status"))
    assert any(p["id"] == "github" and p["kind"] == "engineering" for p in data["providers"])
    assert data["connections"] == []


def test_connect_stores_encrypted_token_then_sync_and_disconnect(client):
    conn = _data(client.post("/v1/connect/github/token", json={"token": "ghp_secrettoken123"}))["connection"]
    assert conn["external_account"] == "octocat"
    assert conn["token_masked"].startswith("ghp_")            # masked, not full value
    stored = client.db.tables["connections"][0]
    assert stored["access_token_enc"] != "ghp_secrettoken123"  # encrypted at rest

    result = _data(client.post("/v1/connect/github/sync", json={"connection_id": conn["id"]}))
    assert result["repos"] == 3 and result["open_issues"] == 7
    assert client.db.tables["connections"][0]["metadata"]["repos"] == 3
    assert client.db.tables["connections"][0]["last_synced_at"]

    assert _data(client.delete(f"/v1/connect/connections/{conn['id']}"))["disconnected"] == conn["id"]
    assert client.db.tables["connections"] == []


def test_bad_token_is_a_clean_error_not_a_crash(client, monkeypatch):
    gh = conn_mod.get_connector("github")

    async def bad(_t):
        raise conn_mod.ConnectorError("invalid GitHub token", code="invalid_token", status=400)
    monkeypatch.setattr(gh, "verify_token", bad)
    r = client.post("/v1/connect/github/token", json={"token": "nope"})
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_token"


def test_unknown_provider_404(client):
    r = client.post("/v1/connect/notreal/token", json={"token": "x"})
    assert r.status_code == 404


def test_connections_are_tenant_scoped(client):
    cid = _data(client.post("/v1/connect/github/token", json={"token": "ghp_x"}))["connection"]["id"]
    client.app.dependency_overrides[get_current_user] = lambda: {"sub": "u2", "email": "b@x.com"}
    # u2 sees no connections, and cannot sync u1's
    assert _data(client.get("/v1/connect/status"))["connections"] == []
    assert client.post("/v1/connect/github/sync", json={"connection_id": cid}).status_code == 404
