"""Growth / Lead Scout department — sources and qualifies leads (P2).

Works as a TEAM with Revenue: the scout mines inbound signals already in the system
(senders in the triaged inbox who aren't contacts yet), enriches + scores each, creates
a CRM contact + a proposal-stage deal, then HANDS OFF to Revenue to draft the outreach.
The handoff is the engine's generic cross-department dispatch — so the pipeline flows
scout → revenue without a human in between.

`enrich` is the only LLM touchpoint; tests monkeypatch it.
"""
from __future__ import annotations

import json
from typing import Any

from winny.council.providers import ask_cheap
from winny.council.summarizer import _parse_json
from winny_gateway.db import db_insert, db_select

_SYSTEM = (
    "You are an SDR qualifying an inbound contact. From the little we know, infer a "
    "likely company, role, and a fit score 0-100, and say why in one sentence. "
    'Respond ONLY with JSON: {"company": "...", "title": "...", "score": 0-100, "why": "..."}'
)


async def enrich(cand: dict[str, Any]) -> tuple[dict[str, Any], float]:
    prompt = (
        f"Name: {cand.get('name')}\nEmail: {cand.get('email')}\n"
        f"They emailed us about: {cand.get('subject') or '(unknown)'}\n\nQualify this lead."
    )
    result = await ask_cheap(prompt, system=_SYSTEM, temperature=0.4, max_tokens=200)
    plan = _parse_json(result.get("output", "")) or {}
    try:
        cost = float(result.get("cost_usd") or 0.0)
    except (TypeError, ValueError):
        cost = 0.0
    return plan, cost


async def run(uid: str, inp: dict[str, Any]) -> dict[str, Any]:
    limit = max(1, min(int(inp.get("limit") or 10), 100))

    contacts = await db_select("crm_contacts", filters={"user_id": uid}, limit=2000)
    known = {(c.get("email") or "").lower() for c in contacts if c.get("email")}

    msgs = await db_select("mail_messages", filters={"user_id": uid}, limit=300)
    cands: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in msgs:
        em = (m.get("from_addr") or "").lower()
        if not em or em in known or em in seen:
            continue
        seen.add(em)
        cands.append({"name": m.get("from_name") or em.split("@")[0], "email": em, "subject": m.get("subject")})
        if len(cands) >= limit:
            break

    created_contacts: list[str] = []
    created_deals: list[str] = []
    cost = 0.0
    calls = 0
    for c in cands:
        info, cc = await enrich(c)
        cost += cc
        calls += 1
        try:
            score = max(0.0, min(100.0, float(info.get("score") or 30)))
        except (TypeError, ValueError):
            score = 30.0
        contact = await db_insert("crm_contacts", {
            "user_id": uid, "name": c["name"], "email": c["email"],
            "company": info.get("company"), "title": info.get("title"),
            "tags": ["lead-scout"], "notes": info.get("why"),
        })
        if not contact:
            continue
        created_contacts.append(contact["id"])
        deal = await db_insert("crm_deals", {
            "user_id": uid, "title": f"{info.get('company') or c['name']} — inbound",
            "contact_id": contact["id"], "stage": "proposal", "probability": score,
            "metadata": {"source": "lead_scout"},
        })
        if deal:
            created_deals.append(deal["id"])

    art = await db_insert("artifacts", {
        "user_id": uid, "title": f"Lead scout — {len(created_contacts)} new leads", "kind": "report",
        "brief": "Lead scouting run", "approach": "",
        "text_dump": f"# Lead scout\n\nSourced and qualified **{len(created_contacts)}** inbound leads, "
                     f"created **{len(created_deals)}** deals, and handed them to Revenue for outreach.",
        "status": "draft", "version": 1,
    })

    # Team handoff: Revenue drafts outreach for the deals we just created.
    handoffs = [{"department": "revenue", "job": "follow_up", "input": {"limit": max(1, len(created_deals))}}] if created_deals else []

    return {
        "artifact_id": (art or {}).get("id"),
        "summary": f"Scouted {len(created_contacts)} leads → handed {len(created_deals)} deals to Revenue",
        "metrics": {"cost_usd": round(cost, 4), "tool_calls": calls, "leads": len(created_contacts)},
        "targeted_ids": created_contacts,
        "handoffs": handoffs,
    }


async def acceptance(uid: str, _inp: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    ids = list(result.get("targeted_ids") or [])
    if not ids:
        return {"accepted": True, "reason": "no new inbound leads to scout"}
    contacts = await db_select("crm_contacts", filters={"user_id": uid}, limit=5000)
    have = {c["id"] for c in contacts}
    for i in ids:
        if i not in have:
            return {"accepted": False, "reason": f"lead {i} not created"}
    return {"accepted": True, "reason": f"{len(ids)} leads sourced, qualified, and handed to Revenue"}
