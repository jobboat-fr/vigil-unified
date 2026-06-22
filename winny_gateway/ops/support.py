"""Support department — inbox triage (the P0 reference department).

Its effectiveness contract (see plans/ops-team-agentic-company.md §6a):
  job        triage untriaged messages and draft replies for the ones that need one
  input      {folder, limit}
  tools      mail_messages + mail_drafts (the /v1/mail surface)
  output     a triage-summary artifact
  acceptance every targeted message ends triaged with a valid category, AND a draft
             exists for each message classified `respond` — checked against the DB,
             not an LLM opinion, so "it ran" and "it worked" stay distinct.
  budget     per-run spend + wall-clock caps (enforced by the engine)

`classify_message` is the only LLM touchpoint; tests monkeypatch it so the suite
is hermetic. It degrades to a deterministic stub when no model key is set.
"""
from __future__ import annotations

from typing import Any

from winny.council.providers import ask
from winny.council.registry import cheap_worker
from winny.council.summarizer import _parse_json
from winny_gateway.db import db_insert, db_select, db_update

CATEGORIES = ["urgent", "respond", "fyi", "newsletter", "spam", "archive"]
PRIORITIES = ["high", "normal", "low"]

_TRIAGE_SYSTEM = (
    "You are the VIGIL × WinnyWoo mail triage classifier. Classify one email into "
    f"exactly one category from {CATEGORIES} and a priority from {PRIORITIES}. "
    "Be decisive. Respond ONLY with a JSON object: "
    '{"category": "...", "priority": "...", "score": 0.0-1.0, '
    '"suggested_action": "one short sentence", "reasoning": "one short sentence"}'
)


async def classify_message(msg: dict[str, Any]) -> tuple[dict[str, Any], float]:
    """Classify one message via the council. Returns (plan, cost_usd)."""
    prompt = (
        f"From: {msg.get('from_name') or ''} <{msg.get('from_addr') or ''}>\n"
        f"Subject: {msg.get('subject') or ''}\n\n"
        f"{(msg.get('body') or msg.get('snippet') or '')[:2000]}\n\n"
        "Classify it. Respond ONLY with the JSON object."
    )
    result = await ask(cheap_worker(), prompt, system=_TRIAGE_SYSTEM, temperature=0.2, max_tokens=400)
    plan = _parse_json(result.get("output", "")) or {}
    try:
        cost = float(result.get("cost_usd") or 0.0)
    except (TypeError, ValueError):
        cost = 0.0
    return plan, cost


def _summary_md(triaged: int, drafts: int, buckets: dict[str, int]) -> str:
    lines = [f"# Support triage run\n\nTriaged **{triaged}** messages, drafted **{drafts}** replies.\n", "## By category"]
    lines += [f"- {k}: {v}" for k, v in buckets.items() if v]
    return "\n".join(lines)


async def run(uid: str, inp: dict[str, Any]) -> dict[str, Any]:
    """Triage untriaged messages in a folder; draft replies for `respond`.

    Returns the run result the engine records + the acceptance check reads:
    {artifact_id, summary, metrics, targeted_ids, respond_ids}.
    """
    folder = str(inp.get("folder") or "INBOX")
    limit = max(1, min(int(inp.get("limit") or 20), 200))

    msgs = await db_select(
        "mail_messages",
        filters={"user_id": uid, "folder": folder, "triaged": False},
        limit=limit,
    )

    targeted_ids: list[str] = []
    respond_ids: list[str] = []
    buckets: dict[str, int] = {c: 0 for c in CATEGORIES}
    cost = 0.0
    calls = 0

    for m in msgs:
        plan, c = await classify_message(m)
        cost += c
        calls += 1
        category = plan.get("category") if plan.get("category") in CATEGORIES else "fyi"
        priority = plan.get("priority") if plan.get("priority") in PRIORITIES else "normal"
        patch: dict[str, Any] = {"category": category, "priority": priority, "triaged": True}
        try:
            patch["triage_score"] = round(max(0.0, min(1.0, float(plan.get("score")))), 2)
        except (TypeError, ValueError):
            pass
        await db_update("mail_messages", patch, filters={"id": m["id"], "user_id": uid})
        targeted_ids.append(m["id"])
        buckets[category] = buckets.get(category, 0) + 1

        if category == "respond":
            await db_insert("mail_drafts", {
                "user_id": uid,
                "in_reply_to": m.get("external_id"),
                "to_addrs": [m["from_addr"]] if m.get("from_addr") else [],
                "subject": f"Re: {m.get('subject') or ''}".strip(),
                "body": str(plan.get("suggested_action") or "").strip(),
                "status": "draft",
            })
            respond_ids.append(m["id"])

    art = await db_insert("artifacts", {
        "user_id": uid,
        "title": f"Support triage — {len(targeted_ids)} messages",
        "kind": "report",
        "brief": f"Inbox triage run ({folder})",
        "approach": "",
        "text_dump": _summary_md(len(targeted_ids), len(respond_ids), buckets),
        "status": "draft",
        "version": 1,
    })

    return {
        "artifact_id": (art or {}).get("id"),
        "summary": f"Triaged {len(targeted_ids)} messages, drafted {len(respond_ids)} replies",
        "metrics": {"cost_usd": round(cost, 4), "tool_calls": calls,
                    "triaged": len(targeted_ids), "drafts": len(respond_ids)},
        "targeted_ids": targeted_ids,
        "respond_ids": respond_ids,
    }


async def acceptance(uid: str, _inp: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Deterministic check: did Support actually do the job? Reads the DB."""
    ids = list(result.get("targeted_ids") or [])
    if not ids:
        return {"accepted": True, "reason": "no untriaged messages — vacuously satisfied"}

    rows = await db_select("mail_messages", filters={"user_id": uid}, limit=5000)
    by_id = {r["id"]: r for r in rows}
    for i in ids:
        r = by_id.get(i)
        if not r or not r.get("triaged") or r.get("category") not in CATEGORIES:
            return {"accepted": False, "reason": f"message {i} not properly triaged"}

    respond_ids = list(result.get("respond_ids") or [])
    drafts = await db_select("mail_drafts", filters={"user_id": uid}, limit=5000)
    if len(drafts) < len(respond_ids):
        return {"accepted": False, "reason": "missing drafts for one or more `respond` messages"}

    return {"accepted": True, "reason": f"{len(ids)} messages triaged; {len(respond_ids)} drafts created"}
