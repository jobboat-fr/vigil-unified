"""Stripe connector — succeeded charges → ledger income, idempotent on charge id."""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import winny_gateway.db as db_mod
from winny_gateway.auth import get_current_user
from winny_gateway.integrations import connector as conn_mod
from winny_gateway.integrations import stripe_conn as st_mod
from winny_gateway.routes.vigil import connect as connect_mod


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
        out = [r.update(data) or dict(r) for r in self._t(table) if self._m(r, filters)]
        return [r for r in out if r]
    async def delete(self, table, *, filters, **_k):
        self.tables[table] = [r for r in self._t(table) if not self._m(r, filters)]; return True


def _fake_get(_token, path, params=None):
    async def inner():
        if path == "/account":
            return {"id": "acct_123", "business_profile": {"name": "Acme"}}
        if path == "/charges":
            return {"data": [
                {"id": "ch_1", "status": "succeeded", "paid": True, "amount": 12000, "currency": "usd", "created": 1750000000, "description": "Plan"},
                {"id": "ch_2", "status": "failed", "paid": False, "amount": 999, "currency": "usd"},
            ]}
        return {}
    return inner()


@pytest.fixture
def client(monkeypatch):
    db = FakeDB()
    for mod in (conn_mod, st_mod, db_mod):
        monkeypatch.setattr(mod, "db_insert", db.insert, raising=False)
        monkeypatch.setattr(mod, "db_select", db.select, raising=False)
        monkeypatch.setattr(mod, "db_update", db.update, raising=False)
        monkeypatch.setattr(mod, "db_delete", db.delete, raising=False)
    monkeypatch.setattr(st_mod, "_get", _fake_get)
    app = FastAPI()
    app.include_router(connect_mod.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}
    c = TestClient(app); c.db = db  # type: ignore[attr-defined]
    return c


def _data(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_stripe_sync_imports_succeeded_charges_as_income(client):
    conn = _data(client.post("/v1/connect/stripe/token", json={"token": "sk_test_x"}))["connection"]
    assert conn["external_account"] == "acct_123"
    first = _data(client.post("/v1/connect/stripe/sync", json={"connection_id": conn["id"]}))
    assert first["charges_added"] == 1                       # only the succeeded+paid one
    txn = client.db.tables["finance_transactions"][0]
    assert txn["amount"] == 120.0 and txn["source"] == "stripe" and txn["category"] == "revenue"
    # idempotent
    assert _data(client.post("/v1/connect/stripe/sync", json={"connection_id": conn["id"]}))["charges_added"] == 0
