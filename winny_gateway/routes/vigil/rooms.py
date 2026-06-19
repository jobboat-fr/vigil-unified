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
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from winny.council import ROLE_SYSTEM_PROMPTS, REVIEWER_SYSTEM_PROMPT, TASK_MATRIX
from winny.council.intervention import WEIGHT_DEFAULTS, check_intervention
from winny.council.summarizer import summarize_meeting
from winny.council.structurer import structure_meeting
from winny_gateway import avatar as avatar_mod
from winny_gateway import livekit as lk
from winny_gateway.auth import get_current_user
from winny_gateway.db import db_delete, db_insert, db_select, db_update
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
        "created_at": row.get("created_at"),
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
async def post_message(room_id: str, body: MessageBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    room = await _owned_row(room_id, uid)
    from datetime import UTC, datetime

    entry = {"speaker": body.speaker, "text": body.text, "ts": datetime.now(UTC).isoformat()}
    transcript = list(room.get("transcript") or []) + [entry]
    await db_update(_TABLE, {"transcript": transcript}, filters={"id": room_id, "user_id": uid})
    return {"ok": True, "data": entry}


@router.get("/{room_id}/transcript")
async def get_transcript(room_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    room = await _owned_row(room_id, _uid(user))
    return {"ok": True, "data": {"transcript": room.get("transcript") or []}}


def _transcript_text(transcript: list[dict[str, Any]]) -> str:
    return "\n".join(f"{m.get('speaker')}: {m.get('text')}" for m in transcript)


@router.get("/{room_id}/stream")
async def convene_stream(
    room_id: str,
    task: str | None = Query(default=None, description="Council lens; defaults to the room lens."),
    question: str | None = Query(default=None),
    user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """Convene the council over the room transcript and stream stage events (SSE)."""
    room = await _owned_row(room_id, _uid(user))
    lens = task or room.get("default_lens") or "cfo_review"
    if lens not in TASK_MATRIX:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "unknown_task", "task": lens})
    transcript = _transcript_text(room.get("transcript") or [])
    primary_user = transcript + (f"\n\nFocus question: {question}" if question else "")
    scenario = {
        "id": f"room:{room_id}",
        "transcript": transcript,
        "primarySystemPrompt": ROLE_SYSTEM_PROMPTS.get(lens, ""),
        "primaryUserPrompt": (
            f"Meeting transcript:\n\n{primary_user}\n\n"
            "What is your intervention? Respond ONLY with the JSON object."
        ),
        "reviewerSystemPrompt": REVIEWER_SYSTEM_PROMPT,
    }
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
async def intervention_check(room_id: str, body: InterventionBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
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
    share_token = room.get("share_token") or lk.new_share_token()
    await db_update("rooms", {
        "live_url": session.get("conversation_url"),
        "live_provider": session.get("provider"),
        "live_persona": body.persona,
        "share_token": share_token,
    }, filters={"id": room_id, "user_id": uid})
    return {"ok": True, "data": {**session, "share_token": share_token}}


@router.delete("/{room_id}/avatar-session")
async def end_avatar(room_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """End the room's active avatar session."""
    uid = _uid(user)
    await _owned_row(room_id, uid)
    session = _AVATAR_SESSIONS.pop(room_id, None)
    if session and session.get("provider") == "tavus" and session.get("conversation_id"):
        await avatar_mod.end_tavus_conversation(session["conversation_id"])
    await db_update("rooms", {"live_url": None, "live_provider": None, "live_persona": None},
                    filters={"id": room_id, "user_id": uid})
    return {"ok": True, "data": {"ended": room_id, "had_session": bool(session)}}


@router.get("/meeting/{share_token}")
async def public_meeting(share_token: str) -> dict[str, Any]:
    """PUBLIC — resolve a share token to the live meeting an external guest joins.
    No auth; the opaque token is the capability. Returns the embeddable room URL
    (the same room the AI avatar + host are in)."""
    rows = await db_select("rooms", filters={"share_token": share_token}, limit=1, allow_unscoped=True)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "invalid_share_token"})
    room = rows[0]
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
    persona: str = Field(default="advisor", description="CFO | CTO | COO | CRM | CRO | advisor")
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
    metadata = json.dumps({"persona": body.persona, "topic": room.get("title") or "", "evidence": evidence[:4000]})
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
    """Generate (or return) a share token so external guests can join the room."""
    uid = _uid(user)
    room = await _owned_row(room_id, uid)
    token = room.get("share_token") or lk.new_share_token()
    if not room.get("share_token"):
        await db_update("rooms", {"share_token": token}, filters={"id": room_id, "user_id": uid})
    return {"ok": True, "data": {"share_token": token}}


class GuestJoinBody(BaseModel):
    name: str = Field(default="Guest", max_length=80)


@router.post("/guest/{share_token}/join")
async def guest_join(share_token: str, body: GuestJoinBody) -> dict[str, Any]:
    """Public — an external (non-account) guest joins the live room via a share
    link. No auth; the opaque share token is the capability."""
    if not lk.livekit_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"error": "livekit_not_configured"})
    rows = await db_select("rooms", filters={"share_token": share_token}, limit=1, allow_unscoped=True)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "invalid_share_token"})
    room = rows[0]
    guest_id = f"guest-{lk.new_share_token()[:10]}"
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
    if body.onboard_guests:
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

    return {
        "ok": True,
        "data": {
            "summary_markdown": result["summary_markdown"],
            "decisions": result["decisions"],
            "next_steps": result["next_steps"],
            "commitments": result["commitments"],
            "follow_ups": result["follow_ups"],
            "artifact_id": artifact_id,
            "canvas": canvas,
            "commitments_saved": commitments_n,
            "contacts_saved": contacts_n,
            "stub": result.get("stub"),
        },
    }
