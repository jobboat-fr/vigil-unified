"""Cross-tenant isolation — the crown-jewel security property of the multi-tenant
ops surface. Proves at the route layer (defense-in-depth on top of Supabase RLS)
that tenant B can never see or act on tenant A's departments, tasks, or queued
outbound actions. A regression guard for the class of bug that once leaked an
owner's data across tenants.

Hermetic: fake DB + a switchable auth identity.
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
from winny_gateway.integrations import github as _gh  # noqa: F401 — registers a connector w/ an action
from winny_gateway.ops import cos as cos_mod
from winny_gateway.ops import engine as engine_mod
from winny_gateway.ops import finance as finance_mod
from winny_gateway.routes.vigil import connect as connect_mod
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
        if order_by:
            rows.sort(key=lambda r: r.get(order_by.lstrip("-")) or "", reverse=order_by.startswith("-"))
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


_ALL = [ops_mod, engine_mod, finance_mod, cos_mod, conn_mod, connect_mod, db_mod]


@pytest.fixture
def ctx(monkeypatch):
    db = FakeDB()
    for mod in _ALL:
        monkeypatch.setattr(mod, "db_insert", db.insert, raising=False)
        monkeypatch.setattr(mod, "db_select", db.select, raising=False)
        monkeypatch.setattr(mod, "db_update", db.update, raising=False)
        monkeypatch.setattr(mod, "db_delete", db.delete, raising=False)

    who = {"user": {"sub": "A", "email": "a@x.com"}}
    app = FastAPI()
    app.include_router(ops_mod.router)
    app.include_router(connect_mod.router)
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    client = TestClient(app)
    return client, db, who


def _data(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _as(who, sub):
    who["user"] = {"sub": sub, "email": f"{sub}@x.com"}


def test_tenant_b_cannot_see_or_act_on_tenant_a(ctx):
    client, db, who = ctx

    # ── Tenant A: seed departments, run a finance report (creates an A task) ──
    _as(who, "A")
    depts_a = {d["slug"]: d for d in _data(client.get("/v1/ops/departments"))["departments"]}
    a_finance = depts_a["finance"]["id"]
    a_task = _data(client.post(f"/v1/ops/departments/{a_finance}/run", json={"job": "report"}))["task"]
    a_task_id = a_task["id"]
    assert a_task["status"] == "done"

    # ── Tenant B: gets its OWN departments, never A's data ──
    _as(who, "B")
    depts_b = {d["slug"]: d for d in _data(client.get("/v1/ops/departments"))["departments"]}
    b_dept_ids = {d["id"] for d in depts_b.values()}
    assert a_finance not in b_dept_ids                        # A's dept id is not B's
    assert _data(client.get("/v1/ops/tasks"))["tasks"] == []  # B sees none of A's tasks

    # B cannot reach A's department, task, or run it
    assert client.get(f"/v1/ops/departments/{a_finance}").status_code == 404
    assert client.get(f"/v1/ops/tasks/{a_task_id}").status_code == 404
    assert client.post(f"/v1/ops/departments/{a_finance}/run", json={"job": "report"}).status_code == 404

    # ── Outbound action isolation ──
    _as(who, "A")
    db._t("connections").append({
        "id": "connA", "user_id": "A", "provider": "github", "kind": "engineering",
        "access_token_enc": "", "status": "active",
    })
    action = _data(client.post("/v1/connect/actions", json={
        "connection_id": "connA", "action": "create_issue",
        "params": {"repo": "a/b", "title": "x"},
    }))["action"]
    a_action_id = action["id"]

    _as(who, "B")
    assert _data(client.get("/v1/connect/actions"))["actions"] == []          # B sees no A actions
    assert client.post(f"/v1/connect/actions/{a_action_id}/approve").status_code == 404  # can't execute
    assert client.post(f"/v1/connect/actions/{a_action_id}/reject").status_code == 404

    # And A's action is still pending (B's reject didn't touch it)
    _as(who, "A")
    assert _data(client.get("/v1/connect/actions"))["actions"][0]["status"] == "pending"
