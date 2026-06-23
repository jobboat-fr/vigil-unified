"""Privacy / GDPR — export (secrets redacted) + erasure, tenant-scoped."""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import winny_gateway.db as db_mod
from winny_gateway.auth import get_current_user
from winny_gateway.routes.vigil import privacy as priv_mod


class FakeDB:
    def __init__(self): self.tables: dict[str, list[dict[str, Any]]] = {}
    def _t(self, n): return self.tables.setdefault(n, [])
    @staticmethod
    def _m(r, f): return all(r.get(k) == v for k, v in (f or {}).items())
    async def insert(self, table, data, **_k):
        row = dict(data); row.setdefault("id", str(uuid.uuid4())); self._t(table).append(row); return dict(row)
    async def select(self, table, *, filters=None, limit=None, order_by=None, **_k):
        rows = [dict(r) for r in self._t(table) if self._m(r, filters)]
        return rows[:limit] if limit else rows
    async def update(self, table, data, *, filters, **_k):
        return [r for r in self._t(table) if self._m(r, filters)]
    async def delete(self, table, *, filters, **_k):
        self.tables[table] = [r for r in self._t(table) if not self._m(r, filters)]; return True


@pytest.fixture
def client(monkeypatch):
    db = FakeDB()
    for mod in (priv_mod, db_mod):
        monkeypatch.setattr(mod, "db_select", db.select, raising=False)
        monkeypatch.setattr(mod, "db_delete", db.delete, raising=False)
    # u1 owns a connection (with an encrypted token) + an artifact; u2 owns one too.
    db._t("connections").extend([
        {"id": "x", "user_id": "u1", "provider": "github", "access_token_enc": "ENCRYPTED_SECRET"},
        {"id": "y", "user_id": "u2", "provider": "github", "access_token_enc": "OTHER"},
    ])
    db._t("artifacts").append({"id": "a1", "user_id": "u1", "title": "memo"})
    app = FastAPI()
    app.include_router(priv_mod.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}
    c = TestClient(app); c.db = db  # type: ignore[attr-defined]
    return c


def _data(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_export_redacts_secrets_and_is_scoped(client):
    data = _data(client.get("/v1/privacy/export"))
    assert data["user_id"] == "u1"
    assert "connections" in data["tables"] and "artifacts" in data["tables"]
    assert data["tables"]["connections"][0]["access_token_enc"] == "***"   # never export the token
    # only u1's rows
    assert all(r["user_id"] == "u1" for rows in data["tables"].values() for r in rows)


def test_erasure_deletes_only_the_tenants_rows(client):
    out = _data(client.delete("/v1/privacy/data"))
    assert out["deleted"].get("connections") == 1 and out["deleted"].get("artifacts") == 1
    # u1 gone, u2 untouched
    assert [r["id"] for r in client.db.tables["connections"]] == ["y"]
    assert client.db.tables["artifacts"] == []
