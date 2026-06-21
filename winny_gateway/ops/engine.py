"""Ops Team engine — on-demand dispatch with an effectiveness gate.

run_job() is the whole loop for a department run: guardrail check → run the job's
handler → run its deterministic acceptance check → enforce the per-run budget →
record the task, an activity event, and the department's recomputed health. A run
that fails acceptance or blows its budget is `blocked`, never a silent success.

P0 jobs are code-defined here (handlers are plain async callables). Later phases
can persist job templates (ops_jobs) and dispatch to Hermes profiles instead.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

from winny_gateway.db import db_insert, db_select, db_update
from winny_gateway.logging import get_logger
from winny_gateway.ops import support

logger = get_logger(__name__)

Handler = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
Acceptance = Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]


# ── Department registry (the effectiveness contracts) ───────────────────────
DEPARTMENTS: dict[str, dict[str, Any]] = {
    "support": {
        "slug": "support",
        "name": "Support",
        "head_lens": "comms",
        "mandate": "Triage the inbox: classify every message and draft replies for the ones that need a response.",
        "kpis": [{"key": "triaged", "label": "Inbox triaged", "target": "100%"}],
        "guardrails": {
            "per_run_spend_cap_usd": 0.50,
            "daily_run_cap": 50,
            "allowed_tools": ["mail_messages", "mail_drafts"],
            "max_wall_ms": 120_000,
            "irreversible_requires_owner": True,
        },
        "jobs": {
            "triage": {
                "handler": support.run,
                "acceptance": support.acceptance,
                "default_input": {"folder": "INBOX", "limit": 20},
                "is_selftest": False,
            },
            "selftest": {
                "handler": support.run,
                "acceptance": support.acceptance,
                "default_input": {"folder": "INBOX", "limit": 5},
                "is_selftest": True,
            },
        },
    },
}


def department_spec(slug: str) -> dict[str, Any] | None:
    return DEPARTMENTS.get(slug)


def department_seed_row(uid: str, slug: str) -> dict[str, Any]:
    """The row to insert when a user first gets a department (status=provisioning
    until its selftest passes)."""
    spec = DEPARTMENTS[slug]
    return {
        "user_id": uid,
        "slug": spec["slug"],
        "name": spec["name"],
        "head_lens": spec.get("head_lens"),
        "hermes_profile": None,
        "mandate": spec.get("mandate", ""),
        "kpis": spec.get("kpis", []),
        "status": "provisioning",
        "paused": False,
        "guardrails": spec.get("guardrails", {}),
        "health": {},
    }


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def compute_health(uid: str, department_id: str) -> dict[str, Any]:
    """Roll up the last ~20 runs into the department's health signal."""
    tasks = await db_select(
        "ops_tasks",
        filters={"user_id": uid, "department_id": department_id},
        order_by="-created_at",
        limit=20,
    )
    if not tasks:
        return {"success_rate": None, "avg_cost_usd": 0, "p50_ms": 0, "last_result": None, "runs": 0}
    accepted = [t for t in tasks if t.get("accepted")]
    costs = [float(t.get("cost_usd") or 0) for t in tasks]
    walls = sorted(int(t.get("wall_ms") or 0) for t in tasks)
    last = tasks[0]
    return {
        "success_rate": round(len(accepted) / len(tasks), 3),
        "avg_cost_usd": round(sum(costs) / len(costs), 4),
        "p50_ms": walls[len(walls) // 2],
        "last_result": ("accepted" if last.get("accepted") else (last.get("status") or "unknown")),
        "last_run_at": last.get("created_at"),
        "runs": len(tasks),
    }


class GuardrailError(Exception):
    """Raised when a run is refused before it starts (paused / cap hit)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def run_job(
    uid: str,
    dept_row: dict[str, Any],
    job_name: str,
    inp: dict[str, Any] | None,
    *,
    trigger: str = "manual",
) -> dict[str, Any]:
    """Execute one on-demand run end-to-end. Returns the recorded ops_task."""
    spec = department_spec(dept_row["slug"])
    if not spec or job_name not in spec["jobs"]:
        raise GuardrailError("unknown_job", f"no job '{job_name}' for department '{dept_row['slug']}'")
    job = spec["jobs"][job_name]
    dept_id = dept_row["id"]
    guardrails = dept_row.get("guardrails") or spec.get("guardrails") or {}

    # ── Guardrails (before any spend) ───────────────────────────────────────
    if dept_row.get("paused"):
        raise GuardrailError("paused", "department is paused (kill switch)")
    cap = guardrails.get("daily_run_cap")
    if cap:
        today = _today()
        recent = await db_select("ops_tasks", filters={"user_id": uid, "department_id": dept_id}, limit=1000)
        if sum(1 for t in recent if str(t.get("created_at") or "").startswith(today)) >= int(cap):
            raise GuardrailError("daily_cap", f"daily run cap ({cap}) reached")

    job_input = {**(job.get("default_input") or {}), **(inp or {})}
    task = await db_insert("ops_tasks", {
        "user_id": uid,
        "department_id": dept_id,
        "job": job_name,
        "trigger": ("selftest" if job.get("is_selftest") else trigger),
        "title": f"{spec['name']} · {job_name}",
        "input": job_input,
        "status": "working",
        "created_at": _now(),
    })
    task_id = (task or {}).get("id")

    # ── Run handler + acceptance, enforce budget ────────────────────────────
    handler: Handler = job["handler"]
    accept: Acceptance = job["acceptance"]
    started = time.monotonic()
    error = None
    accepted = False
    reason = ""
    result: dict[str, Any] = {}
    try:
        result = await handler(uid, job_input)
        verdict = await accept(uid, job_input, result)
        accepted = bool(verdict.get("accepted"))
        reason = str(verdict.get("reason") or "")
    except Exception as exc:  # noqa: BLE001 — a crash is a failed run, not a 500
        error = f"{type(exc).__name__}: {exc}"
        logger.warning("ops.run_failed dept=%s job=%s: %s", dept_row["slug"], job_name, error)

    wall_ms = int((time.monotonic() - started) * 1000)
    metrics = result.get("metrics") or {}
    cost = float(metrics.get("cost_usd") or 0)

    # Over-budget is a failure, not a slow success.
    spend_cap = guardrails.get("per_run_spend_cap_usd")
    wall_cap = guardrails.get("max_wall_ms")
    if accepted and spend_cap is not None and cost > float(spend_cap):
        accepted, reason = False, f"over spend cap (${cost} > ${spend_cap})"
    if accepted and wall_cap is not None and wall_ms > int(wall_cap):
        accepted, reason = False, f"over time budget ({wall_ms}ms > {wall_cap}ms)"

    status = "done" if accepted else "blocked"
    updated = await db_update("ops_tasks", {
        "status": status,
        "accepted": accepted,
        "cost_usd": round(cost, 4),
        "tool_calls": int(metrics.get("tool_calls") or 0),
        "wall_ms": wall_ms,
        "output_artifact_id": result.get("artifact_id"),
        "error": error or (None if accepted else reason),
    }, filters={"id": task_id, "user_id": uid})

    # ── Activity event + health + lifecycle ─────────────────────────────────
    summary = result.get("summary") or reason or error or "run complete"
    await db_insert("ops_events", {
        "user_id": uid,
        "department_id": dept_id,
        "task_id": task_id,
        "kind": "selftest" if job.get("is_selftest") else "run",
        "summary": f"{spec['name']}: {summary}" + ("" if accepted else f" — blocked: {reason or error}"),
        "ts": _now(),
    })

    health = await compute_health(uid, dept_id)
    dept_patch: dict[str, Any] = {"health": health}
    # A selftest result decides whether the department is allowed to be live.
    if job.get("is_selftest"):
        dept_patch["status"] = "live" if accepted else "failing"
    await db_update("departments", dept_patch, filters={"id": dept_id, "user_id": uid})

    return (updated[0] if updated else task) | {"accepted": accepted, "reason": reason}
