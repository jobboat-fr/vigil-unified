"""Marketing department — campaign planning (Phase 4).

Contract:
  job        draft a campaign (audience, channels, message variants) for the tenant's
             contact base on a topic
  input      {topic}
  tools      crm_contacts
  output     a campaign-plan artifact
  acceptance the reported audience size reconciles to the actual contact count
             (deterministic — the plan is built on real numbers, not invented)
  budget     per-run spend + wall-clock caps (engine-enforced)

`draft_campaign` is the only LLM touchpoint; tests monkeypatch it.
"""
from __future__ import annotations

from typing import Any

from winny.council.providers import ask_cheap
from winny_gateway.db import db_insert, db_select

_SYSTEM = (
    "You are a B2B marketer. Given a topic and audience size, draft a concise campaign: "
    "the angle, 2 subject-line options, and a 3-4 sentence email body. Output prose with "
    "clear labels; no preamble."
)


async def draft_campaign(topic: str, audience: int) -> tuple[str, float]:
    prompt = f"Topic: {topic}\nAudience: {audience} contacts\n\nDraft the campaign."
    result = await ask_cheap(prompt, system=_SYSTEM, temperature=0.6, max_tokens=400)
    body = (result.get("output") or "").strip() or f"Campaign on '{topic}' for {audience} contacts."
    try:
        cost = float(result.get("cost_usd") or 0.0)
    except (TypeError, ValueError):
        cost = 0.0
    return body, cost


async def run(uid: str, inp: dict[str, Any]) -> dict[str, Any]:
    topic = str(inp.get("topic") or "Re-engage our pipeline")
    contacts = await db_select("crm_contacts", filters={"user_id": uid}, limit=2000)
    audience = len(contacts)
    content, cost = await draft_campaign(topic, audience)

    art = await db_insert("artifacts", {
        "user_id": uid, "title": f"Campaign — {topic[:60]}", "kind": "report",
        "brief": "Marketing campaign plan", "approach": "",
        "text_dump": f"# Campaign: {topic}\n\n**Audience:** {audience} contacts\n\n{content}",
        "status": "draft", "version": 1,
    })
    return {
        "artifact_id": (art or {}).get("id"),
        "summary": f"Drafted a campaign for {audience} contacts on '{topic}'",
        "metrics": {"cost_usd": round(cost, 4), "tool_calls": 1, "audience": audience},
    }


async def acceptance(uid: str, _inp: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    contacts = await db_select("crm_contacts", filters={"user_id": uid}, limit=5000)
    reported = (result.get("metrics") or {}).get("audience")
    ok = reported == len(contacts)
    return {"accepted": ok, "reason": "audience reconciles to the contact base" if ok else f"audience stale: {reported} vs {len(contacts)}"}
