"""Tests for the VIGIL × WinnyWoo gateway layer — Studio artifacts + Meeting
Rooms — covering exactly the surfaces this project added on top of Hermes:

  • blank-canvas creation and the canvas/tldraw round-trip persistence
    (the "save the board as you last left it" guarantee),
  • the Google-Meet → room transcript bridge (parse + dedupe),
  • the post-meeting summarize → artifact + commitments + CRM onboarding flow,
  • canvas brainstorm/diagram passthrough to the council,
  • multi-tenant scoping (one user can't read another's artifact),
  • the pure structurer/parser helpers.

The Supabase auth dependency is overridden and the DB layer is replaced with an
in-memory fake, so the suite is hermetic — no network, no Supabase, no LLM.
The council calls that would hit the HF router are monkeypatched to deterministic
fixtures, keeping these as route-logic tests rather than model tests.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from winny_gateway.auth import get_current_user
from winny_gateway.routes.vigil import rooms as rooms_mod
from winny_gateway.routes.vigil import studio as studio_mod


# ── In-memory DB fake matching winny_gateway.db's async signatures ──────────
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
            col = order_by.lstrip("-")
            rows.sort(key=lambda r: r.get(col) or "", reverse=desc)
        if limit:
            rows = rows[:limit]
        return rows

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


@pytest.fixture
def client(monkeypatch):
    db = FakeDB()
    for mod in (studio_mod, rooms_mod):
        monkeypatch.setattr(mod, "db_insert", db.insert)
        monkeypatch.setattr(mod, "db_select", db.select)
        monkeypatch.setattr(mod, "db_update", db.update)
        monkeypatch.setattr(mod, "db_delete", db.delete)

    app = FastAPI()
    app.include_router(studio_mod.router)
    app.include_router(rooms_mod.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "user-1", "email": "a@x.com", "role": "authenticated"
    }
    c = TestClient(app)
    c.db = db  # type: ignore[attr-defined]
    return c


def _data(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


# ── Studio: blank canvas + persistence round-trip ───────────────────────────
def test_blank_canvas_creates_artifact_with_empty_canvas(client):
    art = _data(client.post("/v1/artifacts/blank-canvas", json={"title": "Board A"}))
    assert art["title"] == "Board A"
    assert art["canvas"] == {"nodes": [], "edges": [], "table": {"columns": ["Action item", "Owner", "Due"], "rows": []}}
    assert art["id"]


def test_canvas_tldraw_roundtrips_through_save_and_get(client):
    aid = _data(client.post("/v1/artifacts/blank-canvas", json={"title": "B"}))["id"]
    graph = {"reactflow": {"nodes": [{"id": "n1", "type": "vigil", "position": {"x": 1, "y": 2}, "data": {"label": "hi"}}], "edges": []}}

    saved = _data(client.patch(f"/v1/artifacts/{aid}/canvas", json={"tldraw": graph}))
    assert saved["saved"] == aid

    fetched = _data(client.get(f"/v1/artifacts/{aid}"))
    assert fetched["tldraw"] == graph  # reloads exactly as last left


# ── Rooms: Google-Meet transcript bridge (parse + dedupe) ───────────────────
def test_import_transcript_parses_and_dedupes(client):
    rid = _data(client.post("/v1/rooms", json={"title": "R"}))["id"]
    lines = ["[12:00:01] Alice: hello there", "[12:00:05] Bob: hi", "a bare line with no speaker"]

    first = _data(client.post(f"/v1/rooms/{rid}/import-transcript", json={"lines": lines}))
    assert first["imported"] == 3

    transcript = _data(client.get(f"/v1/rooms/{rid}/transcript"))["transcript"]
    by_speaker = {m["speaker"]: m["text"] for m in transcript}
    assert by_speaker["Alice"] == "hello there"
    assert by_speaker["Bob"] == "hi"
    assert by_speaker["Meet"] == "a bare line with no speaker"  # fallback source label

    # Re-importing the same captions is idempotent.
    again = _data(client.post(f"/v1/rooms/{rid}/import-transcript", json={"lines": lines}))
    assert again["imported"] == 0


# ── Rooms: post-meeting summarize → artifact + commitments + CRM ────────────
def test_summarize_builds_artifact_canvas_and_side_effects(client, monkeypatch):
    async def fake_summarize(**_kw):
        return {
            "empty": False,
            "summary_markdown": "# Recap",
            "decisions": ["ship it"],
            "next_steps": ["follow up"],
            "commitments": [{"text": "send deck", "owner": "Bob", "due": "Fri"}],
            "follow_ups": [{"name": "Acme", "company": "Acme Inc", "next_step": "demo"}],
            "stub": True,
        }

    async def fake_structure(**_kw):
        return {
            "nodes": [{"id": "n1", "label": "Problem", "kind": "problem", "x": 0, "y": 0}],
            "edges": [],
            "table": {"columns": ["Action item", "Owner", "Due"], "rows": [["send deck", "Bob", "Fri"]]},
        }

    monkeypatch.setattr(rooms_mod, "summarize_meeting", fake_summarize)
    monkeypatch.setattr(rooms_mod, "structure_meeting", fake_structure)

    rid = _data(client.post("/v1/rooms", json={"title": "Deal review"}))["id"]
    client.post(f"/v1/rooms/{rid}/messages", json={"text": "let's ship", "speaker": "You"})

    out = _data(client.post(f"/v1/rooms/{rid}/summarize", json={}))
    assert out["artifact_id"]
    assert out["canvas"]["nodes"][0]["label"] == "Problem"
    assert out["commitments_saved"] == 1
    assert out["contacts_saved"] == 1

    # The artifact is real and carries the decision-flow canvas.
    art = _data(client.get(f"/v1/artifacts/{out['artifact_id']}"))
    assert art["canvas"]["table"]["rows"] == [["send deck", "Bob", "Fri"]]
    assert "Recap" in art["content"]


def test_summarize_closes_room_and_persists_summary(client, monkeypatch):
    async def fake_summarize(**_kw):
        return {"empty": False, "summary_markdown": "# Recap\nWe agreed to ship.",
                "decisions": [], "next_steps": [], "commitments": [], "follow_ups": [], "stub": True}
    async def fake_structure(**_kw):
        return {"nodes": [], "edges": [], "table": {"columns": [], "rows": []}}
    monkeypatch.setattr(rooms_mod, "summarize_meeting", fake_summarize)
    monkeypatch.setattr(rooms_mod, "structure_meeting", fake_structure)
    # Pretend an AI agent is live in the room — closing must end it.
    rid = _data(client.post("/v1/rooms", json={"title": "Deal review"}))["id"]
    rooms_mod._AVATAR_SESSIONS[rid] = {"provider": "beyond", "conversation_id": "c1"}
    client.post(f"/v1/rooms/{rid}/messages", json={"text": "ship", "speaker": "You"})

    out = _data(client.post(f"/v1/rooms/{rid}/summarize", json={}))
    assert out["status"] == "closed" and out["agent_ended"] is True
    assert rid not in rooms_mod._AVATAR_SESSIONS                # agent left
    room = _data(client.get(f"/v1/rooms/{rid}"))
    assert room["status"] == "closed" and "ship" in room["summary"]  # summary persisted


def test_council_reviews_summary_only_after_close(client, monkeypatch):
    # The post-meeting council convenes over the SUMMARY, not the transcript.
    rid = _data(client.post("/v1/rooms", json={"title": "Q3"}))["id"]
    client.db.tables["rooms"][0]["transcript"] = [{"speaker": "A", "text": "long raw discussion"}]
    client.db.tables["rooms"][0]["summary"] = "# Summary\nWe will raise prices 10%."

    room = client.db.tables["rooms"][0]
    summ = rooms_mod._council_scenario(room, rid, "cfo_review", None, "summary")
    assert summ["transcript"] == "# Summary\nWe will raise prices 10%."
    assert summ["primaryUserPrompt"].startswith("Meeting summary:")
    assert "long raw discussion" not in summ["primaryUserPrompt"]   # transcript never sent

    txt = rooms_mod._council_scenario(room, rid, "cfo_review", None, "transcript")
    assert "long raw discussion" in txt["transcript"]               # explicit transcript still works


def test_summarize_rejects_empty_transcript(client, monkeypatch):
    async def fake_summarize(**_kw):
        return {"empty": True}

    monkeypatch.setattr(rooms_mod, "summarize_meeting", fake_summarize)
    rid = _data(client.post("/v1/rooms", json={"title": "Empty"}))["id"]
    r = client.post(f"/v1/rooms/{rid}/summarize", json={})
    assert r.status_code == 400


# ── Studio: council brainstorm + diagram passthrough ────────────────────────
def test_canvas_brainstorm_returns_blocks(client, monkeypatch):
    async def fake_board(**kw):
        return {"blocks": [{"text": "an idea", "kind": "idea", "color": "#34d399", "lens": kw.get("lens")}],
                "lens": kw.get("lens"), "stub": True}

    monkeypatch.setattr(studio_mod, "brainstorm_board", fake_board)
    out = _data(client.post("/v1/artifacts/canvas-brainstorm", json={"prompt": "grow", "lens": "ideas"}))
    assert out["blocks"][0]["text"] == "an idea"
    assert out["lens"] == "ideas"


def test_canvas_diagram_returns_nodes_and_edges(client, monkeypatch):
    async def fake_diagram(**_kw):
        return {"nodes": [{"id": "n1", "label": "Start", "kind": "problem", "x": 0, "y": 0}], "edges": []}

    monkeypatch.setattr(studio_mod, "diagram_from_prompt", fake_diagram)
    out = _data(client.post("/v1/artifacts/canvas-diagram", json={"prompt": "onboarding"}))
    assert out["nodes"][0]["label"] == "Start"


# ── Multi-tenant scoping ────────────────────────────────────────────────────
def test_artifact_is_not_readable_by_another_user(client):
    aid = _data(client.post("/v1/artifacts/blank-canvas", json={"title": "mine"}))["id"]
    client.app.dependency_overrides[get_current_user] = lambda: {
        "sub": "user-2", "email": "b@x.com", "role": "authenticated"
    }
    assert client.get(f"/v1/artifacts/{aid}").status_code == 404


# ── Pure helpers (no app) ───────────────────────────────────────────────────
def test_layout_orders_problem_decision_outcome_left_to_right():
    from winny.council.structurer import _layout
    out = {n["id"]: n for n in _layout([
        {"id": "a", "label": "x", "kind": "problem"},
        {"id": "b", "label": "y", "kind": "decision"},
        {"id": "c", "label": "z", "kind": "outcome"},
    ])}
    assert out["a"]["x"] < out["b"]["x"] < out["c"]["x"]


def test_table_from_commitments_skips_blanks():
    from winny.council.structurer import _table_from_commitments
    t = _table_from_commitments([
        {"text": "do thing", "owner": "Bob", "due": "Fri"},
        {"text": "  "},  # dropped
    ])
    assert t["rows"] == [["do thing", "Bob", "Fri"]]


def test_parse_json_strips_code_fence():
    from winny_gateway.routes.vigil.studio import _parse_json
    assert _parse_json('```json\n{"a": 1}\n```') == {"a": 1}
