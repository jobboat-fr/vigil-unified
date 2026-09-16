"""Meeting Room routes — ports VIGIL's /v1/rooms surface (the subset needed to
drive the Meeting Room UI) to the unified gateway.

Scope of this port: room lifecycle, Deal Board members (advisors), transcript
capture, and convening the council over the transcript with a live SSE stream.
Avatar/voice/LiveKit/Hume are separate concerns (Stage 3e) and degrade to
absent here.

Persistence (Stage 5): the EXISTING `public.rooms` table (shared with the prior
VIGIL app, RLS on). We map title→title, lens→default_lens, members→members
jsonb, transcript→transcript jsonb. Every read/write is scoped to the
authenticated user's id (the db layer's cross-tenant guard enforces a user_id
filter on this table).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from winny.council import ROLE_SYSTEM_PROMPTS, REVIEWER_SYSTEM_PROMPT, TASK_MATRIX
from winny.council.intervention import WEIGHT_DEFAULTS, check_intervention
from winny.council.summarizer import summarize_meeting
from winny.council.structurer import structure_meeting
from winny_gateway import avatar as avatar_mod
from winny_gateway import breakouts as bk
from winny_gateway import learn_api, learn_link, presence
from winny_gateway import livekit as lk
from winny_gateway.auth import get_current_user, scoped_user
from winny_gateway.db import DatabaseError, db_delete, db_insert, db_select, db_update
from winny_gateway.logging import get_logger
from winny_gateway.routes.vigil.council import _run_council_sse

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/rooms", tags=["rooms"])

_TABLE = "rooms"

# Template advisors for the Deal Board — map to council lenses.
TEMPLATE_MEMBERS = {
    "cfo": {"lens": "cfo_review", "name": "Chief Financial Officer", "title": "CFO", "voiceColor": "#2563EB"},
    "cto": {"lens": "tech_review", "name": "Chief Technology Officer", "title": "CTO", "voiceColor": "#7C3AED"},
    "legal": {"lens": "legal_review", "name": "General Counsel", "title": "Legal", "voiceColor": "#059669"},
    "product": {"lens": "product_review", "name": "Head of Product", "title": "Product", "voiceColor": "#DB2777"},
}


def _uid(user: dict[str, Any]) -> str:
    uid = user.get("sub")
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no user id in token")
    return str(uid)


def _public(row: dict[str, Any]) -> dict[str, Any]:
    """Map a DB row onto the Room shape the web client expects."""
    return {
        "id": row.get("id"),
        "title": row.get("title") or "Advisory Session",
        "lens": row.get("default_lens") or "cfo_review",
        "members": row.get("members") or [],
        "transcript": row.get("transcript") or [],
        "status": row.get("status") or "active",
        "summary": row.get("summary") or "",
        "concluded_at": row.get("concluded_at"),
        "created_at": row.get("created_at"),
        "kind": row.get("kind") or "meeting",
        "learn_session_id": row.get("learn_session_id"),
        "learn_slot_id": row.get("learn_slot_id"),
    }


async def _owned_row(room_id: str, uid: str) -> dict[str, Any]:
    rows = await db_select(_TABLE, filters={"id": room_id, "user_id": uid}, limit=1)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "room_not_found", "room_id": room_id},
        )
    return rows[0]


class CreateRoomBody(BaseModel):
    title: str = Field(default="Advisory Session")
    lens: str | None = Field(default=None, description="Default council lens for the room.")


class MemberBody(BaseModel):
    id: str = Field(description="Template id (cfo/cto/legal/product) or custom id.")
    name: str | None = None
    title: str | None = None
    lens: str | None = None
    model: str | None = None
    voiceColor: str | None = None


class MessageBody(BaseModel):
    text: str
    speaker: str = Field(default="You")


@router.post("")
async def create_room(body: CreateRoomBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    lens = body.lens if body.lens in TASK_MATRIX else "cfo_review"
    row = await db_insert(
        _TABLE,
        {
            "user_id": _uid(user),
            "title": body.title,
            "default_lens": lens,
            "members": [],
            "transcript": [],
            "status": "active",
        },
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "room_write_failed"})
    return {"ok": True, "data": _public(row)}


@router.get("")
async def list_rooms(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rows = await db_select(_TABLE, filters={"user_id": _uid(user)}, order_by="-created_at", limit=100)
    return {"ok": True, "data": {"rooms": [_public(r) for r in rows]}}


@router.get("/{room_id}")
async def get_room(room_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    return {"ok": True, "data": _public(await _owned_row(room_id, _uid(user)))}


@router.delete("/{room_id}")
async def delete_room(room_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    await _owned_row(room_id, uid)  # 404s if not owned
    await db_delete(_TABLE, filters={"id": room_id, "user_id": uid})
    return {"ok": True, "data": {"deleted": room_id}}


@router.post("/{room_id}/members")
async def add_member(room_id: str, body: MemberBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    room = await _owned_row(room_id, uid)
    template = TEMPLATE_MEMBERS.get(body.id, {})
    member = {
        "id": body.id,
        "name": body.name or template.get("name") or body.id.title(),
        "title": body.title or template.get("title") or "Advisor",
        "lens": body.lens or template.get("lens") or "cfo_review",
        "model": body.model,
        "voiceColor": body.voiceColor or template.get("voiceColor") or "#64748B",
        "status": "active",
    }
    # Replace any existing member with the same id (idempotent invite).
    members = [m for m in (room.get("members") or []) if m.get("id") != body.id] + [member]
    await db_update(_TABLE, {"members": members}, filters={"id": room_id, "user_id": uid})
    return {"ok": True, "data": member}


@router.get("/{room_id}/members")
async def list_members(room_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    room = await _owned_row(room_id, _uid(user))
    return {"ok": True, "data": {"members": room.get("members") or []}}


@router.post("/{room_id}/messages")
async def post_message(room_id: str, body: MessageBody, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    # scoped_user : l'agent de salle (jeton de service) écrit au nom du propriétaire de la
    # salle, désigné par X-WinnyWoo-User-Id ; un humain reste lui-même.
    uid = _uid(user)
    room = await _owned_row(room_id, uid)
    from datetime import UTC, datetime

    entry = {"speaker": body.speaker, "text": body.text, "ts": datetime.now(UTC).isoformat()}
    transcript = list(room.get("transcript") or []) + [entry]
    await db_update(_TABLE, {"transcript": transcript}, filters={"id": room_id, "user_id": uid})
    return {"ok": True, "data": entry}


@router.get("/{room_id}/transcript")
async def get_transcript(room_id: str, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    room = await _owned_row(room_id, _uid(user))
    return {"ok": True, "data": {"transcript": room.get("transcript") or []}}


# Caption lines from the Google Meet bot look like "[ts] Speaker: text".
_MEET_LINE = re.compile(r"^\[(?P<ts>[^\]]*)\]\s*(?P<speaker>[^:]{1,60}?):\s*(?P<text>.+)$")


class ImportTranscriptBody(BaseModel):
    lines: list[str] = Field(default_factory=list, description="Raw caption lines, e.g. '[ts] Speaker: text'.")
    source: str = Field(default="Meet", description="Fallback speaker label when a line has no name.")


@router.post("/{room_id}/import-transcript")
async def import_transcript(room_id: str, body: ImportTranscriptBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Fold an external transcript (e.g. the Google Meet bot's captions) into the
    room transcript — deduped — so 'Summarize & close' produces the meeting
    artifact for the Google Meet path exactly as it does for the in-app room."""
    from datetime import UTC, datetime

    uid = _uid(user)
    room = await _owned_row(room_id, uid)
    existing = list(room.get("transcript") or [])
    seen = {(str(m.get("speaker")), str(m.get("text"))) for m in existing}
    added: list[dict[str, Any]] = []
    for raw in body.lines:
        raw = (raw or "").strip()
        if not raw:
            continue
        m = _MEET_LINE.match(raw)
        if m:
            speaker = (m.group("speaker") or "").strip() or body.source
            text = (m.group("text") or "").strip()
        else:
            speaker, text = body.source, raw
        if not text:
            continue
        key = (speaker, text)
        if key in seen:
            continue
        seen.add(key)
        added.append({"speaker": speaker, "text": text, "ts": datetime.now(UTC).isoformat()})
    if added:
        await db_update(_TABLE, {"transcript": existing + added}, filters={"id": room_id, "user_id": uid})
    return {"ok": True, "data": {"imported": len(added), "transcript": existing + added}}


def _transcript_text(transcript: list[dict[str, Any]]) -> str:
    return "\n".join(f"{m.get('speaker')}: {m.get('text')}" for m in transcript)


def _council_scenario(room: dict[str, Any], room_id: str, lens: str,
                      question: str | None, source: str) -> dict[str, Any]:
    """Build the council scenario. With ``source='summary'`` (the post-meeting flow)
    the council reviews ONLY the meeting summary — far fewer tokens than the full
    transcript. Falls back to the transcript when no summary exists yet."""
    summary = (room.get("summary") or "").strip()
    if source == "summary" and summary:
        basis, basis_label = summary, "Meeting summary"
    else:
        basis, basis_label = _transcript_text(room.get("transcript") or []), "Meeting transcript"
    primary_user = basis + (f"\n\nFocus question: {question}" if question else "")
    return {
        "id": f"room:{room_id}",
        "transcript": basis,
        "primarySystemPrompt": ROLE_SYSTEM_PROMPTS.get(lens, ""),
        "primaryUserPrompt": (
            f"{basis_label}:\n\n{primary_user}\n\n"
            "What is your intervention? Respond ONLY with the JSON object."
        ),
        "reviewerSystemPrompt": REVIEWER_SYSTEM_PROMPT,
    }


@router.get("/{room_id}/stream")
async def convene_stream(
    room_id: str,
    task: str | None = Query(default=None, description="Council lens; defaults to the room lens."),
    question: str | None = Query(default=None),
    source: str = Query(
        default="transcript",
        description="What the council reviews: 'summary' (token-economical; the meeting "
        "summary only) or 'transcript' (the full transcript).",
    ),
    user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """Convene the council over the room and stream stage events (SSE).

    The post-meeting flow passes ``source=summary`` so the council (departments'
    review) runs AFTER summarization on the SUMMARY only — the LLMs never see the
    whole transcript, which is far cheaper. Falls back to the transcript when there
    is no summary yet (e.g. a mid-meeting convene)."""
    room = await _owned_row(room_id, _uid(user))
    lens = task or room.get("default_lens") or "cfo_review"
    if lens not in TASK_MATRIX:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "unknown_task", "task": lens})
    scenario = _council_scenario(room, room_id, lens, question, source)
    return StreamingResponse(_run_council_sse(lens, scenario), media_type="text/event-stream")


# ── Live intervention (the "raise hand" brain — Phase 1 of the meeting-room port) ──
async def _load_weights(uid: str) -> dict[str, float]:
    """Per-tenant behavioral weights from pattern_weights (org_id = the user).
    Falls back to defaults; never raises."""
    weights = dict(WEIGHT_DEFAULTS)
    try:
        rows = await db_select("pattern_weights", filters={"org_id": uid}, allow_unscoped=True)
        for r in rows:
            name = r.get("pattern_id")
            if name in WEIGHT_DEFAULTS and r.get("weight") is not None:
                weights[name] = float(r["weight"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("intervention.load_weights_failed: %s", exc)
    return weights


class InterventionBody(BaseModel):
    topic: str = Field(default="")
    active_specialties: list[str] | None = Field(default=None, description="cfo|cto|legal|product")
    window_size: int = Field(default=20, ge=4, le=60)


@router.post("/{room_id}/intervention-check")
async def intervention_check(room_id: str, body: InterventionBody, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """Should the AI raise its hand right now? Runs the specialist fan-out → judge
    → behavioral-overlay pipeline over the room's recent transcript and logs the
    decision to ai_interventions. Poll this on a heartbeat while a meeting is live."""
    uid = _uid(user)
    room = await _owned_row(room_id, uid)
    weights = await _load_weights(uid)
    decision = await check_intervention(
        transcript=list(room.get("transcript") or []),
        topic=body.topic or room.get("title") or "",
        weights=weights,
        active_specialties=body.active_specialties,
        window_size=body.window_size,
    )
    # Fire-and-forget audit log of the decision.
    try:
        await db_insert("ai_interventions", {
            "room_id": room_id,
            "user_id": uid,
            "proposed_text": decision.get("message") or "",
            "urgency": decision.get("urgency") or "normal",
            "reason": decision.get("reason") or "",
            "touched_specialties": decision.get("touched_specialties") or [],
            "cost_usd": decision.get("cost_usd") or 0,
            "decision": "speak" if decision.get("speak") else "silent",
        })
    except Exception as exc:  # noqa: BLE001
        logger.debug("intervention.log_failed: %s", exc)
    return {"ok": True, "data": decision}


@router.get("/{room_id}/weights")
async def get_weights(room_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """The tenant's current behavioral weights (cooldown_turns, min_specialist_signals,
    silence_bias) governing how readily the advisor speaks."""
    uid = _uid(user)
    await _owned_row(room_id, uid)  # 404s if not owned
    return {"ok": True, "data": {"weights": await _load_weights(uid), "defaults": WEIGHT_DEFAULTS}}


# ── AI avatar presence (Tavus primary → Beyond Presence fallback) ──
# Active sessions in-process: room_id → normalized session (carries provider +
# conversation_id so we can end it).
_AVATAR_SESSIONS: dict[str, dict[str, Any]] = {}


async def _end_room_agent(room_id: str) -> bool:
    """End any in-process AI agent (avatar) session for the room — the agent
    LEAVES when the meeting is closed. Tears down the Tavus conversation if any;
    the caller clears the room's live_* columns. Returns whether a session existed."""
    session = _AVATAR_SESSIONS.pop(room_id, None)
    if session and session.get("provider") == "tavus" and session.get("conversation_id"):
        try:
            await avatar_mod.end_tavus_conversation(session["conversation_id"])
        except Exception as exc:  # noqa: BLE001
            logger.info("agent.end_failed room=%s: %s", room_id, exc)
    return bool(session)


class AvatarBody(BaseModel):
    persona: str = Field(default="advisor", description="CFO | CTO | COO | CRM | CRO | advisor")
    language: str | None = Field(default=None)
    greeting: str | None = Field(default=None)
    evidence: str | None = Field(default=None, description="Vault/source text to ground the avatar in.")


@router.get("/avatar/status")
async def avatar_status(_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Which avatar providers are configured (Tavus / Beyond Presence)."""
    return {"ok": True, "data": avatar_mod.avatar_status()}


@router.post("/{room_id}/avatar-session")
async def start_avatar(room_id: str, body: AvatarBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Spawn the AI avatar into the room as the chosen advisor persona, grounded
    in the supplied evidence. Returns the embeddable join URL (Tavus CVI /
    Beyond+LiveKit)."""
    uid = _uid(user)
    room = await _owned_row(room_id, uid)
    advisors = [m.get("title") or m.get("id") for m in (room.get("members") or [])]
    try:
        session = await avatar_mod.create_avatar_session(
            room_id=room_id,
            persona=body.persona,
            topic=room.get("title") or "",
            advisors=[a for a in advisors if a] or None,
            evidence=body.evidence,
            language=body.language,
            greeting=body.greeting,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"error": "avatar_unavailable", "message": str(exc)})
    _AVATAR_SESSIONS[room_id] = session
    # Persist the live room URL + a share token so external guests can resolve
    # and join the SAME room via a public link.
    share_token, _expires = await _ensure_share_token(room, uid)
    await db_update("rooms", {
        "live_url": session.get("conversation_url"),
        "live_provider": session.get("provider"),
        "live_persona": body.persona,
    }, filters={"id": room_id, "user_id": uid})
    return {"ok": True, "data": {**session, "share_token": share_token}}


@router.delete("/{room_id}/avatar-session")
async def end_avatar(room_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """End the room's active avatar session."""
    uid = _uid(user)
    await _owned_row(room_id, uid)
    had_session = await _end_room_agent(room_id)
    await db_update("rooms", {"live_url": None, "live_provider": None, "live_persona": None},
                    filters={"id": room_id, "user_id": uid})
    return {"ok": True, "data": {"ended": room_id, "had_session": had_session}}


def _share_ttl_hours() -> float:
    try:
        return float(os.getenv("ROOM_SHARE_TTL_HOURS", "72") or 72)
    except ValueError:
        return 72.0


async def _room_for_share_token(share_token: str) -> dict[str, Any]:
    """La salle d'un lien d'invitation encore valable — sinon 404 ou 410, sans rien révéler.

    Un lien vaut tant que la salle n'est pas close et que son échéance n'est pas passée.
    """
    from datetime import UTC, datetime

    rows = await db_select("rooms", filters={"share_token": share_token}, limit=1, allow_unscoped=True)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "invalid_share_token"})
    room = rows[0]
    if room.get("status") == "closed":
        raise HTTPException(status_code=status.HTTP_410_GONE, detail={"error": "meeting_closed"})
    expires = room.get("share_expires_at")
    if not expires or datetime.fromisoformat(str(expires).replace("Z", "+00:00")) <= datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail={"error": "expired_share_token"})
    return room


@router.get("/meeting/{share_token}")
async def public_meeting(share_token: str) -> dict[str, Any]:
    """PUBLIC — resolve a share token to the live meeting an external guest joins.
    No auth; the opaque token is the capability. Returns the embeddable room URL
    (the same room the AI avatar + host are in)."""
    room = await _room_for_share_token(share_token)
    return {
        "ok": True,
        "data": {
            "room_title": room.get("title"),
            "live_url": room.get("live_url"),
            "provider": room.get("live_provider"),
            "persona": room.get("live_persona"),
            "has_live": bool(room.get("live_url")),
        },
    }


# ── Bring the AI model INTO the live room (dispatch the livekit-agents worker) ──
class BringAgentBody(BaseModel):
    persona: str = Field(default="AZZMIN", description="AZZMIN | CFO | CTO | COO | CRM | CRO | advisor")
    evidence: str | None = Field(default=None, description="Vault/source text to ground the agent in.")


@router.post("/{room_id}/bring-agent")
async def bring_agent(room_id: str, body: BringAgentBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Dispatch the VIGIL meeting agent (livekit-agents worker `vigil-advisor`)
    into the room's live call as the chosen persona, grounded in evidence. The
    agent then hears/sees the room and speaks via its avatar — a real participant."""
    uid = _uid(user)
    room = await _owned_row(room_id, uid)
    url, key, secret = os.getenv("LIVEKIT_URL"), os.getenv("LIVEKIT_API_KEY"), os.getenv("LIVEKIT_API_SECRET")
    if not (url and key and secret):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"error": "livekit_not_configured"})
    try:
        from livekit import api as lkapi  # lazy: only needed for dispatch
    except ImportError:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail={"error": "livekit_api_missing"})

    evidence = body.evidence or _transcript_text(room.get("transcript") or [])
    metadata = json.dumps({
        "persona": body.persona,
        "topic": room.get("title") or "",
        "evidence": evidence[:4000],
        # Ce dont le worker a besoin pour passer par l'algorithme d'intervention :
        # la salle, au nom de qui il écrit, et qui il écoute en premier.
        "room_id": room_id,
        "owner_id": room.get("user_id") or uid,
        "host_identity": uid,
        "kind": room.get("kind") or "meeting",
    })
    client = lkapi.LiveKitAPI(url, key, secret)
    try:
        await client.agent_dispatch.create_dispatch(
            lkapi.CreateAgentDispatchRequest(agent_name="vigil-advisor", room=f"vigil-{room_id}", metadata=metadata)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("bring_agent.dispatch_failed room=%s: %s", room_id, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "dispatch_failed", "message": str(exc)})
    finally:
        await client.aclose()
    return {"ok": True, "data": {"dispatched": True, "persona": body.persona, "room": f"vigil-{room_id}"}}


# ── Live room (LiveKit transport — Phase 1 of the live meeting) ──
@router.post("/{room_id}/livekit-token")
async def livekit_token(room_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Mint a LiveKit join token for the room owner to join the live room."""
    if not lk.livekit_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"error": "livekit_not_configured"})
    uid = _uid(user)
    room = await _owned_row(room_id, uid)
    name = str(user.get("email") or "Host").split("@")[0]
    return {"ok": True, "data": lk.join_payload(room=f"vigil-{room_id}", identity=uid, name=name, metadata="role=host")}


@router.post("/{room_id}/share")
async def make_share_link(room_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Generate (or return) a share token so external guests can join the room.

    Le même lien est rendu tant qu'il est valable ; expiré, il est remplacé par un nouveau
    (l'ancien cesse alors de fonctionner). Durée : ROOM_SHARE_TTL_HOURS, 72 h par défaut.
    """
    uid = _uid(user)
    room = await _owned_row(room_id, uid)
    if room.get("status") == "closed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": "meeting_closed"})
    token, expires_at = await _ensure_share_token(room, uid)
    return {"ok": True, "data": {"share_token": token, "expires_at": expires_at}}


async def _ensure_share_token(room: dict[str, Any], uid: str) -> tuple[str, str]:
    """Le lien valable de la salle, ou un nouveau avec son échéance. Un lien sans échéance
    (créé avant la migration 024) est remplacé."""
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    expires = room.get("share_expires_at")
    if room.get("share_token") and expires and datetime.fromisoformat(str(expires).replace("Z", "+00:00")) > now:
        return room["share_token"], str(expires)
    token = lk.new_share_token()
    expires_at = (now + timedelta(hours=_share_ttl_hours())).isoformat()
    await db_update("rooms", {"share_token": token, "share_expires_at": expires_at},
                    filters={"id": room["id"], "user_id": uid})
    return token, expires_at


# ── Salle d'un créneau de formation LEARN (phase 1.2) ──
@router.post("/learn/slots/{slot_id}/join")
async def join_learn_slot(slot_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Entrer dans la salle d'un créneau distanciel ou mixte.

    La salle est créée à la première entrée, au nom du formateur du créneau (propriétaire et
    animateur). Qui entre, à quel titre et à quelle heure : voir winny_gateway/learn_link.py.
    Le jeton LiveKit porte le rôle (host / participant) dans ses métadonnées.
    """
    if not lk.livekit_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"error": "livekit_not_configured"})
    learn_role = (user.get("app_metadata") or {}).get("learn_role")
    access = await learn_link.slot_access(slot_id, user, learn_role)
    slot, session = access.slot, access.session

    rows = await db_select(_TABLE, filters={"learn_slot_id": slot_id}, limit=1, allow_unscoped=True)
    if rows:
        room = rows[0]
    else:
        owner = str(slot.get("formateur_id") or _uid(user))
        half = "matin" if slot.get("half") == "am" else "après-midi"
        title = f"{session.get('title') or session.get('code') or 'Formation'} — {slot.get('on_date')} ({half})"
        try:
            room = await db_insert(_TABLE, {
                "user_id": owner,
                "title": title[:200],
                "kind": "formation",
                "learn_session_id": session["id"],
                "learn_slot_id": slot_id,
                "default_lens": "cfo_review",
                "members": [],
                "transcript": [],
                "status": "active",
            })
        except DatabaseError:
            room = None
        if room is None:
            # Deux entrées simultanées : l'autre a créé la salle (index unique sur le créneau).
            rows = await db_select(_TABLE, filters={"learn_slot_id": slot_id}, limit=1, allow_unscoped=True)
            if not rows:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "room_write_failed"})
            room = rows[0]
    if room.get("status") == "closed":
        raise HTTPException(status_code=status.HTTP_410_GONE, detail={"error": "meeting_closed"})

    payload = lk.join_payload(room=f"vigil-{room['id']}", identity=_uid(user), name=access.display_name,
                              metadata=f"role={access.role}")
    return {"ok": True, "data": {
        "room_id": room["id"], "title": room.get("title"), "role": access.role,
        "starts_at": slot.get("starts_at"), "ends_at": slot.get("ends_at"), **payload,
    }}


# ── Présence : webhook LiveKit et rapprochement avec l'émargement (phase 1.7) ──
@router.post("/livekit/webhook")
async def livekit_webhook(request: Request) -> dict[str, Any]:
    """PUBLIC, signé par LiveKit. Enregistre entrées et sorties des salles `vigil-*`."""
    from datetime import UTC, datetime

    body = await request.body()
    try:
        presence.verify_webhook(body, request.headers.get("authorization"))
    except presence.WebhookRefused as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"error": str(exc)}) from exc
    ev = json.loads(body or b"{}")
    kind = {"participant_joined": "joined", "participant_left": "left"}.get(ev.get("event"))
    room_name = (ev.get("room") or {}).get("name") or ""
    part = ev.get("participant") or {}
    if not kind or not room_name.startswith("vigil-") or part.get("kind") in ("AGENT", 4):
        return {"ok": True, "data": {"ignored": True}}
    created = int(ev.get("createdAt") or 0)
    at = datetime.fromtimestamp(created, UTC) if created else datetime.now(UTC)
    try:
        await db_insert("room_presence", {
            "room_id": bk.parent_room_id(room_name),
            "identity": part.get("identity") or "",
            "name": part.get("name") or None,
            "event": kind,
            "at": at.isoformat(),
            "livekit_event_id": ev.get("id") or None,
        }, allow_unscoped=True)
    except DatabaseError as exc:
        # Événement rejoué (id déjà vu) ou salle inconnue : sans conséquence.
        logger.info("livekit_webhook.skip %s: %s", ev.get("id"), exc.reason[:120])
    return {"ok": True, "data": {"recorded": kind}}


@router.get("/{room_id}/attendance-check")
async def attendance_check(room_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Écarts entre présence en visio et émargement, pour la salle d'un créneau LEARN.
    Réservé à qui anime la salle. Signale seulement : ne signe ni ne corrige rien."""
    uid = _uid(user)
    room = await _owned_row(room_id, uid)
    slot_id = room.get("learn_slot_id")
    if not slot_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": "not_a_formation_room"})
    slots = await db_select("learn_session_slots", filters={"id": slot_id}, limit=1, allow_unscoped=True)
    if not slots:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "slot_not_found"})
    slot = slots[0]
    enrolled = await db_select("learn_enrollments", filters={"session_id": slot["session_id"]},
                               limit=500, allow_unscoped=True)
    learners = [e for e in enrolled if e.get("status") in learn_link.VALID_ENROLLMENT]
    for learner in learners:
        prof = await db_select("learn_profiles", filters={"id": learner["apprenant_id"]}, limit=1,
                               allow_unscoped=True)
        learner["full_name"] = (prof[0] if prof else {}).get("full_name")
    sheet = await db_select("learn_attendance_sheet", filters={"slot_id": slot_id}, limit=500, allow_unscoped=True)
    events = await db_select("room_presence", filters={"room_id": room_id}, limit=5000, allow_unscoped=True)
    rows = presence.reconcile(slot, learners, sheet, events)
    return {"ok": True, "data": {
        "slot_id": slot_id, "starts_at": slot.get("starts_at"), "ends_at": slot.get("ends_at"),
        "learners": rows, "ecarts": [r for r in rows if r["ecart"]],
    }}


# ── Sous-salles (phase 1.8) ──
async def _room_role(room_id: str, user: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """(salle, "host" | "participant"). Propriétaire → host ; salle de formation → règles
    LEARN (learn_link) ; sinon 404, sans rien révéler."""
    uid = _uid(user)
    rows = await db_select(_TABLE, filters={"id": room_id}, limit=1, allow_unscoped=True)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "room_not_found", "room_id": room_id})
    room = rows[0]
    if str(room.get("user_id")) == uid:
        return room, "host"
    if room.get("learn_slot_id"):
        learn_role = (user.get("app_metadata") or {}).get("learn_role")
        access = await learn_link.slot_access(str(room["learn_slot_id"]), user, learn_role)
        return room, access.role
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "room_not_found", "room_id": room_id})


class BreakoutPerson(BaseModel):
    id: str
    name: str | None = None


class BreakoutsBody(BaseModel):
    count: int = Field(ge=1, le=20)
    members: list[BreakoutPerson] | None = Field(default=None, description="Hors formation : qui répartir.")


@router.post("/{room_id}/breakouts")
async def create_breakouts(room_id: str, body: BreakoutsBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Créer les sous-salles et répartir les participants. Remplace une répartition ouverte."""
    room, role = await _room_role(room_id, user)
    if role != "host":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "host_only"})
    if room.get("status") == "closed":
        raise HTTPException(status_code=status.HTTP_410_GONE, detail={"error": "meeting_closed"})
    people: list[dict[str, Any]]
    if room.get("learn_session_id"):
        enrolled = await db_select("learn_enrollments", filters={"session_id": room["learn_session_id"]},
                                   limit=500, allow_unscoped=True)
        people = []
        for e in enrolled:
            if e.get("status") not in learn_link.VALID_ENROLLMENT:
                continue
            prof = await db_select("learn_profiles", filters={"id": e["apprenant_id"]}, limit=1, allow_unscoped=True)
            people.append({"id": e["apprenant_id"], "name": (prof[0] if prof else {}).get("full_name")})
    else:
        people = [m.model_dump() for m in (body.members or [])]
    if not people:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": "nobody_to_distribute"})
    groups = bk.distribute(people, body.count)
    await db_update(_TABLE, {"breakouts": groups}, filters={"id": room_id, "user_id": room["user_id"]})
    names = {str(p["id"]): p.get("name") for p in people}
    return {"ok": True, "data": {"breakouts": [
        {**g, "member_names": [names.get(m) or m for m in g["members"]]} for g in groups
    ]}}


@router.get("/{room_id}/breakouts")
async def list_breakouts(room_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Animateur : toutes les sous-salles. Participant : la sienne, ou aucune."""
    room, role = await _room_role(room_id, user)
    groups = [g for g in (room.get("breakouts") or []) if g.get("open", True)]
    if role == "host":
        return {"ok": True, "data": {"role": role, "breakouts": groups}}
    mine = bk.group_of(groups, _uid(user))
    return {"ok": True, "data": {"role": role, "breakouts": [mine] if mine else []}}


@router.post("/{room_id}/breakouts/{gid}/join")
async def join_breakout(room_id: str, gid: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    if not lk.livekit_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"error": "livekit_not_configured"})
    room, role = await _room_role(room_id, user)
    uid = _uid(user)
    group = next((g for g in (room.get("breakouts") or []) if g.get("id") == gid and g.get("open", True)), None)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "breakout_not_found"})
    if role != "host" and uid not in (group.get("members") or []):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "not_in_group"})
    name = str(user.get("email") or "Participant").split("@")[0]
    if room.get("learn_slot_id"):
        prof = await db_select("learn_profiles", filters={"id": uid}, limit=1, allow_unscoped=True)
        name = (prof[0] if prof else {}).get("full_name") or name
    payload = lk.join_payload(room=bk.livekit_room(room_id, gid), identity=uid, name=name,
                              metadata=f"role={role};breakout={gid}")
    return {"ok": True, "data": {"group": group.get("name"), "role": role, **payload}}


@router.delete("/{room_id}/breakouts")
async def close_breakouts(room_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Fermer les sous-salles : tout le monde revient en plénière."""
    room, role = await _room_role(room_id, user)
    if role != "host":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "host_only"})
    groups = room.get("breakouts") or []
    await db_update(_TABLE, {"breakouts": []}, filters={"id": room_id, "user_id": room["user_id"]})
    closed = 0
    if groups and lk.livekit_configured():
        try:
            from livekit import api as lkapi

            client = lkapi.LiveKitAPI(os.getenv("LIVEKIT_URL"), os.getenv("LIVEKIT_API_KEY"), os.getenv("LIVEKIT_API_SECRET"))
            try:
                for g in groups:
                    try:
                        await client.room.delete_room(lkapi.DeleteRoomRequest(room=bk.livekit_room(room_id, g["id"])))
                        closed += 1
                    except Exception as exc:  # noqa: BLE001 — salle déjà vide
                        logger.info("breakouts.delete_room %s: %s", g.get("id"), exc)
            finally:
                await client.aclose()
        except ImportError:
            logger.warning("breakouts.close: livekit-api absent, les sous-salles se videront seules")
    return {"ok": True, "data": {"closed": closed}}


class GuestJoinBody(BaseModel):
    name: str = Field(default="Guest", max_length=80)


@router.post("/guest/{share_token}/join")
async def guest_join(share_token: str, body: GuestJoinBody) -> dict[str, Any]:
    """Public — an external (non-account) guest joins the live room via a share
    link. No auth; the opaque share token is the capability."""
    if not lk.livekit_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"error": "livekit_not_configured"})
    room = await _room_for_share_token(share_token)
    guest_id = f"guest-{lk.new_share_token()[:10]}"
    # Smart onboarding (1/2): record who joined so the post-meeting summarize can
    # convert them into CRM contacts. Best-effort — never block the join.
    try:
        await db_insert("guest_leads", {
            "org_id": room.get("user_id"),
            "room_id": room.get("id"),
            "name": (body.name or "Guest").strip()[:120],
            "consent_to_follow_up": True,
            "status": "new",
            "source": "meeting-invite",
            "metadata": {"joined_via": "share_link"},
        })
    except Exception as exc:  # noqa: BLE001
        logger.info("guest_join.lead_insert_failed room=%s: %s", room.get("id"), exc)
    return {
        "ok": True,
        "data": {
            "room_title": room.get("title"),
            **lk.join_payload(room=f"vigil-{room['id']}", identity=guest_id,
                              name=body.name or "Guest", metadata="role=guest"),
        },
    }


# ── Post-meeting: summary → Studio artifact + commitments + guest onboarding (Phase 3) ──
class SummarizeBody(BaseModel):
    create_artifact: bool = Field(default=True)
    extract_commitments: bool = Field(default=True)
    onboard_guests: bool = Field(default=True)


@router.post("/{room_id}/summarize")
async def summarize_room(room_id: str, body: SummarizeBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Close the meeting: summarize the transcript → a Studio artifact, extract
    commitments (action items), and onboard guest follow-ups into the CRM."""
    uid = _uid(user)
    room = await _owned_row(room_id, uid)
    transcript_text = _transcript_text(room.get("transcript") or [])
    result = await summarize_meeting(transcript_text=transcript_text, topic=room.get("title") or "")
    if result.get("empty"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "empty_transcript"})

    # Phase 4: structure the close into the canvas (decision-flow + action table)
    # so the wrap-up can redirect to the editable artifact page.
    canvas = await structure_meeting(
        summary_markdown=result["summary_markdown"],
        decisions=result["decisions"],
        commitments=result["commitments"],
        topic=room.get("title") or "",
    )

    artifact_id = None
    if body.create_artifact and result["summary_markdown"]:
        parts = [result["summary_markdown"]]
        if result["decisions"]:
            parts.append("## Decisions\n" + "\n".join(f"- {d}" for d in result["decisions"]))
        if result["next_steps"]:
            parts.append("## Next steps\n" + "\n".join(f"- {s}" for s in result["next_steps"]))
        if result["commitments"]:
            parts.append("## Commitments\n" + "\n".join(
                f"- {c.get('text','')}" + (f" — {c.get('owner')}" if c.get('owner') else "") + (f" (due {c.get('due')})" if c.get('due') else "")
                for c in result["commitments"]))
        row = await db_insert("artifacts", {
            "user_id": uid,
            "title": f"Meeting summary — {room.get('title') or room_id}"[:120],
            "kind": "report",
            "brief": f"Summary of meeting: {room.get('title') or room_id}",
            "text_dump": "\n\n".join(parts),
            "canvas": canvas,
            "stub": bool(result.get("stub")),
            "status": "draft",
            "version": 1,
        })
        artifact_id = (row or {}).get("id")

    commitments_n = 0
    if body.extract_commitments:
        for c in result["commitments"]:
            text = str(c.get("text") or "").strip()
            if not text:
                continue
            r = await db_insert("commitments", {
                "org_id": uid,
                "room_id": room_id,
                "speaker_name": c.get("owner") or None,
                "text": text + (f" (due {c.get('due')})" if c.get("due") else ""),
                "kind": "action",
                "status": "open",
            })
            if r:
                commitments_n += 1

    contacts_n = 0
    formation = bool(room.get("learn_session_id"))
    # Une séance de formation n'alimente pas le CRM : ses participants sont des apprenants,
    # pas des prospects.
    if body.onboard_guests and not formation:
        for f in result["follow_ups"]:
            name = str(f.get("name") or "").strip()
            if not name:
                continue
            r = await db_insert("crm_contacts", {
                "user_id": uid,
                "name": name,
                "company": f.get("company") or None,
                "notes": f.get("next_step") or None,
                "tags": ["meeting-guest"],
            })
            if r:
                contacts_n += 1

        # Smart onboarding (2/2): convert the humans who actually JOINED via the
        # invite link (recorded in guest_leads on join) into CRM contacts, deduped
        # against names the summary already onboarded. Mark each lead onboarded so
        # re-summarizing doesn't duplicate.
        seen_names = {str(f.get("name") or "").strip().lower() for f in result["follow_ups"]}
        leads = await db_select("guest_leads", filters={"org_id": uid, "room_id": room_id, "status": "new"}, limit=200)
        for lead in leads:
            nm = str(lead.get("name") or "").strip()
            if nm and nm.lower() not in seen_names:
                seen_names.add(nm.lower())
                r = await db_insert("crm_contacts", {
                    "user_id": uid, "name": nm,
                    "company": lead.get("company") or None,
                    "notes": lead.get("main_need") or "Joined the live meeting",
                    "tags": ["meeting-guest"],
                })
                if r:
                    contacts_n += 1
            await db_update("guest_leads", {"status": "onboarded"},
                            filters={"id": lead["id"], "org_id": uid})

    # Close the meeting: persist the summary (the council later reviews THIS, not
    # the transcript), mark the room concluded, and make the AI agent leave.
    from datetime import UTC, datetime

    agent_ended = await _end_room_agent(room_id)
    await db_update("rooms", {
        "summary": result["summary_markdown"],
        "status": "closed",
        "concluded_at": datetime.now(UTC).isoformat(),
        "artifact_id": artifact_id,
        "live_url": None, "live_provider": None, "live_persona": None,
    }, filters={"id": room_id, "user_id": uid})

    # Séance de formation : le compte rendu rejoint le coffre LEARN de la session, déposé au
    # nom du formateur (propriétaire de la salle) et marqué produit par l'IA. Jamais un
    # compte rendu de repli (IA indisponible) : mieux vaut rien qu'un faux document.
    vault_object_id = None
    vault_error = None
    if formation and result["summary_markdown"] and not result.get("stub"):
        try:
            obj = await learn_api.deposit_text(
                on_behalf_of=str(room.get("user_id") or uid),
                session_id=str(room["learn_session_id"]),
                filename=f"compte-rendu-{datetime.now(UTC):%Y-%m-%d}-{room_id[:8]}.txt",
                text=f"{room.get('title') or 'Séance'}\n\n" + result["summary_markdown"],
            )
            vault_object_id = obj.get("id")
        except Exception as exc:  # noqa: BLE001 — la clôture ne dépend pas du coffre
            vault_error = str(exc)[:200]
            logger.warning("summarize.vault_deposit_failed room=%s: %s", room_id, exc)

    return {
        "ok": True,
        "data": {
            "vault_object_id": vault_object_id,
            "vault_error": vault_error,
            "summary_markdown": result["summary_markdown"],
            "decisions": result["decisions"],
            "next_steps": result["next_steps"],
            "commitments": result["commitments"],
            "follow_ups": result["follow_ups"],
            "artifact_id": artifact_id,
            "canvas": canvas,
            "commitments_saved": commitments_n,
            "contacts_saved": contacts_n,
            "agent_ended": agent_ended,
            "status": "closed",
            "stub": result.get("stub"),
        },
    }
