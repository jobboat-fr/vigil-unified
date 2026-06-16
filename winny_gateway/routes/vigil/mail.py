"""Mail routes — the inbox triage surface the mail-triage skill routes into.

Surface (auth-required, scoped to the caller's user_id via the db guard):

  GET   /v1/mail/messages              the triage inbox (filter category/status/folder)
  POST  /v1/mail/messages              manual ingest of a message
  POST  /v1/mail/sync                  pull envelopes from the himalaya transport
  PATCH /v1/mail/messages/{id}         set category/priority/status/tags by hand
  POST  /v1/mail/messages/{id}/triage  LLM classify → category + priority + action
  DELETE/v1/mail/messages/{id}
  GET   /v1/mail/triage/summary        counts by category + priority + unread/triaged
  GET/POST   /v1/mail/drafts           review-then-send drafts (never auto-sent)
  PATCH/DELETE /v1/mail/drafts/{id}

Outbound is review-then-send: drafts can be marked approved, but this surface
never dispatches mail (the persona hard rule). Sending is a separate, explicitly
gated action.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from winny.council.providers import ask
from winny.council.registry import worker_registry
from winny_gateway import mail_bridge
from winny_gateway.auth import get_current_user
from winny_gateway.db import db_delete, db_insert, db_select, db_update, db_upsert
from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/v1/mail", tags=["mail"])

CATEGORIES = ["urgent", "respond", "fyi", "newsletter", "spam", "archive"]
PRIORITIES = ["high", "normal", "low"]
STATUSES = ["unread", "read", "archived"]
DRAFT_STATUSES = ["draft", "approved", "sent"]


def _uid(user: dict[str, Any]) -> str:
    uid = user.get("sub")
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no user id in token")
    return str(uid)


async def _owned(table: str, row_id: str, uid: str, label: str) -> dict[str, Any]:
    rows = await db_select(table, filters={"id": row_id, "user_id": uid}, limit=1)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": f"{label}_not_found", "id": row_id})
    return rows[0]


# ── Messages ────────────────────────────────────────────────────────────────
class MessageBody(BaseModel):
    from_addr: str | None = None
    from_name: str | None = None
    to_addrs: list[str] | None = None
    subject: str | None = None
    snippet: str | None = None
    body: str | None = None
    received_at: str | None = None
    folder: str = Field(default="INBOX")
    external_id: str | None = None
    thread_id: str | None = None


class MessagePatch(BaseModel):
    category: str | None = None
    priority: str | None = None
    status: str | None = None
    tags: list[str] | None = None


@router.get("/messages")
async def list_messages(
    user: dict = Depends(get_current_user),
    category: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    folder: str | None = Query(default=None),
    limit: int = Query(default=200, le=1000),
) -> dict[str, Any]:
    filters: dict[str, Any] = {"user_id": _uid(user)}
    if category:
        filters["category"] = category
    if status_filter:
        filters["status"] = status_filter
    if folder:
        filters["folder"] = folder
    rows = await db_select("mail_messages", filters=filters, order_by="-received_at", limit=limit)
    return {"ok": True, "data": {"messages": rows}}


@router.post("/messages")
async def ingest_message(body: MessageBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    data = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    data["user_id"] = _uid(user)
    row = await db_insert("mail_messages", data)
    if row is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "message_write_failed"})
    return {"ok": True, "data": row}


@router.post("/sync")
async def sync_mailbox(
    user: dict = Depends(get_current_user),
    folder: str = Query(default="INBOX"),
    limit: int = Query(default=50, le=200),
) -> dict[str, Any]:
    """Pull envelopes from the himalaya transport and upsert them (idempotent)."""
    uid = _uid(user)
    result = await mail_bridge.list_envelopes(folder=folder, limit=limit)
    synced = 0
    for env in result.get("messages", []):
        if not env.get("external_id"):
            continue
        row = await db_upsert(
            "mail_messages",
            {**env, "user_id": uid},
            on_conflict="user_id,external_id",
        )
        if row is not None:
            synced += 1
    return {
        "ok": True,
        "data": {
            "available": result.get("available", False),
            "reason": result.get("reason"),
            "fetched": len(result.get("messages", [])),
            "synced": synced,
        },
    }


@router.patch("/messages/{message_id}")
async def update_message(message_id: str, body: MessagePatch, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    await _owned("mail_messages", message_id, uid, "message")
    patch = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if patch.get("category") and patch["category"] not in CATEGORIES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "bad_category", "available": CATEGORIES})
    if patch.get("priority") and patch["priority"] not in PRIORITIES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "bad_priority", "available": PRIORITIES})
    if patch.get("status") and patch["status"] not in STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "bad_status", "available": STATUSES})
    if "category" in patch:
        patch["triaged"] = True
    if not patch:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "empty_patch"})
    updated = await db_update("mail_messages", patch, filters={"id": message_id, "user_id": uid})
    if not updated:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "message_update_failed"})
    return {"ok": True, "data": updated[0]}


_TRIAGE_SYSTEM = (
    "You are the VIGIL × WinnyWoo mail triage classifier. Classify one email into "
    f"exactly one category from {CATEGORIES} and a priority from {PRIORITIES}. "
    "Be decisive. Respond ONLY with a JSON object: "
    '{"category": "...", "priority": "...", "score": 0.0-1.0, '
    '"suggested_action": "one short sentence", "reasoning": "one short sentence"}'
)


@router.post("/messages/{message_id}/triage")
async def triage_message(message_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """LLM-classify a message into a triage bucket + priority and apply it."""
    uid = _uid(user)
    msg = await _owned("mail_messages", message_id, uid, "message")
    prompt = (
        f"From: {msg.get('from_name') or ''} <{msg.get('from_addr') or ''}>\n"
        f"Subject: {msg.get('subject') or ''}\n\n"
        f"{(msg.get('body') or msg.get('snippet') or '')[:2000]}\n\n"
        "Classify it. Respond ONLY with the JSON object."
    )
    result = await ask(worker_registry()["primary"], prompt, system=_TRIAGE_SYSTEM, temperature=0.2, max_tokens=400)
    plan = _parse_json(result.get("output", ""))
    category = plan.get("category") if plan.get("category") in CATEGORIES else None
    priority = plan.get("priority") if plan.get("priority") in PRIORITIES else "normal"
    patch: dict[str, Any] = {"priority": priority, "triaged": True}
    if category:
        patch["category"] = category
    try:
        score = float(plan.get("score"))
        patch["triage_score"] = round(max(0.0, min(1.0, score)), 2)
    except (TypeError, ValueError):
        pass
    updated = await db_update("mail_messages", patch, filters={"id": message_id, "user_id": uid})
    return {
        "ok": True,
        "data": {
            "message": updated[0] if updated else msg,
            "classification": plan,
            "stub": result.get("stub", False),
        },
    }


@router.delete("/messages/{message_id}")
async def delete_message(message_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    await _owned("mail_messages", message_id, uid, "message")
    await db_delete("mail_messages", filters={"id": message_id, "user_id": uid})
    return {"ok": True, "data": {"deleted": message_id}}


@router.get("/triage/summary")
async def triage_summary(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rows = await db_select("mail_messages", filters={"user_id": _uid(user)}, limit=2000)
    by_category: dict[str, int] = {c: 0 for c in CATEGORIES}
    by_priority: dict[str, int] = {p: 0 for p in PRIORITIES}
    unread = 0
    triaged = 0
    for r in rows:
        cat = r.get("category")
        if cat in by_category:
            by_category[cat] += 1
        pr = r.get("priority") or "normal"
        by_priority[pr] = by_priority.get(pr, 0) + 1
        if r.get("status") == "unread":
            unread += 1
        if r.get("triaged"):
            triaged += 1
    n = len(rows)
    return {
        "ok": True,
        "data": {
            "total": n,
            "unread": unread,
            "triaged": triaged,
            "untriaged": n - triaged,
            "by_category": by_category,
            "by_priority": by_priority,
        },
    }


# ── Drafts (review-then-send) ───────────────────────────────────────────────
class DraftBody(BaseModel):
    to_addrs: list[str] | None = None
    subject: str | None = None
    body: str = Field(default="")
    in_reply_to: str | None = None


class DraftPatch(BaseModel):
    to_addrs: list[str] | None = None
    subject: str | None = None
    body: str | None = None
    status: str | None = None


@router.get("/drafts")
async def list_drafts(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rows = await db_select("mail_drafts", filters={"user_id": _uid(user)}, order_by="-updated_at", limit=200)
    return {"ok": True, "data": {"drafts": rows}}


@router.post("/drafts")
async def create_draft(body: DraftBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    data = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    data["user_id"] = _uid(user)
    row = await db_insert("mail_drafts", data)
    if row is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "draft_write_failed"})
    return {"ok": True, "data": row}


@router.patch("/drafts/{draft_id}")
async def update_draft(draft_id: str, body: DraftPatch, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    await _owned("mail_drafts", draft_id, uid, "draft")
    patch = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if patch.get("status") and patch["status"] not in DRAFT_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "bad_status", "available": DRAFT_STATUSES})
    # We never auto-send: 'sent' must be set by an explicit send action, not here.
    if patch.get("status") == "sent":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "send_not_allowed_here", "hint": "approve the draft; sending is a separate gated action"})
    if not patch:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "empty_patch"})
    updated = await db_update("mail_drafts", patch, filters={"id": draft_id, "user_id": uid})
    if not updated:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "draft_update_failed"})
    return {"ok": True, "data": updated[0]}


@router.delete("/drafts/{draft_id}")
async def delete_draft(draft_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    await _owned("mail_drafts", draft_id, uid, "draft")
    await db_delete("mail_drafts", filters={"id": draft_id, "user_id": uid})
    return {"ok": True, "data": {"deleted": draft_id}}


def _parse_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
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
    return {}
