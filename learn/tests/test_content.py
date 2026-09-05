"""LEARN — content delivery: versioning, gating, progress, xAPI.

Proven live: a prerequisite reported `unlocked=false`, then `true` once the required
module's lesson was completed; `learn_at_risk` classified an active learner correctly.

Covered here: that revising never mutates what a cohort is being taught, that a locked
module withholds its payload rather than relying on the UI to hide a button, and that
progress and the activity stream cannot disagree.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from learn import roles as learn_roles
from learn.roles import Actor, current_actor
from learn.routes import content as ct

TENANT = "11111111-1111-1111-1111-111111111111"
NADIA = "33333333-3333-3333-3333-333333333333"


class FakeConn:
    def __init__(self, rows=None, raises=None):
        self._rows, self._raises = list(rows or []), raises
        self.sql: list[str] = []
        self.args: list[tuple] = []

    async def fetch(self, q, *a):
        self.sql.append(q); self.args.append(a)
        if self._raises:
            raise self._raises
        return self._rows

    async def fetchrow(self, q, *a):
        self.sql.append(q); self.args.append(a)
        if self._raises:
            raise self._raises
        if not self._rows:
            return None
        row = self._rows[0]
        if len(self._rows) > 1:
            self._rows = self._rows[1:]
        return row

    async def execute(self, q, *a):
        self.sql.append(q); self.args.append(a)
        return "INSERT 1"


def build(conn, actor):
    app = FastAPI()
    app.include_router(ct.router)
    app.dependency_overrides[current_actor] = lambda: actor

    @asynccontextmanager
    async def fake_scoped(_a):
        yield conn

    ct.scoped = fake_scoped
    ct.available = lambda: True
    return TestClient(app)


@pytest.fixture(autouse=True)
def caps():
    learn_roles.CAPS._grants = {
        ("admin", "program", "read"), ("formateur", "program", "read"),
        ("apprenant", "program", "read"),
    }
    learn_roles.CAPS._loaded = True
    yield
    learn_roles.CAPS._grants, learn_roles.CAPS._loaded = set(), False


def nadia():
    return Actor(user_id=NADIA, role="apprenant", tenant_id=TENANT)


def admin():
    return Actor(user_id=NADIA, role="admin", tenant_id=TENANT)


# ------------------------------------------------------------------ versioning

def test_revising_inserts_a_version_and_never_updates_the_old_one():
    """A cohort mid-course must keep being taught what it started with."""
    conn = FakeConn([{"id": "c1", "code": "EXC-AV", "version": 1},
                     {"id": "c2", "code": "EXC-AV", "version": 2}])
    c = build(conn, admin())
    r = c.post("/api/v1/learn/courses/c1/revise")
    assert r.status_code == 201
    assert r.json()["supersedes"] == "c1"
    joined = " ".join(conn.sql)
    assert "version + 1" in joined
    # The only UPDATE is the supersede pointer; content is never rewritten in place.
    updates = [q for q in conn.sql if q.strip().lower().startswith("update")]
    assert len(updates) == 1 and "superseded_by" in updates[0]


def test_superseded_versions_stay_readable():
    conn = FakeConn([])
    c = build(conn, admin())
    c.get("/api/v1/learn/courses", params={"include_superseded": "true"})
    assert conn.args[0][0] is True


# ------------------------------------------------------------------ gating

def test_a_locked_module_withholds_the_payload():
    """Not merely hidden in the UI — the content is not returned at all."""
    conn = FakeConn([{"id": "l1", "title": "Champs calculés", "unlocked": False,
                      "content": {"secret": "x"}}])
    c = build(conn, nadia())
    r = c.get("/api/v1/learn/lessons/l1")
    assert r.status_code == 423
    assert r.json()["detail"]["error"] == "module_locked"
    assert "secret" not in r.text


def test_staff_are_not_gated_by_prerequisites():
    conn = FakeConn([{"id": "l1", "title": "Champs calculés", "unlocked": False,
                      "content": {}}])
    c = build(conn, Actor(user_id=NADIA, role="formateur", tenant_id=TENANT))
    assert c.get("/api/v1/learn/lessons/l1").status_code == 200


def test_the_outline_resolves_lock_state_server_side():
    # The outline issues two fetches; this row is shaped to satisfy both the module list
    # and the lesson list the handler groups by module_id.
    conn = FakeConn([{"id": "m1", "module_id": "m1", "position": 1,
                      "title": "Bases", "unlocked": True, "kind": "video",
                      "status": None, "progress_pct": None, "duration_minutes": 12}])
    c = build(conn, nadia())
    body = c.get("/api/v1/learn/courses/c1/outline").json()
    assert "unlocked" in body["modules"][0]
    assert any("learn_module_unlocked" in q for q in conn.sql)


# ------------------------------------------------------------------ progress

def test_progress_and_the_activity_stream_are_written_together():
    """One transaction, so the xAPI stream and the progress table cannot disagree."""
    conn = FakeConn([{"id": "p1", "status": "termine", "progress_pct": 100}])
    c = build(conn, nadia())
    c.put("/api/v1/learn/lessons/l1/progress", json={"progress_pct": 100})
    assert any("learn_lesson_progress" in q for q in conn.sql)
    assert any("learn_xapi_statements" in q for q in conn.sql)


def test_progress_never_moves_backwards():
    conn = FakeConn([{"id": "p1", "status": "en_cours", "progress_pct": 60}])
    c = build(conn, nadia())
    c.put("/api/v1/learn/lessons/l1/progress", json={"progress_pct": 20})
    upsert = [q for q in conn.sql if "on conflict" in q][0]
    assert "greatest(" in upsert


def test_progress_is_bounded():
    c = build(FakeConn([]), nadia())
    assert c.put("/api/v1/learn/lessons/l1/progress",
                 json={"progress_pct": 140}).status_code == 422


def test_time_spent_accumulates_rather_than_replaces():
    conn = FakeConn([{"id": "p1"}])
    c = build(conn, nadia())
    c.put("/api/v1/learn/lessons/l1/progress",
          json={"progress_pct": 50, "seconds_spent": 300})
    upsert = [q for q in conn.sql if "on conflict" in q][0]
    assert "seconds_spent + excluded.seconds_spent" in upsert


# ------------------------------------------------------------------ indicator 19

def test_at_risk_lists_only_people_needing_action():
    conn = FakeConn([{"full_name": "Bruno Weber", "days_since": 9,
                      "percent_complete": 20.0, "reason": "inactif_7j"}])
    c = build(conn, Actor(user_id=NADIA, role="formateur", tenant_id=TENANT))
    body = c.get("/api/v1/learn/at-risk").json()
    assert body["count"] == 1
    assert all(i["reason"] != "actif" for i in body["items"])
    assert any("reason <> 'actif'" in q for q in conn.sql)
    assert "intervention" in body["note"]
