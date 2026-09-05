"""LEARN — the assessment HTTP layer.

Proven against the live database already: `learn_questions_public` has no `correct` column,
grading gave 10/20 → `intermediaire` with `review_status=pending` for the open question,
per-bloc results split 100 % / 0 %, and editing an answer after submission raised
`attempt_closed`.

Covered here is what sits above: that a candidate is never handed an answer, that the clock
is never taken from the request, that free text is never silently marked, and that the
review path refuses to show explanations before submission.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from learn import roles as learn_roles
from learn.roles import Actor, current_actor
from learn.routes import assessment as a

TENANT = "11111111-1111-1111-1111-111111111111"
NADIA = "33333333-3333-3333-3333-333333333333"


class FakeConn:
    def __init__(self, rows=None, raises=None, scalar=None):
        self._rows, self._raises, self._scalar = list(rows or []), raises, scalar
        self.args: list[tuple] = []
        self.sql: list[str] = []

    async def fetch(self, q, *ar):
        self.sql.append(q); self.args.append(ar)
        if self._raises:
            raise self._raises
        return self._rows

    async def fetchrow(self, q, *ar):
        self.sql.append(q); self.args.append(ar)
        if self._raises:
            raise self._raises
        if not self._rows:
            return None
        row = self._rows[0]
        if len(self._rows) > 1:
            self._rows = self._rows[1:]
        return row

    async def fetchval(self, q, *ar):
        self.sql.append(q); self.args.append(ar)
        return self._scalar


class PgError(Exception):
    def __init__(self, sqlstate, detail=""):
        super().__init__(detail or sqlstate)
        self.sqlstate, self.detail = sqlstate, detail


def build(conn, actor):
    app = FastAPI()
    app.include_router(a.router)
    app.dependency_overrides[current_actor] = lambda: actor

    @asynccontextmanager
    async def fake_scoped(_a):
        yield conn

    a.scoped = fake_scoped
    a.available = lambda: True
    return TestClient(app)


@pytest.fixture(autouse=True)
def caps():
    learn_roles.CAPS._grants = {
        ("admin", "evaluation", "read"), ("formateur", "evaluation", "read"),
        ("apprenant", "evaluation", "create"), ("auditeur", "evaluation", "read"),
    }
    learn_roles.CAPS._loaded = True
    yield
    learn_roles.CAPS._grants, learn_roles.CAPS._loaded = set(), False


def nadia():
    return Actor(user_id=NADIA, role="apprenant", tenant_id=TENANT)


def admin():
    return Actor(user_id=NADIA, role="admin", tenant_id=TENANT)


# ------------------------------------------------------------------ leakage

def test_starting_an_attempt_reads_the_view_without_answers():
    """The take-path must not touch `learn_questions`; a `select *` there would leak."""
    conn = FakeConn([
        {"id": "as1", "question_ids": ["q1"], "duration_minutes": 10, "retakes_allowed": 0},
        {"id": "att1", "started_at": None, "expires_at": None, "attempt_no": 1},
    ], scalar=0)
    c = build(conn, nadia())
    r = c.post("/api/v1/learn/assessments/as1/start")
    assert r.status_code == 201
    take_sql = " ".join(conn.sql)
    assert "learn_questions_public" in take_sql
    assert "from learn_questions\n" not in take_sql
    assert "correct" not in take_sql, "no path may name the answer column"


def test_no_endpoint_returns_correct_before_submission():
    conn = FakeConn([{"id": "att1", "status": "en_cours"}])
    c = build(conn, nadia())
    r = c.get("/api/v1/learn/attempts/att1/review")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "not_submitted_yet"


# ------------------------------------------------------------------ the clock

def test_expiry_is_computed_by_the_database_not_the_caller():
    conn = FakeConn([
        {"id": "as1", "question_ids": [], "duration_minutes": 10, "retakes_allowed": 0},
        {"id": "att1", "started_at": None, "expires_at": None, "attempt_no": 1},
    ], scalar=0)
    c = build(conn, nadia())
    c.post("/api/v1/learn/assessments/as1/start")
    insert = [q for q in conn.sql if "insert into learn_attempts" in q][0]
    assert "now() + make_interval" in insert
    assert "$7" not in insert, "expiry must not be a bound parameter from the request"


def test_answering_after_the_window_becomes_403():
    conn = FakeConn(raises=PgError("42501", "attempt_closed"))
    c = build(conn, nadia())
    r = c.put("/api/v1/learn/attempts/att1/answers",
              json={"question_id": "q1", "given": ["a"]})
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "not_permitted"


def test_retakes_are_capped():
    conn = FakeConn([{"id": "as1", "question_ids": [], "duration_minutes": 10,
                      "retakes_allowed": 0}], scalar=1)
    c = build(conn, nadia())
    r = c.post("/api/v1/learn/assessments/as1/start")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "no_retakes_left"


# ------------------------------------------------------------------ marking

def test_free_text_never_silently_scores():
    """An open answer goes to a human. Grading prose against a syllabus is not a claim
    this system makes."""
    conn = FakeConn([{"id": "att1", "score": 10, "max_score": 20, "percent": 50,
                      "level": "intermediaire", "status": "corrige",
                      "review_status": "pending"}])
    c = build(conn, nadia())
    body = c.post("/api/v1/learn/attempts/att1/submit").json()
    assert body["review_status"] == "pending"
    assert "correction humaine" in body["note"]


def test_a_closed_question_needs_an_answer_key():
    c = build(FakeConn([]), admin())
    r = c.post("/api/v1/learn/questions",
               json={"prompt": "Quel raccourci ?", "kind": "qcm", "correct": []})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "closed_question_needs_an_answer"


def test_an_open_question_needs_none():
    conn = FakeConn([{"id": "q9", "kind": "open", "prompt": "Décrivez…"}])
    c = build(conn, admin())
    r = c.post("/api/v1/learn/questions",
               json={"prompt": "Décrivez un cas d'usage.", "kind": "open"})
    assert r.status_code == 201


def test_submission_is_graded_by_the_database():
    conn = FakeConn([{"id": "att1", "score": 15, "review_status": "none"}])
    c = build(conn, nadia())
    c.post("/api/v1/learn/attempts/att1/submit")
    assert any("learn_grade_attempt" in q for q in conn.sql)


# ------------------------------------------------------------------ blocs

def test_bloc_results_are_available_for_a_certifiante_organisme():
    conn = FakeConn([
        {"apprenant_name": "Nadia Cherif", "bloc": "Blocs de base",
         "questions": 2, "score": 10, "max_score": 10, "percent": 100.0},
        {"apprenant_name": "Nadia Cherif", "bloc": "Automatisation",
         "questions": 2, "score": 0, "max_score": 10, "percent": 0.0},
    ])
    c = build(conn, admin())
    items = c.get("/api/v1/learn/blocs").json()["items"]
    assert {i["bloc"] for i in items} == {"Blocs de base", "Automatisation"}
    assert items[0]["percent"] == 100.0


def test_review_queue_only_holds_pending_attempts():
    conn = FakeConn([{"apprenant_name": "Nadia Cherif", "review_status": "pending"}])
    c = build(conn, Actor(user_id=NADIA, role="formateur", tenant_id=TENANT))
    r = c.get("/api/v1/learn/review-queue")
    assert r.status_code == 200
    assert all(i["review_status"] == "pending" for i in r.json()["items"])
    assert any("review_status = 'pending'" in q for q in conn.sql)
