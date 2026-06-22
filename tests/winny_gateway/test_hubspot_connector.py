"""HubSpot connector — syncs the tenant's contacts + deals into our crm_* tables,
idempotent on the HubSpot object id, so Revenue + Lead Scout work live data.

Hermetic: HubSpot HTTP (`_get`) is monkeypatched with canned payloads; the real
mapping + idempotency logic runs against a fake DB.
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
from winny_gateway.integrations import hubspot as hs_mod
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


def _fake_get(_token, path, params=None):
    async def inner():
        if path.endswith("/account-info/v3/details"):
            return {"portalId": 424242}
        if "contacts" in path:
            return {"results": [
                {"id": "c1", "properties": {"email": "dana@acme.com", "firstname": "Dana", "company": "Acme", "jobtitle": "CTO"}},
                {"id": "c2", "properties": {"email": "lee@globex.com", "firstname": "Lee"}},
            ]}
        if "deals" in path:
            return {"results": [
                {"id": "d1", "properties": {"dealname": "Acme expansion", "amount": "12000", "dealstage": "presentationscheduled"}},
                {"id": "d2", "properties": {"dealname": "Globex pilot", "amount": "5000", "dealstage": "closedwon"}},
            ]}
        return {}
    return inner()


@pytest.fixture
def client(monkeypatch):
    db = FakeDB()
    for mod in (conn_mod, hs_mod, db_mod):
        monkeypatch.setattr(mod, "db_insert", db.insert, raising=False)
        monkeypatch.setattr(mod, "db_select", db.select, raising=False)
        monkeypatch.setattr(mod, "db_update", db.update, raising=False)
        monkeypatch.setattr(mod, "db_delete", db.delete, raising=False)
    monkeypatch.setattr(hs_mod, "_get", _fake_get)

    app = FastAPI()
    app.include_router(connect_mod.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "u1", "email": "a@x.com"}
    c = TestClient(app)
    c.db = db  # type: ignore[attr-defined]
    return c


def _data(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_hubspot_registered(client):
    assert any(p["id"] == "hubspot" and p["kind"] == "crm" for p in _data(client.get("/v1/connect/status"))["providers"])


def test_connect_and_sync_into_crm_idempotently(client):
    conn = _data(client.post("/v1/connect/hubspot/token", json={"token": "pat-na1-secret"}))["connection"]
    assert conn["external_account"] == "424242"

    first = _data(client.post("/v1/connect/hubspot/sync", json={"connection_id": conn["id"]}))
    assert first["contacts_added"] == 2 and first["deals_added"] == 2
    contacts = client.db.tables["crm_contacts"]
    deals = client.db.tables["crm_deals"]
    assert {c["email"] for c in contacts} == {"dana@acme.com", "lee@globex.com"}
    assert all("hubspot" in c["tags"] for c in contacts)
    assert any(d["stage"] == "won" for d in deals)        # closedwon mapped
    assert any(d["value"] == 12000.0 for d in deals)      # amount parsed

    second = _data(client.post("/v1/connect/hubspot/sync", json={"connection_id": conn["id"]}))
    assert second["contacts_added"] == 0 and second["deals_added"] == 0  # idempotent
    assert len(client.db.tables["crm_contacts"]) == 2
