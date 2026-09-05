"""LEARN — qualité: appréciations, réclamations, actions d'amélioration, risques.

Indicator 30 fails for ~44 % of audited organismes, and almost never because no survey was
sent. It fails because nothing connects the feedback to what changed. So the shape of this
module is deliberate:

- **You cannot record an improvement action without naming its cause.** `source_kind` and
  `source_id` are NOT NULL in the schema; the API does not offer a way around that.
- **Closing anything requires saying what happened.** A réclamation marked `resolue` needs
  a resolution; an action marked `faite` needs an outcome. Both are check constraints.
- **Responding needs no account.** A financeur or an entreprise contact will not create a
  login to answer four questions, so the response route authenticates by invitation token —
  the same pattern as the ICS feed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..db import available, pool, scoped, translate
from ..roles import Actor, capabilities_for, current_actor

router = APIRouter(prefix="/api/v1/learn", tags=["learn:qualite"])


def _guard() -> None:
    if not available():
        raise HTTPException(503, {"error": "learn_database_unavailable"})


def _rows(records, actor: Actor, resource: str) -> list[dict[str, Any]]:
    can = capabilities_for(actor, resource)
    return [{**dict(r), "_can": can} for r in records]


# ------------------------------------------------------------------ questionnaires

class SurveyIn(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    audience: str = Field(pattern="^(apprenant|formateur|entreprise|financeur)$")
    timing: str = Field(default="chaud", pattern="^(chaud|froid|positionnement|ponctuel)$")
    code: str | None = None
    questions: list[dict[str, Any]] = []


@router.get("/surveys")
async def list_surveys(actor: Actor = Depends(current_actor)):
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch("select * from learn_surveys where active order by title")
    return {"items": _rows(rows, actor, "evaluation")}


@router.post("/surveys", status_code=201)
async def create_survey(body: SurveyIn, actor: Actor = Depends(current_actor)):
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """insert into learn_surveys (tenant_id, code, title, audience, timing, questions)
                   values ($1,$2,$3,$4,$5,$6::jsonb) returning *""",
                actor.tenant_id, body.code, body.title, body.audience, body.timing,
                _json(body.questions))
    except Exception as e:
        raise translate(e) from e
    return _rows([row], actor, "evaluation")[0]


# ------------------------------------------------------------------ campaigns

class CampaignIn(BaseModel):
    survey_id: str
    audience: str = Field(pattern="^(apprenant|formateur|entreprise|financeur)$")
    due_in_days: int = Field(default=14, ge=1, le=365)
    anonymous: bool = True


@router.post("/sessions/{session_id}/campaigns", status_code=201)
async def open_campaign(session_id: str, body: CampaignIn,
                        actor: Actor = Depends(current_actor)):
    """Open a campaign and invite the audience in one call.

    Invitations are derived from who is actually attached to the session — enrolled
    learners, or the trainers who hold its slots — rather than typed in. An audience list
    assembled by hand is how a response rate quietly becomes meaningless.
    """
    _guard()
    due = datetime.now(timezone.utc) + timedelta(days=body.due_in_days)
    try:
        async with scoped(actor) as c:
            camp = await c.fetchrow(
                """insert into learn_survey_campaigns
                     (tenant_id, survey_id, session_id, audience, due_at, anonymous)
                   values ($1,$2,$3,$4,$5,$6) returning *""",
                actor.tenant_id, body.survey_id, session_id, body.audience,
                due, body.anonymous)

            if body.audience == "apprenant":
                invited = await c.fetch(
                    """insert into learn_survey_invitations (tenant_id, campaign_id, profile_id)
                       select $1, $2, e.apprenant_id from learn_enrollments e
                        where e.session_id = $3 and e.status in ('inscrit','confirme')
                       returning id, profile_id, token""",
                    actor.tenant_id, camp["id"], session_id)
            elif body.audience == "formateur":
                invited = await c.fetch(
                    """insert into learn_survey_invitations (tenant_id, campaign_id, profile_id)
                       select distinct $1, $2, sl.formateur_id from learn_session_slots sl
                        where sl.session_id = $3 and sl.formateur_id is not null
                          and sl.status <> 'cancelled'
                       returning id, profile_id, token""",
                    actor.tenant_id, camp["id"], session_id)
            else:
                # entreprise and financeur are invited by e-mail; they have no account here.
                invited = []
    except Exception as e:
        raise translate(e) from e
    return {**dict(camp), "invited": len(invited),
            "invitations": [dict(r) for r in invited]}


@router.get("/campaigns/{campaign_id}")
async def campaign(campaign_id: str, actor: Actor = Depends(current_actor)):
    _guard()
    async with scoped(actor) as c:
        camp = await c.fetchrow("select * from learn_survey_campaigns where id = $1",
                                campaign_id)
        if camp is None:
            raise HTTPException(404, {"error": "not_found"})
        stats = await c.fetchrow(
            """select count(distinct i.id) as invited, count(distinct r.id) as responded,
                      round(avg(r.score),2) as avg_score
                 from learn_survey_invitations i
                 left join learn_survey_responses r on r.campaign_id = i.campaign_id
                where i.campaign_id = $1""", campaign_id)
    return {**dict(camp), **dict(stats)}


class RespondIn(BaseModel):
    answers: dict[str, Any] = {}
    score: float | None = Field(None, ge=0, le=5)
    comment: str | None = Field(None, max_length=4000)


@router.post("/survey/{token}/respond", status_code=201)
async def respond(token: str, body: RespondIn, request: Request):
    """Answer a survey with nothing but the link.

    No session: an entreprise contact or an OPCO will not create an account to answer four
    questions, and requiring one is how a response rate collapses. When the campaign is
    anonymous the respondent is not recorded on the response at all — only the invitation
    is marked answered, so the rate still counts while the answers stay unattributable.
    """
    _guard()
    p = await pool()
    async with p.acquire() as conn:
        inv = await conn.fetchrow(
            """select i.id, i.tenant_id, i.campaign_id, i.profile_id, i.responded_at,
                      c.anonymous, c.status, c.due_at
                 from learn_survey_invitations i
                 join learn_survey_campaigns c on c.id = i.campaign_id
                where i.token = $1""", token)
        if inv is None:
            raise HTTPException(404, {"error": "not_found"})
        if inv["responded_at"] is not None:
            raise HTTPException(409, {"error": "already_answered"})
        if inv["status"] == "closed":
            raise HTTPException(410, {"error": "campaign_closed"})

        async with conn.transaction():
            row = await conn.fetchrow(
                """insert into learn_survey_responses
                     (tenant_id, campaign_id, invitation_id, profile_id, answers, score, comment)
                   values ($1,$2,$3,$4,$5::jsonb,$6,$7)
                   returning id, submitted_at""",
                inv["tenant_id"], inv["campaign_id"], inv["id"],
                None if inv["anonymous"] else inv["profile_id"],
                _json(body.answers), body.score, body.comment)
            await conn.execute(
                "update learn_survey_invitations set responded_at = now() where id = $1",
                inv["id"])
    return {"id": row["id"], "submitted_at": row["submitted_at"],
            "anonymous": inv["anonymous"]}


# ------------------------------------------------------------------ réclamations

class ReclamationIn(BaseModel):
    subject: str = Field(min_length=3, max_length=300)
    body: str | None = None
    session_id: str | None = None
    severity: str = Field(default="normale", pattern="^(faible|normale|haute|critique)$")
    raised_by_kind: str = Field(default="apprenant",
                                pattern="^(apprenant|formateur|entreprise|financeur|autre)$")
    raised_by_name: str | None = None


class ResolveIn(BaseModel):
    resolution: str = Field(min_length=5, max_length=4000)
    status: str = Field(default="resolue", pattern="^(resolue|classee)$")


@router.get("/reclamations")
async def list_reclamations(actor: Actor = Depends(current_actor),
                            status: str | None = None):
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            """select r.*,
                      (select count(*) from learn_improvement_actions a
                        where a.source_kind='reclamation' and a.source_id = r.id) as actions
                 from learn_reclamations r
                where ($1::text is null or r.status = $1)
                order by r.received_at desc""", status)
    return {"items": _rows(rows, actor, "reclamation")}


@router.post("/reclamations", status_code=201)
async def raise_reclamation(body: ReclamationIn, actor: Actor = Depends(current_actor)):
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """insert into learn_reclamations
                     (tenant_id, session_id, raised_by, raised_by_kind, raised_by_name,
                      subject, body, severity)
                   values ($1,$2,$3,$4,$5,$6,$7,$8) returning *""",
                actor.tenant_id, body.session_id, actor.user_id or None,
                body.raised_by_kind, body.raised_by_name, body.subject,
                body.body, body.severity)
    except Exception as e:
        raise translate(e) from e
    return _rows([row], actor, "reclamation")[0]


@router.post("/reclamations/{reclamation_id}/resolve")
async def resolve(reclamation_id: str, body: ResolveIn,
                  actor: Actor = Depends(current_actor)):
    """Closing requires saying what was done. The check constraint enforces it; this
    endpoint simply has no way to close without one."""
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """update learn_reclamations
                      set status=$2, resolved_at=now(), resolution=$3
                    where id=$1 returning *""",
                reclamation_id, body.status, body.resolution)
    except Exception as e:
        raise translate(e) from e
    if row is None:
        raise HTTPException(404, {"error": "not_found"})
    return _rows([row], actor, "reclamation")[0]


# ------------------------------------------------------------------ actions & risks

class ActionIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    description: str | None = None
    # Required, and there is no default. An action with no cause is the thing that fails
    # an audit, so the API refuses to invent one.
    source_kind: str = Field(pattern="^(evaluation|reclamation|risque|veille|audit)$")
    source_id: str
    owner_id: str | None = None
    due_on: str | None = None


class CloseActionIn(BaseModel):
    outcome: str = Field(min_length=5, max_length=4000)
    status: str = Field(default="faite", pattern="^(faite|abandonnee)$")


@router.get("/actions")
async def list_actions(actor: Actor = Depends(current_actor), status: str | None = None):
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            """select * from learn_improvement_actions
                where ($1::text is null or status = $1)
                order by coalesce(due_on, '2999-12-31'::date), created_at""", status)
    return {"items": _rows(rows, actor, "evaluation")}


@router.post("/actions", status_code=201)
async def create_action(body: ActionIn, actor: Actor = Depends(current_actor)):
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """insert into learn_improvement_actions
                     (tenant_id, title, description, source_kind, source_id, owner_id, due_on)
                   values ($1,$2,$3,$4,$5,$6,$7::date) returning *""",
                actor.tenant_id, body.title, body.description, body.source_kind,
                body.source_id, body.owner_id, body.due_on)
    except Exception as e:
        raise translate(e) from e
    return _rows([row], actor, "evaluation")[0]


@router.post("/actions/{action_id}/close")
async def close_action(action_id: str, body: CloseActionIn,
                       actor: Actor = Depends(current_actor)):
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """update learn_improvement_actions
                      set status=$2, outcome=$3, closed_at=now()
                    where id=$1 returning *""", action_id, body.status, body.outcome)
    except Exception as e:
        raise translate(e) from e
    if row is None:
        raise HTTPException(404, {"error": "not_found"})
    return _rows([row], actor, "evaluation")[0]


class RiskIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    description: str | None = None
    likelihood: int = Field(default=2, ge=1, le=4)
    impact: int = Field(default=2, ge=1, le=4)
    mitigation: str | None = None


@router.get("/risks")
async def list_risks(actor: Actor = Depends(current_actor)):
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            """select *, likelihood * impact as gravity from learn_risks
                order by likelihood * impact desc""")
    return {"items": _rows(rows, actor, "evaluation")}


@router.post("/risks", status_code=201)
async def create_risk(body: RiskIn, actor: Actor = Depends(current_actor)):
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """insert into learn_risks
                     (tenant_id, title, description, likelihood, impact, mitigation)
                   values ($1,$2,$3,$4,$5,$6) returning *""",
                actor.tenant_id, body.title, body.description,
                body.likelihood, body.impact, body.mitigation)
    except Exception as e:
        raise translate(e) from e
    return _rows([row], actor, "evaluation")[0]


# ------------------------------------------------------------------ what gets published

@router.get("/quality/sessions/{session_id}")
async def session_quality(session_id: str, actor: Actor = Depends(current_actor)):
    _guard()
    async with scoped(actor) as c:
        row = await c.fetchrow(
            "select * from learn_quality_by_session where session_id = $1", session_id)
    if row is None:
        raise HTTPException(404, {"error": "not_found"})
    return dict(row)


@router.get("/quality/indicators")
async def indicators(actor: Actor = Depends(current_actor), year: int | None = None):
    """The figures an organisme publishes, each with the population behind it.

    V10 indicator 1 requires a published statistic to be verifiable, so the counts travel
    with the rate: a satisfaction of 4.6 means nothing without the number of responses and
    the response rate beside it.
    """
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            """select * from learn_quality_indicators
                where ($1::int is null or year = $1) order by year desc""", year)
    return {"items": [dict(r) for r in rows],
            "note": "chaque taux est publié avec la population qui l'a produit"}


def _json(v: Any) -> str:
    import json
    return json.dumps(v, ensure_ascii=False)
