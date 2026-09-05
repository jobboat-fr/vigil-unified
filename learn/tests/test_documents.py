"""LEARN — documents, coffre and the RGPD conflict.

Proven live already: retention computes 2029/2031/2032/2036 from the funding basis,
deleting inside the window raises `retention_active` naming the date, and a legal hold
raises `legal_hold` naming the reason.

Covered here is the part no constraint can express — that erasure tells the truth about
what it kept, that a document is refused rather than rendered with a hole in it, and that
reading the coffre is logged for everyone rather than only for the people we distrust.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from learn import roles as learn_roles
from learn.roles import Actor, current_actor
from learn.routes import documents as d

TENANT = "11111111-1111-1111-1111-111111111111"
NADIA = "33333333-3333-3333-3333-333333333333"


class FakeConn:
    def __init__(self, rows=None, raises=None, scalar=None):
        self._rows, self._raises, self._scalar = list(rows or []), raises, scalar
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

    async def fetchval(self, q, *a):
        self.sql.append(q); self.args.append(a)
        return self._scalar

    async def execute(self, q, *a):
        self.sql.append(q); self.args.append(a)
        return "UPDATE 1"


class PgError(Exception):
    def __init__(self, sqlstate, detail=""):
        super().__init__(detail or sqlstate)
        self.sqlstate, self.detail = sqlstate, detail


def build(conn, actor):
    app = FastAPI()
    app.include_router(d.router)
    app.dependency_overrides[current_actor] = lambda: actor

    @asynccontextmanager
    async def fake_scoped(_a):
        yield conn

    d.scoped = fake_scoped
    d.available = lambda: True
    return TestClient(app)


@pytest.fixture(autouse=True)
def caps():
    learn_roles.CAPS._grants = {
        ("admin", "document", "create"), ("admin", "document", "update"),
        ("admin", "document", "read"), ("admin", "vault_object", "read"),
        ("auditeur", "document", "read"), ("auditeur", "vault_object", "read"),
        ("apprenant", "document", "read"),
    }
    learn_roles.CAPS._loaded = True
    yield
    learn_roles.CAPS._grants, learn_roles.CAPS._loaded = set(), False


def admin():
    return Actor(user_id=NADIA, role="admin", tenant_id=TENANT)


def nadia():
    return Actor(user_id=NADIA, role="apprenant", tenant_id=TENANT)


# ------------------------------------------------------------------ RGPD vs retention

def test_erasure_reports_what_it_kept_and_until_when():
    """The conflict this product cannot dodge: the obligation outranks the request, and
    the answer has to say so rather than pretend."""
    conn = FakeConn([[{"kind": "convention", "filename": "c.pdf",
                       "retention_until": "2032-12-31", "legal_hold": False}]],
                    scalar=6)
    conn._rows = [{"kind": "convention", "filename": "c.pdf",
                   "retention_until": "2032-12-31", "legal_hold": False}]
    c = build(conn, nadia())
    body = c.delete("/api/v1/learn/privacy/data").json()
    assert body["erased"], "something must actually be erased"
    assert body["retained"]["attendance_signatures"] == 6
    assert body["retained"]["documents"][0]["deletable_from"] == "2032-12-31"
    assert "obligation légale" in body["retained"]["reason"]


def test_erasure_does_not_touch_attendance():
    conn = FakeConn([], scalar=0)
    c = build(conn, nadia())
    c.delete("/api/v1/learn/privacy/data")
    written = " ".join(q for q in conn.sql if q.strip().lower().startswith(("update", "delete")))
    assert "learn_attendance_signatures" not in written
    assert "learn_vault_objects" not in written


def test_export_covers_every_category_held():
    conn = FakeConn([{"id": NADIA}])
    c = build(conn, nadia())
    body = c.get("/api/v1/learn/privacy/export").json()
    for key in ("profile", "enrolments", "attendance", "assessments", "documents"):
        assert key in body


# ------------------------------------------------------------------ generation

def test_a_document_is_refused_rather_than_rendered_with_a_hole():
    conn = FakeConn([
        {"id": "t1", "kind": "convention", "title": "Convention",
         "required_fields": ["intitule", "prix"], "active": True},
        {"tenant_id": TENANT, "legal_name": "HBS FORMATION", "nda": "28760809976"},
    ])
    c = build(conn, admin())
    r = c.post("/api/v1/learn/documents",
               json={"template_id": "t1", "data": {"intitule": "Excel avancé"}})
    assert r.status_code == 422
    assert r.json()["detail"]["fields"] == ["prix"]


def test_generation_refuses_before_branding_is_configured():
    """The NDA is a mandatory mention; a convention without it is not a convention."""
    conn = FakeConn([
        {"id": "t1", "kind": "convention", "title": "C", "required_fields": [], "active": True},
        None,
    ])
    conn._rows = [{"id": "t1", "kind": "convention", "title": "C",
                   "required_fields": [], "active": True}]

    async def fetchrow(q, *a):
        conn.sql.append(q)
        return conn._rows.pop(0) if conn._rows else None
    conn.fetchrow = fetchrow

    c = build(conn, admin())
    r = c.post("/api/v1/learn/documents", json={"template_id": "t1", "data": {}})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "branding_not_configured"


def test_branding_is_per_tenant_not_global():
    conn = FakeConn([{"tenant_id": TENANT, "legal_name": "HBS FORMATION"}])
    c = build(conn, admin())
    c.put("/api/v1/learn/branding", json={"legal_name": "HBS FORMATION"})
    assert conn.args[0][0] == TENANT, "branding must be written against the caller's tenant"


# ------------------------------------------------------------------ certificat

def test_certificate_warns_when_attendance_is_incomplete():
    """It reports what the signatures say, not what someone would like them to say."""
    conn = FakeConn([
        {"apprenant_name": "Nadia Cherif", "hours_total": 21.0,
         "hours_attended": 3.5, "complete": False},
        {"legal_name": "HBS FORMATION", "nda": "28760809976", "address": None},
    ])
    c = build(conn, admin())
    body = c.get(f"/api/v1/learn/sessions/s1/certificate/{NADIA}").json()
    assert body["complete"] is False
    assert "3.5" in body["warning"] and "21.0" in body["warning"]
    assert body["issuer"]["nda"] == "28760809976"


# ------------------------------------------------------------------ the coffre

def test_deleting_inside_retention_becomes_403():
    conn = FakeConn(raises=PgError("42501", "retention_active: must be kept until 2032-12-31"))
    c = build(conn, admin())
    r = c.post("/api/v1/learn/vault/v1/hold", json={"reason": "Contrôle DREETS"})
    assert r.status_code == 403
    assert "2032-12-31" in r.json()["detail"]["detail"]


def test_reading_the_vault_is_logged_for_everyone():
    """A log that only fires for the people you distrust proves nothing about the rest."""
    for role in ("admin", "auditeur"):
        conn = FakeConn([])
        c = build(conn, Actor(user_id=NADIA, role=role, tenant_id=TENANT))
        c.get("/api/v1/learn/vault")
        assert any("learn_access_log" in q for q in conn.sql), f"{role} read was not logged"


def test_a_hold_requires_a_reason():
    c = build(FakeConn([]), admin())
    assert c.post("/api/v1/learn/vault/v1/hold", json={}).status_code == 422
    assert c.post("/api/v1/learn/vault/v1/hold", json={"reason": "x"}).status_code == 422


def test_retention_summary_separates_held_from_purgeable():
    conn = FakeConn([
        {"id": "1", "purgeable": True, "legal_hold": False, "retention_until": "2020-12-31"},
        {"id": "2", "purgeable": False, "legal_hold": True, "retention_until": "2020-12-31"},
        {"id": "3", "purgeable": False, "legal_hold": False, "retention_until": "2032-12-31"},
    ])
    c = build(conn, admin())
    body = c.get("/api/v1/learn/vault/retention").json()
    assert body["total"] == 3 and body["purgeable"] == 1 and body["held"] == 1
