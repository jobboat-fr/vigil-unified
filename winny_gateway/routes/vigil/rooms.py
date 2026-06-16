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

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from winny.council import ROLE_SYSTEM_PROMPTS, REVIEWER_SYSTEM_PROMPT, TASK_MATRIX
from winny_gateway.auth import get_current_user
from winny_gateway.db import db_delete, db_insert, db_select, db_update
from winny_gateway.routes.vigil.council import _run_council_sse

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
