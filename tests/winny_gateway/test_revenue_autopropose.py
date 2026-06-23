"""Revenue auto-proposes outbound sends — the full owner-gated loop end to end:
a stalled deal → a draft AND a PENDING gmail.send (never auto-sent) for the human to
approve. With no Gmail connection, it just drafts. Hermetic.
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
from winny_gateway.integrations import gmail as _gmail  # noqa: F401 — registers GmailConnector
from winny_gateway.integrations.secrets import encrypt_secret
from winny_gateway.ops import engine as engine_mod
from winny_gateway.ops import revenue as revenue_mod
from winny_gateway.routes.vigil import ops as ops_mod


class FakeDB:
    def __init__(self): self.tables: dict[str, list[dict[str, Any]]] = {}
    def _t(self, n): return self.tables.setdefault(n, [])
    @staticmethod
    def _m(r, f): return all(r.get(k) == v for k, v in (f or {}).items())
    async def insert(self, table, data, **_k):
        row = dict(data); row.setdefault("id", str(uuid.uuid4())); row.setdefault("created_at", "2026-01-01T00:00:00Z")
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
        self.tables[table] = [r for r in self._t(table) if not self._m(r, filters)]; return True


@pytest.fixture
def client(monkeypatch):
    db = FakeDB()
    for mod in (ops_mod, engine_mod, revenue_mod, conn_mod, db_mod):
        monkeypatch.setattr(mod, "db_insert", db.insert, raising=False)
        monkeypatch.setattr(mod, "db_select", db.select, raising=False)
        monkeypatch.setattr(mod, "db_update", db.update, raising=False)
        monkeypatch.setattr(mod, "db_delete", db.delete, raising=False)

    async def draft(_d, _c): return ("Hi, following up.", 0.001)
    monkeypatch.setattr(revenue_mod, "draft_followup", draft)

    app = FastAPI()
    app.include_router(ops_mod.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}
    c = TestClient(app)
    c.db = db  # type: ignore[attr-defined]
    return c


def _data(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _revenue_id(client) -> str:
    return next(d["id"] for d in _data(client.get("/v1/ops/departments"))["departments"] if d["slug"] == "revenue")


def _seed_deal(client):
    client.db._t("crm_contacts").append({"id": "c1", "user_id": "u1", "name": "Dana", "email": "d@x.com"})
    client.db._t("crm_deals").append({"id": "d1", "user_id": "u1", "title": "Acme", "stage": "proposal", "contact_id": "c1"})


def test_drafts_only_when_no_gmail(client):
    _seed_deal(client)
    did = _revenue_id(client)
    task = _data(client.post(f"/v1/ops/departments/{did}/run", json={"job": "follow_up"}))["task"]
    assert task["accepted"] is True
    assert len(client.db.tables["mail_drafts"]) == 1
    assert client.db.tables.get("outbound_actions", []) == []   # nothing proposed without a connection


def test_proposes_pending_send_when_gmail_connected(client):
    client.db._t("connections").append({
        "id": "conn-g", "user_id": "u1", "provider": "gmail", "kind": "email",
        "access_token_enc": encrypt_secret("app-pw"), "external_account": "me@gmail.com",
        "status": "active", "metadata": {},
    })
    _seed_deal(client)
    did = _revenue_id(client)
    task = _data(client.post(f"/v1/ops/departments/{did}/run", json={"job": "follow_up"}))["task"]
    assert task["accepted"] is True
    assert len(client.db.tables["mail_drafts"]) == 1
    actions = client.db.tables["outbound_actions"]
    assert len(actions) == 1
    a = actions[0]
    assert a["action"] == "send" and a["status"] == "pending" and a["requested_by"] == "agent"
    assert a["params"]["to"] == "d@x.com"   # never sent — waits in Approvals
