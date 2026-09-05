"""LEARN — documents, coffre, rétention, marque blanche.

The awkward truth this module has to hold: **a learner's right to erasure and an
organisme's retention obligation are in direct conflict**, and the obligation wins. Under
RGPD the lawful basis for keeping an émargement is *legal obligation*, so "delete my data"
must not remove it. `privacy.py` in the VIGIL codebase deletes unconditionally; porting
that shape here would hand a learner a button that destroys their organisme's audit trail.

So erasure is partial by design and says so: it reports what it removed and what it kept,
with the date each held item becomes deletable. That is both the correct legal answer and
the honest one.

Everything else follows from the same place — retention computed from who paid, deletion
refused by the database, and every read by an auditeur written to a log that is itself an
audit artefact.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..db import available, scoped, translate
from ..roles import Actor, capabilities_for, current_actor

router = APIRouter(prefix="/api/v1/learn", tags=["learn:documents"])


def _guard() -> None:
    if not available():
        raise HTTPException(503, {"error": "learn_database_unavailable"})


def _rows(records, actor: Actor, resource: str) -> list[dict[str, Any]]:
    can = capabilities_for(actor, resource)
    return [{**dict(r), "_can": can} for r in records]


async def _log(conn, actor: Actor, request: Request, *, vault_id=None,
               document_id=None, action="read", purpose=None) -> None:
    """Record a read of the coffre.

    Written for every reader, not only auditors — a log that only fires for the people you
    distrust proves nothing about the people you do.
    """
    fwd = (request.headers.get("x-forwarded-for") or "").split(",")
    ip = (fwd[0].strip() if fwd and fwd[0].strip()
          else (request.client.host if request.client else None))
    await conn.execute(
        """insert into learn_access_log
             (tenant_id, vault_object_id, document_id, actor_id, actor_role,
              principal, action, purpose, evidence)
           values ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)""",
        actor.tenant_id, vault_id, document_id, actor.user_id or None, actor.role,
        actor.principal, action, purpose,
        _json({"ip": ip, "user_agent": (request.headers.get("user-agent") or "")[:300]}))


# ------------------------------------------------------------------ marque blanche

class BrandingIn(BaseModel):
    legal_name: str = Field(min_length=2, max_length=200)
    logo_url: str | None = None
    primary_colour: str | None = "#1D3FAE"
    address: str | None = None
    nda: str | None = None
    siret: str | None = None
    footer_mentions: str | None = None


@router.get("/branding")
async def get_branding(actor: Actor = Depends(current_actor)):
    _guard()
    async with scoped(actor) as c:
        row = await c.fetchrow("select * from learn_tenant_branding where tenant_id = $1",
                               actor.tenant_id)
    return dict(row) if row else {"tenant_id": actor.tenant_id, "configured": False}


@router.put("/branding")
async def set_branding(body: BrandingIn, actor: Actor = Depends(current_actor)):
    """Each tenant's own identity on every document it sends.

    An organisme will not hand its learners a convocation carrying another company's name,
    so this is not a later feature — it is a column the template engine reads from the
    first document it renders.
    """
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """insert into learn_tenant_branding
                     (tenant_id, legal_name, logo_url, primary_colour, address,
                      nda, siret, footer_mentions, updated_at)
                   values ($1,$2,$3,$4,$5,$6,$7,$8, now())
                   on conflict (tenant_id) do update set
                     legal_name = excluded.legal_name, logo_url = excluded.logo_url,
                     primary_colour = excluded.primary_colour, address = excluded.address,
                     nda = excluded.nda, siret = excluded.siret,
                     footer_mentions = excluded.footer_mentions, updated_at = now()
                   returning *""",
                actor.tenant_id, body.legal_name, body.logo_url, body.primary_colour,
                body.address, body.nda, body.siret, body.footer_mentions)
    except Exception as e:
        raise translate(e) from e
    return dict(row)


# ------------------------------------------------------------------ generation

class GenerateIn(BaseModel):
    template_id: str
    session_id: str | None = None
    subject_id: str | None = None
    company_id: str | None = None
    retention_basis: str = Field(default="direct",
                                 pattern="^(direct|qualiopi|opco|fse|legal)$")
    data: dict[str, Any] = {}


@router.post("/documents", status_code=201)
async def generate(body: GenerateIn, actor: Actor = Depends(current_actor)):
    """Merge a template with the tenant's branding and the supplied data.

    Refuses before producing anything if a required field is missing — a convention with a
    hole where the intitulé should be is worse than no convention, because it looks
    finished.
    """
    _guard()
    try:
        async with scoped(actor) as c:
            tpl = await c.fetchrow(
                "select * from learn_doc_templates where id = $1 and active", body.template_id)
            if tpl is None:
                raise HTTPException(404, {"error": "template_not_found"})

            brand = await c.fetchrow(
                "select * from learn_tenant_branding where tenant_id = $1", actor.tenant_id)
            if brand is None:
                raise HTTPException(409, {
                    "error": "branding_not_configured",
                    "detail": "set /branding first — the NDA is a mandatory mention"})

            merged = {**body.data, "_branding": dict(brand)}
            missing = [f for f in (tpl["required_fields"] or []) if not body.data.get(f)]
            if missing:
                raise HTTPException(422, {"error": "missing_fields", "fields": missing})

            doc = await c.fetchrow(
                """insert into learn_documents
                     (tenant_id, template_id, kind, title, session_id, subject_id,
                      company_id, merged, status, issued_by)
                   values ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,'genere',$9) returning *""",
                actor.tenant_id, tpl["id"], tpl["kind"], tpl["title"], body.session_id,
                body.subject_id, body.company_id, _json(merged), actor.user_id or None)
    except HTTPException:
        raise
    except Exception as e:
        raise translate(e) from e
    return {**dict(doc), "retention_basis": body.retention_basis,
            "_can": capabilities_for(actor, "document")}


@router.get("/documents")
async def list_documents(actor: Actor = Depends(current_actor),
                         session_id: str | None = Query(None)):
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            """select * from learn_documents
                where ($1::uuid is null or session_id = $1)
                order by created_at desc""", session_id)
    return {"items": _rows(rows, actor, "document")}


# ------------------------------------------------------------------ certificat

@router.get("/sessions/{session_id}/certificate/{apprenant_id}")
async def certificate(session_id: str, apprenant_id: str, request: Request,
                      actor: Actor = Depends(current_actor)):
    """The certificat de réalisation, computed from signed attendance.

    Hours are what the émargements say. A certificate that disagrees with its own
    attendance sheet is precisely the finding an auditor is looking for, so no field here
    is typed by hand.
    """
    _guard()
    async with scoped(actor) as c:
        row = await c.fetchrow(
            "select * from learn_certificate_data($1,$2)", session_id, apprenant_id)
        if row is None:
            raise HTTPException(404, {"error": "not_found"})
        brand = await c.fetchrow(
            "select legal_name, nda, address from learn_tenant_branding where tenant_id = $1",
            actor.tenant_id)
        await _log(c, actor, request, document_id=None, action="certificate",
                   purpose=f"session={session_id}")
    out = dict(row)
    out["issuer"] = dict(brand) if brand else None
    if not out["complete"]:
        out["warning"] = ("assiduité incomplète : "
                          f"{out['hours_attended']} h sur {out['hours_total']} h signées")
    return out


# ------------------------------------------------------------------ coffre

@router.get("/vault")
async def list_vault(request: Request, actor: Actor = Depends(current_actor),
                     session_id: str | None = Query(None)):
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            """select v.*, r.expired, r.purgeable, r.days_remaining
                 from learn_vault_objects v
                 join learn_vault_retention r on r.id = v.id
                where ($1::uuid is null or v.session_id = $1)
                order by v.created_at desc""", session_id)
        await _log(c, actor, request, action="list", purpose="vault index")
    return {"items": _rows(rows, actor, "vault_object")}


class HoldIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


@router.post("/vault/{object_id}/hold")
async def place_hold(object_id: str, body: HoldIn, request: Request,
                     actor: Actor = Depends(current_actor)):
    """Freeze a document beyond its retention date — a control, a dispute, an inspection."""
    _guard()
    try:
        async with scoped(actor) as c:
            row = await c.fetchrow(
                """update learn_vault_objects
                      set legal_hold = true, held_reason = $2, held_at = now()
                    where id = $1 returning *""", object_id, body.reason)
            if row is None:
                raise HTTPException(404, {"error": "not_found"})
            await _log(c, actor, request, vault_id=object_id, action="legal_hold",
                       purpose=body.reason)
    except HTTPException:
        raise
    except Exception as e:
        raise translate(e) from e
    return dict(row)


@router.get("/vault/retention")
async def retention(actor: Actor = Depends(current_actor)):
    """What is due for purge, what is held, and what must still be kept."""
    _guard()
    async with scoped(actor) as c:
        rows = await c.fetch(
            "select * from learn_vault_retention order by retention_until")
    held = [dict(r) for r in rows if r["legal_hold"]]
    return {
        "total": len(rows),
        "purgeable": sum(1 for r in rows if r["purgeable"]),
        "held": len(held),
        "items": [dict(r) for r in rows],
    }


# ------------------------------------------------------------------ RGPD

@router.get("/privacy/export")
async def export_me(request: Request, actor: Actor = Depends(current_actor)):
    """Everything held about the caller, in one payload."""
    _guard()
    async with scoped(actor) as c:
        profile = await c.fetchrow("select * from learn_profiles where id = $1", actor.user_id)
        enrolments = await c.fetch(
            "select * from learn_enrollments where apprenant_id = $1", actor.user_id)
        signatures = await c.fetch(
            """select slot_id, kind, signed_at from learn_attendance_signatures
                where profile_id = $1 order by signed_at""", actor.user_id)
        attempts = await c.fetch(
            "select * from learn_gradebook where profile_id = $1", actor.user_id)
        docs = await c.fetch(
            "select id, kind, title, created_at from learn_documents where subject_id = $1",
            actor.user_id)
        await _log(c, actor, request, action="rgpd_export", purpose="droit d'accès")
    return {
        "profile": dict(profile) if profile else None,
        "enrolments": [dict(r) for r in enrolments],
        "attendance": [dict(r) for r in signatures],
        "assessments": [dict(r) for r in attempts],
        "documents": [dict(r) for r in docs],
    }


@router.delete("/privacy/data")
async def erase_me(request: Request, actor: Actor = Depends(current_actor)):
    """Erasure, honestly partial — and it says which parts and until when.

    Attendance signatures and the documents they support are kept under *legal obligation*,
    not under consent, so the right to erasure does not reach them. Silently deleting them
    would break the organisme's obligation; silently keeping them without saying so would
    misrepresent what was done. So the response names both halves.
    """
    _guard()
    async with scoped(actor) as c:
        held = await c.fetch(
            """select v.kind, v.filename, v.retention_until, v.legal_hold
                 from learn_vault_objects v
                where v.subject_id = $1 order by v.retention_until""", actor.user_id)
        sig_count = await c.fetchval(
            "select count(*) from learn_attendance_signatures where profile_id = $1",
            actor.user_id)

        # What consent actually covers: contact details and free-text comments.
        await c.execute(
            """update learn_profiles set full_name = null, email = concat('efface+', id, '@invalid')
                where id = $1""", actor.user_id)
        await c.execute(
            "update learn_survey_responses set comment = null where profile_id = $1",
            actor.user_id)
        await _log(c, actor, request, action="rgpd_erase", purpose="droit à l'effacement")

    return {
        "erased": ["identité de contact", "commentaires d'évaluation"],
        "retained": {
            "reason": "obligation légale (conservation 3 à 10 ans selon le financeur)",
            "attendance_signatures": sig_count,
            "documents": [
                {"kind": d["kind"], "deletable_from": str(d["retention_until"]),
                 "legal_hold": d["legal_hold"]} for d in held
            ],
        },
        "note": ("les preuves d'assiduité et les pièces justificatives sont conservées au "
                 "titre d'une obligation légale, pas d'un consentement"),
    }


def _json(v: Any) -> str:
    import json
    return json.dumps(v, ensure_ascii=False, default=str)
