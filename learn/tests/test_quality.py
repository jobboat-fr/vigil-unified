"""LEARN — the qualité loop's HTTP layer.

The constraints were proven against the live database: an action with no cause is refused
by NOT NULL, closing without an outcome by a check constraint, and resolving a réclamation
without a resolution by another. Covered here is the layer above — that the API offers no
way around any of them, that anonymity actually holds, and that a published figure never
travels without the population behind it.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from learn import roles as learn_roles
from learn.roles import Actor, current_actor
from learn.routes import quality as q

TENANT = "11111111-1111-1111-1111-111111111111"
ADMIN = "22222222-2222-2222-2222-222222222222"


class FakeConn:
    def __init__(self, rows=None, raises=None):
        self._rows, self._raises = rows or [], raises
        self.args: list[tuple] = []

    async def fetch(self, qs, *a):
        self.args.append(a)
        if self._raises:
            raise self._raises
        return self._rows

    async def fetchrow(self, qs, *a):
        # Successive fetchrow calls consume successive rows: a handler that reads an
        # invitation and then inserts a response must not be handed the same dict twice.
        self.args.append(a)
        if self._raises:
            raise self._raises
        if not self._rows:
            return None
        row = self._rows[0]
        if len(self._rows) > 1:
            self._rows = self._rows[1:]
        return row

    async def execute(self, qs, *a):
        self.args.append(a)
        return "UPDATE 1"


class PgError(Exception):
    def __init__(self, sqlstate, detail=""):
        super().__init__(detail or sqlstate)
        self.sqlstate, self.detail = sqlstate, detail


def build(conn, actor):
    app = FastAPI()
    app.include_router(q.router)
    app.dependency_overrides[current_actor] = lambda: actor

    @asynccontextmanager
    async def fake_scoped(_a):
        yield conn

    q.scoped = fake_scoped
    q.available = lambda: True
    return TestClient(app)


@pytest.fixture(autouse=True)
def caps():
    learn_roles.CAPS._grants = {
        ("admin", "evaluation", "read"), ("admin", "reclamation", "read"),
        ("admin", "reclamation", "update"), ("apprenant", "reclamation", "create"),
        ("apprenant", "evaluation", "create"), ("auditeur", "evaluation", "read"),
        ("auditeur", "reclamation", "read"),
    }
    learn_roles.CAPS._loaded = True
    yield
    learn_roles.CAPS._grants, learn_roles.CAPS._loaded = set(), False


def admin():
    return Actor(user_id=ADMIN, role="admin", tenant_id=TENANT)


# ------------------------------------------------------------------ the loop

def test_an_action_cannot_be_created_without_naming_its_cause():
    """The field that decides indicator 30. No default, no fallback, no way past it."""
    c = build(FakeConn([]), admin())
    r = c.post("/api/v1/learn/actions", json={"title": "Changer de salle"})
    assert r.status_code == 422
    missing = {tuple(e["loc"])[-1] for e in r.json()["detail"]}
    assert "source_kind" in missing and "source_id" in missing


def test_source_kind_is_restricted_to_real_causes():
    c = build(FakeConn([]), admin())
    r = c.post("/api/v1/learn/actions", json={
        "title": "x", "source_kind": "parce_que", "source_id": "abc"})
    assert r.status_code == 422


def test_closing_an_action_demands_an_outcome():
    c = build(FakeConn([]), admin())
    assert c.post("/api/v1/learn/actions/a1/close", json={}).status_code == 422
    assert c.post("/api/v1/learn/actions/a1/close",
                  json={"outcome": "ok"}).status_code == 422  # min_length 5


def test_resolving_a_reclamation_demands_a_resolution():
    c = build(FakeConn([]), admin())
    assert c.post("/api/v1/learn/reclamations/r1/resolve", json={}).status_code == 422


def test_check_constraint_violation_becomes_422_not_500():
    conn = FakeConn(raises=PgError("23514", 'violates check constraint "learn_action_closed"'))
    c = build(conn, admin())
    r = c.post("/api/v1/learn/actions/a1/close",
               json={"outcome": "Sessions déplacées en salle C"})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "invalid_value"


# ------------------------------------------------------------------ anonymity

def test_anonymous_campaign_stores_no_respondent():
    """The invitation is marked answered so the rate still counts; the response is not
    attributable to a person, not even by an admin."""
    conn = FakeConn([{"id": "i1", "tenant_id": TENANT, "campaign_id": "c1",
                      "profile_id": "p-nadia", "responded_at": None,
                      "anonymous": True, "status": "open", "due_at": None},
                     {"id": "resp1", "submitted_at": None}])

    class P:
        @asynccontextmanager
        async def acquire(self):
            yield conn
    conn.transaction = lambda: _null_ctx()
    q.pool = _async(P())  # module attribute, now patchable

    app = FastAPI()
    app.include_router(q.router)
    q.available = lambda: True
    client = TestClient(app)
    r = client.post("/api/v1/learn/survey/tok123/respond",
                    json={"score": 4.5, "comment": "Très bon"})
    assert r.status_code == 201
    assert r.json()["anonymous"] is True
    insert_args = conn.args[1]
    assert insert_args[3] is None, "an anonymous response must carry no profile_id"


def test_named_campaign_keeps_the_respondent():
    conn = FakeConn([{"id": "i1", "tenant_id": TENANT, "campaign_id": "c1",
                      "profile_id": "p-nadia", "responded_at": None,
                      "anonymous": False, "status": "open", "due_at": None},
                     {"id": "resp1", "submitted_at": None}])

    class P:
        @asynccontextmanager
        async def acquire(self):
            yield conn
    conn.transaction = lambda: _null_ctx()
    q.pool = _async(P())  # module attribute, now patchable

    app = FastAPI()
    app.include_router(q.router)
    q.available = lambda: True
    r = TestClient(app).post("/api/v1/learn/survey/tok123/respond", json={"score": 5})
    assert r.json()["anonymous"] is False
    assert conn.args[1][3] == "p-nadia"


def test_answering_twice_is_refused():
    conn = FakeConn([{"id": "i1", "tenant_id": TENANT, "campaign_id": "c1",
                      "profile_id": None, "responded_at": "2026-05-20",
                      "anonymous": True, "status": "open", "due_at": None}])

    class P:
        @asynccontextmanager
        async def acquire(self):
            yield conn
    q.pool = _async(P())  # module attribute, now patchable
    app = FastAPI()
    app.include_router(q.router)
    q.available = lambda: True
    r = TestClient(app).post("/api/v1/learn/survey/tok/respond", json={"score": 3})
    assert r.status_code == 409


# ------------------------------------------------------------------ what gets published

def test_indicators_never_travel_without_their_population():
    """A satisfaction of 4.6 means nothing without the responses behind it — V10 ind. 1."""
    conn = FakeConn([{"year": 2026, "sessions": 8, "learners": 96, "responses": 71,
                      "satisfaction": 4.6, "response_rate": 74.0, "reclamations": 2}])
    c = build(conn, admin())
    body = c.get("/api/v1/learn/quality/indicators").json()
    row = body["items"][0]
    for field in ("responses", "response_rate", "learners"):
        assert row[field] is not None, f"{field} must ship beside the rate"
    assert "population" in body["note"]


def test_score_is_bounded():
    conn = FakeConn([])
    c = build(conn, admin())

    class P:
        @asynccontextmanager
        async def acquire(self):
            yield conn
    q.pool = _async(P())  # module attribute, now patchable
    r = c.post("/api/v1/learn/survey/tok/respond", json={"score": 9})
    assert r.status_code == 422


def test_read_only_auditeur_can_read_the_loop():
    conn = FakeConn([])
    a = Actor(user_id=ADMIN, role="auditeur", tenant_id=TENANT)
    c = build(conn, a)
    assert c.get("/api/v1/learn/reclamations").status_code == 200
    assert learn_roles.can(a, "reclamation", "update") is False


# ------------------------------------------------------------------ helpers

@asynccontextmanager
async def _null_ctx():
    yield None


def _async(value):
    async def _f():
        return value
    return _f
