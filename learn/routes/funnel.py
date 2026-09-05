"""LEARN — le tunnel : vitrine → demande → positionnement → inscription.

Six endpoints, split down the middle by who may call them.

**Unauthenticated** — the visitor's half. Catalogue, demande, and the positioning test they
take before anyone has minted them an account. These run through `db.public_scope()`, which
is not `scoped()` with an empty actor: the role is `prospect`, the tenant comes from the URL
slug resolved by us, and the connection drops into `learn_public` — a database role holding
INSERT on one table. Even a total failure of this module reaches one organisme and one table.

**Authenticated** — the organisme's half. Listing demandes and converting one into a learner.

The line those two halves must never cross is that **the public path never creates an
account**. An open endpoint that minted profiles is a spam surface with a login page
attached, and worse, it would let anyone put a name on an organisme's roster — which is the
list an auditor reads. So a demande stays a demande until a named admin converts it, and the
positioning result is attached to the demande, not to a person who does not exist yet.

Indicator 8 is why the test sits *here* rather than after enrolment: the organisme must
establish the candidate's level before it takes them, and evidence of that is the thing an
audit asks for.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from .. import invite as invite_svc
from ..db import available, public_scope, resolve_tenant, scoped, translate
from ..roles import Actor, can, capabilities_for, current_actor

router = APIRouter(prefix="/api/v1/learn", tags=["learn:funnel"])

# The wording a visitor actually agreed to, stored with the demande. A boolean column
# proves nothing a year later; the sentence does.
CONSENT_FR = (
    "J'accepte que mes coordonnées soient utilisées par l'organisme de formation pour "
    "traiter ma demande d'inscription. Elles ne sont ni cédées ni revendues."
)


def _guard() -> None:
    if not available():
        raise HTTPException(503, {"error": "learn_database_unavailable"})


async def _tenant(slug: str) -> dict[str, Any]:
    t = await resolve_tenant(slug)
    if t is None:
        raise HTTPException(404, {"error": "unknown_organisme"})
    return t


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip() or None
    return request.client.host if request.client else None


# ============================================================== the visitor's half


@router.get("/public/programs/{tenant_slug}")
async def public_catalogue(tenant_slug: str):
    """The catalogue a stranger reads, and the figures the organisme must publish.

    Every rate ships with the population behind it: V10 indicator 1 requires a published
    statistic to be verifiable, and "96 % satisfaction" over four responses is not.
    """
    _guard()
    t = await _tenant(tenant_slug)
    async with public_scope(str(t["id"])) as c:
        programs = await c.fetch(
            """select pr.id, pr.title, pr.duration_hours, pr.modality, pr.objectives,
                      pr.prerequisites, pr.certifiante, pr.rncp_code,
                      (select min(s.starts_on) from learn_sessions s
                        where s.program_id = pr.id and s.starts_on >= current_date
                          and s.status = 'planned') as next_session
                 from learn_programs pr
                where pr.published order by pr.title""")
        ind = await c.fetchrow("select * from learn_published_indicators($1)", t["id"])
    return {
        "organisme": t["name"],
        "slug": t["slug"],
        "programmes": [dict(r) for r in programs],
        "indicateurs": dict(ind) if ind else None,
        "mention": "chaque taux est publié avec la population qui l'a produit",
        "consent_text": CONSENT_FR,
    }


class LeadIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    phone: str | None = Field(None, max_length=40)
    company: str | None = Field(None, max_length=200)
    message: str | None = Field(None, max_length=2000)
    program_id: str | None = None
    session_id: str | None = None
    campaign: str | None = Field(None, max_length=120)
    consent: bool = False


@router.post("/public/leads/{tenant_slug}", status_code=201)
async def submit_lead(tenant_slug: str, body: LeadIn, request: Request):
    """A visitor asks for a place. This is the moment they enter the system.

    Creates a demande and a positioning link — never an account. The link is returned
    rather than emailed because sending is `hbs-backend`'s job and every outbound message
    passes a named human first; handing the caller the URL keeps that rule intact.
    """
    _guard()
    if not body.consent:
        raise HTTPException(422, {
            "error": "consent_required",
            "detail": "le consentement au traitement de la demande est obligatoire"})
    t = await _tenant(tenant_slug)

    try:
        async with public_scope(str(t["id"])) as c:
            created = await c.fetchval(
                "select learn_submit_lead($1,$2,$3,$4,$5,$6,$7,$8::uuid,$9::uuid,$10,$11,$12)",
                t["id"], body.full_name, str(body.email), CONSENT_FR, body.phone,
                body.company, body.message, body.program_id, body.session_id,
                body.campaign, request.headers.get("referer"), _client_ip(request))
    except Exception as e:
        # 53400 is `configuration_limit_exceeded`, raised by learn_submit_lead's throttle.
        if getattr(e, "sqlstate", None) == "53400":
            raise HTTPException(429, {"error": "rate_limited"}) from e
        raise translate(e) from e

    # The public connection is never told the id of what it wrote — `learn_submit_lead`
    # returns whether a row appeared, not which one. Resolving it, and minting the
    # positioning link, happen on a second connection as a server-side actor: issuing a
    # token is `learn_app`'s job, because a caller able to mint one for an arbitrary lead
    # could sit someone else's positioning test. That actor is pinned to the tenant we
    # resolved from the slug, never to anything in the body, and no route builds an Actor
    # this way from a request.
    server = Actor(user_id="", role="admin", tenant_id=str(t["id"]), principal="human")
    async with scoped(server) as c:
        lead = await c.fetchrow(
            """select id, status from learn_leads
                where tenant_id = $1 and lower(email) = lower($2)
                  and program_id is not distinct from $3::uuid
                  and status in ('recue','positionnement_envoye','positionnement_fait')
                order by created_at desc limit 1""",
            t["id"], str(body.email), body.program_id)
        if lead is None:
            raise HTTPException(500, {"error": "lead_not_persisted"})

        if not created:
            # Already on file. Say so, and do not mint a second link — re-issuing one on
            # demand would make the first email a way to get a fresh test.
            return {"status": lead["status"], "created": False,
                    "next": "votre demande est déjà enregistrée auprès de l'organisme"}

        token = await c.fetchval("select learn_lead_token_issue($1)", lead["id"])
        await c.execute(
            """update learn_leads set status = 'positionnement_envoye', updated_at = now()
                where id = $1 and status = 'recue'""", lead["id"])
        await c.execute(
            """insert into learn_lead_events (tenant_id, lead_id, event, detail, actor_role)
               values ($1,$2,'positionnement_envoye','{}'::jsonb,'system')""",
            t["id"], lead["id"])

    return {
        "status": "positionnement_envoye",
        "created": True,
        "positionnement_path": f"/positionnement/{token}",
        "next": "un test de positionnement établit votre niveau avant l'inscription",
    }


@router.get("/public/positionnement/{token}")
async def positioning_paper(token: str):
    """The questions, without their answers — by construction, not by stripping them.

    `learn_positioning_for_lead()` selects the columns a candidate may see. There is no
    code path here that has ever held a correct answer, so there is none that can leak one.
    """
    _guard()
    try:
        async with public_scope(_NO_TENANT) as c:
            row = await c.fetchrow("select * from learn_positioning_for_lead($1)", token)
    except Exception as e:
        raise _funnel_error(e) from e
    if row is None:
        raise HTTPException(404, {"error": "invalid_or_expired_token"})
    return dict(row)


class PositioningIn(BaseModel):
    answers: list[dict[str, Any]] = Field(default_factory=list, max_length=200)


@router.post("/public/positionnement/{token}")
async def positioning_submit(token: str, body: PositioningIn):
    """Grade in the database and burn the token.

    A score computed anywhere the candidate can reach is a score the candidate chose, so
    the marking happens in `learn_grade_positioning()` — using the same set-equality
    expression `learn_grade_attempt()` uses for enrolled learners.
    """
    _guard()
    try:
        async with public_scope(_NO_TENANT) as c:
            row = await c.fetchrow(
                "select * from learn_grade_positioning($1, $2::jsonb)",
                token, _json(body.answers))
    except Exception as e:
        raise _funnel_error(e) from e
    if row is None:
        raise HTTPException(404, {"error": "invalid_or_expired_token"})
    return {**dict(row),
            "next": "l'organisme revient vers vous pour confirmer votre inscription"}


# ============================================================== the organisme's half


@router.get("/leads")
async def list_leads(actor: Actor = Depends(current_actor), status: str | None = None):
    """The funnel as an admin sees it — one row per demande, with where it stopped."""
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            """select * from learn_funnel
                where ($1::text is null or status = $1)
                order by created_at desc limit 300""", status)
    return {"items": [dict(r) for r in rows],
            "_can": capabilities_for(actor, "enrollment")}


@router.get("/leads/{lead_id}")
async def lead_detail(lead_id: str, actor: Actor = Depends(current_actor)):
    _guard()
    async with scoped(actor) as c:
        row = await c.fetchrow("select * from learn_funnel where id = $1", lead_id)
        if row is None:
            raise HTTPException(404, {"error": "not_found"})
        events = await c.fetch(
            "select event, detail, actor_role, at from learn_lead_events "
            "where lead_id = $1 order by at", lead_id)
    return {**dict(row), "events": [dict(e) for e in events]}


class ConvertIn(BaseModel):
    session_id: str
    company_id: str | None = None
    # Supplied when the organisme already knows the person's auth id, or when the invite
    # service is not configured. Otherwise we invite and use what comes back.
    auth_user_id: str | None = None
    invite_redirect: str | None = None


@router.post("/leads/{lead_id}/convert")
async def convert(lead_id: str, body: ConvertIn, actor: Actor = Depends(current_actor)):
    """Turn a demande into a learner on a session. The end of the tunnel.

    Refused for an agent. Enrolling a person is the organisme putting a name on the list an
    auditor reads and the invoice it issues; an assistant may prepare that and never commit
    it — the same rule that governs sending.
    """
    _guard()
    if actor.principal == "agent":
        raise HTTPException(403, {
            "error": "human_approval_required",
            "detail": "un assistant prépare une inscription, il ne la prononce pas"})
    if not can(actor, "enrollment", "create"):
        raise HTTPException(403, {"error": "capability_missing:enrollment:create"})

    async with scoped(actor) as c:
        lead = await c.fetchrow(
            "select id, full_name, email, status from learn_leads where id = $1", lead_id)
        if lead is None:
            raise HTTPException(404, {"error": "not_found"})

        user_id = body.auth_user_id
        if not user_id:
            if not invite_svc.configured():
                raise HTTPException(503, {
                    "error": "invite_unavailable",
                    "detail": ("LEARN_SUPABASE_URL / LEARN_SUPABASE_SERVICE_KEY absents — "
                               "fournir auth_user_id, ou configurer l'invitation")})
            try:
                user_id = await invite_svc.find_or_invite(
                    lead["email"], lead["full_name"], body.invite_redirect)
            except invite_svc.InviteRefused as e:
                raise HTTPException(422, {"error": "invite_refused",
                                          "detail": str(e)}) from e
            except invite_svc.InviteUnavailable as e:
                raise HTTPException(503, {"error": "invite_unavailable",
                                          "detail": str(e)}) from e

        try:
            row = await c.fetchrow(
                "select * from learn_convert_lead($1,$2,$3,$4)",
                lead_id, body.session_id, user_id, body.company_id)
        except Exception as e:
            raise translate(e) from e

    return {"lead_id": lead_id, "profile_id": str(row["profile_id"]),
            "enrollment_id": str(row["enrollment_id"]),
            "invited": body.auth_user_id is None}


class RefuseIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


@router.post("/leads/{lead_id}/refuse")
async def refuse(lead_id: str, body: RefuseIn, actor: Actor = Depends(current_actor)):
    """Declining is recorded with its reason.

    Indicator 4 asks how the organisme analyses a need; a demande that simply goes quiet
    answers that badly. A refusal with a reason answers it.
    """
    _guard()
    if not can(actor, "enrollment", "create"):
        raise HTTPException(403, {"error": "capability_missing:enrollment:create"})
    async with scoped(actor) as c:
        row = await c.fetchrow(
            """update learn_leads set status='refusee', refused_reason=$2, updated_at=now()
                where id = $1 and status <> 'convertie' returning id, status""",
            lead_id, body.reason)
        if row is None:
            raise HTTPException(409, {"error": "not_refusable"})
        await c.execute(
            """insert into learn_lead_events (tenant_id, lead_id, event, detail,
                                              actor_id, actor_role)
               values ($1,$2,'refusee', jsonb_build_object('reason',$3::text), $4, $5)""",
            actor.tenant_id, lead_id, body.reason, actor.user_id or None, actor.role)
    return dict(row)


# ------------------------------------------------------------------ internals

# The token functions are SECURITY DEFINER and resolve their own tenant from the token, so
# these two routes open a public connection without one. That is not a gap: with no tenant
# set, the restrictive floor from 0001 matches no row on any table, so the connection can
# reach nothing except the functions it was granted EXECUTE on.
_NO_TENANT = ""


def _funnel_error(e: Exception) -> HTTPException:
    state = getattr(e, "sqlstate", None)
    if state == "P0002":
        msg = str(e)
        if "no_positioning_assessment" in msg:
            return HTTPException(409, {"error": "no_positioning_assessment"})
        return HTTPException(404, {"error": "invalid_or_expired_token"})
    return translate(e)


def _json(v: Any) -> str:
    import json
    return json.dumps(v, ensure_ascii=False, default=str)
