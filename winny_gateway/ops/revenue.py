"""Revenue department — keep the pipeline warm (P1).

Contract:
  job        for every deal stalled in proposal/negotiation, draft a follow-up to
             the contact (review-then-send — never auto-sent)
  input      {limit}
  tools      crm_deals + crm_contacts + mail_drafts
  output     a pipeline-followups artifact
  acceptance every targeted deal has a follow-up draft (idempotent by deal id)
  budget     per-run spend + wall-clock caps (engine-enforced)

`draft_followup` is the only LLM touchpoint; tests monkeypatch it.
"""
from __future__ import annotations

from typing import Any

from winny.council.providers import ask
from winny.council.registry import worker_registry
from winny_gateway.db import db_insert, db_select
from winny_gateway.integrations import connector
from winny_gateway.ops import brand

STALLED_STAGES = ["proposal", "negotiation"]

_SYSTEM = (
    "You are a B2B sales rep writing a short, warm follow-up email to nudge a stalled "
    "deal forward. 2-4 sentences, specific, no fluff. Output ONLY the email body."
)


async def draft_followup(deal: dict[str, Any], contact: dict[str, Any] | None) -> tuple[str, float]:
    who = (contact or {}).get("name") or "there"
    prompt = (
        f"Deal: {deal.get('title')}\nStage: {deal.get('stage')}\nValue: {deal.get('value')}\n"
        f"Contact: {who} at {(contact or {}).get('company') or 'their company'}\n"
        f"Notes: {deal.get('notes') or ''}\n\nWrite the follow-up email body."
    )
    result = await ask(worker_registry()["primary"], prompt, system=_SYSTEM, temperature=0.6, max_tokens=300)
    body = (result.get("output") or "").strip() or f"Hi {who}, just checking in on {deal.get('title')}."
    try:
        cost = float(result.get("cost_usd") or 0.0)
    except (TypeError, ValueError):
        cost = 0.0
    return body, cost


async def run(uid: str, inp: dict[str, Any]) -> dict[str, Any]:
    limit = max(1, min(int(inp.get("limit") or 25), 200))

    deals = await db_select("crm_deals", filters={"user_id": uid}, limit=1000)
    stalled = [d for d in deals if d.get("stage") in STALLED_STAGES]

    existing = await db_select("mail_drafts", filters={"user_id": uid}, limit=5000)
    drafted_deal_ids = {
        (d.get("metadata") or {}).get("deal_id")
        for d in existing if isinstance(d.get("metadata"), dict)
    }

    # If the tenant has connected Gmail, we'll PROPOSE a send for each draft — pending
    # human approval (never auto-sent). Best-effort; no connection = drafts only.
    gmail_cid: str | None = None
    try:
        gconns = await connector.list_connections(uid, "gmail")
        gmail_cid = gconns[0]["id"] if gconns else None
    except Exception:  # noqa: BLE001
        gmail_cid = None

    drafted: list[str] = []
    proposed = 0
    off_brand = 0
    cost = 0.0
    calls = 0
    for d in stalled:
        if d["id"] in drafted_deal_ids or len(drafted) >= limit:
            continue
        contact = None
        if d.get("contact_id"):
            cs = await db_select("crm_contacts", filters={"id": d["contact_id"], "user_id": uid}, limit=1)
            contact = cs[0] if cs else None
        body, c = await draft_followup(d, contact)
        cost += c
        calls += 1
        to = contact["email"] if contact and contact.get("email") else None
        subject = f"Following up: {d.get('title') or 'our conversation'}"
        await db_insert("mail_drafts", {
            "user_id": uid, "to_addrs": [to] if to else [], "subject": subject, "body": body,
            "status": "draft", "metadata": {"deal_id": d["id"], "source": "revenue_dept"},
        })
        drafted.append(d["id"])
        if gmail_cid and to:
            # Brand-voice QA gate: only the agent's autonomous send-proposal is gated;
            # the draft above always exists for the human to edit.
            qa = await brand.brand_qa(body, channel="email")
            cost += float(qa.get("cost_usd") or 0.0)
            if not qa["ok"]:
                off_brand += 1
                continue
            try:
                await connector.propose_action(uid, gmail_cid, "send",
                                                {"to": to, "subject": subject, "body": body},
                                                requested_by="agent")
                proposed += 1
            except Exception:  # noqa: BLE001 — proposing is additive, never fail the run
                pass

    summary = f"Drafted {len(drafted)} follow-ups for stalled deals"
    if proposed:
        summary += f", proposed {proposed} sends (pending approval)"
    if off_brand:
        summary += f", held {off_brand} off-brand (draft only)"
    art = await db_insert("artifacts", {
        "user_id": uid, "title": f"Pipeline follow-ups — {len(drafted)} deals",
        "kind": "report", "brief": "Revenue follow-up run", "approach": "",
        "text_dump": f"# Pipeline follow-ups\n\n{summary}.",
        "status": "draft", "version": 1,
    })

    return {
        "artifact_id": (art or {}).get("id"),
        "summary": summary,
        "metrics": {"cost_usd": round(cost, 4), "tool_calls": calls, "drafted": len(drafted),
                    "proposed": proposed, "off_brand": off_brand},
        "targeted_ids": drafted,
    }


async def acceptance(uid: str, _inp: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    ids = list(result.get("targeted_ids") or [])
    if not ids:
        return {"accepted": True, "reason": "no stalled deals to follow up"}
    drafts = await db_select("mail_drafts", filters={"user_id": uid}, limit=5000)
    have = {(d.get("metadata") or {}).get("deal_id") for d in drafts if isinstance(d.get("metadata"), dict)}
    for i in ids:
        if i not in have:
            return {"accepted": False, "reason": f"no follow-up draft for deal {i}"}
    return {"accepted": True, "reason": f"{len(ids)} follow-up drafts created"}
