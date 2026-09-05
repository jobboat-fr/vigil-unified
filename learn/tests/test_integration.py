"""LEARN ↔ hbs-backend — the send path, end to end.

The approval is checked three times on one journey, and each layer catches a different kind
of mistake:

    the route     — an agent, or a row nobody approved
    the table     — `learn_notif_sent_needs_approval`, if a write bypassed the route
    the bridge    — a 412 if the payload arrives without a named approver

These tests cover the first and the last. The middle one is a constraint and was verified
against the live database.

The other thing asserted here is failure behaviour: a bridge that is down must leave the row
in `echec` with the reason attached. Silently dropping a message an organisme believes it
sent is worse than an error, because nobody goes looking for it.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from learn import notify as notify_bridge
from learn import roles as learn_roles
from learn.roles import Actor, current_actor
from learn.routes import reporting as rp

TENANT = "11111111-1111-1111-1111-111111111111"
ADMIN = "22222222-2222-2222-2222-222222222222"


class FakeConn:
    def __init__(self, rows=None):
        self._rows = list(rows or [])
        self.sql: list[str] = []
        self.args: list[tuple] = []

    async def fetch(self, q, *a):
        self.sql.append(q); self.args.append(a)
        return self._rows

    async def fetchrow(self, q, *a):
        self.sql.append(q); self.args.append(a)
        if not self._rows:
            return None
        row = self._rows[0]
        if len(self._rows) > 1:
            self._rows = self._rows[1:]
        return row

    async def execute(self, q, *a):
        self.sql.append(q); self.args.append(a)
        return "UPDATE 1"


def build(conn, actor):
    app = FastAPI()
    app.include_router(rp.router)
    app.dependency_overrides[current_actor] = lambda: actor

    @asynccontextmanager
    async def fake_scoped(_a):
        yield conn

    rp.scoped = fake_scoped
    rp.available = lambda: True
    return TestClient(app)


@pytest.fixture(autouse=True)
def caps():
    learn_roles.CAPS._grants = {("admin", "document", "read")}
    learn_roles.CAPS._loaded = True
    yield
    learn_roles.CAPS._grants, learn_roles.CAPS._loaded = set(), False


def admin():
    return Actor(user_id=ADMIN, role="admin", tenant_id=TENANT)


APPROVED = {
    "id": "n1", "kind": "convocation", "subject": "Votre convocation",
    "body": "Vous êtes attendue le 12 mai.", "email": "n@delta-log.fr",
    "approved_by": ADMIN, "approved_at": "2026-05-06T10:00:00Z",
    "status": "planifie", "tenant_id": TENANT,
}


# ------------------------------------------------------------------ the gate

def test_an_unapproved_notification_never_reaches_the_bridge(monkeypatch):
    called = False

    async def spy(_row):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(notify_bridge, "dispatch", spy)
    conn = FakeConn([{**APPROVED, "approved_at": None, "approved_by": None}])
    c = build(conn, admin())
    r = c.post("/api/v1/learn/notifications/n1/send")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "not_approved"
    assert called is False, "nothing may reach the bridge without an approval"


def test_an_agent_cannot_trigger_a_send():
    agent = Actor(user_id=ADMIN, role="admin", tenant_id=TENANT, principal="agent")
    c = build(FakeConn([APPROVED]), agent)
    r = c.post("/api/v1/learn/notifications/n1/send")
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "human_approval_required"


def test_the_dispatcher_itself_refuses_an_unapproved_row():
    """Belt and braces: the bridge client checks before it opens a socket."""
    import asyncio
    with pytest.raises(notify_bridge.NotifyRefused):
        asyncio.get_event_loop().run_until_complete(
            notify_bridge.dispatch({"id": "n1", "approved_at": None, "approved_by": None}))


# ------------------------------------------------------------------ the happy path

def test_a_successful_send_marks_the_row_and_carries_the_approver(monkeypatch):
    seen: dict = {}

    async def spy(row):
        seen.update(row)
        return {"sent": True, "to": "n@delta-log.fr"}

    monkeypatch.setattr(notify_bridge, "dispatch", spy)
    conn = FakeConn([APPROVED, {**APPROVED, "status": "envoye", "sent_at": "now"}])
    c = build(conn, admin())
    body = c.post("/api/v1/learn/notifications/n1/send").json()
    assert body["status"] == "envoye"
    assert body["bridge"]["sent"] is True
    assert seen["approved_by"] == ADMIN, "the approver travels with the payload"


# ------------------------------------------------------------------ failure

def test_a_bridge_outage_leaves_the_row_visible_not_lost(monkeypatch):
    async def down(_row):
        raise notify_bridge.NotifyUnavailable("pont injoignable (ConnectError)")

    monkeypatch.setattr(notify_bridge, "dispatch", down)
    conn = FakeConn([APPROVED])
    c = build(conn, admin())
    r = c.post("/api/v1/learn/notifications/n1/send")
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "bridge_unavailable"
    failed = [q for q in conn.sql if "status='echec'" in q]
    assert failed, "the row must be marked failed, with the reason kept"


def test_a_refusal_is_not_retried_as_an_outage(monkeypatch):
    async def refuse(_row):
        raise notify_bridge.NotifyRefused("le pont exige une approbation nommée")

    monkeypatch.setattr(notify_bridge, "dispatch", refuse)
    c = build(FakeConn([APPROVED]), admin())
    r = c.post("/api/v1/learn/notifications/n1/send")
    assert r.status_code == 422, "a refusal is permanent; 503 would invite a retry loop"


def test_sending_twice_is_refused():
    c = build(FakeConn([{**APPROVED, "status": "envoye"}]), admin())
    r = c.post("/api/v1/learn/notifications/n1/send")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "already_sent"


def test_the_bridge_is_optional(monkeypatch):
    """LEARN runs without it; only sending is unavailable."""
    monkeypatch.setattr(notify_bridge, "BRIDGE_URL", "")
    monkeypatch.setattr(notify_bridge, "BRIDGE_TOKEN", "")
    assert notify_bridge.configured() is False
