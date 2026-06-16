"""Meeting Room routes — ports VIGIL's /v1/rooms surface (the subset needed to
drive the Meeting Room UI) to the unified gateway.

Scope of this port: room lifecycle, Deal Board members (advisors), transcript
capture, and convening the council over the transcript with a live SSE stream.
Avatar/voice/LiveKit/Hume are separate concerns (Stage 3e) and degrade to
absent here. Storage is in-memory and scoped to the authenticated user — good
enough for the live session model; Supabase persistence can layer on later.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from winny.council import ROLE_SYSTEM_PROMPTS, REVIEWER_SYSTEM_PROMPT, TASK_MATRIX
from winny_gateway.auth import get_current_user
from winny_gateway.routes.vigil.council import _run_council_sse

router = APIRouter(prefix="/v1/rooms", tags=["rooms"])

# In-memory room store: room_id -> room dict (carries owner_sub for scoping).
_ROOMS: dict[str, dict[str, Any]] = {}

# Template advisors for the Deal Board — map to council lenses.
TEMPLATE_MEMBERS = {
    "cfo": {"lens": "cfo_review", "name": "Chief Financial Officer", "title": "CFO", "voiceColor": "#2563EB"},
    "cto": {"lens": "tech_review", "name": "Chief Technology Officer", "title": "CTO", "voiceColor": "#7C3AED"},
    "legal": {"lens": "legal_review", "name": "General Counsel", "title": "Legal", "voiceColor": "#059669"},
    "product": {"lens": "product_review", "name": "Head of Product", "title": "Product", "voiceColor": "#DB2777"},
}


def _sub(user: dict[str, Any]) -> str:
    return str(user.get("sub") or user.get("email") or "anon")


def _owned(room_id: str, user: dict[str, Any]) -> dict[str, Any]:
    room = _ROOMS.get(room_id)
    if room is None or room["owner_sub"] != _sub(user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "room_not_found", "room_id": room_id})
    return room


def _public(room: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in room.items() if k != "owner_sub"}


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
    room_id = str(uuid.uuid4())
    room = {
        "id": room_id,
        "owner_sub": _sub(user),
        "title": body.title,
        "lens": body.lens if body.lens in TASK_MATRIX else "cfo_review",
        "members": [],
        "transcript": [],
        "created_at": datetime.now(UTC).isoformat(),
    }
    _ROOMS[room_id] = room
    return {"ok": True, "data": _public(room)}


@router.get("")
async def list_rooms(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    sub = _sub(user)
    rooms = [_public(r) for r in _ROOMS.values() if r["owner_sub"] == sub]
    rooms.sort(key=lambda r: r["created_at"], reverse=True)
    return {"ok": True, "data": {"rooms": rooms}}


@router.get("/{room_id}")
async def get_room(room_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    return {"ok": True, "data": _public(_owned(room_id, user))}


@router.delete("/{room_id}")
async def delete_room(room_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    _owned(room_id, user)
    _ROOMS.pop(room_id, None)
    return {"ok": True, "data": {"deleted": room_id}}


@router.post("/{room_id}/members")
async def add_member(room_id: str, body: MemberBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    room = _owned(room_id, user)
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
    room["members"] = [m for m in room["members"] if m["id"] != body.id] + [member]
    return {"ok": True, "data": member}


@router.get("/{room_id}/members")
async def list_members(room_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    room = _owned(room_id, user)
    return {"ok": True, "data": {"members": room["members"]}}


@router.post("/{room_id}/messages")
async def post_message(room_id: str, body: MessageBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    room = _owned(room_id, user)
    entry = {"speaker": body.speaker, "text": body.text, "ts": datetime.now(UTC).isoformat()}
    room["transcript"].append(entry)
    return {"ok": True, "data": entry}


@router.get("/{room_id}/transcript")
async def get_transcript(room_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    room = _owned(room_id, user)
    return {"ok": True, "data": {"transcript": room["transcript"]}}


def _transcript_text(room: dict[str, Any]) -> str:
    return "\n".join(f"{m['speaker']}: {m['text']}" for m in room["transcript"])


@router.get("/{room_id}/stream")
async def convene_stream(
    room_id: str,
    task: str | None = Query(default=None, description="Council lens; defaults to the room lens."),
    question: str | None = Query(default=None),
    user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """Convene the council over the room transcript and stream stage events (SSE)."""
    room = _owned(room_id, user)
    lens = task or room["lens"]
    if lens not in TASK_MATRIX:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "unknown_task", "task": lens})
    transcript = _transcript_text(room)
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
