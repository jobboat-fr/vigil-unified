"""LEARN — le tunnel : vitrine → demande → positionnement → inscription.

What is worth asserting here is not that the happy path returns 201. It is the set of
things the public half must be *unable* to do, because it is the only unauthenticated write
surface in the product:

    it never creates a profile          — a stranger cannot put a name on the roster
    it never sees a correct answer      — the questions arrive without them, by construction
    it never runs as `learn_app`        — that role can write every table; this one, one
    it never files a réclamation        — a demande is not a complaint (indicator 30)
    it never accepts silence as consent — the wording is stored, not a boolean

And on the organisme's half: converting a demande is a human act, refused for an agent, for
the same reason sending is.

The SQL underneath — the policies, the grants, the throttle — is verified by the live
suite; these tests hold the shape of the calls that reach it.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from learn import invite as invite_svc
from learn import roles as learn_roles
from learn.roles import Actor, current_actor
from learn.routes import funnel as fn

TENANT = "11111111-1111-1111-1111-111111111111"
ADMIN = "22222222-2222-2222-2222-222222222222"
LEAD = "33333333-3333-3333-3333-333333333333"
USER = "44444444-4444-4444-4444-444444444444"


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

    async def fetchval(self, q, *a):
        self.sql.append(q); self.args.append(a)
        if self._raises:
            raise self._raises
        row = await self.fetchrow(q, *a) if self._rows else None
        return row if not isinstance(row, dict) else next(iter(row.values()))

    async def execute(self, q, *a):
        self.sql.append(q); self.args.append(a)
        return "UPDATE 1"


class PgError(Exception):
    def __init__(self, sqlstate, msg=""):
        super().__init__(msg or sqlstate)
        self.sqlstate = sqlstate


def build(conn, actor=None, tenant=True, public_conn=None):
    """Mount the router with both connection paths faked and distinguishable.

    `public_conn` is separate on purpose: several assertions below are about *which* of the
    two paths a statement went down, and one shared fake could not tell them apart.
    """
    app = FastAPI()
    app.include_router(fn.router)
    if actor is not None:
        app.dependency_overrides[current_actor] = lambda: actor

    pub = public_conn if public_conn is not None else conn

    @asynccontextmanager
    async def fake_scoped(_a):
        yield conn

    @asynccontextmanager
    async def fake_public(_t):
        yield pub

    async def fake_resolve(slug):
        return {"id": TENANT, "name": "HBS FORMATION", "slug": slug} if tenant else None

    fn.scoped = fake_scoped
    fn.public_scope = fake_public
    fn.resolve_tenant = fake_resolve
    fn.available = lambda: True
    return TestClient(app)


@pytest.fixture(autouse=True)
def caps():
    learn_roles.CAPS._grants = {
        ("admin", "enrollment", "create"), ("admin", "enrollment", "read"),
        ("prospect", "lead", "create"), ("prospect", "program", "read"),
    }
    learn_roles.CAPS._loaded = True
    yield
    learn_roles.CAPS._grants, learn_roles.CAPS._loaded = set(), False


def admin():
    return Actor(user_id=ADMIN, role="admin", tenant_id=TENANT)


LEAD_BODY = {"full_name": "Nadia Cherif", "email": "n@delta-log.fr",
             "company": "Delta Logistique", "consent": True}


def _submitted():
    """A successful submission: the public side answers "created", the server side then
    resolves the row and mints a token. Two connections, because which statement went down
    which one is most of what these tests are checking."""
    return FakeConn([True]), FakeConn([{"id": LEAD, "status": "recue"}, "tok-abc"])


# ------------------------------------------------------------------ the catalogue

def test_the_catalogue_publishes_the_population_behind_each_rate():
    """"96 % satisfaction" over four responses is not a verifiable statistic (ind. 1)."""
    conn = FakeConn([{"satisfaction": 4.6, "responses": 71, "response_rate": 74.0,
                      "learners": 96, "year": 2026}])
    c = build(conn)
    body = c.get("/api/v1/learn/public/programs/hbs").json()
    assert body["indicateurs"]["responses"] == 71
    assert "population" in body["mention"]
    assert body["organisme"] == "HBS FORMATION"


def test_the_catalogue_never_reads_the_raw_survey_tables():
    """Publishing four aggregates must not require SELECT on the complaints register."""
    conn = FakeConn([{"satisfaction": 4.6, "responses": 71, "response_rate": 74.0,
                      "learners": 96, "year": 2026}])
    c = build(conn)
    c.get("/api/v1/learn/public/programs/hbs")
    written = " ".join(conn.sql)
    assert "learn_published_indicators" in written
    assert "learn_reclamations" not in written
    assert "learn_evaluations" not in written


def test_an_unknown_organisme_is_a_404_not_an_empty_page():
    c = build(FakeConn([]), tenant=False)
    assert c.get("/api/v1/learn/public/programs/nope").status_code == 404


# ------------------------------------------------------------------ the demande

def test_a_demande_never_creates_an_account():
    """The line the public half may not cross."""
    pub, srv = _submitted()
    c = build(srv, public_conn=pub)
    r = c.post("/api/v1/learn/public/leads/hbs", json=LEAD_BODY)
    assert r.status_code == 201
    written = " ".join(pub.sql + srv.sql)
    assert "insert into learn_profiles" not in written
    assert "learn_submit_lead" in " ".join(pub.sql)


def test_the_public_connection_is_never_told_which_row_it_wrote():
    """`learn_submit_lead` returns whether a row appeared, not which one — INSERT …
    RETURNING would have applied the SELECT policy and leaked an id to a stranger."""
    pub, srv = _submitted()
    c = build(srv, public_conn=pub)
    body = c.post("/api/v1/learn/public/leads/hbs", json=LEAD_BODY).json()
    assert "id" not in body
    assert "learn_leads" not in " ".join(pub.sql), "the public path reads nothing"
    assert any("select id, status from learn_leads" in q for q in srv.sql)


def test_a_second_submission_does_not_mint_a_second_link():
    """Re-issuing on demand would turn the first email into a way to get a fresh test."""
    pub = FakeConn([False])
    srv = FakeConn([{"id": LEAD, "status": "positionnement_envoye"}])
    c = build(srv, public_conn=pub)
    body = c.post("/api/v1/learn/public/leads/hbs", json=LEAD_BODY).json()
    assert body["created"] is False
    assert "positionnement_path" not in body
    assert "learn_lead_token_issue" not in " ".join(srv.sql)


def test_a_demande_is_not_filed_as_a_reclamation():
    """The register an auditor reads for indicator 30 stays a register of complaints."""
    pub, srv = _submitted()
    c = build(srv, public_conn=pub)
    c.post("/api/v1/learn/public/leads/hbs", json=LEAD_BODY)
    assert "learn_reclamations" not in " ".join(pub.sql + srv.sql)
    assert "learn_submit_lead" in " ".join(pub.sql)


def test_silence_is_not_consent():
    c = build(FakeConn([]))
    r = c.post("/api/v1/learn/public/leads/hbs",
               json={**LEAD_BODY, "consent": False})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "consent_required"


def test_the_wording_consented_to_travels_with_the_demande():
    """A boolean proves nothing a year later; the sentence shown does."""
    pub, srv = _submitted()
    c = build(srv, public_conn=pub)
    c.post("/api/v1/learn/public/leads/hbs", json=LEAD_BODY)
    assert any(fn.CONSENT_FR in a for args in pub.args for a in args if isinstance(a, str))


def test_a_demande_needs_a_real_address():
    c = build(FakeConn([]))
    r = c.post("/api/v1/learn/public/leads/hbs",
               json={"full_name": "X Y", "email": "pas-une-adresse", "consent": True})
    assert r.status_code == 422


def test_the_throttle_answers_429_not_500():
    """`learn_submit_lead` raises 53400 when the bucket is full — an answer, not a crash."""
    pub = FakeConn(raises=PgError("53400", "rate_limited"))
    c = build(FakeConn([]), public_conn=pub)
    r = c.post("/api/v1/learn/public/leads/hbs", json=LEAD_BODY)
    assert r.status_code == 429


def test_the_positioning_link_is_minted_server_side():
    """Issuing a token needs learn_app; a public role able to mint one could take
    someone else's test."""
    pub, srv = _submitted()
    c = build(srv, public_conn=pub)
    body = c.post("/api/v1/learn/public/leads/hbs", json=LEAD_BODY).json()
    assert body["positionnement_path"].endswith("tok-abc")
    assert "learn_lead_token_issue" in " ".join(srv.sql)
    assert "learn_lead_token_issue" not in " ".join(pub.sql)


# ------------------------------------------------------------------ le positionnement

def test_the_paper_arrives_without_its_answers():
    conn = FakeConn([{"assessment_id": "a1", "title": "Positionnement bureautique",
                      "duration_minutes": 20,
                      "questions": [{"id": "q1", "prompt": "…", "options": []}]}])
    c = build(conn)
    body = c.get("/api/v1/learn/public/positionnement/tok-abc").json()
    assert body["questions"][0].get("correct") is None
    assert "learn_positioning_for_lead" in " ".join(conn.sql)
    assert "learn_questions " not in " ".join(conn.sql)


def test_an_expired_link_is_404_and_says_nothing_more():
    conn = FakeConn(raises=PgError("P0002", "invalid_or_expired_token"))
    c = build(conn)
    r = c.get("/api/v1/learn/public/positionnement/tok-old")
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "invalid_or_expired_token"


def test_an_organisme_with_no_positioning_test_gets_a_clear_409():
    conn = FakeConn(raises=PgError("P0002", "no_positioning_assessment"))
    c = build(conn)
    r = c.get("/api/v1/learn/public/positionnement/tok-abc")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "no_positioning_assessment"


def test_the_score_is_computed_in_the_database():
    """A score computed where the candidate can reach it is a score the candidate chose."""
    conn = FakeConn([{"lead_id": LEAD, "score": 12, "max_score": 20,
                      "percent": 60.0, "level": "intermediaire"}])
    c = build(conn)
    body = c.post("/api/v1/learn/public/positionnement/tok-abc",
                  json={"answers": [{"question_id": "q1", "given": ["a"]}]}).json()
    assert body["level"] == "intermediaire"
    assert "learn_grade_positioning" in " ".join(conn.sql)


# ------------------------------------------------------------------ the conversion

def test_an_agent_cannot_enrol_anyone():
    """Putting a name on the roster is the organisme's act, not its assistant's."""
    agent = Actor(user_id=ADMIN, role="admin", tenant_id=TENANT, principal="agent")
    c = build(FakeConn([{"id": LEAD, "full_name": "N C", "email": "n@delta-log.fr",
                         "status": "positionnement_fait"}]), agent)
    r = c.post(f"/api/v1/learn/leads/{LEAD}/convert",
               json={"session_id": "s1", "auth_user_id": USER})
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "human_approval_required"


def test_a_formateur_cannot_enrol_anyone():
    formateur = Actor(user_id=USER, role="formateur", tenant_id=TENANT)
    c = build(FakeConn([]), formateur)
    r = c.post(f"/api/v1/learn/leads/{LEAD}/convert",
               json={"session_id": "s1", "auth_user_id": USER})
    assert r.status_code == 403


def test_conversion_passes_the_auth_id_through_to_the_database():
    """`learn_profiles.id` IS the auth id — the profile cannot be minted with any other."""
    conn = FakeConn([
        {"id": LEAD, "full_name": "N C", "email": "n@delta-log.fr", "status": "positionnement_fait"},
        {"profile_id": USER, "enrollment_id": "e1"},
    ])
    c = build(conn, admin())
    body = c.post(f"/api/v1/learn/leads/{LEAD}/convert",
                  json={"session_id": "s1", "auth_user_id": USER}).json()
    assert body["profile_id"] == USER
    assert body["invited"] is False
    assert any("learn_convert_lead" in q for q in conn.sql)


def test_without_an_invite_service_conversion_says_so_instead_of_failing_on_a_constraint(
        monkeypatch):
    monkeypatch.setattr(invite_svc, "SUPABASE_URL", "")
    monkeypatch.setattr(invite_svc, "SERVICE_KEY", "")
    conn = FakeConn([{"id": LEAD, "full_name": "N C", "email": "n@delta-log.fr",
                      "status": "positionnement_fait"}])
    c = build(conn, admin())
    r = c.post(f"/api/v1/learn/leads/{LEAD}/convert", json={"session_id": "s1"})
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "invite_unavailable"


def test_conversion_invites_when_no_auth_id_was_supplied(monkeypatch):
    seen = {}

    async def spy(email, name, redirect=None):
        seen.update(email=email, name=name)
        return USER

    monkeypatch.setattr(invite_svc, "configured", lambda: True)
    monkeypatch.setattr(invite_svc, "find_or_invite", spy)
    conn = FakeConn([
        {"id": LEAD, "full_name": "Nadia Cherif", "email": "n@delta-log.fr",
         "status": "positionnement_fait"},
        {"profile_id": USER, "enrollment_id": "e1"},
    ])
    c = build(conn, admin())
    body = c.post(f"/api/v1/learn/leads/{LEAD}/convert", json={"session_id": "s1"}).json()
    assert seen["email"] == "n@delta-log.fr"
    assert body["invited"] is True


def test_a_refusal_records_its_reason():
    """A demande that simply goes quiet answers indicator 4 badly; one with a reason does not."""
    conn = FakeConn([{"id": LEAD, "status": "refusee"}])
    c = build(conn, admin())
    r = c.post(f"/api/v1/learn/leads/{LEAD}/refuse",
               json={"reason": "prérequis non atteints, orientation vers le module socle"})
    assert r.status_code == 200
    assert "learn_lead_events" in " ".join(conn.sql)


def test_a_refusal_needs_an_actual_reason():
    c = build(FakeConn([]), admin())
    assert c.post(f"/api/v1/learn/leads/{LEAD}/refuse",
                  json={"reason": "non"}).status_code == 422
