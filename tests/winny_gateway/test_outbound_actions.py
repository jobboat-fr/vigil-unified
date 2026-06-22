"""Outbound write-actions — owner-gated propose → approve → execute.

Proves the human-in-the-loop gate: proposing queues a PENDING action and never
executes; only approval runs the connector's `act`. Plus reject, unsupported action,
and tenant isolation. The connector's `act` is monkeypatched (no real GitHub).
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
    for mod in (conn_mod, db_mod):
        monkeypatch.setattr(mod, "db_insert", db.insert, raising=False)
        monkeypatch.setattr(mod, "db_select", db.select, raising=False)
        monkeypatch.setattr(mod, "db_update", db.update, raising=False)
        monkeypatch.setattr(mod, "db_delete", db.delete, raising=False)

    gh = conn_mod.get_connector("github")
    acted: list[tuple[str, dict]] = []

    async def verify(_t, _a=None): return {"external_account": "octocat"}
    async def act(action, params, conn, token):
        acted.append((action, params)); return {"issue_url": "https://github.com/o/r/issues/1", "number": 1}
    monkeypatch.setattr(gh, "verify_token", verify)
    monkeypatch.setattr(gh, "act", act)

    app = FastAPI()
    app.include_router(connect_mod.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}
    c = TestClient(app)
    c.db = db          # type: ignore[attr-defined]
    c.acted = acted    # type: ignore[attr-defined]
    return c


def _data(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _connect(client) -> str:
    return _data(client.post("/v1/connect/github/token", json={"token": "ghp_x"}))["connection"]["id"]


def test_propose_queues_pending_and_does_not_execute(client):
    cid = _connect(client)
    a = _data(client.post("/v1/connect/actions", json={"connection_id": cid, "action": "create_issue", "params": {"repo": "o/r", "title": "Bug"}}))["action"]
    assert a["status"] == "pending"
    assert client.acted == []   # the autonomous propose NEVER executes
    pending = _data(client.get("/v1/connect/actions?status=pending"))["actions"]
    assert len(pending) == 1


def test_approve_executes_through_the_connector(client):
    cid = _connect(client)
    aid = _data(client.post("/v1/connect/actions", json={"connection_id": cid, "action": "create_issue", "params": {"repo": "o/r", "title": "Bug"}}))["action"]["id"]
    out = _data(client.post(f"/v1/connect/actions/{aid}/approve"))["action"]
    assert out["status"] == "executed"
    assert out["result"]["issue_url"].endswith("/issues/1")
    assert client.acted == [("create_issue", {"repo": "o/r", "title": "Bug"})]
    # already executed → cannot approve again
    assert client.post(f"/v1/connect/actions/{aid}/approve").status_code == 409


def test_reject_does_not_execute(client):
    cid = _connect(client)
    aid = _data(client.post("/v1/connect/actions", json={"connection_id": cid, "action": "create_issue", "params": {"repo": "o/r", "title": "x"}}))["action"]["id"]
    assert _data(client.post(f"/v1/connect/actions/{aid}/reject"))["action"]["status"] == "rejected"
    assert client.acted == []


def test_unsupported_action_rejected(client):
    cid = _connect(client)
    r = client.post("/v1/connect/actions", json={"connection_id": cid, "action": "delete_everything", "params": {}})
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "unsupported_action"


def test_actions_are_tenant_scoped(client):
    cid = _connect(client)
    aid = _data(client.post("/v1/connect/actions", json={"connection_id": cid, "action": "create_issue", "params": {"repo": "o/r", "title": "x"}}))["action"]["id"]
    client.app.dependency_overrides[get_current_user] = lambda: {"sub": "u2"}
    assert client.post(f"/v1/connect/actions/{aid}/approve").status_code == 404
    assert _data(client.get("/v1/connect/actions"))["actions"] == []
