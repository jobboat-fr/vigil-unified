"""Ops Team routes (P0) — the agentic-company surface.

Departments are on-demand agent units (no clock schedules). This router exposes:
read the org board + health, dispatch a run, run the effectiveness selftest, read
the task ledger + activity feed, and the global kill switch. The work itself runs
through the engine (winny_gateway.ops.engine), which enforces guardrails + the
acceptance gate. Every read/write is scoped to the authenticated user.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from winny_gateway.auth import get_current_user
from winny_gateway.db import db_insert, db_select, db_update
from winny_gateway.logging import get_logger
from winny_gateway.ops import billing
from winny_gateway.ops.engine import (
    DEPARTMENTS,
    GuardrailError,
    compute_health,
    department_seed_row,
    department_spec,
    primary_job,
    run_job,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/v1/ops", tags=["ops"])

_TABLE = "departments"


def _uid(user: dict[str, Any]) -> str:
    uid = user.get("sub")
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no user id in token")
    return str(uid)


def _public(row: dict[str, Any]) -> dict[str, Any]:
    spec = department_spec(row.get("slug") or "")
    jobs = [j for j in (spec["jobs"] if spec else {}) if j != "selftest"]
    return {
        "id": row.get("id"),
        "slug": row.get("slug"),
        "name": row.get("name"),
        "head_lens": row.get("head_lens"),
        "mandate": row.get("mandate") or "",
        "kpis": row.get("kpis") or [],
        "status": row.get("status") or "provisioning",
        "paused": bool(row.get("paused")),
        "guardrails": row.get("guardrails") or {},
        "health": row.get("health") or {},
        "jobs": jobs,
        "primary_job": primary_job(spec) if spec else None,
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


async def _owned_department(dept_id: str, uid: str) -> dict[str, Any]:
    rows = await db_select(_TABLE, filters={"id": dept_id, "user_id": uid}, limit=1)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "department_not_found", "id": dept_id})
    return rows[0]


async def _ensure_seeded(uid: str) -> list[dict[str, Any]]:
    """First visit: provision the default departments for this user."""
    rows = await db_select(_TABLE, filters={"user_id": uid}, limit=100)
    have = {r.get("slug") for r in rows}
    for slug in DEPARTMENTS:
        if slug not in have:
            inserted = await db_insert(_TABLE, department_seed_row(uid, slug))
            if inserted:
                rows.append(inserted)
    return rows


# ── Org board ───────────────────────────────────────────────────────────────
@router.get("/departments")
async def list_departments(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rows = await _ensure_seeded(_uid(user))
    rows.sort(key=lambda r: r.get("slug") or "")
    return {"ok": True, "data": {"departments": [_public(r) for r in rows]}}


@router.get("/departments/{dept_id}")
async def get_department(dept_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    return {"ok": True, "data": _public(await _owned_department(dept_id, _uid(user)))}


@router.get("/departments/{dept_id}/health")
async def department_health(dept_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    dept = await _owned_department(dept_id, uid)
    health = await compute_health(uid, dept["id"])
    await db_update(_TABLE, {"health": health}, filters={"id": dept["id"], "user_id": uid})
    return {"ok": True, "data": {"health": health}}


# ── On-demand dispatch ────────────────────────────────────────────────────────
class RunBody(BaseModel):
    job: str | None = Field(default=None, description="Job name; null runs the department's primary job.")
    input: dict[str, Any] = Field(default_factory=dict)


async def _dispatch(uid: str, dept: dict[str, Any], job: str, inp: dict[str, Any], trigger: str) -> dict[str, Any]:
    # Plan quota gate (commercial model) — refuse over the plan's daily run cap.
    allowed, usage = await billing.check_run_quota(uid)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail={"error": "quota_exceeded", "plan": usage["plan"],
                                    "daily_cap": usage["daily_cap"], "runs_today": usage["runs_today"]})
    try:
        task = await run_job(uid, dept, job, inp, trigger=trigger)
    except GuardrailError as exc:
        # 409: the run was refused by a guardrail (paused / cap), not a server error.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": exc.code, "message": exc.message})
    return {"ok": True, "data": {"task": task}}


@router.get("/usage")
async def usage(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """The tenant's plan + this period's usage (runs today/month, cost, cap)."""
    return {"ok": True, "data": await billing.usage_summary(_uid(user))}


@router.post("/departments/{dept_id}/run")
async def run_department(dept_id: str, body: RunBody | None = None, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    dept = await _owned_department(dept_id, uid)
    body = body or RunBody()
    return await _dispatch(uid, dept, body.job, body.input, "manual")


@router.post("/departments/{dept_id}/selftest")
async def selftest_department(dept_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    dept = await _owned_department(dept_id, uid)
    return await _dispatch(uid, dept, "selftest", {}, "selftest")


# ── Ledger + feed ─────────────────────────────────────────────────────────────
@router.get("/tasks")
async def list_tasks(
    department: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    filters: dict[str, Any] = {"user_id": _uid(user)}
    if department:
        filters["department_id"] = department
    if status_filter:
        filters["status"] = status_filter
    rows = await db_select("ops_tasks", filters=filters, order_by="-created_at", limit=limit)
    return {"ok": True, "data": {"tasks": rows}}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rows = await db_select("ops_tasks", filters={"id": task_id, "user_id": _uid(user)}, limit=1)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "task_not_found", "id": task_id})
    return {"ok": True, "data": {"task": rows[0]}}


@router.get("/feed")
async def feed(limit: int = Query(default=30, ge=1, le=200), user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rows = await db_select("ops_events", filters={"user_id": _uid(user)}, order_by="-ts", limit=limit)
    return {"ok": True, "data": {"events": rows}}


# ── Kill switch ───────────────────────────────────────────────────────────────
@router.post("/pause-all")
async def pause_all(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    rows = await db_select(_TABLE, filters={"user_id": uid}, limit=100)
    for r in rows:
        await db_update(_TABLE, {"paused": True}, filters={"id": r["id"], "user_id": uid})
    return {"ok": True, "data": {"paused": len(rows)}}


@router.post("/resume-all")
async def resume_all(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    rows = await db_select(_TABLE, filters={"user_id": uid}, limit=100)
    for r in rows:
        await db_update(_TABLE, {"paused": False}, filters={"id": r["id"], "user_id": uid})
    return {"ok": True, "data": {"resumed": len(rows)}}
