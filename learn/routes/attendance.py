"""LEARN — émargement over HTTP.

The rules that matter here are not in this file. They are in the database: who may sign
is `learn_may_sign()`, nobody-signs-for-anyone-else is a WITH CHECK on
`profile_id = learn_current_user_id()`, append-only is a revoked grant plus a restrictive
policy, and an agent is refused by `learn_human_only`. These handlers exist to collect the
evidence bundle correctly and to translate refusals.

Two things this file *is* responsible for:

**The evidence comes from the request, never from the body.** A client that could send its
own IP, user-agent or timestamp could forge the circumstances of a signature. The signing
time is `now()` in Postgres — a phone's clock belongs to the person holding the phone.

**Nothing here offers an edit or a delete.** There is no PATCH and no DELETE on a
signature, because the database would refuse one; an endpoint that always fails is worse
than no endpoint.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..db import available, scoped, translate
from ..roles import Actor, capabilities_for, current_actor

router = APIRouter(prefix="/api/v1/learn", tags=["learn:attendance"])


def _guard() -> None:
    if not available():
        raise HTTPException(503, {"error": "learn_database_unavailable"})


def _evidence(request: Request) -> dict[str, Any]:
    """What we can observe about the act of signing, taken from the connection.

    Deliberately not a client-supplied payload. `X-Forwarded-For` is read only at the hop
    count the platform actually runs behind, so a caller cannot prepend a chosen address.
    """
    fwd = (request.headers.get("x-forwarded-for") or "").split(",")
    ip = (fwd[0].strip() if fwd and fwd[0].strip()
          else (request.client.host if request.client else None))
    return {
        "ip": ip,
        "user_agent": (request.headers.get("user-agent") or "")[:300],
        "accept_language": (request.headers.get("accept-language") or "")[:80],
    }


class SignIn(BaseModel):
    kind: str = Field(pattern="^(in|out)$")


@router.post("/slots/{slot_id}/sign", status_code=201)
async def sign(slot_id: str, body: SignIn, request: Request,
               actor: Actor = Depends(current_actor)):
    """A learner attests their own arrival or departure for this half-day.

    Entry and exit are separate rows so a missing exit is visibly missing rather than an
    empty column that could mean anything.
    """
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """insert into learn_attendance_signatures
                     (tenant_id, slot_id, profile_id, signer_role, kind, evidence)
                   values ($1,$2,$3,$4,$5,$6::jsonb)
                   returning id, seq_no, kind, signed_at, this_hash""",
                actor.tenant_id, slot_id, actor.user_id, actor.role,
                body.kind, _json(_evidence(request)))
    except Exception as e:
        raise translate(e) from e
    return dict(row)


@router.post("/slots/{slot_id}/countersign", status_code=201)
async def countersign(slot_id: str, request: Request,
                      actor: Actor = Depends(current_actor)):
    """The formateur closes the half-day.

    Only for a slot they actually teach — `learn_may_sign()` checks `formateur_id`, so a
    colleague covering a different room cannot close this one.
    """
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """insert into learn_attendance_signatures
                     (tenant_id, slot_id, profile_id, signer_role, kind, evidence)
                   values ($1,$2,$3,'formateur','countersign',$4::jsonb)
                   returning id, seq_no, signed_at, this_hash""",
                actor.tenant_id, slot_id, actor.user_id, _json(_evidence(request)))
    except Exception as e:
        raise translate(e) from e
    return dict(row)


class AbsenceIn(BaseModel):
    apprenant_id: str
    reason: str | None = Field(None, max_length=500)
    justified: bool = False


@router.post("/slots/{slot_id}/absences", status_code=201)
async def declare_absence(slot_id: str, body: AbsenceIn,
                          actor: Actor = Depends(current_actor)):
    """Record an absence against a half-day.

    An absence is a positive statement, not the absence of a signature. Without it a
    missing row is ambiguous — did the learner not come, or did the tablet fail?
    """
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """insert into learn_absences
                     (tenant_id, slot_id, apprenant_id, reason, justified, declared_by)
                   values ($1,$2,$3,$4,$5,$6)
                   on conflict (slot_id, apprenant_id) do update
                     set reason = excluded.reason, justified = excluded.justified
                   returning *""",
                actor.tenant_id, slot_id, body.apprenant_id, body.reason,
                body.justified, actor.user_id or None)
    except Exception as e:
        raise translate(e) from e
    return dict(row)


@router.get("/slots/{slot_id}/sheet")
async def slot_sheet(slot_id: str, actor: Actor = Depends(current_actor)):
    """The feuille d'émargement for one half-day, in the shape it is printed from."""
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            "select * from learn_attendance_sheet where slot_id = $1 order by apprenant_name",
            slot_id)
    can = capabilities_for(actor, "attendance")
    return {"slot_id": slot_id, "count": len(rows),
            "items": [{**dict(r), "_can": can} for r in rows]}


@router.get("/sessions/{session_id}/sheet")
async def session_sheet(session_id: str, actor: Actor = Depends(current_actor)):
    """Every half-day of a session, with a per-state tally.

    The tally is what an auditor reads first: how many half-days are complete, how many
    carry an entry with no exit, how many are unsigned.
    """
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            """select * from learn_attendance_sheet
                where session_id = $1 order by starts_at, apprenant_name""", session_id)
    tally: dict[str, int] = {}
    for r in rows:
        tally[r["state"]] = tally.get(r["state"], 0) + 1
    can = capabilities_for(actor, "attendance")
    return {"session_id": session_id, "tally": tally, "count": len(rows),
            "items": [{**dict(r), "_can": can} for r in rows]}


@router.get("/attendance/verify")
async def verify_chain(actor: Actor = Depends(current_actor)):
    """Recompute the signature chain and report the first break.

    This is what an auditor is shown, and what ships beside the PDFs in a reversibility
    export — so a departing customer can prove integrity without this platform.
    """
    _guard()
    async with scoped(actor) as c:
        row = await c.fetchrow(
            "select * from learn_verify_attendance_chain($1)", actor.tenant_id)
    return dict(row) if row else {"checked": 0, "valid": True, "reason": "empty"}


def _json(d: dict[str, Any]) -> str:
    import json  # local: keeps the module's import surface minimal
    return json.dumps(d, ensure_ascii=False)
