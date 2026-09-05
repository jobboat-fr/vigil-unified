"""LEARN — cours, modules, leçons, progression, xAPI.

Two behaviours here are worth stating because they are easy to get wrong quietly.

**Revising a course creates a version, never an edit.** `POST /courses/{id}/revise` inserts
a new row and marks the old one superseded. Sessions already running keep pointing at the
version they started with, so a learner is never assessed on material that changed after
they saw it.

**A locked module stays locked server-side.** `learn_module_unlocked()` decides, and the
lesson payload is withheld rather than merely hidden — a front end that forgets to grey out
a button must not be able to fetch the content anyway.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..db import available, scoped, translate
from ..roles import Actor, capabilities_for, current_actor

router = APIRouter(prefix="/api/v1/learn", tags=["learn:content"])


def _guard() -> None:
    if not available():
        raise HTTPException(503, {"error": "learn_database_unavailable"})


def _rows(records, actor: Actor, resource: str) -> list[dict[str, Any]]:
    can = capabilities_for(actor, resource)
    return [{**dict(r), "_can": can} for r in records]


# ------------------------------------------------------------------ authoring

class CourseIn(BaseModel):
    code: str = Field(min_length=2, max_length=60)
    title: str = Field(min_length=2, max_length=300)
    summary: str | None = None
    program_id: str | None = None
    language: str = "fr"


@router.get("/courses")
async def list_courses(actor: Actor = Depends(current_actor),
                       include_superseded: bool = Query(False)):
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            """select c.*, (select count(*) from learn_modules m where m.course_id = c.id) as modules
                 from learn_courses c
                where ($1 or c.superseded_by is null)
                order by c.code, c.version desc""", include_superseded)
    return {"items": _rows(rows, actor, "program")}


@router.post("/courses", status_code=201)
async def create_course(body: CourseIn, actor: Actor = Depends(current_actor)):
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """insert into learn_courses (tenant_id, program_id, code, title, summary, language)
                   values ($1,$2,$3,$4,$5,$6) returning *""",
                actor.tenant_id, body.program_id, body.code, body.title,
                body.summary, body.language)
    except Exception as e:
        raise translate(e) from e
    return _rows([row], actor, "program")[0]


@router.post("/courses/{course_id}/revise", status_code=201)
async def revise(course_id: str, actor: Actor = Depends(current_actor)):
    """Publish a new version, leaving the old one intact and readable.

    Copies the structure so an author edits a draft rather than the material a running
    cohort is being taught from.
    """
    _guard()
    try:
        async with scoped(actor) as c:
            old = await c.fetchrow("select * from learn_courses where id = $1", course_id)
            if old is None:
                raise HTTPException(404, {"error": "not_found"})
            new = await c.fetchrow(
                """insert into learn_courses
                     (tenant_id, program_id, code, version, title, summary, language)
                   select tenant_id, program_id, code, version + 1, title, summary, language
                     from learn_courses where id = $1 returning *""", course_id)
            # Structure is copied; content edits happen on the new version only.
            await c.execute(
                """insert into learn_modules (tenant_id, course_id, position, title, summary, required)
                   select tenant_id, $2, position, title, summary, required
                     from learn_modules where course_id = $1""", course_id, new["id"])
            await c.execute(
                "update learn_courses set superseded_by = $2 where id = $1",
                course_id, new["id"])
    except HTTPException:
        raise
    except Exception as e:
        raise translate(e) from e
    return {**dict(new), "supersedes": course_id}


# ------------------------------------------------------------------ consuming

@router.get("/courses/{course_id}/outline")
async def outline(course_id: str, actor: Actor = Depends(current_actor)):
    """The course as a learner sees it, with each module's lock state resolved server-side."""
    _guard()
    async with scoped(actor) as c:
        modules = await c.fetch(
            """select m.*, learn_module_unlocked(m.id, $2) as unlocked
                 from learn_modules m where m.course_id = $1 order by m.position""",
            course_id, actor.user_id)
        lessons = await c.fetch(
            """select l.id, l.module_id, l.position, l.title, l.kind, l.duration_minutes,
                      pr.status, pr.progress_pct
                 from learn_lessons l
                 join learn_modules m on m.id = l.module_id
                 left join learn_lesson_progress pr
                        on pr.lesson_id = l.id and pr.profile_id = $2
                where m.course_id = $1 order by m.position, l.position""",
            course_id, actor.user_id)
    by_module: dict[str, list[dict]] = {}
    for lsn in lessons:
        by_module.setdefault(str(lsn["module_id"]), []).append(dict(lsn))
    return {"modules": [{**dict(m), "lessons": by_module.get(str(m["id"]), [])}
                        for m in modules]}


@router.get("/lessons/{lesson_id}")
async def lesson(lesson_id: str, actor: Actor = Depends(current_actor)):
    """The lesson payload — withheld, not merely hidden, when the module is locked."""
    _guard()
    async with scoped(actor) as c:
        row = await c.fetchrow(
            """select l.*, learn_module_unlocked(l.module_id, $2) as unlocked
                 from learn_lessons l where l.id = $1""", lesson_id, actor.user_id)
        if row is None:
            raise HTTPException(404, {"error": "not_found"})
        if not row["unlocked"] and actor.role == "apprenant":
            raise HTTPException(423, {
                "error": "module_locked",
                "detail": "un module requis n'est pas terminé"})
    return dict(row)


class ProgressIn(BaseModel):
    progress_pct: float = Field(ge=0, le=100)
    seconds_spent: int = Field(default=0, ge=0)
    session_id: str | None = None


@router.put("/lessons/{lesson_id}/progress")
async def set_progress(lesson_id: str, body: ProgressIn,
                       actor: Actor = Depends(current_actor)):
    """Record progress, and emit the xAPI statement alongside it.

    The statement is written in the same transaction as the progress row, so the activity
    stream and the progress table can never disagree about whether something happened.
    """
    _guard()
    status = "termine" if body.progress_pct >= 100 else "en_cours"
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """insert into learn_lesson_progress
                     (tenant_id, lesson_id, profile_id, session_id, status,
                      progress_pct, seconds_spent, completed_at)
                   values ($1,$2,$3,$4,$5,$6,$7, case when $5='termine' then now() end)
                   on conflict (lesson_id, profile_id) do update set
                     status = excluded.status,
                     progress_pct = greatest(learn_lesson_progress.progress_pct, excluded.progress_pct),
                     seconds_spent = learn_lesson_progress.seconds_spent + excluded.seconds_spent,
                     last_at = now(),
                     completed_at = coalesce(learn_lesson_progress.completed_at, excluded.completed_at)
                   returning *""",
                actor.tenant_id, lesson_id, actor.user_id, body.session_id,
                status, body.progress_pct, body.seconds_spent)
            await c.execute(
                """insert into learn_xapi_statements
                     (tenant_id, actor_id, verb, object_id, object_type, result)
                   values ($1,$2,$3,$4,'Activity',$5::jsonb)""",
                actor.tenant_id, actor.user_id,
                "completed" if status == "termine" else "progressed",
                f"lesson:{lesson_id}",
                _json({"completion": status == "termine",
                       "progress": float(body.progress_pct),
                       "duration_seconds": body.seconds_spent}))
    except Exception as e:
        raise translate(e) from e
    return dict(row)


# ------------------------------------------------------------------ follow-up

@router.get("/progress")
async def progress(actor: Actor = Depends(current_actor),
                   course_id: str | None = Query(None)):
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            """select * from learn_course_progress
                where ($1::uuid is null or course_id = $1)
                order by full_name""", course_id)
    return {"items": [dict(r) for r in rows]}


@router.get("/at-risk")
async def at_risk(actor: Actor = Depends(current_actor),
                  session_id: str | None = Query(None)):
    """Learners a formateur is expected to do something about.

    V10 indicator 19 stopped accepting connection logs as proof of distance-learning
    follow-up; it wants evidence the follow-up worked. So this is a worklist with a reason
    attached, and the intervention that answers it is an improvement action (P3) pointing
    back at this learner.
    """
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            """select * from learn_at_risk
                where reason <> 'actif'
                  and ($1::uuid is null or session_id = $1)
                order by days_since desc nulls first""", session_id)
    return {"count": len(rows), "items": [dict(r) for r in rows],
            "note": "indicateur 19 : documenter l'intervention, pas seulement la détection"}


def _json(v: Any) -> str:
    import json
    return json.dumps(v, ensure_ascii=False)
