"""LEARN — the émargement HTTP layer.

The rules themselves were proven against the real database: the chain links, an admin
gets `permission denied` on an update, an agent is refused by `learn_human_only`, and a
formateur cannot counter-sign a slot they do not teach. What is covered here is the layer
above — that the evidence bundle is built from the connection rather than the body, that
no edit endpoint exists to be found, and that refusals arrive as the right status.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from learn import roles as learn_roles
from learn.roles import Actor, current_actor
from learn.routes import attendance as att

TENANT = "11111111-1111-1111-1111-111111111111"
NADIA = "33333333-3333-3333-3333-333333333333"
SLOT = "44444444-4444-4444-4444-444444444444"


class FakeConn:
    def __init__(self, rows=None, raises=None):
        self._rows, self._raises = rows or [], raises
        self.args: list[tuple] = []

    async def fetch(self, q, *a):
        self.args.append(a)
        if self._raises:
            raise self._raises
        return self._rows

    async def fetchrow(self, q, *a):
        self.args.append(a)
        if self._raises:
            raise self._raises
        return self._rows[0] if self._rows else None


class PgError(Exception):
    def __init__(self, sqlstate, detail=""):
        super().__init__(detail or sqlstate)
        self.sqlstate, self.detail = sqlstate, detail


def build(conn, actor):
    app = FastAPI()
    app.include_router(att.router)
    app.dependency_overrides[current_actor] = lambda: actor

    @asynccontextmanager
    async def fake_scoped(_a):
        yield conn

    att.scoped = fake_scoped
    att.available = lambda: True
    return TestClient(app)


@pytest.fixture(autouse=True)
def caps():
    learn_roles.CAPS._grants = {
        ("apprenant", "attendance", "sign"), ("apprenant", "attendance", "read"),
        ("formateur", "attendance", "sign"), ("formateur", "attendance", "read"),
        ("admin", "attendance", "read"), ("auditeur", "attendance", "read"),
    }
    learn_roles.CAPS._loaded = True
    yield
    learn_roles.CAPS._grants, learn_roles.CAPS._loaded = set(), False


def nadia(**kw):
    return Actor(user_id=NADIA, role="apprenant", tenant_id=TENANT, **kw)


# ------------------------------------------------------------------ evidence

def test_evidence_comes_from_the_connection_not_the_body():
    """A client that could set its own IP could forge the circumstances of a signature."""
    conn = FakeConn([{"id": "s", "seq_no": 1, "kind": "in",
                      "signed_at": None, "this_hash": "abc"}])
    c = build(conn, nadia())
    r = c.post(f"/api/v1/learn/slots/{SLOT}/sign",
               json={"kind": "in", "ip": "1.2.3.4", "signed_at": "1999-01-01"},
               headers={"user-agent": "iPhone Safari", "x-forwarded-for": "82.66.14.9"})
    assert r.status_code == 201
    evidence = conn.args[0][5]
    assert '"82.66.14.9"' in evidence, "IP must come from the forwarded header"
    assert "1.2.3.4" not in evidence, "a client-supplied IP must be ignored"
    assert "1999" not in evidence, "a client-supplied timestamp must be ignored"
    assert "iPhone Safari" in evidence


def test_signature_time_is_never_client_supplied():
    """`signed_at` is not a parameter at all — Postgres defaults it to now()."""
    conn = FakeConn([{"id": "s", "seq_no": 1, "kind": "in",
                      "signed_at": None, "this_hash": "abc"}])
    c = build(conn, nadia())
    c.post(f"/api/v1/learn/slots/{SLOT}/sign", json={"kind": "in"})
    assert len(conn.args[0]) == 6, "tenant, slot, profile, role, kind, evidence — no time"


def test_a_signer_signs_only_as_themselves():
    """profile_id is taken from the verified actor, never from the request."""
    conn = FakeConn([{"id": "s", "seq_no": 1, "kind": "in",
                      "signed_at": None, "this_hash": "abc"}])
    c = build(conn, nadia())
    c.post(f"/api/v1/learn/slots/{SLOT}/sign",
           json={"kind": "in", "profile_id": "someone-else"})
    assert conn.args[0][2] == NADIA


# ------------------------------------------------------------------ shape

def test_there_is_no_way_to_edit_or_delete_a_signature():
    """An endpoint that always fails is worse than no endpoint."""
    app = FastAPI()
    app.include_router(att.router)
    paths = app.openapi()["paths"]
    for path, ops in paths.items():
        if "signature" in path or path.endswith("/sign"):
            assert "patch" not in ops and "delete" not in ops and "put" not in ops


def test_only_in_or_out_is_accepted():
    c = build(FakeConn([]), nadia())
    r = c.post(f"/api/v1/learn/slots/{SLOT}/sign", json={"kind": "countersign"})
    assert r.status_code == 422, "a learner must not reach the counter-signature path"


# ------------------------------------------------------------------ refusals

def test_policy_refusal_becomes_403():
    """The database refuses; the handler translates rather than re-checking."""
    conn = FakeConn(raises=PgError("42501", 'violates policy "learn_human_only"'))
    c = build(conn, nadia(principal="agent"))
    r = c.post(f"/api/v1/learn/slots/{SLOT}/sign", json={"kind": "in"})
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "not_permitted"


def test_signing_twice_is_a_conflict():
    conn = FakeConn(raises=PgError("23505", "learn_sig_once"))
    c = build(conn, nadia())
    r = c.post(f"/api/v1/learn/slots/{SLOT}/sign", json={"kind": "in"})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "already_exists"


def test_agent_holds_no_sign_capability_whatever_its_delegator_is():
    for role in ("apprenant", "formateur"):
        human = Actor(user_id=NADIA, role=role, tenant_id=TENANT)
        agent = Actor(user_id=NADIA, role=role, tenant_id=TENANT, principal="agent")
        assert learn_roles.can(human, "attendance", "sign") is True
        assert learn_roles.can(agent, "attendance", "sign") is False


def test_admin_and_auditeur_may_read_but_never_attest():
    for role in ("admin", "auditeur"):
        a = Actor(user_id=NADIA, role=role, tenant_id=TENANT)
        assert learn_roles.can(a, "attendance", "read") is True
        assert learn_roles.can(a, "attendance", "sign") is False


# ------------------------------------------------------------------ the sheet

def test_sheet_tallies_states_for_the_auditor():
    conn = FakeConn([
        {"state": "complet", "apprenant_name": "Nadia Cherif"},
        {"state": "complet", "apprenant_name": "Thomas Roy"},
        {"state": "entree_seule", "apprenant_name": "Léa Fontaine"},
        {"state": "absent", "apprenant_name": "Bruno Weber"},
        {"state": "non_signe", "apprenant_name": "Malik Diallo"},
    ])
    c = build(conn, Actor(user_id=NADIA, role="admin", tenant_id=TENANT))
    r = c.get("/api/v1/learn/sessions/abc/sheet")
    assert r.status_code == 200
    assert r.json()["tally"] == {"complet": 2, "entree_seule": 1,
                                 "absent": 1, "non_signe": 1}


def test_verify_endpoint_reports_the_chain():
    conn = FakeConn([{"checked": 3, "valid": True,
                      "first_broken_seq": None, "reason": "intact"}])
    c = build(conn, Actor(user_id=NADIA, role="auditeur", tenant_id=TENANT))
    r = c.get("/api/v1/learn/attendance/verify")
    assert r.status_code == 200
    assert r.json()["valid"] is True and r.json()["reason"] == "intact"
