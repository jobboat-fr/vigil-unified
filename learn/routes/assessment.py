"""LEARN — positionnement, évaluation des acquis, examens, gradebook.

Indicator 8 (positionnement à l'entrée) is a top-five non-conformité; indicator 11 wants
proof of what was acquired. Same machinery, distinguished by `kind`.

Three things this module refuses to do, each because the alternative is a familiar bug:

- **Serve a correct answer to a candidate.** The take-path reads `learn_questions_public`,
  a view without `correct` or `why_correct`. Stripping fields in a handler works until
  someone adds a `select *`.
- **Trust a client's clock.** `expires_at` is computed by Postgres at start and checked by
  Postgres at write. Nothing in the request body influences either.
- **Mark free text automatically.** An open answer scores zero and sends the attempt to a
  human review queue. Claiming to grade prose against a syllabus would be a claim we can't
  support, and an exam is the wrong place to guess.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..db import available, scoped, translate
from ..roles import Actor, capabilities_for, current_actor

router = APIRouter(prefix="/api/v1/learn", tags=["learn:assessment"])


def _guard() -> None:
    if not available():
        raise HTTPException(503, {"error": "learn_database_unavailable"})


def _rows(records, actor: Actor, resource: str) -> list[dict[str, Any]]:
    can = capabilities_for(actor, resource)
    return [{**dict(r), "_can": can} for r in records]


# ------------------------------------------------------------------ authoring

class QuestionIn(BaseModel):
    prompt: str = Field(min_length=3)
    kind: str = Field(default="qcm", pattern="^(qcm|multi|scale|open)$")
    options: list[dict[str, Any]] = []
    correct: list[str] = []
    points: float = 1
    why_correct: str | None = None
    bloc: str | None = None
    bank: str | None = None
    program_id: str | None = None


@router.post("/questions", status_code=201)
async def create_question(body: QuestionIn, actor: Actor = Depends(current_actor)):
    _guard()
    if body.kind != "open" and not body.correct:
        raise HTTPException(422, {"error": "closed_question_needs_an_answer"})
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """insert into learn_questions
                     (tenant_id, program_id, bank, kind, prompt, options, correct,
                      points, why_correct, bloc)
                   values ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8,$9,$10) returning *""",
                actor.tenant_id, body.program_id, body.bank, body.kind, body.prompt,
                _json(body.options), _json(body.correct), body.points,
                body.why_correct, body.bloc)
    except Exception as e:
        raise translate(e) from e
    return _rows([row], actor, "evaluation")[0]


class AssessmentIn(BaseModel):
    title: str = Field(min_length=2)
    kind: str = Field(default="positionnement",
                      pattern="^(positionnement|acquis_entree|acquis_sortie|examen)$")
    program_id: str | None = None
    code: str | None = None
    duration_minutes: int = Field(default=20, ge=1, le=480)
    pass_mark: float | None = None
    question_ids: list[str] = []
    level_thresholds: dict[str, float] = {}


@router.post("/assessments", status_code=201)
async def create_assessment(body: AssessmentIn, actor: Actor = Depends(current_actor)):
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """insert into learn_assessments
                     (tenant_id, program_id, code, title, kind, duration_minutes,
                      pass_mark, question_ids, level_thresholds)
                   values ($1,$2,$3,$4,$5,$6,$7,$8::uuid[],$9::jsonb) returning *""",
                actor.tenant_id, body.program_id, body.code, body.title, body.kind,
                body.duration_minutes, body.pass_mark, body.question_ids,
                _json(body.level_thresholds))
    except Exception as e:
        raise translate(e) from e
    return _rows([row], actor, "evaluation")[0]


@router.get("/assessments")
async def list_assessments(actor: Actor = Depends(current_actor),
                           kind: str | None = Query(None)):
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            """select id, code, title, kind, duration_minutes, pass_mark,
                      cardinality(question_ids) as questions, level_thresholds
                 from learn_assessments
                where active and ($1::text is null or kind = $1) order by title""", kind)
    return {"items": _rows(rows, actor, "evaluation")}


# ------------------------------------------------------------------ taking one

@router.post("/assessments/{assessment_id}/start", status_code=201)
async def start(assessment_id: str, session_id: str | None = None,
                actor: Actor = Depends(current_actor)):
    """Open an attempt and hand back the questions — without their answers.

    `expires_at` is computed by the database from its own clock and the assessment's
    duration. It is never sent by the caller and never read from the body.
    """
    _guard()
    try:
        async with scoped(actor) as c:
            asmt = await c.fetchrow(
                "select * from learn_assessments where id = $1 and active", assessment_id)
            if asmt is None:
                raise HTTPException(404, {"error": "not_found"})

            prior = await c.fetchval(
                """select coalesce(max(attempt_no), 0) from learn_attempts
                    where assessment_id = $1 and profile_id = $2""",
                assessment_id, actor.user_id)
            if prior > asmt["retakes_allowed"]:
                raise HTTPException(409, {"error": "no_retakes_left",
                                          "allowed": asmt["retakes_allowed"]})

            att = await c.fetchrow(
                """insert into learn_attempts
                     (tenant_id, assessment_id, profile_id, session_id, attempt_no, expires_at)
                   values ($1,$2,$3,$4,$5, now() + make_interval(mins => $6))
                   returning id, started_at, expires_at, attempt_no""",
                actor.tenant_id, assessment_id, actor.user_id, session_id,
                prior + 1, asmt["duration_minutes"])

            questions = await c.fetch(
                """select * from learn_questions_public
                    where id = any($1::uuid[]) order by array_position($1::uuid[], id)""",
                asmt["question_ids"])
    except HTTPException:
        raise
    except Exception as e:
        raise translate(e) from e
    return {"attempt": dict(att), "duration_minutes": asmt["duration_minutes"],
            "questions": [dict(q) for q in questions]}


class AnswerIn(BaseModel):
    question_id: str
    given: list[str] = []


@router.put("/attempts/{attempt_id}/answers")
async def answer(attempt_id: str, body: AnswerIn, actor: Actor = Depends(current_actor)):
    """Record or revise one answer while the attempt is open.

    Whether it is still open is decided by `learn_answer_window()`, in the database. A
    handler checking the clock would be checking a value the same request could have
    changed.
    """
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """insert into learn_attempt_answers (tenant_id, attempt_id, question_id, given)
                   values ($1,$2,$3,$4::jsonb)
                   on conflict (attempt_id, question_id)
                     do update set given = excluded.given
                   returning id, question_id, given""",
                actor.tenant_id, attempt_id, body.question_id, _json(body.given))
    except Exception as e:
        raise translate(e) from e
    return dict(row)


@router.post("/attempts/{attempt_id}/submit")
async def submit(attempt_id: str, actor: Actor = Depends(current_actor)):
    """Close the attempt and grade it in the database.

    A score computed anywhere the candidate can reach is a score the candidate chose.
    """
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow("select * from learn_grade_attempt($1)", attempt_id)
    except Exception as e:
        raise translate(e) from e
    if row is None:
        raise HTTPException(404, {"error": "not_found"})
    out = dict(row)
    if out.get("review_status") == "pending":
        out["note"] = ("réponses libres présentes : correction humaine requise avant "
                       "que le résultat ne soit définitif")
    return out


@router.get("/attempts/{attempt_id}/review")
async def review(attempt_id: str, actor: Actor = Depends(current_actor)):
    """The corrected paper — with the explanations, which only exist after submission."""
    _guard()
    async with scoped(actor) as c:
        att = await c.fetchrow("select * from learn_attempts where id = $1", attempt_id)
        if att is None:
            raise HTTPException(404, {"error": "not_found"})
        if att["status"] == "en_cours":
            raise HTTPException(409, {"error": "not_submitted_yet"})
        answers = await c.fetch(
            """select q.prompt, q.kind, q.bloc, q.points as max_points,
                      ans.given, ans.is_correct, ans.points, q.why_correct
                 from learn_attempt_answers ans
                 join learn_questions q on q.id = ans.question_id
                where ans.attempt_id = $1""", attempt_id)
    return {**dict(att), "answers": [dict(a) for a in answers]}


# ------------------------------------------------------------------ staff views

@router.get("/gradebook")
async def gradebook(actor: Actor = Depends(current_actor),
                    session_id: str | None = Query(None)):
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            """select * from learn_gradebook
                where ($1::uuid is null or session_id = $1)
                order by apprenant_name, submitted_at""", session_id)
    return {"items": _rows(rows, actor, "evaluation")}


@router.get("/blocs")
async def blocs(actor: Actor = Depends(current_actor),
                session_id: str | None = Query(None)):
    """Results per bloc de compétences — indicator 3 for a certifiante organisme."""
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            """select * from learn_bloc_results
                where ($1::uuid is null or session_id = $1)
                order by apprenant_name, bloc""", session_id)
    return {"items": [dict(r) for r in rows]}


@router.get("/review-queue")
async def review_queue(actor: Actor = Depends(current_actor)):
    """Attempts holding free text a human still has to read."""
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            """select * from learn_gradebook
                where review_status = 'pending' order by submitted_at""")
    return {"items": _rows(rows, actor, "evaluation")}


def _json(v: Any) -> str:
    import json
    return json.dumps(v, ensure_ascii=False)
