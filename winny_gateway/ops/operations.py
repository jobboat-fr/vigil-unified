"""Operations department — the open-items digest (P2).

Deterministic and read-only: it counts open commitments (action items captured from
meetings) and blocked department runs, and writes a status digest. No LLM, so it is
exact and cheap; acceptance re-counts and confirms the digest reconciles.
"""
from __future__ import annotations

from typing import Any

from winny_gateway.db import db_insert, db_select


async def _open_commitments(uid: str) -> int:
    rows = await db_select("commitments", filters={"org_id": uid}, limit=2000)
    return sum(1 for c in rows if (c.get("status") or "open") == "open")


async def run(uid: str, _inp: dict[str, Any]) -> dict[str, Any]:
    open_commits = await _open_commitments(uid)
    tasks = await db_select("ops_tasks", filters={"user_id": uid}, order_by="-created_at", limit=200)
    blocked = sum(1 for t in tasks if t.get("status") == "blocked")

    body = (
        f"# Operations digest\n\n"
        f"- Open action items: **{open_commits}**\n"
        f"- Blocked department runs: **{blocked}**\n"
        f"- Total recent runs: {len(tasks)}\n"
    )
    art = await db_insert("artifacts", {
        "user_id": uid, "title": f"Operations digest — {open_commits} open items", "kind": "report",
        "brief": "Operations digest", "approach": "", "text_dump": body, "status": "draft", "version": 1,
    })
    return {
        "artifact_id": (art or {}).get("id"),
        "summary": f"{open_commits} open action items, {blocked} blocked runs",
        "metrics": {"cost_usd": 0, "tool_calls": 0, "open_commitments": open_commits, "blocked": blocked},
    }


async def acceptance(uid: str, _inp: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    actual = await _open_commitments(uid)
    reported = (result.get("metrics") or {}).get("open_commitments")
    ok = reported == actual
    return {"accepted": ok, "reason": "digest counts reconcile" if ok else f"stale: {reported} vs {actual}"}
