"""LEARN — reporting, audit export, notifications, signalement.

Proven live: `learn_audit_manifest()` returned ten pieces for the Excel session and marked
four absent, including the convention and the certificats.

Covered here: that the export leads with what is missing, that nothing leaves in the
organisme's name without a named human approving it, and that an agent cannot be that human.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from learn import roles as learn_roles
from learn.roles import Actor, current_actor
from learn.routes import reporting as rp

TENANT = "11111111-1111-1111-1111-111111111111"
ADMIN = "22222222-2222-2222-2222-222222222222"


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
    learn_roles.CAPS._grants = {
        ("admin", "document", "read"), ("admin", "document", "create"),
        ("auditeur", "document", "read"),
    }
    learn_roles.CAPS._loaded = True
    yield
    learn_roles.CAPS._grants, learn_roles.CAPS._loaded = set(), False


def admin():
    return Actor(user_id=ADMIN, role="admin", tenant_id=TENANT)


MANIFEST = [
    {"piece": "Convention ou contrat", "indicator": "ind. 9", "present": False, "detail": None},
    {"piece": "Programme de formation", "indicator": "ind. 5-6", "present": True, "detail": "v3"},
    {"piece": "Feuilles d'émargement", "indicator": "ind. 10", "present": True, "detail": "3"},
    {"piece": "Certificats de réalisation", "indicator": "ind. 11", "present": False, "detail": None},
]


# ------------------------------------------------------------------ audit export

def test_the_export_leads_with_what_is_missing():
    """A manifest that quietly omits the gaps turns a fixable problem into a surprise."""
    conn = FakeConn(MANIFEST)
    c = build(conn, admin())
    body = c.get("/api/v1/learn/sessions/s1/audit").json()
    assert body["ready"] is False
    assert body["readiness"] == "2/4"
    assert {m["piece"] for m in body["missing"]} == {
        "Convention ou contrat", "Certificats de réalisation"}


def test_a_complete_session_reports_ready():
    conn = FakeConn([{**m, "present": True} for m in MANIFEST])
    c = build(conn, admin())
    body = c.get("/api/v1/learn/sessions/s1/audit").json()
    assert body["ready"] is True and body["missing"] == []


def test_reading_the_audit_export_is_logged():
    conn = FakeConn(MANIFEST)
    c = build(conn, admin())
    c.get("/api/v1/learn/sessions/s1/audit")
    assert any("learn_access_log" in q for q in conn.sql)


def test_every_manifest_piece_names_its_indicator():
    conn = FakeConn(MANIFEST)
    c = build(conn, admin())
    items = c.get("/api/v1/learn/sessions/s1/audit").json()["items"]
    assert all(i["indicator"].startswith("ind.") for i in items)


# ------------------------------------------------------------------ notifications

def test_a_notification_starts_as_a_draft():
    conn = FakeConn([{"id": "n1", "status": "brouillon"}])
    c = build(conn, admin())
    r = c.post("/api/v1/learn/notifications",
               json={"kind": "convocation", "subject": "Votre convocation"})
    assert r.status_code == 201
    insert = [q for q in conn.sql if "insert into learn_notifications" in q][0]
    assert "status" not in insert, "status must fall to its default, not be chosen"


def test_an_agent_cannot_approve_a_send():
    """It drafts; a human takes responsibility for anything leaving in the organisme's name."""
    conn = FakeConn([{"id": "n1"}])
    agent = Actor(user_id=ADMIN, role="admin", tenant_id=TENANT, principal="agent")
    c = build(conn, agent)
    r = c.post("/api/v1/learn/notifications/n1/approve")
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "human_approval_required"


def test_approval_records_who_approved():
    conn = FakeConn([{"id": "n1", "status": "planifie", "approved_by": ADMIN}])
    c = build(conn, admin())
    c.post("/api/v1/learn/notifications/n1/approve")
    upd = [q for q in conn.sql if "update learn_notifications" in q][0]
    assert "approved_by = $2" in upd and "approved_at = now()" in upd


def test_approving_something_already_sent_is_a_conflict():
    conn = FakeConn([])
    c = build(conn, admin())
    assert c.post("/api/v1/learn/notifications/n1/approve").status_code == 409


# ------------------------------------------------------------------ signalement

def test_an_anonymous_report_stores_no_reporter():
    """A channel that records who spoke is a channel people stop using."""
    conn = FakeConn([{"id": "s1", "category": "harcelement", "status": "recu",
                      "anonymous": True, "received_at": None}])
    c = build(conn, Actor(user_id=ADMIN, role="apprenant", tenant_id=TENANT))
    c.post("/api/v1/learn/signalements",
           json={"category": "harcelement", "body": "x" * 20, "anonymous": True})
    assert conn.args[0][2] is None, "no reporter id may be stored"


def test_a_named_report_keeps_the_reporter():
    conn = FakeConn([{"id": "s1", "anonymous": False}])
    c = build(conn, Actor(user_id=ADMIN, role="apprenant", tenant_id=TENANT))
    c.post("/api/v1/learn/signalements",
           json={"category": "violence", "body": "y" * 20, "anonymous": False})
    assert conn.args[0][2] == ADMIN


def test_a_report_needs_substance():
    c = build(FakeConn([]), admin())
    assert c.post("/api/v1/learn/signalements",
                  json={"category": "autre", "body": "court"}).status_code == 422


def test_closing_a_report_demands_an_outcome():
    c = build(FakeConn([]), admin())
    assert c.post("/api/v1/learn/signalements/s1/handle", json={}).status_code == 422


def test_dashboard_counts_things_needing_action():
    conn = FakeConn([{"tenant_id": TENANT, "reclamations_ouvertes": 2,
                      "copies_a_corriger": 1, "apprenants_a_risque": 3,
                      "programmes_a_reviser": 1, "pieces_purgeables": 0}])
    c = build(conn, admin())
    body = c.get("/api/v1/learn/dashboard").json()
    for k in ("reclamations_ouvertes", "copies_a_corriger", "apprenants_a_risque"):
        assert k in body
