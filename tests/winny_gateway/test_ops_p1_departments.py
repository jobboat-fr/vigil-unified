"""Tests for the P1 departments — Finance (reconcile) and Revenue (follow-ups).

Same hermetic discipline as the Support slice: fake DB + overridden auth + stubbed
council. Proves each department's contract end-to-end: dispatch → work → artifact →
deterministic acceptance → selftest marks it live.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import winny_gateway.db as db_mod
from winny_gateway.auth import get_current_user
from winny_gateway.integrations import finance_connect as fc
from winny_gateway.ops import engine as engine_mod
from winny_gateway.ops import finance as finance_mod
from winny_gateway.ops import revenue as revenue_mod
from winny_gateway.ops import support as support_mod
from winny_gateway.routes.vigil import ops as ops_mod


class FakeDB:
    def __init__(self): self.tables: dict[str, list[dict[str, Any]]] = {}
    def _t(self, n): return self.tables.setdefault(n, [])
    @staticmethod
    def _m(r, f): return all(r.get(k) == v for k, v in (f or {}).items())

    async def insert(self, table, data, **_k):
        row = dict(data); row.setdefault("id", str(uuid.uuid4()))
        row.setdefault("created_at", "2026-01-01T00:00:00Z")
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


@pytest.fixture
def client(monkeypatch):
    db = FakeDB()
    for mod in (ops_mod, engine_mod, support_mod, finance_mod, revenue_mod, fc, db_mod):
        monkeypatch.setattr(mod, "db_insert", db.insert, raising=False)
        monkeypatch.setattr(mod, "db_select", db.select, raising=False)
        monkeypatch.setattr(mod, "db_update", db.update, raising=False)
        monkeypatch.setattr(mod, "db_delete", db.delete, raising=False)

    async def fake_classify(_txn): return ("software", 0.002)
    async def fake_draft(_deal, _contact): return ("Hi, just following up.", 0.002)
    monkeypatch.setattr(finance_mod, "classify_txn", fake_classify)
    monkeypatch.setattr(revenue_mod, "draft_followup", fake_draft)

    app = FastAPI()
    app.include_router(ops_mod.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "user-1", "email": "a@x.com"}
    c = TestClient(app)
    c.db = db  # type: ignore[attr-defined]
    return c


def _data(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _dept_id(client, slug: str) -> str:
    depts = _data(client.get("/v1/ops/departments"))["departments"]
    return next(d["id"] for d in depts if d["slug"] == slug)


def test_all_three_departments_seed(client):
    slugs = {d["slug"] for d in _data(client.get("/v1/ops/departments"))["departments"]}
    assert {"support", "finance", "revenue"} <= slugs


def test_finance_reconciles_pending_transactions(client):
    for i in range(3):
        client.db._t("finance_transactions").append({
            "id": f"t{i}", "user_id": "user-1", "amount": -10.0 * (i + 1),
            "description": f"vendor {i}", "status": "uncategorized", "metadata": {},
        })
    did = _dept_id(client, "finance")
    task = _data(client.post(f"/v1/ops/departments/{did}/run", json={"job": "reconcile"}))["task"]
    assert task["status"] == "done" and task["accepted"] is True
    txns = client.db.tables["finance_transactions"]
    assert all(t["status"] == "reconciled" and t["category"] == "software" for t in txns)


def test_finance_flags_large_amounts(client):
    client.db._t("finance_transactions").append({
        "id": "big", "user_id": "user-1", "amount": -9000.0, "description": "wire",
        "status": "uncategorized", "metadata": {},
    })
    did = _dept_id(client, "finance")
    task = _data(client.post(f"/v1/ops/departments/{did}/run", json={"job": "reconcile"}))["task"]
    assert task["accepted"] is True
    flagged = client.db.tables["finance_transactions"][0]
    assert flagged["metadata"].get("anomaly")


def test_finance_selftest_marks_live(client):
    did = _dept_id(client, "finance")
    task = _data(client.post(f"/v1/ops/departments/{did}/selftest"))["task"]
    assert task["accepted"] is True
    assert _data(client.get(f"/v1/ops/departments/{did}"))["status"] == "live"


def test_revenue_drafts_followups_for_stalled_deals(client):
    client.db._t("crm_contacts").append({"id": "c1", "user_id": "user-1", "name": "Dana", "email": "d@x.com"})
    client.db._t("crm_deals").extend([
        {"id": "d1", "user_id": "user-1", "title": "Acme", "stage": "proposal", "contact_id": "c1"},
        {"id": "d2", "user_id": "user-1", "title": "Globex", "stage": "negotiation", "contact_id": None},
        {"id": "d3", "user_id": "user-1", "title": "Won Co", "stage": "won", "contact_id": None},
    ])
    did = _dept_id(client, "revenue")
    task = _data(client.post(f"/v1/ops/departments/{did}/run", json={"job": "follow_up"}))["task"]
    assert task["status"] == "done" and task["accepted"] is True
    drafts = client.db.tables["mail_drafts"]
    deal_ids = {d["metadata"]["deal_id"] for d in drafts}
    assert deal_ids == {"d1", "d2"}            # stalled deals only; the won deal is skipped
    assert any(d["to_addrs"] == ["d@x.com"] for d in drafts)  # contact email wired in

    # idempotent: a second run drafts nothing new
    again = _data(client.post(f"/v1/ops/departments/{did}/run", json={"job": "follow_up"}))["task"]
    assert again["accepted"] is True
    assert len(client.db.tables["mail_drafts"]) == 2
