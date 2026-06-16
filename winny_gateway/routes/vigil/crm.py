"""CRM routes — contacts + deal pipeline the `crm` skill routes into.

Surface (auth-required, scoped to the caller's user_id via the db guard):

  GET/POST       /v1/crm/contacts            list / create contacts
  PATCH/DELETE   /v1/crm/contacts/{id}       edit / remove
  GET/POST       /v1/crm/deals               list (filter by stage) / create
  PATCH/DELETE   /v1/crm/deals/{id}          move stage / edit / remove
  GET            /v1/crm/pipeline            rollup by stage: count, value,
                                             weighted (value*probability) value

Pipeline value rolls up to Finance; deal reviews route to the Council; account
briefs to Studio (the skill supplies that orchestration — this is the data layer).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from winny_gateway.auth import get_current_user
from winny_gateway.db import db_delete, db_insert, db_select, db_update
from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/v1/crm", tags=["crm"])

DEAL_STAGES = ["lead", "qualified", "proposal", "negotiation", "won", "lost"]


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


# ── Contacts ────────────────────────────────────────────────────────────────
class ContactBody(BaseModel):
    name: str = Field(min_length=1)
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    title: str | None = None
    tags: list[str] | None = None
    notes: str | None = None


class ContactPatch(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    title: str | None = None
    tags: list[str] | None = None
    notes: str | None = None


@router.get("/contacts")
async def list_contacts(user: dict = Depends(get_current_user), limit: int = Query(default=500, le=2000)) -> dict[str, Any]:
    rows = await db_select("crm_contacts", filters={"user_id": _uid(user)}, order_by="-updated_at", limit=limit)
    return {"ok": True, "data": {"contacts": rows}}


@router.post("/contacts")
async def create_contact(body: ContactBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    data = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    data["user_id"] = _uid(user)
    row = await db_insert("crm_contacts", data)
    if row is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "contact_write_failed"})
    return {"ok": True, "data": row}


@router.patch("/contacts/{contact_id}")
async def update_contact(contact_id: str, body: ContactPatch, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    await _owned("crm_contacts", contact_id, uid, "contact")
    patch = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not patch:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "empty_patch"})
    updated = await db_update("crm_contacts", patch, filters={"id": contact_id, "user_id": uid})
    if not updated:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "contact_update_failed"})
    return {"ok": True, "data": updated[0]}


@router.delete("/contacts/{contact_id}")
async def delete_contact(contact_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    await _owned("crm_contacts", contact_id, uid, "contact")
    await db_delete("crm_contacts", filters={"id": contact_id, "user_id": uid})
    return {"ok": True, "data": {"deleted": contact_id}}


# ── Deals ───────────────────────────────────────────────────────────────────
class DealBody(BaseModel):
    title: str = Field(min_length=1)
    contact_id: str | None = None
    stage: str = Field(default="lead")
    value: float = Field(default=0)
    currency: str = Field(default="USD")
    probability: float = Field(default=0, ge=0, le=100)
    expected_close: str | None = None
    notes: str | None = None


class DealPatch(BaseModel):
    title: str | None = None
    contact_id: str | None = None
    stage: str | None = None
    value: float | None = None
    currency: str | None = None
    probability: float | None = Field(default=None, ge=0, le=100)
    expected_close: str | None = None
    notes: str | None = None


@router.get("/deals")
async def list_deals(
    user: dict = Depends(get_current_user),
    stage: str | None = Query(default=None),
    limit: int = Query(default=500, le=2000),
) -> dict[str, Any]:
    filters: dict[str, Any] = {"user_id": _uid(user)}
    if stage:
        filters["stage"] = stage
    rows = await db_select("crm_deals", filters=filters, order_by="-updated_at", limit=limit)
    return {"ok": True, "data": {"deals": rows}}


@router.post("/deals")
async def create_deal(body: DealBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    if body.stage not in DEAL_STAGES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "bad_stage", "stage": body.stage, "available": DEAL_STAGES})
    data = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    data["user_id"] = _uid(user)
    row = await db_insert("crm_deals", data)
    if row is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "deal_write_failed"})
    return {"ok": True, "data": row}


@router.patch("/deals/{deal_id}")
async def update_deal(deal_id: str, body: DealPatch, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    await _owned("crm_deals", deal_id, uid, "deal")
    patch = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if "stage" in patch and patch["stage"] not in DEAL_STAGES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "bad_stage", "stage": patch["stage"], "available": DEAL_STAGES})
    if not patch:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "empty_patch"})
    updated = await db_update("crm_deals", patch, filters={"id": deal_id, "user_id": uid})
    if not updated:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "deal_update_failed"})
    return {"ok": True, "data": updated[0]}


@router.delete("/deals/{deal_id}")
async def delete_deal(deal_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    await _owned("crm_deals", deal_id, uid, "deal")
    await db_delete("crm_deals", filters={"id": deal_id, "user_id": uid})
    return {"ok": True, "data": {"deleted": deal_id}}


@router.get("/pipeline")
async def pipeline(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rows = await db_select("crm_deals", filters={"user_id": _uid(user)}, limit=2000)
    stages: dict[str, dict[str, float]] = {
        s: {"count": 0, "value": 0.0, "weighted": 0.0} for s in DEAL_STAGES
    }
    open_value = 0.0
    weighted_open = 0.0
    for r in rows:
        st = r.get("stage") or "lead"
        if st not in stages:
            stages[st] = {"count": 0, "value": 0.0, "weighted": 0.0}
        val = float(r.get("value") or 0)
        prob = float(r.get("probability") or 0) / 100.0
        stages[st]["count"] += 1
        stages[st]["value"] = round(stages[st]["value"] + val, 2)
        stages[st]["weighted"] = round(stages[st]["weighted"] + val * prob, 2)
        if st not in ("won", "lost"):
            open_value += val
            weighted_open += val * prob
    return {
        "ok": True,
        "data": {
            "stages": stages,
            "open_value": round(open_value, 2),
            "weighted_open_value": round(weighted_open, 2),
            "deal_count": len(rows),
        },
    }
