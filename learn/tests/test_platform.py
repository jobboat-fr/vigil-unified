"""LEARN — importer, tenant-#2 gate, réversibilité, tunnel public.

Proven live: the readiness gate reports `DPA signé = false` and the reversibility manifest
counts ten datasets including the émargements with their hash chain.

Covered here: that an import cannot be applied unseen, that imported attendance is never
converted into a signature, that the gate refuses rather than merely reports, and that the
public funnel creates a request rather than an account.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from learn import roles as learn_roles
from learn.roles import Actor, current_actor
from learn.routes import platform as pf

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
    app.include_router(pf.router)
    app.dependency_overrides[current_actor] = lambda: actor

    @asynccontextmanager
    async def fake_scoped(_a):
        yield conn

    class P:
        @asynccontextmanager
        async def acquire(self):
            yield conn

    async def fake_pool():
        return P()

    pf.scoped = fake_scoped
    pf.pool = fake_pool
    pf.available = lambda: True
    return TestClient(app)


@pytest.fixture(autouse=True)
def caps():
    learn_roles.CAPS._grants = {("admin", "document", "read")}
    learn_roles.CAPS._loaded = True
    yield
    learn_roles.CAPS._grants, learn_roles.CAPS._loaded = set(), False


def admin():
    return Actor(user_id=ADMIN, role="admin", tenant_id=TENANT)


# ------------------------------------------------------------------ importer

def test_imported_attendance_is_never_called_a_signature():
    """A signature asserts a human signed *here*. Back-dating one fabricates evidence."""
    conn = FakeConn([{"id": "j1", "entity": "emargements", "status": "prepare"}])
    c = build(conn, admin())
    body = c.post("/api/v1/learn/imports",
                  json={"source": "digiforma", "entity": "emargements",
                        "rows": [{"nom": "Nadia", "date": "2023-04-12"}]}).json()
    assert "jamais convertis en signatures" in body["note"]
    written = " ".join(conn.sql)
    assert "learn_attendance_signatures" not in written


def test_an_import_cannot_be_applied_without_a_dry_run():
    conn = FakeConn([{"id": "j1", "status": "prepare"}])
    c = build(conn, admin())
    r = c.post("/api/v1/learn/imports/j1/apply")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "dry_run_required"


def test_apply_proceeds_once_the_dry_run_was_seen():
    conn = FakeConn([{"id": "j1", "status": "simule"},
                     {"id": "j1", "status": "applique", "applied_at": "now"}])
    c = build(conn, admin())
    assert c.post("/api/v1/learn/imports/j1/apply").status_code == 200


def test_staging_writes_nothing_to_the_domain():
    conn = FakeConn([{"id": "j1", "entity": "apprenants", "status": "prepare"}])
    c = build(conn, admin())
    c.post("/api/v1/learn/imports",
           json={"source": "csv", "entity": "apprenants",
                 "rows": [{"nom": "X"}, {"nom": "Y"}]})
    written = " ".join(conn.sql)
    for domain in ("learn_profiles", "learn_enrollments", "learn_sessions"):
        assert domain not in written, f"staging must not touch {domain}"


def test_a_source_must_be_one_we_actually_support():
    c = build(FakeConn([]), admin())
    r = c.post("/api/v1/learn/imports",
               json={"source": "moodle", "entity": "apprenants", "rows": []})
    assert r.status_code == 422


# ------------------------------------------------------------------ the gate

def test_readiness_refuses_without_a_signed_dpa():
    """Its absence is a standalone CNIL violation, so this is a gate not a progress bar."""
    conn = FakeConn([
        {"requirement": "DPA signé (art. 28)", "met": False, "detail": "…"},
        {"requirement": "Marque blanche configurée", "met": True, "detail": None},
    ])
    c = build(conn, admin())
    body = c.get("/api/v1/learn/platform/readiness").json()
    assert body["ready"] is False
    assert body["blocking"][0]["requirement"].startswith("DPA")


def test_readiness_passes_when_everything_is_met():
    conn = FakeConn([{"requirement": "DPA signé (art. 28)", "met": True, "detail": None}])
    c = build(conn, admin())
    assert c.get("/api/v1/learn/platform/readiness").json()["ready"] is True


def test_the_register_states_we_are_the_processor():
    conn = FakeConn([{"activity": "Émargement", "legal_basis": "Obligation légale"}])
    c = build(conn, admin())
    body = c.get("/api/v1/learn/platform/register").json()
    assert "sous-traitant" in body["role"]


# ------------------------------------------------------------------ reversibility

def test_reversibility_ships_the_chain_not_just_the_rows():
    conn = FakeConn([
        {"dataset": "emargements", "rows": 96,
         "note": "chaîne de hachage incluse, vérifiable hors plateforme"},
    ])
    c = build(conn, admin())
    body = c.get("/api/v1/learn/platform/reversibility").json()
    assert "vérification" in body["formats"]["emargements"]
    assert "survit à l'abonnement" in body["note"]


# ------------------------------------------------------------------ the funnel

def test_the_public_catalogue_publishes_its_population():
    conn = FakeConn([
        {"id": TENANT, "name": "HBS FORMATION"},
        {"satisfaction": 4.6, "responses": 71, "response_rate": 74.0,
         "learners": 96, "year": 2026},
    ])
    conn._rows = [{"id": TENANT, "name": "HBS FORMATION"}]

    seq = [
        {"id": TENANT, "name": "HBS FORMATION"},
        {"satisfaction": 4.6, "responses": 71, "response_rate": 74.0,
         "learners": 96, "year": 2026},
    ]

    async def fetchrow(q, *a):
        conn.sql.append(q)
        return seq.pop(0) if seq else None
    conn.fetchrow = fetchrow

    c = build(conn, admin())
    body = c.get(f"/api/v1/learn/public/programs/hbs").json()
    assert body["indicateurs"]["responses"] == 71
    assert "population" in body["mention"]


def test_a_lead_creates_a_request_not_an_account():
    """An open endpoint that minted accounts would be a spam surface with a login page."""
    conn = FakeConn([{"id": TENANT}, {"id": "r1", "received_at": None}])
    c = build(conn, admin())
    r = c.post("/api/v1/learn/public/leads/hbs",
               json={"full_name": "Nadia Cherif", "email": "n@delta-log.fr"})
    assert r.status_code == 201
    assert "positionnement" in r.json()["next"]
    written = " ".join(conn.sql)
    assert "insert into learn_profiles" not in written


def test_a_lead_needs_a_real_address():
    c = build(FakeConn([]), admin())
    r = c.post("/api/v1/learn/public/leads/hbs",
               json={"full_name": "X Y", "email": "pas-une-adresse"})
    assert r.status_code == 422
