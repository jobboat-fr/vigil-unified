"""Studio routes — artifact drafting that enforces the brainstorm-first gate.

This is the end-to-end proof of the VIGIL × WinnyWoo agentic spine: the
`brainstorming` thinking skill (think-first HARD-GATE) wired to a real product
surface. The flow is two explicit stages, mirroring the skill's checklist:

  1. POST /v1/artifacts/brainstorm  → explore intent, propose 2-3 approaches
     with trade-offs + a recommendation + clarifying questions. NO artifact is
     produced. This is the gate.
  2. POST /v1/artifacts              → only after the user picks an approach;
     drafts the structured document and stores it.

Plus list/get/delete and /refine to iterate.

Persistence (Stage 5): the EXISTING `public.artifacts` table (shared with the
prior VIGIL app, RLS on). We map content→text_dump, brief→brief, approach→
approach, the Markdown stays in text_dump, and `version` counts revisions. All
reads/writes are scoped to the authenticated user's id (the db layer's
cross-tenant guard enforces a user_id filter on this table). The LLM call reuses
the council's provider (`winny.council.providers.ask`) which degrades to a
deterministic stub when no API key is set, so the surface never crashes keyless.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from winny.council.providers import ask
from winny.council.registry import worker_registry
from winny.council.canvas_brainstorm import brainstorm_board
from winny.council.structurer import diagram_from_prompt
from winny.council.confiance import PourQui, contexte_identite, donnees
from winny_gateway.auth import scoped_user
from winny_gateway.db import db_delete, db_insert, db_select, db_update
from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/v1/artifacts", tags=["studio"])

_TABLE = "artifacts"
_SHARES = "artifact_shares"
LINK_MAX_DAYS = 30

# Artifact kinds the Studio understands → a one-line shape hint for the drafter.
KINDS: dict[str, str] = {
    "proposal": "a persuasive business proposal with problem, solution, scope, pricing, and next steps",
    "brief": "a tight brief: objective, background, requirements, success criteria, constraints",
    "contract": "a plain-language agreement: parties, scope, deliverables, terms, payment, termination",
    "memo": "an internal decision memo: context, options considered, recommendation, rationale",
    "report": "a structured report: summary, findings, analysis, recommendations",
}


def _uid(user: dict[str, Any]) -> str:
    uid = user.get("sub")
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no user id in token")
    return str(uid)


def _public(row: dict[str, Any]) -> dict[str, Any]:
    """Map a DB row onto the Artifact shape the web client expects."""
    return {
        "id": row.get("id"),
        "title": row.get("title") or "Untitled artifact",
        "kind": row.get("kind") or "proposal",
        "brief": row.get("brief") or "",
        "approach": row.get("approach") or "",
        "content": row.get("text_dump") or "",
        "canvas": row.get("canvas") or None,
        "tldraw": row.get("tldraw") or None,
        "stub": bool(row.get("stub", False)),
        "revisions": max(int(row.get("version") or 1) - 1, 0),
        "access": row.get("_access", "owner"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _primary_worker() -> dict[str, Any]:
    return worker_registry()["primary"]


def _grounding_block(grounding: str | None) -> str:
    if not grounding:
        return ""
    return (
        "\n\nGround your work strictly in these source documents — quote and cite "
        "them, do not invent facts beyond them:\n\n"
        + donnees("documents sources", grounding, surface="studio.document") + "\n"
    )


async def _pour_qui(user: dict[str, Any]) -> PourQui:
    """Pour qui le modèle travaille — tiré de l'authentification et du profil, jamais du texte."""
    uid = _uid(user)
    prof = await _profile(uid) or {}
    organisme = None
    if prof.get("tenant_id"):
        rows = await db_select("learn_tenants", filters={"id": prof["tenant_id"]}, columns="name", limit=1)
        organisme = rows[0]["name"] if rows else None
    cred = user.get("agent_credential") or {}
    return PourQui(user_id=uid, role=prof.get("role"), nom=prof.get("full_name"), organisme=organisme,
                   principal="agent" if cred else "human", agent=cred.get("agent"))


async def _systeme(user: dict[str, Any], base: str) -> str:
    return contexte_identite(await _pour_qui(user)) + "\n\n" + base


def _not_found(artifact_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "artifact_not_found", "artifact_id": artifact_id},
    )


def _valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _share_active(share: dict[str, Any]) -> bool:
    if share.get("revoked_at"):
        return False
    expires = _parse_ts(share.get("expires_at"))
    return expires is None or expires > _now()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _profile(user_id: str) -> dict[str, Any] | None:
    rows = await db_select("learn_profiles", filters={"id": user_id},
                           columns="id,tenant_id,email,full_name,role", limit=1)
    return rows[0] if rows else None


async def _owned_row(artifact_id: str, uid: str) -> dict[str, Any]:
    """L'artefact de cette personne — sinon 404 (jamais 403 : on ne confirme pas qu'il existe)."""
    if not _valid_uuid(artifact_id):
        raise _not_found(artifact_id)
    rows = await db_select(_TABLE, filters={"id": artifact_id, "user_id": uid}, limit=1)
    if not rows:
        raise _not_found(artifact_id)
    return rows[0]


async def _accessible_row(artifact_id: str, uid: str) -> dict[str, Any]:
    """L'artefact, s'il est à cette personne ou partagé avec elle, avec ``_access`` :
    ``owner``, ``edit`` ou ``view``. Un partage révoqué, expiré, ou dont le destinataire a
    changé d'organisme ne donne rien : 404, comme pour un artefact qui n'existe pas."""
    if not _valid_uuid(artifact_id):
        raise _not_found(artifact_id)
    rows = await db_select(_TABLE, filters={"id": artifact_id}, limit=1, allow_unscoped=True)
    if not rows:
        raise _not_found(artifact_id)
    row = rows[0]
    if str(row.get("user_id")) == uid:
        return {**row, "_access": "owner"}
    shares = await db_select(_SHARES, filters={"artifact_id": artifact_id, "grantee_id": uid})
    share = next((s for s in shares if _share_active(s)), None)
    me = await _profile(uid)
    if share is None:
        # Seule exception : l'administration voit les documents de son organisme (super_admin : tous),
        # en lecture seule, et chaque consultation est journalisée.
        role = (me or {}).get("role")
        meme_organisme = bool(row.get("tenant_id")) and str((me or {}).get("tenant_id") or "") == str(row.get("tenant_id"))
        if role == "super_admin" or (role == "admin" and meme_organisme):
            logger.info("Consultation administrative de l'artefact %s par %s (%s).", artifact_id, uid, role,
                        extra={"evenement": "studio.consultation_admin", "artifact_id": artifact_id,
                               "acteur": uid, "role": role, "proprietaire": row.get("user_id")})
            return {**row, "_access": "view"}
        raise _not_found(artifact_id)
    if row.get("tenant_id"):
        if not me or str(me.get("tenant_id") or "") != str(row.get("tenant_id")):
            logger.warning(
                "Partage ignoré : %s n'appartient plus à l'organisme de l'artefact %s.", uid, artifact_id,
                extra={"evenement": "securite.partage_hors_organisme", "artifact_id": artifact_id, "acteur": uid})
            raise _not_found(artifact_id)
    return {**row, "_access": share.get("access") or "view"}


def _require_write(row: dict[str, Any]) -> None:
    if row.get("_access") not in ("owner", "edit"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={
            "error": "lecture_seule", "detail": "Ce document vous est partagé en lecture seule."})


def _require_owner(row: dict[str, Any]) -> None:
    if row.get("_access") != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={
            "error": "reserve_au_proprietaire",
            "detail": "Seule la personne qui a créé ce document peut faire cela."})


# ── Stage 1: brainstorm (the gate) ──────────────────────────────────────────
class BrainstormBody(BaseModel):
    brief: str = Field(description="What the user wants to create, in their words.")
    kind: str = Field(default="proposal", description="Artifact kind: " + " | ".join(KINDS))
    grounding: str | None = Field(default=None, description="Optional Vault/source text to ground in.")


_BRAINSTORM_SYSTEM = (
    "You are the VIGIL × WinnyWoo Studio strategist running the `brainstorming` "
    "discipline. You DO NOT write the final artifact yet. First you think: explore "
    "intent, surface assumptions, and propose distinct approaches with honest "
    "trade-offs and a clear recommendation. 'Too simple to need a design' is a trap "
    "— always think first. Respond ONLY with a JSON object, no prose around it, "
    "matching exactly:\n"
    '{"understanding": "1-2 sentences on what they actually need",'
    ' "clarifying_questions": ["...", "..."],'
    ' "approaches": [{"name": "...", "summary": "...", "tradeoffs": "...", "recommended": true|false}],'
    ' "recommended_design": "a few sentences describing the recommended shape of the artifact"}'
)


@router.post("/brainstorm")
async def brainstorm(body: BrainstormBody, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """Stage 1 — think before drafting. Returns approaches + a design, never an artifact."""
    if body.kind not in KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "unknown_kind", "kind": body.kind, "available": list(KINDS)},
        )
    user_prompt = (
        f"The user wants to create {KINDS[body.kind]}.\n\n"
        "Their brief:\n" + donnees("brief", body.brief, surface="studio.brainstorm", longueur_max=4000)
        + f"{_grounding_block(body.grounding)}\n\n"
        "Think it through and respond ONLY with the JSON object (values written in French)."
    )
    result = await ask(_primary_worker(), user_prompt, system=await _systeme(user, _BRAINSTORM_SYSTEM),
                       temperature=0.4, max_tokens=1200)
    plan = _parse_json(result.get("output", ""))
    return {
        "ok": True,
        "data": {
            "kind": body.kind,
            "brief": body.brief,
            "stub": result.get("stub", False),
            "plan": plan,
        },
    }


# ── Stage 2: draft (only after an approach is chosen) ───────────────────────
class CreateArtifactBody(BaseModel):
    title: str = Field(default="Untitled artifact")
    kind: str = Field(default="proposal")
    brief: str = Field(description="The original brief.")
    approach: str = Field(description="The approved approach/design to draft against (the gate output).")
    grounding: str | None = Field(default=None)


_DRAFT_SYSTEM = (
    "You are the VIGIL × WinnyWoo Studio drafter. The thinking is done and an "
    "approach was approved — now produce the artifact. Write it in clean Markdown, "
    "well structured with headings, concrete and specific. No preamble, no 'here is "
    "your draft' — output only the document body."
)


@router.post("")
async def create_artifact(body: CreateArtifactBody, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """Stage 2 — draft the artifact against an approved approach and store it."""
    if body.kind not in KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "unknown_kind", "kind": body.kind, "available": list(KINDS)},
        )
    uid = _uid(user)
    user_prompt = (
        f"Draft {KINDS[body.kind]}.\n\n"
        "Brief:\n" + donnees("brief", body.brief, surface="studio.document", longueur_max=4000) + "\n\n"
        "Approved approach / design to follow:\n" + donnees("approche retenue", body.approach, surface="studio.document", longueur_max=4000)
        + ""
        f"{_grounding_block(body.grounding)}\n\n"
        "Write the full document now."
    )
    result = await ask(_primary_worker(), user_prompt, system=await _systeme(user, _DRAFT_SYSTEM),
                       temperature=0.5, max_tokens=2400)
    row = await db_insert(
        _TABLE,
        {
            "user_id": uid,
            "title": body.title,
            "kind": body.kind,
            "brief": body.brief,
            "approach": body.approach,
            "text_dump": result.get("output", ""),
            "stub": bool(result.get("stub", False)),
            "status": "draft",
            "version": 1,
        },
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "artifact_write_failed"})
    return {"ok": True, "data": _public(row)}


@router.get("")
async def list_artifacts(portee: str = "moi", user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """Mes documents, et ceux que d'autres m'ont partagés.
    ``?portee=organisme`` : réservé à l'administration — les documents de l'organisme (super_admin : tous)."""
    uid = _uid(user)
    if portee == "organisme":
        return await _list_organisme(uid)

    def summary(r: dict[str, Any]) -> dict[str, Any]:
        art = _public(r)
        if len(art["content"]) > 280:
            art["content"] = art["content"][:280] + "…"
        return art

    rows = await db_select(_TABLE, filters={"user_id": uid}, order_by="-updated_at", limit=100)
    shared: list[dict[str, Any]] = []
    owners: dict[str, str] = {}
    for share in await db_select(_SHARES, filters={"grantee_id": uid}, limit=200):
        if not _share_active(share):
            continue
        try:
            row = await _accessible_row(str(share["artifact_id"]), uid)
        except HTTPException:
            continue
        owner_id = str(row.get("user_id"))
        if owner_id not in owners:
            prof = await _profile(owner_id) or {}
            owners[owner_id] = prof.get("full_name") or prof.get("email") or "Un membre de l'organisme"
        shared.append({**summary(row), "owner_name": owners[owner_id]})
    shared.sort(key=lambda a: a.get("updated_at") or "", reverse=True)
    return {"ok": True, "data": {"artifacts": [summary(r) for r in rows], "shared_with_me": shared}}


async def _list_organisme(uid: str) -> dict[str, Any]:
    me = await _profile(uid) or {}
    role = me.get("role")
    if role not in ("admin", "super_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={
            "error": "reserve_a_l_administration",
            "detail": "La vue de l'organisme est réservée à l'administration."})
    filters = {} if role == "super_admin" else {"tenant_id": me.get("tenant_id")}
    if role == "admin" and not me.get("tenant_id"):
        return {"ok": True, "data": {"artifacts": []}}
    rows = await db_select(_TABLE, filters=filters, order_by="-updated_at", limit=200, allow_unscoped=True)
    owners: dict[str, str] = {}
    out = []
    for r in rows:
        if str(r.get("user_id")) == uid:
            continue
        oid = str(r.get("user_id"))
        if oid not in owners:
            prof = await _profile(oid) or {}
            owners[oid] = prof.get("full_name") or prof.get("email") or "Un membre de l'organisme"
        art = _public({**r, "_access": "view"})
        art["content"] = art["content"][:280] + ("…" if len(art["content"]) > 280 else "")
        out.append({**art, "owner_name": owners[oid]})
    logger.info("Vue organisme du studio ouverte par %s (%s) : %s documents.", uid, role, len(out),
                extra={"evenement": "studio.consultation_admin", "acteur": uid, "role": role, "nombre": len(out)})
    return {"ok": True, "data": {"artifacts": out}}


# ── Lien public en lecture seule ────────────────────────────────────────────
@router.get("/partage/{token}")
async def public_shared_artifact(token: str) -> dict[str, Any]:
    """PUBLIC — un artefact ouvert par son lien de partage. Lecture seule ; ni le brief ni
    l'approche : seulement le document tel que l'auteur le montre."""
    shares = await db_select(_SHARES, filters={"token_hash": _token_hash(token)}, limit=1) if 16 <= len(token) <= 128 else []
    share = shares[0] if shares else None
    if share is None or share.get("revoked_at"):
        logger.warning("Lien de partage refusé : jeton inconnu ou révoqué.",
                       extra={"evenement": "securite.lien_partage_invalide", "raison": "inconnu_ou_revoque"})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "lien_invalide"})
    if not _share_active(share):
        logger.info("Lien de partage expiré ouvert (partage %s).", share.get("id"),
                    extra={"evenement": "securite.lien_partage_invalide", "raison": "expire"})
        raise HTTPException(status_code=status.HTTP_410_GONE, detail={"error": "lien_expire"})
    rows = await db_select(_TABLE, filters={"id": share["artifact_id"]}, limit=1, allow_unscoped=True)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "lien_invalide"})
    await db_update(_SHARES, {"last_opened_at": _now().isoformat()}, filters={"id": share["id"]})
    logger.info("Artefact %s ouvert par lien public.", share["artifact_id"],
                extra={"evenement": "studio.lien_ouvert", "artifact_id": share["artifact_id"]})
    art = _public(rows[0])
    return {"ok": True, "data": {
        "title": art["title"], "kind": art["kind"], "content": art["content"],
        "canvas": art["canvas"], "tldraw": art["tldraw"], "updated_at": art["updated_at"],
        "expires_at": share.get("expires_at"),
    }}


@router.get("/{artifact_id}")
async def get_artifact(artifact_id: str, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    return {"ok": True, "data": _public(await _accessible_row(artifact_id, _uid(user)))}


@router.delete("/{artifact_id}")
async def delete_artifact(artifact_id: str, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    uid = _uid(user)
    _require_owner(await _accessible_row(artifact_id, uid))
    await db_delete(_TABLE, filters={"id": artifact_id, "user_id": uid})
    return {"ok": True, "data": {"deleted": artifact_id}}


# ── Partages ────────────────────────────────────────────────────────────────
class ShareBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    access: Literal["view", "edit"] = "view"


class LinkBody(BaseModel):
    days: int = Field(default=7, ge=1, le=LINK_MAX_DAYS)


def _share_public(share: dict[str, Any], person: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": share.get("id"),
        "access": share.get("access"),
        "created_at": share.get("created_at"),
        "expires_at": share.get("expires_at"),
        "last_opened_at": share.get("last_opened_at"),
        "person": None if person is None else {
            "id": person.get("id"), "email": person.get("email"), "full_name": person.get("full_name"),
        },
    }


@router.get("/{artifact_id}/shares")
async def list_shares(artifact_id: str, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """Qui a accès à ce document, et le lien public s'il y en a un. Le jeton du lien n'est
    jamais renvoyé : il n'est montré qu'une fois, à sa création."""
    uid = _uid(user)
    _require_owner(await _accessible_row(artifact_id, uid))
    people, link = [], None
    for s in await db_select(_SHARES, filters={"artifact_id": artifact_id}, order_by="-created_at", limit=200):
        if not _share_active(s):
            continue
        if s.get("grantee_id"):
            people.append(_share_public(s, await _profile(str(s["grantee_id"]))))
        elif link is None:
            link = _share_public(s)
    return {"ok": True, "data": {"people": people, "link": link}}


@router.post("/{artifact_id}/shares")
async def share_with_person(artifact_id: str, body: ShareBody, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """Partager avec une personne de son organisme, en lecture ou en modification."""
    uid = _uid(user)
    _require_owner(await _accessible_row(artifact_id, uid))
    me = await _profile(uid)
    email = body.email.strip().lower()
    filters: dict[str, Any] = {"email": email}
    if me and me.get("tenant_id"):
        filters["tenant_id"] = me["tenant_id"]
    found = await db_select("learn_profiles", filters=filters, columns="id,tenant_id,email,full_name,role", limit=1)
    target = found[0] if found else None
    if target is None or target.get("role") == "prospect":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={
            "error": "personne_introuvable",
            "detail": "Aucune personne de votre organisme n'a cette adresse."})
    if str(target["id"]) == uid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={
            "error": "partage_a_soi_meme", "detail": "Ce document est déjà le vôtre."})
    existing = [s for s in await db_select(_SHARES, filters={"artifact_id": artifact_id, "grantee_id": target["id"]})
                if _share_active(s)]
    if existing:
        updated = await db_update(_SHARES, {"access": body.access}, filters={"id": existing[0]["id"]})
        share = updated[0] if updated else {**existing[0], "access": body.access}
    else:
        share = await db_insert(_SHARES, {
            "artifact_id": artifact_id, "owner_id": uid, "grantee_id": target["id"], "access": body.access,
        })
    logger.info("Artefact %s partagé en %s avec %s par %s.", artifact_id, body.access, target["id"], uid,
                extra={"evenement": "studio.partage_cree", "artifact_id": artifact_id, "acteur": uid,
                       "destinataire": target["id"], "acces": body.access})
    return {"ok": True, "data": _share_public(share or {}, target)}


@router.delete("/{artifact_id}/shares/{share_id}")
async def revoke_share(artifact_id: str, share_id: str, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """Retirer un accès (personne ou lien). Le partage est révoqué, jamais effacé."""
    uid = _uid(user)
    _require_owner(await _accessible_row(artifact_id, uid))
    rows = await db_select(_SHARES, filters={"id": share_id, "artifact_id": artifact_id}, limit=1) if _valid_uuid(share_id) else []
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "partage_introuvable"})
    await db_update(_SHARES, {"revoked_at": _now().isoformat()}, filters={"id": share_id})
    logger.info("Partage %s de l'artefact %s révoqué par %s.", share_id, artifact_id, uid,
                extra={"evenement": "studio.partage_revoque", "artifact_id": artifact_id, "acteur": uid})
    return {"ok": True, "data": {"revoked": share_id}}


@router.post("/{artifact_id}/link")
async def create_link(artifact_id: str, body: LinkBody, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """Un lien public en lecture seule. Un nouveau lien remplace l'ancien."""
    uid = _uid(user)
    _require_owner(await _accessible_row(artifact_id, uid))
    for s in await db_select(_SHARES, filters={"artifact_id": artifact_id}, limit=200):
        if s.get("token_hash") and _share_active(s):
            await db_update(_SHARES, {"revoked_at": _now().isoformat()}, filters={"id": s["id"]})
    token = secrets.token_urlsafe(24)
    expires = _now() + timedelta(days=body.days)
    share = await db_insert(_SHARES, {
        "artifact_id": artifact_id, "owner_id": uid, "token_hash": _token_hash(token),
        "access": "view", "expires_at": expires.isoformat(),
    })
    logger.info("Lien public créé pour l'artefact %s par %s, valable %s jours.", artifact_id, uid, body.days,
                extra={"evenement": "studio.partage_cree", "artifact_id": artifact_id, "acteur": uid,
                       "acces": "lien_public", "jours": body.days})
    return {"ok": True, "data": {**_share_public(share or {}), "token": token, "path": f"/partage/{token}"}}


class CanvasSaveBody(BaseModel):
    tldraw: dict[str, Any] | None = Field(default=None, description="The tldraw editor document.")
    canvas: dict[str, Any] | None = Field(default=None, description="The {nodes,edges,table} structure.")


@router.patch("/{artifact_id}/canvas")
async def save_canvas(artifact_id: str, body: CanvasSaveBody, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """Persist the user's edits to the artifact canvas (tldraw doc + structure)."""
    uid = _uid(user)
    row = await _accessible_row(artifact_id, uid)
    _require_write(row)
    patch: dict[str, Any] = {}
    if body.tldraw is not None:
        patch["tldraw"] = body.tldraw
    if body.canvas is not None:
        patch["canvas"] = body.canvas
    if patch:
        await db_update(_TABLE, patch, filters={"id": artifact_id, "user_id": str(row["user_id"])})
    return {"ok": True, "data": {"saved": artifact_id}}


class CanvasBrainstormBody(BaseModel):
    prompt: str = Field(default="", description="Free-text brainstorm prompt.")
    board_text: str = Field(default="", description="Text of the current canvas blocks, for context.")
    lens: str = Field(default="ideas", description="ideas|expand|risks|missing|next_steps|critique|summarize|council")
    topic: str = Field(default="")


@router.post("/canvas-brainstorm")
async def canvas_brainstorm(body: CanvasBrainstormBody, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """Brainstorm on the canvas: the council returns blocks (ideas/risks/takes)
    to drop onto the tldraw board, given the board context + a prompt or lens."""
    res = await brainstorm_board(
        prompt=body.prompt, board_text=body.board_text, lens=body.lens, topic=body.topic,
        contexte=contexte_identite(await _pour_qui(user)),
    )
    return {"ok": True, "data": res}


class BlankCanvasBody(BaseModel):
    title: str = Field(default="New board")


@router.post("/blank-canvas")
async def create_blank_canvas(body: BlankCanvasBody, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """Create an empty canvas artifact so the user can jump straight onto a board."""
    row = await db_insert("artifacts", {
        "user_id": _uid(user),
        "title": (body.title or "New board")[:120],
        "kind": "report",
        "brief": "Brainstorming board",
        "text_dump": "",
        "canvas": {"nodes": [], "edges": [], "table": {"columns": ["Action item", "Owner", "Due"], "rows": []}},
        "status": "draft",
        "version": 1,
    })
    return {"ok": True, "data": _public(row or {})}


class CanvasDiagramBody(BaseModel):
    prompt: str = Field(description="What to diagram, e.g. 'our onboarding flow'.")
    board_text: str = Field(default="")
    topic: str = Field(default="")


@router.post("/canvas-diagram")
async def canvas_diagram(body: CanvasDiagramBody, _user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """Agent draws a diagram on demand: prompt -> auto-laid-out {nodes, edges}
    the user can drop onto the board and edit."""
    res = await diagram_from_prompt(prompt=body.prompt, context=body.board_text, topic=body.topic)
    return {"ok": True, "data": res}


class RefineBody(BaseModel):
    instruction: str = Field(description="How to change the artifact, e.g. 'make it shorter and add a timeline'.")


@router.post("/{artifact_id}/refine")
async def refine_artifact(artifact_id: str, body: RefineBody, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """Iterate on an existing artifact with the agent (the Studio side-chat)."""
    uid = _uid(user)
    art = await _accessible_row(artifact_id, uid)
    _require_write(art)
    user_prompt = (
        f"Here is the current {art.get('kind')} (Markdown):\n\n"
        + donnees("document actuel", art.get("text_dump") or "", surface="studio.affiner") + "\n\n"
        "Revise it per this instruction:\n" + donnees("consigne", body.instruction, surface="studio.affiner", longueur_max=2000)
        + "\n\nOutput only the full revised document, in French."
    )
    result = await ask(_primary_worker(), user_prompt, system=await _systeme(user, _DRAFT_SYSTEM),
                       temperature=0.5, max_tokens=2400)
    updated = await db_update(
        _TABLE,
        {
            "text_dump": result.get("output", art.get("text_dump") or ""),
            "stub": bool(result.get("stub", False)),
            "version": int(art.get("version") or 1) + 1,
            "updated_at": datetime.now(UTC).isoformat(),
        },
        filters={"id": artifact_id, "user_id": str(art["user_id"])},
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "artifact_update_failed"})
    return {"ok": True, "data": _public({**updated[0], "_access": art["_access"]})}


# ── L'assistant écrit dans l'artefact ───────────────────────────────────────
class AgentBody(BaseModel):
    instruction: str = Field(default="", max_length=2000, description="Ce que l'assistant doit faire.")
    lens: str | None = Field(default=None, description="Tableau : ideas|expand|risks|missing|next_steps|critique|summarize|council")


def _graphe(art: dict[str, Any]) -> dict[str, Any] | None:
    td = art.get("tldraw")
    if isinstance(td, dict) and isinstance(td.get("reactflow"), dict):
        return td["reactflow"]
    return None


def _texte_tableau(graphe: dict[str, Any] | None, canvas: Any) -> str:
    if graphe:
        return "\n".join(f"- {(n.get('data') or {}).get('label', '')}" for n in graphe.get("nodes") or []
                         if (n.get("data") or {}).get("label"))
    if isinstance(canvas, dict):
        return "\n".join(f"- {n.get('label', '')}" for n in canvas.get("nodes") or [] if n.get("label"))
    return ""


@router.post("/{artifact_id}/agent")
async def agent_in_artifact(artifact_id: str, body: AgentBody, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """L'assistant travaille DANS le document ou le tableau, pour la personne qui le demande.

    Il ne touche qu'un artefact que cette personne peut modifier (le sien, ou partagé en
    modification), et chaque écriture est journalisée avec l'auteur réel : la personne, et
    l'agent s'il agit pour elle.
    """
    uid = _uid(user)
    art = await _accessible_row(artifact_id, uid)
    _require_write(art)
    qui = await _pour_qui(user)
    graphe = _graphe(art)
    est_tableau = graphe is not None or (bool(art.get("canvas")) and not (art.get("text_dump") or "").strip())
    if not est_tableau and not body.instruction.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={
            "error": "consigne_vide", "detail": "Dites à l'assistant ce qu'il doit changer dans le document."})
    now = _now().isoformat()

    if est_tableau:
        res = await brainstorm_board(prompt=body.instruction, board_text=_texte_tableau(graphe, art.get("canvas")),
                                     lens=body.lens or ("ideas" if not body.instruction.strip() else "expand"),
                                     topic=art.get("title") or "", contexte=contexte_identite(qui))
        blocs = res.get("blocks") or []
        noeuds = list((graphe or {}).get("nodes") or [])
        aretes = list((graphe or {}).get("edges") or [])
        bas = max((float((n.get("position") or {}).get("y", 0)) for n in noeuds), default=-160.0) + 180
        for i, b in enumerate(blocs):
            noeuds.append({
                "id": f"assistant-{uuid.uuid4().hex[:8]}",
                "type": "vigil",
                "position": {"x": 60 + (i % 3) * 240, "y": bas + (i // 3) * 170},
                "data": {"label": b["text"], "kind": b.get("lens") or b.get("kind") or "idea", "shape": "note",
                         "color": b.get("color") or "blue", "auteur": "assistant"},
            })
        tldraw = {**(art.get("tldraw") if isinstance(art.get("tldraw"), dict) else {}),
                  "reactflow": {"nodes": noeuds, "edges": aretes}}
        updated = await db_update(_TABLE, {"tldraw": tldraw, "updated_at": now},
                                  filters={"id": artifact_id, "user_id": str(art["user_id"])})
        resume = (f"{len(blocs)} bloc{'s' if len(blocs) > 1 else ''} ajouté{'s' if len(blocs) > 1 else ''} au tableau."
                  if blocs else "L'assistant n'a rien trouvé de pertinent à ajouter.")
        mode, ajouts, stub = "tableau", len(blocs), bool(res.get("stub"))
    else:
        prompt = (
            f"Document actuel ({art.get('kind')}, Markdown) :\n\n"
            + donnees("document actuel", art.get("text_dump") or "", surface="studio.agent") + "\n\n"
            "Demande de la personne :\n" + donnees("consigne", body.instruction, surface="studio.agent", longueur_max=2000)
            + "\n\nRends le document complet révisé, en français, sans préambule."
        )
        result = await ask(_primary_worker(), prompt, system=contexte_identite(qui) + "\n\n" + _DRAFT_SYSTEM,
                           temperature=0.5, max_tokens=2400)
        texte = (result.get("output") or "").strip()
        if not texte:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={
                "error": "assistant_sans_reponse", "detail": "L'assistant n'a rien rendu ; le document est inchangé."})
        updated = await db_update(_TABLE, {"text_dump": texte, "stub": bool(result.get("stub", False)),
                                           "version": int(art.get("version") or 1) + 1, "updated_at": now},
                                  filters={"id": artifact_id, "user_id": str(art["user_id"])})
        resume, mode, ajouts, stub = "Document mis à jour par l'assistant.", "document", 0, bool(result.get("stub"))

    if not updated:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "artifact_update_failed"})
    logger.info("L'assistant a écrit dans l'artefact %s (%s) pour %s%s : %s", artifact_id, mode, uid,
                f" via {qui.agent}" if qui.agent else "", resume,
                extra={"evenement": "studio.agent_ecrit", "artifact_id": artifact_id, "acteur": uid,
                       "agent": qui.agent, "mode": mode, "ajouts": ajouts, "acces": art["_access"]})
    return {"ok": True, "data": {"artifact": _public({**updated[0], "_access": art["_access"]}),
                                 "mode": mode, "resume": resume, "ajouts": ajouts, "stub": stub}}


def _parse_json(text: str) -> dict[str, Any]:
    """Best-effort JSON parse of a model reply that should be a single object."""
    text = text.strip()
    if text.startswith("```"):
        # strip a ```json fence if the model added one
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except (json.JSONDecodeError, ValueError):
                pass
    return {"understanding": "", "clarifying_questions": [], "approaches": [], "recommended_design": text}
