"""Tests for the P2 departments + the cross-department team mechanics:

  • Finance accountant report — numbers computed deterministically; acceptance is an
    arithmetic invariant (category sums reconcile to net).
  • Legal — grounded in the Vault; accepted only when it cites REAL documents.
  • Lead Scout → Revenue handoff — the team: scouting a lead drafts the outreach.
  • Operations — deterministic open-items digest.
  • Chief of Staff — routes the whole company via handoffs; compiles a brief.

Hermetic: fake DB + overridden auth + stubbed council functions.
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
from winny_gateway.ops import cos as cos_mod
from winny_gateway.ops import engine as engine_mod
from winny_gateway.ops import finance as finance_mod
from winny_gateway.ops import growth as growth_mod
from winny_gateway.ops import legal as legal_mod
from winny_gateway.ops import operations as ops_dept_mod
from winny_gateway.ops import revenue as revenue_mod
from winny_gateway.ops import support as support_mod
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


_ALL = [ops_mod, engine_mod, support_mod, finance_mod, revenue_mod,
        growth_mod, legal_mod, ops_dept_mod, cos_mod, fc, db_mod]


@pytest.fixture
def client(monkeypatch):
    db = FakeDB()
    for mod in _ALL:
        monkeypatch.setattr(mod, "db_insert", db.insert, raising=False)
        monkeypatch.setattr(mod, "db_select", db.select, raising=False)
        monkeypatch.setattr(mod, "db_update", db.update, raising=False)
        monkeypatch.setattr(mod, "db_delete", db.delete, raising=False)

    async def classify(_t): return ("software", 0.001)
    async def narrate(_f): return ("Commentary.", 0.001)
    async def enrich(_c): return ({"company": "Acme", "title": "CTO", "score": 70, "why": "good fit"}, 0.001)
    async def draft(_d, _c): return ("Hi, following up.", 0.001)
    async def brief_narrate(_r): return ("All systems healthy.", 0.001)
    monkeypatch.setattr(finance_mod, "classify_txn", classify)
    monkeypatch.setattr(finance_mod, "narrate", narrate)
    monkeypatch.setattr(growth_mod, "enrich", enrich)
    monkeypatch.setattr(revenue_mod, "draft_followup", draft)
    monkeypatch.setattr(cos_mod, "brief_narrate", brief_narrate)

    app = FastAPI()
    app.include_router(ops_mod.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "u1", "email": "a@x.com"}
    c = TestClient(app)
    c.db = db  # type: ignore[attr-defined]
    return c


def _data(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _dept(client, slug):
    return next(d for d in _data(client.get("/v1/ops/departments"))["departments"] if d["slug"] == slug)


def test_full_roster_seeds_with_jobs(client):
    depts = {d["slug"]: d for d in _data(client.get("/v1/ops/departments"))["departments"]}
    assert set(depts) == {"support", "finance", "revenue", "growth", "legal", "operations", "cos"}
    assert depts["finance"]["jobs"] == ["reconcile", "report", "analyze"]
    assert depts["cos"]["primary_job"] == "route"


def test_finance_report_reconciles(client):
    for i, (amt, cat) in enumerate([(1000.0, "revenue"), (-300.0, "software"), (-200.0, "office")]):
        client.db._t("finance_transactions").append({"id": f"t{i}", "user_id": "u1", "amount": amt, "category": cat, "status": "reconciled"})
    did = _dept(client, "finance")["id"]
    task = _data(client.post(f"/v1/ops/departments/{did}/run", json={"job": "report"}))["task"]
    assert task["status"] == "done" and task["accepted"] is True  # arithmetic invariant held


def test_finance_analyze_computes_runway_and_valuation(client):
    for i, (amt, mo) in enumerate([(1000.0, "01"), (-400.0, "01"), (300.0, "02"), (-500.0, "02"), (200.0, "03")]):
        client.db._t("finance_transactions").append({
            "id": f"t{i}", "user_id": "u1", "amount": amt, "category": "x",
            "status": "reconciled", "txn_date": f"2026-{mo}-10", "metadata": {},
        })
    did = _dept(client, "finance")["id"]
    task = _data(client.post(f"/v1/ops/departments/{did}/run", json={"job": "analyze"}))["task"]
    assert task["status"] == "done" and task["accepted"] is True   # monthly series reconciles to net cash


def test_finance_report_acceptance_rejects_mismatch():
    import asyncio
    bad = {"figures": {"pnl": {"net_income": 500, "by_category": {"a": 100, "b": 100}}}}  # sums to 200, not 500
    verdict = asyncio.run(finance_mod.report_acceptance("u1", {}, bad))
    assert verdict["accepted"] is False


def test_legal_requires_real_citations(client, monkeypatch):
    client.db._t("vault_documents").append({"id": "vd1", "user_id": "u1", "title": "NDA", "summary": "mutual nda", "extracted_text": "x"})
    did = _dept(client, "legal")["id"]

    async def grounded(_q, _ctx): return ("Risk in the NDA [doc:vd1].", ["vd1"], 0.001)
    monkeypatch.setattr(legal_mod, "review", grounded)
    task = _data(client.post(f"/v1/ops/departments/{did}/run", json={"job": "review"}))["task"]
    assert task["accepted"] is True

    async def ungrounded(_q, _ctx): return ("Generic advice [doc:made-up].", ["made-up"], 0.001)
    monkeypatch.setattr(legal_mod, "review", ungrounded)
    task2 = _data(client.post(f"/v1/ops/departments/{did}/run", json={"job": "review"}))["task"]
    assert task2["accepted"] is False  # cited a non-existent document → ungrounded


def test_legal_precedent_board_stores_and_feeds_back(client, monkeypatch):
    client.db._t("vault_documents").append({"id": "vd1", "user_id": "u1", "title": "NDA", "summary": "mutual nda", "extracted_text": "x"})
    did = _dept(client, "legal")["id"]
    seen_context: list[str] = []

    async def grounded(_q, ctx):
        seen_context.append(ctx)
        return ("Auto-renewal risk [doc:vd1].", ["vd1"], 0.001)
    monkeypatch.setattr(legal_mod, "review", grounded)

    # First review → stores a precedent
    client.post(f"/v1/ops/departments/{did}/run", json={"job": "review"})
    assert len(client.db.tables["legal_precedents"]) == 1
    # Second review → the prior finding is fed into the context (cross-engagement learning)
    client.post(f"/v1/ops/departments/{did}/run", json={"job": "review"})
    assert "Prior findings (precedent board" in seen_context[-1]


def test_legal_multipass_blocks_low_confidence(client, monkeypatch):
    client.db._t("vault_documents").append({"id": "vd1", "user_id": "u1", "title": "NDA", "summary": "x", "extracted_text": "x"})
    did = _dept(client, "legal")["id"]

    async def grounded(_q, _ctx): return ("Risk [doc:vd1].", ["vd1"], 0.001)
    async def doubt(_memo, _ctx): return ({"confidence": 0.2, "flags": ["clause overstated"]}, 0.001)
    monkeypatch.setattr(legal_mod, "review", grounded)
    monkeypatch.setattr(legal_mod, "verify", doubt)

    task = _data(client.post(f"/v1/ops/departments/{did}/run", json={"job": "review"}))["task"]
    assert task["accepted"] is False    # grounded, but the verification pass flagged it → blocked


def test_legal_vacuous_when_no_documents(client):
    did = _dept(client, "legal")["id"]
    task = _data(client.post(f"/v1/ops/departments/{did}/run", json={"job": "review"}))["task"]
    assert task["accepted"] is True  # nothing to ground in yet


def test_lead_scout_hands_off_to_revenue(client):
    # two inbound senders not yet in the CRM
    client.db._t("mail_messages").extend([
        {"id": "m1", "user_id": "u1", "from_addr": "dana@acme.com", "from_name": "Dana", "subject": "pricing?"},
        {"id": "m2", "user_id": "u1", "from_addr": "lee@globex.com", "from_name": "Lee", "subject": "demo"},
    ])
    did = _dept(client, "growth")["id"]
    task = _data(client.post(f"/v1/ops/departments/{did}/run", json={"job": "scout"}))["task"]
    assert task["accepted"] is True
    # leads + proposal-stage deals created
    assert len(client.db.tables["crm_contacts"]) == 2
    assert all(d["stage"] == "proposal" for d in client.db.tables["crm_deals"])
    # THE TEAM: Revenue ran via handoff and drafted outreach for the new deals
    drafts = client.db.tables.get("mail_drafts", [])
    deal_ids = {d["id"] for d in client.db.tables["crm_deals"]}
    drafted_for = {d["metadata"]["deal_id"] for d in drafts}
    assert drafted_for == deal_ids


def test_operations_digest_reconciles(client):
    client.db._t("commitments").extend([
        {"id": "c1", "org_id": "u1", "status": "open", "text": "ship"},
        {"id": "c2", "org_id": "u1", "status": "done", "text": "done"},
    ])
    did = _dept(client, "operations")["id"]
    task = _data(client.post(f"/v1/ops/departments/{did}/run", json={"job": "digest"}))["task"]
    assert task["accepted"] is True


def test_chief_of_staff_routes_the_whole_company(client):
    did = _dept(client, "cos")["id"]
    task = _data(client.post(f"/v1/ops/departments/{did}/run", json={"job": "route"}))["task"]
    assert task["accepted"] is True
    # tasks were created for the routed operational departments
    depts = {d["id"]: d["slug"] for d in _data(client.get("/v1/ops/departments"))["departments"]}
    ran_slugs = {depts.get(t["department_id"]) for t in client.db.tables["ops_tasks"]}
    assert {"support", "finance", "revenue", "growth", "legal", "operations"} <= ran_slugs


def test_chief_of_staff_brief(client):
    did = _dept(client, "cos")["id"]
    task = _data(client.post(f"/v1/ops/departments/{did}/run", json={"job": "brief"}))["task"]
    assert task["accepted"] is True and task["output_artifact_id"]
