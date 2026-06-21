"""Chief of Staff — orchestrates the company (P2).

Two jobs:
  • route (primary) — dispatch every operational department's primary job via the
    engine's handoff mechanism. The "run the whole company" button.
  • brief — a company brief: a deterministic rollup of each department's status +
    health, with a short council-written narrative on top.

The Chief of Staff never does a department's work itself; it routes and summarizes.
`brief_narrate` is the only LLM touchpoint; tests monkeypatch it.
"""
from __future__ import annotations

import json
from typing import Any

from winny.council.providers import ask
from winny.council.registry import worker_registry
from winny_gateway.db import db_insert, db_select

# Operational departments the Chief of Staff routes to (everyone but itself).
ROUTABLE = ["support", "finance", "revenue", "growth", "legal", "operations"]


async def route(uid: str, _inp: dict[str, Any]) -> dict[str, Any]:
    handoffs = [{"department": d, "job": None, "input": {}} for d in ROUTABLE]
    art = await db_insert("artifacts", {
        "user_id": uid, "title": "Chief of Staff — company run", "kind": "report",
        "brief": "Company-wide routing", "approach": "",
        "text_dump": "# Company run\n\nDispatched work to: " + ", ".join(ROUTABLE) + ".",
        "status": "draft", "version": 1,
    })
    return {
        "artifact_id": (art or {}).get("id"),
        "summary": f"Routed work to {len(ROUTABLE)} departments",
        "metrics": {"cost_usd": 0, "tool_calls": 0},
        "handoffs": handoffs,
    }


async def route_acceptance(_uid: str, _inp: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    n = len(result.get("handoffs") or [])
    return {"accepted": n > 0, "reason": f"dispatched {n} departments"}


async def brief_narrate(rollup: list[dict[str, Any]]) -> tuple[str, float]:
    prompt = (
        "Here is the live status of each company department (already computed):\n"
        f"{json.dumps(rollup, indent=2)}\n\n"
        "Write a 3-5 sentence executive brief: what's healthy, what needs attention, and the "
        "single most important thing to do next. Prose only; do not invent departments."
    )
    result = await ask(worker_registry()["primary"],
                       prompt, system="You are a chief of staff writing a crisp executive brief.",
                       temperature=0.4, max_tokens=350)
    try:
        cost = float(result.get("cost_usd") or 0.0)
    except (TypeError, ValueError):
        cost = 0.0
    return (result.get("output") or "").strip(), cost


async def brief(uid: str, _inp: dict[str, Any]) -> dict[str, Any]:
    depts = await db_select("departments", filters={"user_id": uid}, limit=100)
    rollup = [{
        "name": d.get("name"),
        "status": d.get("status"),
        "paused": bool(d.get("paused")),
        "success_rate": (d.get("health") or {}).get("success_rate"),
        "runs": (d.get("health") or {}).get("runs", 0),
    } for d in depts if d.get("slug") != "cos"]

    narrative, cost = await brief_narrate(rollup)
    lines = ["# Company brief\n", narrative or "", "\n## Departments"]
    lines += [f"- {r['name']}: {r['status']}"
              + (f" · success {round((r['success_rate'] or 0) * 100)}%" if r.get("success_rate") is not None else "")
              + (f" · {r['runs']} runs" if r.get("runs") else "")
              for r in rollup]
    art = await db_insert("artifacts", {
        "user_id": uid, "title": "Company brief", "kind": "report",
        "brief": "Chief of Staff company brief", "approach": "",
        "text_dump": "\n".join(lines), "status": "draft", "version": 1,
    })
    return {
        "artifact_id": (art or {}).get("id"),
        "summary": f"Company brief across {len(rollup)} departments",
        "metrics": {"cost_usd": round(cost, 4), "tool_calls": 1},
        "dept_count": len(rollup),
    }


async def brief_acceptance(_uid: str, _inp: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    ok = bool(result.get("artifact_id")) and (result.get("dept_count") or 0) >= 0
    return {"accepted": ok, "reason": "company brief compiled"}
