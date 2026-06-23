"""Ops Team commercial model — plans, usage metering, quota gating.

Inspired by VIGIL's existing business model: the same tier ids and EUR pricing
(free / starter / pro / team / enterprise), per-feature caps, and feature flags — mapped
to Ops Team concepts (runs/day, connectors, departments, write-actions, BYOK). A tenant's
plan resolves from their org's active subscription (VIGIL's `subscriptions` table);
usage is derived from `ops_tasks` (we already record cost per run). No new tables.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from winny_gateway.db import db_select
from winny_gateway.logging import get_logger

logger = get_logger(__name__)

# Mirror of VIGIL's plan tiers (prices in EUR cents), mapped to Ops Team limits.
OPS_PLANS: dict[str, dict[str, Any]] = {
    "free":       {"name": "Gratuit",    "price_eur_cents": 0,     "ops_runs_per_day": 20,   "max_connectors": 1,    "departments": 3, "write_actions": False, "byok": False},
    "starter":    {"name": "Starter",    "price_eur_cents": 1900,  "ops_runs_per_day": 100,  "max_connectors": 3,    "departments": 5, "write_actions": False, "byok": False},
    "pro":        {"name": "Pro",        "price_eur_cents": 4900,  "ops_runs_per_day": 500,  "max_connectors": 10,   "departments": 7, "write_actions": True,  "byok": True},
    "team":       {"name": "Team",       "price_eur_cents": 14900, "ops_runs_per_day": 2000, "max_connectors": 50,   "departments": 7, "write_actions": True,  "byok": True},
    "enterprise": {"name": "Enterprise", "price_eur_cents": 0,     "ops_runs_per_day": None, "max_connectors": None, "departments": 7, "write_actions": True,  "byok": True, "contact_sales": True},
}


def plan_limits(plan: str) -> dict[str, Any]:
    return OPS_PLANS.get(plan) or OPS_PLANS["free"]


async def tenant_plan(uid: str) -> str:
    """A tenant's plan: their org's active subscription tier (VIGIL model), else
    DEFAULT_OPS_PLAN (default 'pro', so existing single-tenant use isn't capped)."""
    try:
        members = await db_select("org_members", filters={"user_id": uid}, limit=1)
        if members:
            org_id = members[0].get("org_id")
            subs = await db_select("subscriptions", filters={"org_id": org_id}, limit=10)
            active = [s for s in subs if (s.get("status") or "") in ("active", "trialing")]
            tier = active[0].get("plan_tier") if active else None
            if tier in OPS_PLANS:
                return tier
    except Exception as exc:  # noqa: BLE001 — never block a run on a billing lookup
        logger.debug("tenant_plan resolve failed: %s", exc)
    plan = os.getenv("DEFAULT_OPS_PLAN", "pro")
    return plan if plan in OPS_PLANS else "pro"


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


async def usage_summary(uid: str) -> dict[str, Any]:
    tasks = await db_select("ops_tasks", filters={"user_id": uid}, order_by="-created_at", limit=3000)
    today, month = _today(), _month()
    runs_today = sum(1 for t in tasks if str(t.get("created_at") or "").startswith(today))
    runs_month = sum(1 for t in tasks if str(t.get("created_at") or "").startswith(month))
    cost_month = round(sum(float(t.get("cost_usd") or 0) for t in tasks if str(t.get("created_at") or "").startswith(month)), 4)
    plan = await tenant_plan(uid)
    limits = plan_limits(plan)
    cap = limits.get("ops_runs_per_day")
    return {
        "plan": plan, "plan_name": limits.get("name"), "price_eur_cents": limits.get("price_eur_cents"),
        "runs_today": runs_today, "runs_month": runs_month, "cost_usd_month": cost_month,
        "daily_cap": cap, "remaining_today": (None if cap is None else max(0, cap - runs_today)),
        "limits": limits,
    }


async def check_run_quota(uid: str) -> tuple[bool, dict[str, Any]]:
    """(allowed, usage_summary). Allowed unless the plan's daily run cap is reached."""
    s = await usage_summary(uid)
    cap = s["daily_cap"]
    return (cap is None or s["runs_today"] < cap), s
