"""LEARN — the calendar read model and its ICS feed.

`GET /calendar` is deliberately the only calendar endpoint. Admin, formateur, entreprise
and apprenant all call it and all get a different number of rows, because
`learn_calendar` is a `security_invoker` view and RLS narrows it per caller. Proven at the
data layer: 7 / 6 / 1 / 6 rows for the same query.

The ICS feed is the one route here that is not authenticated by a session. Calendar clients
cannot carry a bearer token, so the feed authenticates by an unguessable per-user token in
the path — revocable, and scoped to exactly one profile.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..db import available, pool, scoped, translate
from ..roles import Actor, capabilities_for, current_actor

router = APIRouter(prefix="/api/v1/learn", tags=["learn:calendar"])

ICS_MAX_DAYS = 400


def _guard() -> None:
    if not available():
        raise HTTPException(503, {"error": "learn_database_unavailable"})


@router.get("/calendar")
async def calendar(
    actor: Actor = Depends(current_actor),
    date_from: date = Query(..., alias="from"),
    date_to: date = Query(..., alias="to"),
    formateur_id: str | None = Query(None),
    room_id: str | None = Query(None),
):
    """Everything overlapping a window.

    One range predicate against the stored `tstzrange` and its GiST index — the same
    structure the double-booking constraint uses. Filters are optional narrowings for the
    resource-timeline view ("this trainer's week", "this room's week"); they never widen
    what the caller may see, RLS having already decided that.
    """
    _guard()
    if date_to < date_from:
        raise HTTPException(422, {"error": "range_inverted"})
    if (date_to - date_from).days > ICS_MAX_DAYS:
        raise HTTPException(422, {"error": "range_too_wide", "max_days": ICS_MAX_DAYS})
    async with scoped(actor) as c:
        rows = await c.fetch(
            """select * from learn_calendar
                where starts_at >= $1::date
                  and starts_at <  ($2::date + 1)
                  and ($3::uuid is null or formateur_id = $3)
                  and ($4::uuid is null or room_id = $4)
                order by starts_at, half""",
            date_from, date_to, formateur_id, room_id)
    can = capabilities_for(actor, "slot")
    return {
        "from": date_from, "to": date_to,
        "count": len(rows),
        "items": [{**dict(r), "_can": can} for r in rows],
    }


@router.get("/calendar/resources")
async def resources(actor: Actor = Depends(current_actor)):
    """The lanes of a resource-timeline view: the trainers and rooms this caller can see."""
    _guard()
    async with scoped(actor) as c:
        trainers = await c.fetch(
            """select distinct f.id, f.full_name as name
                 from learn_session_slots sl join learn_profiles f on f.id = sl.formateur_id
                order by 2""")
        rooms = await c.fetch(
            "select id, name, colour, capacity from learn_rooms where active order by name")
    return {"formateurs": [dict(r) for r in trainers],
            "rooms": [dict(r) for r in rooms]}


# ------------------------------------------------------------------ ICS subscription

@router.post("/calendar/token", status_code=201)
async def issue_token(actor: Actor = Depends(current_actor)):
    """Issue (or rotate) my subscription token. Rotating revokes the previous one."""
    _guard()
    try:
        async with scoped(actor) as c:
            await c.execute(
                """update learn_calendar_tokens set revoked_at = now()
                    where profile_id = $1 and revoked_at is null""", actor.user_id)
            row = await c.fetchrow(
                """insert into learn_calendar_tokens (tenant_id, profile_id)
                   values ($1, $2) returning token""",
                actor.tenant_id, actor.user_id)
    except Exception as e:
        raise translate(e) from e
    return {"token": row["token"],
            "url": f"/api/v1/learn/calendar/{row['token']}.ics"}


def _esc(v: str | None) -> str:
    """RFC 5545 escaping. Unescaped commas and semicolons silently corrupt a feed."""
    if not v:
        return ""
    return (v.replace("\\", "\\\\").replace(";", r"\;")
             .replace(",", r"\,").replace("\n", r"\n"))


def _stamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


@router.get("/calendar/{token}.ics")
async def ics_feed(token: str):
    """Subscribable feed. Authenticated by the token in the path, not by a session.

    Deliberately not behind `current_actor`: a calendar client cannot send a bearer token.
    The token resolves to exactly one profile, and the feed is then built with that
    profile's own scope — so a leaked URL exposes that person's schedule and nothing else.
    """
    _guard()
    p = await pool()
    async with p.acquire() as conn:
        owner = await conn.fetchrow(
            """select p.id, p.tenant_id, p.role, p.company_id, p.full_name
                 from learn_calendar_tokens t join learn_profiles p on p.id = t.profile_id
                where t.token = $1 and t.revoked_at is null""", token)
        if owner is None:
            # Same answer for an unknown and a revoked token — no oracle.
            raise HTTPException(404, {"error": "not_found"})

        actor = Actor(
            user_id=str(owner["id"]),
            role=owner["role"],
            tenant_id=str(owner["tenant_id"]) if owner["tenant_id"] else None,
            company_id=str(owner["company_id"]) if owner["company_id"] else None,
        )

    horizon_from = date.today() - timedelta(days=60)
    horizon_to = date.today() + timedelta(days=ICS_MAX_DAYS)
    async with scoped(actor) as c:
        rows = await c.fetch(
            """select * from learn_calendar
                where starts_at >= $1::date and starts_at < $2::date
                  and status <> 'cancelled'
                order by starts_at""", horizon_from, horizon_to)

    now = _stamp(datetime.now(timezone.utc))
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//AZZ&CO//LEARN//FR", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_esc(owner['full_name'] or 'Mon planning')}",
        "X-WR-TIMEZONE:Europe/Paris",
    ]
    for r in rows:
        where = " · ".join(x for x in (r["room_name"], r["modality"]) if x)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{r['id']}@learn.azzco",
            f"DTSTAMP:{now}",
            f"DTSTART:{_stamp(r['starts_at'])}",
            f"DTEND:{_stamp(r['ends_at'])}",
            f"SUMMARY:{_esc(r['title'])}",
            f"LOCATION:{_esc(where)}",
            f"DESCRIPTION:{_esc(r['formateur_name'] or '')}",
            f"STATUS:{'TENTATIVE' if r['status'] == 'planned' else 'CONFIRMED'}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")

    return Response(
        content="\r\n".join(lines) + "\r\n",
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="planning.ics"',
            "Cache-Control": "private, max-age=300",
        },
    )
