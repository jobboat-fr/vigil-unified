"""Brand-voice QA gate on Revenue's outbound send-proposal.

The draft is always created; only the agent's autonomous gmail.send PROPOSAL is
gated. Off-brand copy → draft exists, no send queued. On-brand copy → send proposed
(pending human approval, as always).

Hermetic: fake DB + Gmail connector registered + draft/brand_qa monkeypatched.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

import winny_gateway.integrations.connector as conn_mod
import winny_gateway.integrations.gmail as _gmail  # noqa: F401 — registers the Gmail connector
from winny_gateway.ops import brand as brand_mod
from winny_gateway.ops import revenue as revenue_mod


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


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    for mod in (revenue_mod, conn_mod):
        monkeypatch.setattr(mod, "db_insert", d.insert, raising=False)
        monkeypatch.setattr(mod, "db_select", d.select, raising=False)
        monkeypatch.setattr(mod, "db_update", d.update, raising=False)
        monkeypatch.setattr(mod, "db_delete", d.delete, raising=False)

    async def fixed_draft(_deal, _contact): return ("Hi — quick nudge on our proposal.", 0.0)
    monkeypatch.setattr(revenue_mod, "draft_followup", fixed_draft)

    d._t("connections").append({"id": "g1", "user_id": "u1", "provider": "gmail",
                                "kind": "email", "access_token_enc": "", "status": "active"})
    d._t("crm_contacts").append({"id": "ct1", "user_id": "u1", "name": "Dana",
                                 "email": "dana@acme.com", "company": "Acme"})
    return d


def test_offbrand_copy_is_not_proposed_but_draft_exists(db, monkeypatch):
    db._t("crm_deals").append({"id": "dl1", "user_id": "u1", "stage": "proposal",
                               "title": "Acme expansion", "contact_id": "ct1"})

    async def fail(_copy, **_k): return {"ok": False, "confidence": 0.0, "issues": ["too salesy"], "cost_usd": 0.0}
    monkeypatch.setattr(brand_mod, "brand_qa", fail)

    res = asyncio.run(revenue_mod.run("u1", {"limit": 25}))
    assert len(db.tables["mail_drafts"]) == 1                  # draft always created
    assert db.tables.get("outbound_actions", []) == []        # but no send proposed
    assert res["metrics"]["off_brand"] == 1 and res["metrics"]["proposed"] == 0


def test_onbrand_copy_is_proposed(db, monkeypatch):
    db._t("crm_deals").append({"id": "dl2", "user_id": "u1", "stage": "proposal",
                               "title": "Globex pilot", "contact_id": "ct1"})

    async def ok(_copy, **_k): return {"ok": True, "confidence": 1.0, "issues": [], "cost_usd": 0.0}
    monkeypatch.setattr(brand_mod, "brand_qa", ok)

    res = asyncio.run(revenue_mod.run("u1", {"limit": 25}))
    assert len(db.tables["outbound_actions"]) == 1            # send proposed (pending approval)
    assert db.tables["outbound_actions"][0]["action"] == "send"
    assert res["metrics"]["proposed"] == 1 and res["metrics"]["off_brand"] == 0
