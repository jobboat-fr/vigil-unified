"""Ops Team commercial model — plans (mirrored from VIGIL), usage metering, and
plan quota gating on dispatch."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import winny_gateway.db as db_mod
from winny_gateway.auth import get_current_user
from winny_gateway.ops import billing as billing_mod
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
        out = [r.update(data) or dict(r) for r in self._t(table) if self._m(r, filters)]
        return [r for r in out if r]
    async def delete(self, table, *, filters, **_k):
        self.tables[table] = [r for r in self._t(table) if not self._m(r, filters)]; return True


@pytest.fixture
def client(monkeypatch):
    db = FakeDB()
    for mod in (ops_mod, billing_mod, db_mod):
        monkeypatch.setattr(mod, "db_insert", db.insert, raising=False)
        monkeypatch.setattr(mod, "db_select", db.select, raising=False)
        monkeypatch.setattr(mod, "db_update", db.update, raising=False)
        monkeypatch.setattr(mod, "db_delete", db.delete, raising=False)
    monkeypatch.delenv("DEFAULT_OPS_PLAN", raising=False)
    app = FastAPI()
    app.include_router(ops_mod.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}
    c = TestClient(app); c.db = db  # type: ignore[attr-defined]
    return c


def _data(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_plans_mirror_vigil_tiers():
    assert set(billing_mod.OPS_PLANS) == {"free", "starter", "pro", "team", "enterprise"}
    assert billing_mod.OPS_PLANS["pro"]["price_eur_cents"] == 4900       # €49, like VIGIL
    assert billing_mod.OPS_PLANS["free"]["write_actions"] is False
    assert billing_mod.OPS_PLANS["enterprise"]["ops_runs_per_day"] is None


def test_usage_summary_counts_todays_runs(client):
    today = billing_mod._today()
    for i in range(3):
        client.db._t("ops_tasks").append({"id": f"t{i}", "user_id": "u1", "cost_usd": 0.01, "created_at": f"{today}T10:0{i}:00Z"})
    data = _data(client.get("/v1/ops/usage"))
    assert data["plan"] == "pro"                 # default when no org subscription
    assert data["runs_today"] == 3
    assert data["daily_cap"] == 500 and data["remaining_today"] == 497


def test_run_blocked_when_over_quota(client, monkeypatch):
    async def over(_uid):
        return False, {"plan": "free", "daily_cap": 20, "runs_today": 20}
    monkeypatch.setattr(billing_mod, "check_run_quota", over)
    did = next(d["id"] for d in _data(client.get("/v1/ops/departments"))["departments"] if d["slug"] == "support")
    r = client.post(f"/v1/ops/departments/{did}/run")
    assert r.status_code == 429
    assert r.json()["detail"]["error"] == "quota_exceeded"


def test_check_run_quota_logic(client, monkeypatch):
    async def free_plan(_uid): return "free"
    monkeypatch.setattr(billing_mod, "tenant_plan", free_plan)
    today = billing_mod._today()
    for i in range(20):                          # free cap is 20/day
        client.db._t("ops_tasks").append({"id": f"t{i}", "user_id": "u1", "created_at": f"{today}T00:00:0{i % 10}Z"})
    allowed, summary = asyncio.run(billing_mod.check_run_quota("u1"))
    assert allowed is False and summary["plan"] == "free"
