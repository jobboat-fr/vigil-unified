"""Notion connector — syncs the integration's shared pages into `commitments`
(source='notion'), idempotent on the Notion page id, so the Operations digest counts
real tasks. A page that reads "done" closes its commitment.

Hermetic: Notion HTTP (`_get`/`_post`) is monkeypatched with canned payloads; the
real title-extraction, done-detection, idempotency, and DB mapping run against a fake DB.
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
from winny_gateway.integrations import notion as notion_mod
from winny_gateway.routes.vigil import connect as connect_mod


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


def _title(text):
    return {"Name": {"type": "title", "title": [{"plain_text": text}]}}


# search payload: one open todo, one with a "Done" status, one archived
_PAGES = {
    "results": [
        {"id": "p1", "archived": False, "properties": _title("Ship the launch page")},
        {"id": "p2", "archived": False, "properties": {
            **_title("Old migration"),
            "Status": {"type": "status", "status": {"name": "Done"}},
        }},
        {"id": "p3", "archived": True, "properties": _title("Archived idea")},
    ]
}


async def _fake_get(_token, path):
    if path.endswith("/users/me"):
        return {"id": "bot1", "bot": {"workspace_name": "Acme HQ"}}
    return {}


async def _fake_post(_token, path, body):
    if path.endswith("/search"):
        return _PAGES
    return {}


@pytest.fixture
def client(monkeypatch):
    db = FakeDB()
    for mod in (conn_mod, notion_mod, db_mod):
        monkeypatch.setattr(mod, "db_insert", db.insert, raising=False)
        monkeypatch.setattr(mod, "db_select", db.select, raising=False)
        monkeypatch.setattr(mod, "db_update", db.update, raising=False)
        monkeypatch.setattr(mod, "db_delete", db.delete, raising=False)
    monkeypatch.setattr(notion_mod, "_get", _fake_get)
    monkeypatch.setattr(notion_mod, "_post", _fake_post)

    app = FastAPI()
    app.include_router(connect_mod.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "u1", "email": "a@x.com"}
    c = TestClient(app)
    c.db = db  # type: ignore[attr-defined]
    return c


def _data(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_notion_registered_as_tasks(client):
    assert any(p["id"] == "notion" and p["kind"] == "tasks"
               for p in _data(client.get("/v1/connect/status"))["providers"])


def test_sync_creates_open_commitments_idempotently(client):
    conn = _data(client.post("/v1/connect/notion/token", json={"token": "secret_abc"}))["connection"]
    assert conn["external_account"] == "Acme HQ"

    first = _data(client.post("/v1/connect/notion/sync", json={"connection_id": conn["id"]}))
    # p1 → open commitment; p2 (Done) and p3 (archived) → skipped
    assert first["added"] == 1
    commits = client.db.tables["commitments"]
    assert len(commits) == 1
    assert commits[0]["text"] == "Ship the launch page"
    assert commits[0]["source"] == "notion" and commits[0]["external_id"] == "p1"
    assert commits[0]["org_id"] == "u1" and commits[0]["status"] == "open"

    second = _data(client.post("/v1/connect/notion/sync", json={"connection_id": conn["id"]}))
    assert second["added"] == 0                 # idempotent on the page id
    assert len(client.db.tables["commitments"]) == 1


def test_done_page_closes_existing_commitment(client, monkeypatch):
    conn = _data(client.post("/v1/connect/notion/token", json={"token": "secret_abc"}))["connection"]
    client.post("/v1/connect/notion/sync", json={"connection_id": conn["id"]})
    assert client.db.tables["commitments"][0]["status"] == "open"

    # Next sync: p1 now reads Done → its commitment should close.
    async def now_done(_token, path, body):
        return {"results": [{"id": "p1", "archived": False, "properties": {
            **_title("Ship the launch page"),
            "Done": {"type": "checkbox", "checkbox": True},
        }}]}
    monkeypatch.setattr(notion_mod, "_post", now_done)
    out = _data(client.post("/v1/connect/notion/sync", json={"connection_id": conn["id"]}))
    assert out["closed"] == 1
    assert client.db.tables["commitments"][0]["status"] == "done"
