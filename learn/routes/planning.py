"""LEARN — planning: programmes, salles, sessions, créneaux, inscriptions.

Two rules run through every handler here.

**One endpoint per capability, never one per role.** There is no `/admin/sessions` and no
`/formateur/sessions`. Everyone calls the same route; the row set differs because RLS
narrows it. A handler that branched on `actor.role` would be restating a rule the database
already holds, in a second place, where it can drift.

**The database is the authority on refusals.** Handlers do not re-check what a policy or a
trigger already enforces — they translate the refusal. A double-booking comes back as a
409 naming the conflicting range because an exclusion constraint said so, not because a
handler counted overlaps.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..db import available, scoped, translate
from ..roles import Actor, capabilities_for, current_actor

router = APIRouter(prefix="/api/v1/learn", tags=["learn:planning"])


def _guard() -> None:
    if not available():
        raise HTTPException(503, {"error": "learn_database_unavailable",
                                  "detail": "LEARN_DATABASE_URL is not configured"})


def _rows(records, actor: Actor, resource: str) -> list[dict[str, Any]]:
    """Every row leaves with what the caller may do to it.

    The front end renders controls from `_can` rather than inferring them from the role,
    so the rule stays in one place instead of being restated in TypeScript.
    """
    can = capabilities_for(actor, resource)
    return [{**dict(r), "_can": can} for r in records]


# --------------------------------------------------------------------- programmes

class ProgramIn(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    code: str | None = None
    nature: str = "action_formation"
    objectives: str | None = None
    prerequisites: str | None = None
    duration_hours: float = 0
    modality: str = "presentiel"
    certifiante: bool = False
    rncp_code: str | None = None
    published: bool = False


@router.get("/programs")
async def list_programs(actor: Actor = Depends(current_actor)):
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            "select * from learn_programs order by title")
    return {"items": _rows(rows, actor, "program")}


@router.post("/programs", status_code=201)
async def create_program(body: ProgramIn, actor: Actor = Depends(current_actor)):
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """insert into learn_programs
                     (tenant_id, title, code, nature, objectives, prerequisites,
                      duration_hours, modality, certifiante, rncp_code, published)
                   values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) returning *""",
                actor.tenant_id, body.title, body.code, body.nature, body.objectives,
                body.prerequisites, body.duration_hours, body.modality,
                body.certifiante, body.rncp_code, body.published)
    except Exception as e:
        raise translate(e) from e
    return _rows([row], actor, "program")[0]


# --------------------------------------------------------------------- salles

class RoomIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    site: str | None = None
    capacity: int | None = None
    colour: str | None = None


@router.get("/rooms")
async def list_rooms(actor: Actor = Depends(current_actor)):
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch("select * from learn_rooms where active order by name")
    return {"items": _rows(rows, actor, "session")}


@router.post("/rooms", status_code=201)
async def create_room(body: RoomIn, actor: Actor = Depends(current_actor)):
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """insert into learn_rooms (tenant_id, name, site, capacity, colour)
                   values ($1,$2,$3,$4,$5) returning *""",
                actor.tenant_id, body.name, body.site, body.capacity, body.colour)
    except Exception as e:
        raise translate(e) from e
    return _rows([row], actor, "session")[0]


# --------------------------------------------------------------------- sessions

class SessionIn(BaseModel):
    program_id: str
    code: str | None = None
    title: str | None = None
    starts_on: date
    ends_on: date
    modality: str = "presentiel"
    place: str | None = None
    capacity: int = 12


class CancelIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.get("/sessions")
async def list_sessions(
    actor: Actor = Depends(current_actor),
    status: str | None = Query(None),
):
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            """select s.*, p.title as program_title,
                      (select count(*) from learn_enrollments e
                        where e.session_id = s.id and e.status in ('inscrit','confirme')) as enrolled
                 from learn_sessions s join learn_programs p on p.id = s.program_id
                where ($1::text is null or s.status = $1)
                order by s.starts_on desc""", status)
    return {"items": _rows(rows, actor, "session")}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, actor: Actor = Depends(current_actor)):
    """Session detail: the programme, its formateurs, its learners.

    Formateurs are a DISTINCT over the slots rather than a column on the session — co-
    animation and module splits are normal, so "the formateur of this formation" is a
    derived set, not a field.
    """
    _guard()
    async with scoped(actor) as c:
        s = await c.fetchrow(
            """select s.*, p.title as program_title, p.version as program_version,
                      p.next_review_due, p.certifiante, p.rncp_code
                 from learn_sessions s join learn_programs p on p.id = s.program_id
                where s.id = $1""", session_id)
        if s is None:
            raise HTTPException(404, {"error": "not_found"})
        formateurs = await c.fetch(
            """select distinct f.id, f.full_name, f.email
                 from learn_session_slots sl join learn_profiles f on f.id = sl.formateur_id
                where sl.session_id = $1 and sl.status <> 'cancelled'
                order by f.full_name""", session_id)
        learners = await c.fetch(
            """select e.id as enrollment_id, e.status, e.level, e.enrolled_at,
                      pr.id, pr.full_name, pr.email, co.name as company
                 from learn_enrollments e
                 join learn_profiles pr on pr.id = e.apprenant_id
                 left join learn_companies co on co.id = e.company_id
                where e.session_id = $1 order by pr.full_name""", session_id)
        slots = await c.fetch(
            "select * from learn_calendar where session_id = $1 order by starts_at",
            session_id)
    return {
        **dict(s),
        "_can": capabilities_for(actor, "session"),
        "formateurs": [dict(r) for r in formateurs],
        "learners": _rows(learners, actor, "profile"),
        "slots": _rows(slots, actor, "slot"),
    }


@router.post("/sessions", status_code=201)
async def create_session(body: SessionIn, actor: Actor = Depends(current_actor)):
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """insert into learn_sessions
                     (tenant_id, program_id, code, title, starts_on, ends_on,
                      modality, place, capacity, created_by)
                   values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) returning *""",
                actor.tenant_id, body.program_id, body.code, body.title,
                body.starts_on, body.ends_on, body.modality, body.place,
                body.capacity, actor.user_id or None)
    except Exception as e:
        raise translate(e) from e
    return _rows([row], actor, "session")[0]


@router.post("/sessions/{session_id}/cancel")
async def cancel_session(session_id: str, body: CancelIn,
                         actor: Actor = Depends(current_actor)):
    """Cancel, never delete.

    Once a créneau carries a signature the row is evidence under a retention obligation,
    and deleting the session would orphan it. Cancelling keeps the trail and records who
    decided, when and why.
    """
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """update learn_sessions
                      set status='cancelled', cancelled_at=now(), cancel_reason=$2
                    where id=$1 returning *""", session_id, body.reason)
            if row is None:
                raise HTTPException(404, {"error": "not_found"})
            await c.execute(
                """update learn_session_slots
                      set status='cancelled', cancelled_at=now(), cancel_reason=$2
                    where session_id=$1 and status <> 'done'""", session_id, body.reason)
    except HTTPException:
        raise
    except Exception as e:
        raise translate(e) from e
    return _rows([row], actor, "session")[0]


# --------------------------------------------------------------------- créneaux

class GenerateIn(BaseModel):
    dates: list[date] = Field(min_length=1, max_length=200)
    halves: list[str] = ["am", "pm"]
    am_start: time = time(9, 0)
    am_end: time = time(12, 30)
    pm_start: time = time(13, 30)
    pm_end: time = time(17, 0)
    formateur_id: str | None = None
    room_id: str | None = None


@router.post("/sessions/{session_id}/slots:generate", status_code=201)
async def generate_slots(session_id: str, body: GenerateIn,
                         actor: Actor = Depends(current_actor)):
    """Expand dates into real rows.

    Recurrence is materialised here, once, in the tenant's timezone — never evaluated at
    render time. An émargement attaches to a concrete créneau; a rule that could later be
    edited out from under it cannot carry a signature.

    Holidays and unavailability are simply dates the caller leaves out.
    """
    _guard()
    if any(h not in ("am", "pm") for h in body.halves):
        raise HTTPException(422, {"error": "invalid_half"})
    try:
        async with scoped(actor) as c:
            rows = await c.fetch(
                """select * from learn_generate_slots(
                       $1, $2::date[], $3::text[], $4, $5, $6, $7, $8, $9)""",
                session_id, body.dates, body.halves,
                body.am_start, body.am_end, body.pm_start, body.pm_end,
                body.formateur_id, body.room_id)
    except Exception as e:
        raise translate(e) from e
    return {"created": len(rows), "items": _rows(rows, actor, "slot")}


class SlotPatch(BaseModel):
    formateur_id: str | None = None
    room_id: str | None = None
    title: str | None = None
    status: str | None = None


@router.patch("/slots/{slot_id}")
async def update_slot(slot_id: str, body: SlotPatch,
                      actor: Actor = Depends(current_actor)):
    _guard()
    sets, args = [], []
    for i, (col, val) in enumerate(
            (("formateur_id", body.formateur_id), ("room_id", body.room_id),
             ("title", body.title), ("status", body.status)), start=2):
        if val is not None:
            sets.append(f"{col} = ${i}")
            args.append(val)
    if not sets:
        raise HTTPException(422, {"error": "nothing_to_update"})
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                f"update learn_session_slots set {', '.join(sets)} where id = $1 returning *",
                slot_id, *args)
    except Exception as e:
        raise translate(e) from e
    if row is None:
        raise HTTPException(404, {"error": "not_found"})
    return _rows([row], actor, "slot")[0]


@router.post("/slots/{slot_id}/cancel")
async def cancel_slot(slot_id: str, body: CancelIn,
                      actor: Actor = Depends(current_actor)):
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """update learn_session_slots
                      set status='cancelled', cancelled_at=now(), cancel_reason=$2
                    where id=$1 returning *""", slot_id, body.reason)
    except Exception as e:
        raise translate(e) from e
    if row is None:
        raise HTTPException(404, {"error": "not_found"})
    return _rows([row], actor, "slot")[0]


# --------------------------------------------------------------------- inscriptions

class EnrollIn(BaseModel):
    apprenant_id: str
    company_id: str | None = None
    level: str | None = None


@router.post("/sessions/{session_id}/enrollments", status_code=201)
async def enroll(session_id: str, body: EnrollIn, actor: Actor = Depends(current_actor)):
    _guard()
    try:
        async with scoped(actor) as c:
            cap = await c.fetchrow(
                """select s.capacity,
                          (select count(*) from learn_enrollments e
                            where e.session_id = s.id
                              and e.status in ('inscrit','confirme')) as taken
                     from learn_sessions s where s.id = $1""", session_id)
            if cap is None:
                raise HTTPException(404, {"error": "session_not_found"})
            if cap["taken"] >= cap["capacity"]:
                raise HTTPException(409, {"error": "session_full",
                                          "capacity": cap["capacity"]})
            row = await c.fetchrow(
                """insert into learn_enrollments
                     (tenant_id, session_id, apprenant_id, company_id, level)
                   values ($1,$2,$3,$4,$5) returning *""",
                actor.tenant_id, session_id, body.apprenant_id,
                body.company_id, body.level)
    except HTTPException:
        raise
    except Exception as e:
        raise translate(e) from e
    return _rows([row], actor, "enrollment")[0]


@router.delete("/enrollments/{enrollment_id}", status_code=204)
async def unenroll(enrollment_id: str, actor: Actor = Depends(current_actor)):
    _guard()
    try:
        async with scoped(actor) as c:
            res = await c.execute("delete from learn_enrollments where id = $1",
                                  enrollment_id)
    except Exception as e:
        raise translate(e) from e
    if res.endswith(" 0"):
        raise HTTPException(404, {"error": "not_found"})
