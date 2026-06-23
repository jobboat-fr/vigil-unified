"""Operations department — the open-items digest (P2).

Deterministic and read-only: it reads open commitments (action items — now from
multiple sources: meetings, Notion, …) and blocked department runs, and writes a
status digest broken down by source with an overdue count. No LLM, so it is exact
and cheap; acceptance re-counts and confirms the digest reconciles.
"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from winny_gateway.db import db_insert, db_select


async def _open_rows(uid: str) -> list[dict[str, Any]]:
    rows = await db_select("commitments", filters={"org_id": uid}, limit=2000)
    return [c for c in rows if (c.get("status") or "open") == "open"]


def _source(row: dict[str, Any]) -> str:
    return (row.get("source") or ("meeting" if row.get("room_id") else "other")) or "other"


def _is_overdue(row: dict[str, Any], now: datetime) -> bool:
    due = row.get("due_at")
    if not due:
        return False
    try:
        d = datetime.fromisoformat(str(due).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=UTC)
        return d < now
    except (ValueError, TypeError):
        return False


async def run(uid: str, _inp: dict[str, Any]) -> dict[str, Any]:
    open_rows = await _open_rows(uid)
    open_commits = len(open_rows)
    now = datetime.now(UTC)
    by_source = Counter(_source(r) for r in open_rows)
    overdue = sum(1 for r in open_rows if _is_overdue(r, now))

    tasks = await db_select("ops_tasks", filters={"user_id": uid}, order_by="-created_at", limit=200)
    blocked = sum(1 for t in tasks if t.get("status") == "blocked")

    source_lines = "".join(f"  - {src}: {n}\n" for src, n in sorted(by_source.items(), key=lambda kv: -kv[1]))
    body = (
        f"# Operations digest\n\n"
        f"- Open action items: **{open_commits}**"
        + (f" ({overdue} overdue)\n" if overdue else "\n")
        + (f"- By source:\n{source_lines}" if by_source else "")
        + f"- Blocked department runs: **{blocked}**\n"
        f"- Total recent runs: {len(tasks)}\n"
    )
    art = await db_insert("artifacts", {
        "user_id": uid, "title": f"Operations digest — {open_commits} open items", "kind": "report",
        "brief": "Operations digest", "approach": "", "text_dump": body, "status": "draft", "version": 1,
    })
    return {
        "artifact_id": (art or {}).get("id"),
        "summary": f"{open_commits} open action items"
                   + (f" ({overdue} overdue)" if overdue else "") + f", {blocked} blocked runs",
        "metrics": {"cost_usd": 0, "tool_calls": 0, "open_commitments": open_commits,
                    "overdue": overdue, "blocked": blocked, "by_source": dict(by_source)},
    }


async def acceptance(uid: str, _inp: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    actual = len(await _open_rows(uid))
    reported = (result.get("metrics") or {}).get("open_commitments")
    ok = reported == actual
    return {"accepted": ok, "reason": "digest counts reconcile" if ok else f"stale: {reported} vs {actual}"}
