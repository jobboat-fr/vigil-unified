"""Gmail connector — IMAP App-Password login + inbox sync into mail_messages.

Hermetic: the blocking IMAP helpers (_verify_login, _fetch_messages) are
monkeypatched; the real mapping + idempotency logic runs against a fake DB.
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
from winny_gateway.integrations import gmail as gm_mod
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


@pytest.fixture
def client(monkeypatch):
    db = FakeDB()
    for mod in (conn_mod, gm_mod, db_mod):
        monkeypatch.setattr(mod, "db_insert", db.insert, raising=False)
        monkeypatch.setattr(mod, "db_select", db.select, raising=False)
        monkeypatch.setattr(mod, "db_update", db.update, raising=False)
        monkeypatch.setattr(mod, "db_delete", db.delete, raising=False)

    monkeypatch.setattr(gm_mod, "_verify_login", lambda account, pw: None)
    monkeypatch.setattr(gm_mod, "_fetch_messages", lambda account, pw, limit=30: [
        {"external_id": "<m1@x>", "from_name": "Dana", "from_addr": "dana@acme.com", "subject": "Pricing?", "body": "please reply", "received_at": "2026-06-20T10:00:00"},
        {"external_id": "<m2@x>", "from_name": "Lee", "from_addr": "lee@globex.com", "subject": "Demo", "body": "interested", "received_at": "2026-06-20T11:00:00"},
    ])

    app = FastAPI()
    app.include_router(connect_mod.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}
    c = TestClient(app); c.db = db  # type: ignore[attr-defined]
    return c


def _data(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_gmail_registered(client):
    assert any(p["id"] == "gmail" and p["kind"] == "email" for p in _data(client.get("/v1/connect/status"))["providers"])


def test_gmail_requires_email_account(client):
    r = client.post("/v1/connect/gmail/token", json={"token": "apppassword"})  # no account
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "missing_account"


def test_gmail_connect_and_sync_into_mailbox_idempotently(client):
    conn = _data(client.post("/v1/connect/gmail/token", json={"token": "app-pw-16", "account": "me@gmail.com"}))["connection"]
    assert conn["external_account"] == "me@gmail.com"

    first = _data(client.post("/v1/connect/gmail/sync", json={"connection_id": conn["id"]}))
    assert first["messages_added"] == 2
    msgs = client.db.tables["mail_messages"]
    assert {m["from_addr"] for m in msgs} == {"dana@acme.com", "lee@globex.com"}
    assert all(m["triaged"] is False and m["status"] == "unread" for m in msgs)   # ready for Support triage

    second = _data(client.post("/v1/connect/gmail/sync", json={"connection_id": conn["id"]}))
    assert second["messages_added"] == 0   # idempotent on Message-ID
