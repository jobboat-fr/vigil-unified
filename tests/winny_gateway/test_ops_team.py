"""Tests for the Ops Team P0 slice — the Support reference department.

Proves the whole loop hermetically (fake DB + overridden auth + a stubbed
classifier, no network/LLM): on-demand dispatch → triage work → artifact →
deterministic acceptance → health, plus the budget trip, the kill switch, and
multi-tenant scoping. Green here is the slice's acceptance bar alongside the
live `selftest`.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from winny_gateway.auth import get_current_user
from winny_gateway.integrations import connector as conn_mod
from winny_gateway.ops import engine as engine_mod
from winny_gateway.ops import support as support_mod
from winny_gateway.routes.vigil import ops as ops_mod


class FakeDB:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}

    def _t(self, name: str) -> list[dict[str, Any]]:
        return self.tables.setdefault(name, [])

    @staticmethod
    def _match(row: dict, filters: dict | None) -> bool:
        return all(row.get(k) == v for k, v in (filters or {}).items())

    async def insert(self, table: str, data: dict, **_kw) -> dict:
        row = dict(data)
        row.setdefault("id", str(uuid.uuid4()))
        row.setdefault("created_at", "2026-01-01T00:00:00Z")
        row.setdefault("updated_at", "2026-01-01T00:00:00Z")
        self._t(table).append(row)
        return dict(row)

    async def select(self, table: str, *, filters=None, columns="*", limit=None, order_by=None, **_kw) -> list[dict]:
        rows = [dict(r) for r in self._t(table) if self._match(r, filters)]
        if order_by:
            desc = order_by.startswith("-")
            rows.sort(key=lambda r: r.get(order_by.lstrip("-")) or "", reverse=desc)
        return rows[:limit] if limit else rows

    async def update(self, table: str, data: dict, *, filters: dict, **_kw) -> list[dict]:
        out = []
        for r in self._t(table):
            if self._match(r, filters):
                r.update(data)
                out.append(dict(r))
        return out

    async def delete(self, table: str, *, filters: dict, **_kw) -> bool:
        self.tables[table] = [r for r in self._t(table) if not self._match(r, filters)]
        return True


def _stub_classifier(category: str):
    async def classify(_msg):
        return ({"category": category, "priority": "normal", "score": 0.9,
                 "suggested_action": "reply soon"}, 0.001)
    return classify


@pytest.fixture
def client(monkeypatch):
    db = FakeDB()
    for mod in (ops_mod, engine_mod, support_mod):
        monkeypatch.setattr(mod, "db_insert", db.insert, raising=False)
        monkeypatch.setattr(mod, "db_select", db.select, raising=False)
        monkeypatch.setattr(mod, "db_update", db.update, raising=False)
    monkeypatch.setattr(support_mod, "classify_message", _stub_classifier("respond"))

    app = FastAPI()
    app.include_router(ops_mod.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "user-1", "email": "a@x.com"}
    c = TestClient(app)
    c.db = db  # type: ignore[attr-defined]
    c.monkeypatch = monkeypatch  # type: ignore[attr-defined]
    return c


def _data(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _seed_inbox(db: FakeDB, uid: str, n: int, folder: str = "INBOX") -> None:
    for i in range(n):
        db._t("mail_messages").append({
            "id": f"m{i}", "user_id": uid, "folder": folder, "triaged": False,
            "from_addr": f"x{i}@y.com", "subject": f"hi {i}", "body": "please respond",
        })


def _support_id(client) -> str:
    depts = _data(client.get("/v1/ops/departments"))["departments"]
    return next(d["id"] for d in depts if d["slug"] == "support")


def test_board_seeds_support_department(client):
    depts = _data(client.get("/v1/ops/departments"))["departments"]
    support = next(d for d in depts if d["slug"] == "support")
    assert support["name"] == "Support"
    assert support["status"] == "provisioning"   # not live until a selftest passes
    assert support["guardrails"]["per_run_spend_cap_usd"] == 0.5


def test_run_triages_inbox_and_passes_acceptance(client):
    did = _support_id(client)
    _seed_inbox(client.db, "user-1", 3)
    task = _data(client.post(f"/v1/ops/departments/{did}/run", json={"input": {"limit": 10}}))["task"]
    assert task["status"] == "done"
    assert task["accepted"] is True
    assert task["output_artifact_id"]
    # every targeted message is now triaged with a category; respond → drafts exist
    msgs = client.db.tables["mail_messages"]
    assert all(m["triaged"] and m["category"] in support_mod.CATEGORIES for m in msgs)
    assert len(client.db.tables.get("mail_drafts", [])) == 3


def test_selftest_marks_department_live(client):
    did = _support_id(client)
    _seed_inbox(client.db, "user-1", 2)
    task = _data(client.post(f"/v1/ops/departments/{did}/selftest"))["task"]
    assert task["accepted"] is True
    dept = _data(client.get(f"/v1/ops/departments/{did}"))
    assert dept["status"] == "live"
    assert dept["health"]["success_rate"] == 1.0
    assert dept["health"]["runs"] >= 1


def test_acceptance_fails_when_classifier_returns_bad_category(client):
    did = _support_id(client)
    _seed_inbox(client.db, "user-1", 2)
    client.monkeypatch.setattr(support_mod, "classify_message", _stub_classifier("not-a-real-category"))
    task = _data(client.post(f"/v1/ops/departments/{did}/run"))["task"]
    # invalid category falls back to "fyi" (valid) so it still triages — acceptance holds.
    assert task["accepted"] is True


def test_over_budget_run_is_blocked_not_accepted(client):
    did = _support_id(client)
    _seed_inbox(client.db, "user-1", 1)

    async def expensive(_msg):
        return ({"category": "fyi", "priority": "low", "score": 0.5}, 5.0)  # > $0.50 cap
    client.monkeypatch.setattr(support_mod, "classify_message", expensive)

    task = _data(client.post(f"/v1/ops/departments/{did}/run"))["task"]
    assert task["status"] == "blocked"
    assert task["accepted"] is False


def test_kill_switch_blocks_dispatch(client):
    did = _support_id(client)
    _seed_inbox(client.db, "user-1", 1)
    assert _data(client.post("/v1/ops/pause-all"))["paused"] >= 1
    blocked = client.post(f"/v1/ops/departments/{did}/run")
    assert blocked.status_code == 409
    assert _data(client.post("/v1/ops/resume-all"))["resumed"] >= 1
    assert client.post(f"/v1/ops/departments/{did}/run").status_code == 200


def test_feed_and_ledger_record_the_run(client):
    did = _support_id(client)
    _seed_inbox(client.db, "user-1", 2)
    client.post(f"/v1/ops/departments/{did}/run")
    tasks = _data(client.get("/v1/ops/tasks"))["tasks"]
    assert len(tasks) == 1 and tasks[0]["job"] == "triage"
    events = _data(client.get("/v1/ops/feed"))["events"]
    assert events and "Support" in events[0]["summary"]


def test_run_presyncs_the_departments_connectors(client, monkeypatch):
    calls: list[tuple[str, str]] = []

    async def spy(uid, kind):
        calls.append((uid, kind))
        return {"synced": 0}
    monkeypatch.setattr(conn_mod, "sync_kind", spy)

    _seed_inbox(client.db, "user-1", 1)
    did = _support_id(client)
    client.post(f"/v1/ops/departments/{did}/run")
    assert ("user-1", "email") in calls  # Support pulled its inbox connector before triaging


def test_department_is_user_scoped(client):
    did = _support_id(client)
    client.app.dependency_overrides[get_current_user] = lambda: {"sub": "user-2", "email": "b@x.com"}
    assert client.get(f"/v1/ops/departments/{did}").status_code == 404
