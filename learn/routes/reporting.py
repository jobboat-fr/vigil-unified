"""LEARN — tableau de bord, export d'audit, notifications, signalement.

The audit export is the point of this module, and its design decision is that it reports
**what is missing as loudly as what is present**. A manifest that quietly omits the four
pieces you do not have is worse than no manifest: it turns a fixable gap into a surprise
during an inspection. So `readiness` counts both halves and the response leads with what is
absent.

Notifications are rows with an approval column rather than a function that sends mail.
Anything leaving in the organisme's name is drafted, approved by a named human, then sent —
which is also what makes the assistant safe to let near them.

Signalement is the narrowest surface here. A report about a formateur must not be readable
by that formateur, so it does not use the session scope everything else uses.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .. import notify as notify_bridge
from ..db import available, scoped, translate
from ..roles import Actor, capabilities_for, current_actor

router = APIRouter(prefix="/api/v1/learn", tags=["learn:reporting"])


def _guard() -> None:
    if not available():
        raise HTTPException(503, {"error": "learn_database_unavailable"})


# ------------------------------------------------------------------ dashboard

@router.get("/dashboard")
async def dashboard(actor: Actor = Depends(current_actor)):
    """One row of counters, narrowed by RLS like everything else.

    Deliberately a list of things needing action rather than vanity totals — open
    réclamations, copies to mark, learners at risk, programmes due for review.
    """
    _guard()
    async with scoped(actor) as c:
        row = await c.fetchrow("select * from learn_dashboard where tenant_id = $1",
                               actor.tenant_id)
    return dict(row) if row else {"tenant_id": actor.tenant_id}


# ------------------------------------------------------------------ audit export

@router.get("/sessions/{session_id}/audit")
async def audit_manifest(session_id: str, request: Request,
                         actor: Actor = Depends(current_actor)):
    """Every piece Qualiopi expects for this session, present or missing.

    The missing list is the finding an auditor would have made, surfaced while there is
    still time to act on it.
    """
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch("select * from learn_audit_manifest($1)", session_id)
        if not rows:
            raise HTTPException(404, {"error": "not_found"})
        sess = await c.fetchrow(
            """select s.code, s.starts_on, s.ends_on, p.title as program_title
                 from learn_sessions s join learn_programs p on p.id = s.program_id
                where s.id = $1""", session_id)
        await c.execute(
            """insert into learn_access_log (tenant_id, actor_id, actor_role, principal,
                                             action, purpose)
               values ($1,$2,$3,$4,'audit_export',$5)""",
            actor.tenant_id, actor.user_id or None, actor.role, actor.principal,
            f"session={session_id}")

    items = [dict(r) for r in rows]
    missing = [i for i in items if not i["present"]]
    return {
        "session": dict(sess) if sess else None,
        "ready": len(missing) == 0,
        "readiness": f"{len(items) - len(missing)}/{len(items)}",
        "missing": missing,
        "items": items,
    }


@router.get("/audit/overview")
async def audit_overview(actor: Actor = Depends(current_actor)):
    """Readiness across every finished session — where to look first."""
    _guard()
    async with scoped(actor) as c:
        sessions = await c.fetch(
            """select id, code, starts_on from learn_sessions
                where status in ('finished','running') order by starts_on desc limit 50""")
        out = []
        for s in sessions:
            rows = await c.fetch("select * from learn_audit_manifest($1)", s["id"])
            missing = [r["piece"] for r in rows if not r["present"]]
            out.append({"session_id": str(s["id"]), "code": s["code"],
                        "starts_on": s["starts_on"],
                        "readiness": f"{len(rows) - len(missing)}/{len(rows)}",
                        "missing": missing})
    return {"items": out}


# ------------------------------------------------------------------ notifications

class NotificationIn(BaseModel):
    kind: str = Field(min_length=2, max_length=60)
    subject: str = Field(min_length=2, max_length=300)
    body: str | None = None
    profile_id: str | None = None
    email: str | None = None
    channel: str = Field(default="email", pattern="^(email|sms|in_app)$")
    related_kind: str | None = None
    related_id: str | None = None


@router.post("/notifications", status_code=201)
async def draft(body: NotificationIn, actor: Actor = Depends(current_actor)):
    """Draft only. Sending is a separate, human act — see `/approve`."""
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """insert into learn_notifications
                     (tenant_id, profile_id, email, kind, channel, subject, body,
                      related_kind, related_id)
                   values ($1,$2,$3,$4,$5,$6,$7,$8,$9) returning *""",
                actor.tenant_id, body.profile_id, body.email, body.kind, body.channel,
                body.subject, body.body, body.related_kind, body.related_id)
    except Exception as e:
        raise translate(e) from e
    return dict(row)


@router.post("/notifications/{notification_id}/approve")
async def approve(notification_id: str, actor: Actor = Depends(current_actor)):
    """A named human takes responsibility for something going out.

    The database refuses to mark a notification sent without this — an agent can fill the
    queue but cannot empty it.
    """
    _guard()
    if actor.principal == "agent":
        raise HTTPException(403, {
            "error": "human_approval_required",
            "detail": "un assistant prépare un envoi, il ne le valide pas"})
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """update learn_notifications
                      set status = 'planifie', approved_by = $2, approved_at = now()
                    where id = $1 and status = 'brouillon' returning *""",
                notification_id, actor.user_id)
    except Exception as e:
        raise translate(e) from e
    if row is None:
        raise HTTPException(409, {"error": "not_draft_or_missing"})
    return dict(row)


@router.post("/notifications/{notification_id}/send")
async def send(notification_id: str, actor: Actor = Depends(current_actor)):
    """Hand an approved notification to hbs-backend, which owns the WhatsApp path.

    The approval is checked three times on one journey — here, by the table constraint, and
    again by the bridge. That is not redundancy for its own sake: each layer is the one a
    different kind of bug would slip past.

    A bridge that is down leaves the row in `echec` with the reason attached, rather than
    silently dropping something an organisme believes it sent.
    """
    _guard()
    if actor.principal == "agent":
        raise HTTPException(403, {"error": "human_approval_required"})
    async with scoped(actor) as c:
        row = await c.fetchrow(
            "select * from learn_notifications where id = $1", notification_id)
        if row is None:
            raise HTTPException(404, {"error": "not_found"})
        if not row["approved_at"]:
            raise HTTPException(409, {
                "error": "not_approved",
                "detail": "un humain nommé doit valider avant l'envoi"})
        if row["status"] == "envoye":
            raise HTTPException(409, {"error": "already_sent"})

        try:
            result = await notify_bridge.dispatch(dict(row))
        except notify_bridge.NotifyRefused as e:
            await c.execute(
                "update learn_notifications set status='echec', error=$2 where id=$1",
                notification_id, str(e))
            raise HTTPException(422, {"error": "refused", "detail": str(e)}) from e
        except notify_bridge.NotifyUnavailable as e:
            await c.execute(
                "update learn_notifications set status='echec', error=$2 where id=$1",
                notification_id, str(e))
            raise HTTPException(503, {"error": "bridge_unavailable",
                                      "detail": str(e)}) from e

        sent = await c.fetchrow(
            "update learn_notifications set status='envoye', sent_at=now(), error=null "
            "where id=$1 returning *", notification_id)
    return {**dict(sent), "bridge": result}


@router.get("/notifications")
async def list_notifications(actor: Actor = Depends(current_actor),
                             status: str | None = Query(None)):
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            """select * from learn_notifications
                where ($1::text is null or status = $1)
                order by scheduled_for desc limit 200""", status)
    return {"items": [dict(r) for r in rows],
            "_can": capabilities_for(actor, "document")}


# ------------------------------------------------------------------ signalement (V10 ind. 12)

class SignalementIn(BaseModel):
    category: str = Field(pattern="^(violence|harcelement|discrimination|autre)$")
    body: str = Field(min_length=10, max_length=8000)
    session_id: str | None = None
    anonymous: bool = False


class HandleIn(BaseModel):
    outcome: str = Field(min_length=10, max_length=4000)
    status: str = Field(default="traite", pattern="^(traite|classe)$")


@router.post("/signalements", status_code=201)
async def report(body: SignalementIn, actor: Actor = Depends(current_actor)):
    """Required from 1 November 2026 by V10 indicator 12.

    Anonymous reports store no reporter at all. That costs the ability to follow up with
    the person, and it is the right trade: a channel that records who spoke is a channel
    people stop using.
    """
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """insert into learn_signalements
                     (tenant_id, session_id, reported_by, anonymous, category, body)
                   values ($1,$2,$3,$4,$5,$6)
                   returning id, category, status, received_at, anonymous""",
                actor.tenant_id, body.session_id,
                None if body.anonymous else (actor.user_id or None),
                body.anonymous, body.category, body.body)
    except Exception as e:
        raise translate(e) from e
    return dict(row)


@router.get("/signalements")
async def list_signalements(actor: Actor = Depends(current_actor)):
    """Admin only, by policy — a report about a formateur must not reach that formateur."""
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            "select * from learn_signalements order by received_at desc")
    return {"items": [dict(r) for r in rows]}


@router.post("/signalements/{signalement_id}/handle")
async def handle(signalement_id: str, body: HandleIn,
                 actor: Actor = Depends(current_actor)):
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """update learn_signalements
                      set status = $2, outcome = $3, handled_by = $4, handled_at = now()
                    where id = $1 returning *""",
                signalement_id, body.status, body.outcome, actor.user_id)
    except Exception as e:
        raise translate(e) from e
    if row is None:
        raise HTTPException(404, {"error": "not_found"})
    return dict(row)


def _json(v: Any) -> str:
    import json
    return json.dumps(v, ensure_ascii=False)
