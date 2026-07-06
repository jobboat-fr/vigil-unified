"""Stripe billing — checkout provisioning, webhook → subscriptions, fail-closed.

The revenue-path invariant: a completed checkout MUST change what
``ops.billing.tenant_plan`` resolves (org_members → subscriptions.plan_tier),
because that's what quotas and feature gates read. The old implementation
wrote ``user_preferences.tier`` + an in-memory dict — a customer could pay and
their plan wouldn't change. These tests pin the bridge.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from winny_gateway.auth import get_current_user
from winny_gateway.ops import billing as ops_billing_mod
from winny_gateway.routes import billing as billing_routes


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
        hits = [r for r in self._t(table) if self._m(r, filters)]
        for r in hits: r.update(data)
        return [dict(r) for r in hits]
    async def upsert(self, table, data, *, on_conflict="user_id", **_k):
        keys = [k.strip() for k in on_conflict.split(",")]
        for r in self._t(table):
            if all(r.get(k) == data.get(k) for k in keys):
                r.update(data); return dict(r)
        return await self.insert(table, data)


@pytest.fixture
def client(monkeypatch):
    db = FakeDB()
    for mod in (billing_routes, ops_billing_mod):
        monkeypatch.setattr(mod, "db_insert", db.insert, raising=False)
        monkeypatch.setattr(mod, "db_select", db.select, raising=False)
        monkeypatch.setattr(mod, "db_update", db.update, raising=False)
        monkeypatch.setattr(mod, "db_upsert", db.upsert, raising=False)
    # No Stripe key → dev-mock checkout; observable plan default is 'free' so
    # upgrades/downgrades are visible through tenant_plan.
    monkeypatch.setattr(billing_routes, "STRIPE_SECRET_KEY", "")
    monkeypatch.setattr(billing_routes, "STRIPE_WEBHOOK_SECRET", "")
    monkeypatch.delenv("WW_ENV", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.setenv("DEFAULT_OPS_PLAN", "free")
    app = FastAPI()
    app.include_router(billing_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "u1", "email": "buyer@example.com"}
    c = TestClient(app); c.db = db  # type: ignore[attr-defined]
    return c


def test_mock_checkout_provisions_subscription_and_changes_tenant_plan(client):
    # Before: no org, plan resolves to the env default.
    import asyncio
    assert asyncio.get_event_loop().run_until_complete(ops_billing_mod.tenant_plan("u1")) == "free"

    r = client.post("/api/v1/billing/checkout", json={"tier": "starter"})
    assert r.status_code == 200 and r.json()["ok"]

    # Org + membership auto-provisioned; subscription row active on starter.
    subs = client.db.tables.get("subscriptions", [])
    assert len(subs) == 1
    assert subs[0]["plan_tier"] == "starter" and subs[0]["status"] == "active"
    assert subs[0]["provider"] == "stripe" and subs[0]["product_code"] == "vigil"
    members = client.db.tables.get("org_members", [])
    assert members and members[0]["user_id"] == "u1" and members[0]["role"] == "owner"
    assert subs[0]["org_id"] == members[0]["org_id"]

    # THE invariant: tenant_plan now resolves the paid tier.
    assert asyncio.get_event_loop().run_until_complete(ops_billing_mod.tenant_plan("u1")) == "starter"


def test_webhook_checkout_completed_provisions(client):
    org_id = str(uuid.uuid4())
    r = client.post("/api/v1/billing/webhook", json={
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_123", "subscription": "sub_123", "customer": "cus_123",
            "metadata": {"user_id": "u1", "org_id": org_id, "tier": "pro"},
        }},
    })
    assert r.status_code == 200
    subs = client.db.tables.get("subscriptions", [])
    assert len(subs) == 1 and subs[0]["external_id"] == "sub_123"
    assert subs[0]["plan_tier"] == "pro" and subs[0]["org_id"] == org_id
    # Legacy lite/pro flag kept in sync.
    prefs = client.db.tables.get("user_preferences", [])
    assert prefs and prefs[0]["tier"] == "pro"


def test_webhook_subscription_deleted_downgrades(client):
    org_id = str(uuid.uuid4())
    meta = {"user_id": "u1", "org_id": org_id, "tier": "pro"}
    client.post("/api/v1/billing/webhook", json={
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_1", "subscription": "sub_1", "customer": "cus_1", "metadata": meta}},
    })
    r = client.post("/api/v1/billing/webhook", json={
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_1", "status": "canceled", "customer": "cus_1", "metadata": meta}},
    })
    assert r.status_code == 200
    subs = client.db.tables["subscriptions"]
    assert len(subs) == 1  # upsert keyed on (provider, external_id), no dupes
    assert subs[0]["status"] == "canceled"
    prefs = client.db.tables.get("user_preferences", [])
    assert prefs and prefs[0]["tier"] == "lite"


def test_webhook_fails_closed_in_production_without_secret(client, monkeypatch):
    monkeypatch.setenv("WW_ENV", "production")
    r = client.post("/api/v1/billing/webhook", json={"type": "checkout.session.completed", "data": {"object": {}}})
    assert r.status_code == 503
    assert not client.db.tables.get("subscriptions")


def test_checkout_rejects_unknown_tier(client):
    r = client.post("/api/v1/billing/checkout", json={"tier": "enterprise"})
    assert r.status_code == 400
