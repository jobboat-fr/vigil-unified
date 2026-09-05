"""LEARN — the HTTP layer, exercised against a fake connection.

The data layer was proven against the real database (six roles, 6 slots from 3 days, a 409
naming the conflicting range, 7/6/1/6 rows for four callers). What that could not reach is
the plumbing above it: dependency resolution, capability gating, `_can` decoration, error
translation, and the ICS rendering. This file covers that, with no database and no
credential — the same shape as `tests/winny_gateway`'s FakeDB harness.

What deliberately is NOT asserted here: that RLS narrows rows. A fake connection returns
whatever it is told to. Row-level isolation is the database's job and was proven there.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from learn import roles as learn_roles
from learn.roles import Actor, current_actor
from learn.routes import calendar as cal_routes
from learn.routes import planning as plan_routes

TENANT = "11111111-1111-1111-1111-111111111111"
ADMIN = "22222222-2222-2222-2222-222222222222"


class FakeConn:
    """Records the SQL it was asked to run and replays canned rows."""

    def __init__(self, rows=None, raises: Exception | None = None):
        self._rows = rows or []
        self._raises = raises
        self.queries: list[str] = []

    async def fetch(self, q, *a):
        self.queries.append(q)
        if self._raises:
            raise self._raises
        return self._rows

    async def fetchrow(self, q, *a):
        self.queries.append(q)
        if self._raises:
            raise self._raises
        return self._rows[0] if self._rows else None

    async def execute(self, q, *a):
        self.queries.append(q)
        if self._raises:
            raise self._raises
        return "DELETE 1"


class PgError(Exception):
    """Stands in for asyncpg's error, which carries the SQLSTATE we translate on."""

    def __init__(self, sqlstate: str, detail: str = ""):
        super().__init__(detail or sqlstate)
        self.sqlstate = sqlstate
        self.detail = detail


def build(conn: FakeConn, actor: Actor) -> TestClient:
    app = FastAPI()
    app.include_router(plan_routes.router)
    app.include_router(cal_routes.router)
    app.dependency_overrides[current_actor] = lambda: actor

    @asynccontextmanager
    async def fake_scoped(_actor):
        yield conn

    # The route modules did `from ..db import available, scoped` — so the names to
    # replace live on those modules, not on learn.db. Patching learn.db here would
    # rebind something nobody reads.
    for mod in (plan_routes, cal_routes):
        mod.scoped = fake_scoped
        mod.available = lambda: True
    return TestClient(app)


@pytest.fixture(autouse=True)
def seeded_capabilities():
    """Mirror of learn_capabilities. Absent = denied, so this is the whole grant list."""
    learn_roles.CAPS._grants = {
        ("admin", "session", "create"), ("admin", "session", "update"),
        ("admin", "session", "read"), ("admin", "session", "cancel"),
        ("admin", "slot", "create"), ("admin", "slot", "update"),
        ("admin", "slot", "read"), ("admin", "program", "read"),
        ("admin", "enrollment", "create"), ("admin", "enrollment", "read"),
        ("formateur", "slot", "read"), ("formateur", "slot", "update"),
        ("formateur", "session", "read"), ("formateur", "attendance", "sign"),
        ("apprenant", "attendance", "sign"), ("apprenant", "session", "read"),
        ("auditeur", "session", "read"), ("auditeur", "slot", "read"),
    }
    learn_roles.CAPS._loaded = True
    yield
    learn_roles.CAPS._grants = set()
    learn_roles.CAPS._loaded = False


def admin() -> Actor:
    return Actor(user_id=ADMIN, role="admin", tenant_id=TENANT)


# --------------------------------------------------------------------- shape

def test_calendar_rows_carry_capabilities():
    """`_can` travels with the data so the front end never infers controls from the role."""
    conn = FakeConn([{"id": "s1", "title": "Excel avancé", "starts_at": None,
                      "ends_at": None, "status": "planned", "room_name": None,
                      "formateur_name": None, "modality": "presentiel"}])
    c = build(conn, admin())
    r = c.get("/api/v1/learn/calendar", params={"from": "2026-05-11", "to": "2026-05-17"})
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["_can"]["update"] is True
    assert item["_can"]["sign"] is False, "admin must not be able to attest presence"


def test_formateur_and_admin_hit_the_same_route():
    """No /admin/... and no /formateur/... — one endpoint, and the row set differs."""
    for role in ("admin", "formateur", "auditeur", "apprenant"):
        conn = FakeConn([])
        c = build(conn, Actor(user_id=ADMIN, role=role, tenant_id=TENANT))
        r = c.get("/api/v1/learn/calendar",
                  params={"from": "2026-05-11", "to": "2026-05-17"})
        assert r.status_code == 200, f"{role} was refused the shared route"


def test_only_the_two_attesting_roles_may_sign():
    for role, expected in (("apprenant", True), ("formateur", True),
                           ("admin", False), ("auditeur", False)):
        actor = Actor(user_id=ADMIN, role=role, tenant_id=TENANT)
        assert learn_roles.can(actor, "attendance", "sign") is expected


# --------------------------------------------------------------------- refusals

def test_double_booking_becomes_409_with_the_conflict():
    """The constraint refuses; the handler translates rather than re-checking."""
    conn = FakeConn(raises=PgError("23P01", "Key (formateur_id, span)=(…) conflicts"))
    c = build(conn, admin())
    r = c.post("/api/v1/learn/sessions/abc/slots:generate",
               json={"dates": ["2026-05-13"], "halves": ["am"]})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "slot_conflict"
    assert "conflicts" in r.json()["detail"]["detail"]


def test_policy_refusal_becomes_403():
    conn = FakeConn(raises=PgError("42501", "capability_missing"))
    c = build(conn, admin())
    r = c.post("/api/v1/learn/sessions", json={
        "program_id": "p1", "starts_on": "2026-05-12", "ends_on": "2026-05-14"})
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "not_permitted"


def test_read_only_role_holds_no_write_capability():
    auditeur = Actor(user_id=ADMIN, role="auditeur", tenant_id=TENANT)
    assert learn_roles.can(auditeur, "session", "read") is True
    assert learn_roles.can(auditeur, "session", "create") is False
    assert learn_roles.can(auditeur, "session", "update") is False


def test_agent_cannot_sign_even_when_its_delegator_could():
    """The ceiling caps; it never grants. A formateur may sign — its agent may not."""
    human = Actor(user_id=ADMIN, role="formateur", tenant_id=TENANT)
    agent = Actor(user_id=ADMIN, role="formateur", tenant_id=TENANT,
                  principal="agent", on_behalf_of=ADMIN)
    assert learn_roles.can(human, "attendance", "sign") is True
    assert learn_roles.can(agent, "attendance", "sign") is False


def test_unknown_role_fails_closed():
    stranger = Actor(user_id=ADMIN, role="nonesuch", tenant_id=TENANT)
    assert stranger.read_only is True
    assert learn_roles.can(stranger, "session", "read") is False


def test_capabilities_never_guessed_before_they_are_loaded():
    learn_roles.CAPS._loaded = False
    assert learn_roles.can(admin(), "session", "create") is False
    learn_roles.CAPS._loaded = True


# --------------------------------------------------------------------- validation

def test_inverted_range_refused():
    c = build(FakeConn([]), admin())
    r = c.get("/api/v1/learn/calendar", params={"from": "2026-05-17", "to": "2026-05-11"})
    assert r.status_code == 422


def test_absurd_range_refused():
    c = build(FakeConn([]), admin())
    r = c.get("/api/v1/learn/calendar", params={"from": "2020-01-01", "to": "2030-01-01"})
    assert r.status_code == 422


def test_bad_half_refused_before_the_database():
    c = build(FakeConn([]), admin())
    r = c.post("/api/v1/learn/sessions/abc/slots:generate",
               json={"dates": ["2026-05-13"], "halves": ["evening"]})
    assert r.status_code == 422


def test_full_session_refuses_enrolment():
    conn = FakeConn([{"capacity": 12, "taken": 12}])
    c = build(conn, admin())
    r = c.post("/api/v1/learn/sessions/abc/enrollments", json={"apprenant_id": "x"})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "session_full"


def test_learn_degrades_without_a_database():
    """A missing DSN must answer 503, not 500 — LEARN off, gateway up."""
    c = build(FakeConn([]), admin())
    plan_routes.available = lambda: False
    try:
        r = c.get("/api/v1/learn/programs")
        assert r.status_code == 503
        assert r.json()["detail"]["error"] == "learn_database_unavailable"
    finally:
        plan_routes.available = lambda: True


# --------------------------------------------------------------------- ICS

def test_ics_escaping_is_rfc5545():
    """Unescaped commas and semicolons silently corrupt a subscribed feed."""
    assert cal_routes._esc("Excel, avancé; TCD") == r"Excel\, avancé\; TCD"
    assert cal_routes._esc("a\nb") == r"a\nb"
    assert cal_routes._esc(None) == ""


def test_ics_timestamps_are_utc_basic_format():
    from datetime import datetime, timezone
    dt = datetime(2026, 5, 12, 9, 0, tzinfo=timezone.utc)
    assert cal_routes._stamp(dt) == "20260512T090000Z"
