"""Multi-reviewer consensus — the AutoGen/MetaGPT 'debate → vote' pattern,
reimplemented on our own council workers (no framework dependency).

Asks several council workers the same yes/no question and tallies a weighted verdict,
for a department's high-stakes decision (e.g. 'is this memo fully grounded?'). Offline
workers abstain rather than skew the vote; an empty panel returns no verdict so the
caller can fall back to its deterministic gate.
"""
from __future__ import annotations

from typing import Any

from winny.council.providers import ask
from winny.council.registry import worker_registry
from winny.council.summarizer import _parse_json

_SYSTEM = (
    "You are one reviewer on a panel answering a strict yes/no question. Be decisive. "
    'Respond ONLY with JSON: {"vote": "yes|no", "reason": "one short sentence"}'
)


async def consensus(question: str, context: str = "", *, threshold: float = 0.66) -> dict[str, Any]:
    reg = worker_registry()
    workers = [w for w in (reg.get("primary"), reg.get("reviewer_1"), reg.get("reviewer_2")) if w]
    prompt = f"{context}\n\nQuestion: {question}" if context else question

    votes: list[dict[str, Any]] = []
    cost = 0.0
    for w in workers:
        res = await ask(w, prompt, system=_SYSTEM, temperature=0.1, max_tokens=120)
        if res.get("stub"):
            continue  # offline → abstain
        plan = _parse_json(res.get("output", "")) or {}
        v = str(plan.get("vote", "")).lower()
        if v in ("yes", "no"):
            votes.append({"vote": v, "reason": plan.get("reason")})
        try:
            cost += float(res.get("cost_usd") or 0)
        except (TypeError, ValueError):
            pass

    yes = sum(1 for v in votes if v["vote"] == "yes")
    no = sum(1 for v in votes if v["vote"] == "no")
    total = yes + no
    confidence = round(yes / total, 3) if total else None
    return {
        "decision": bool(confidence is not None and confidence >= threshold),
        "confidence": confidence,
        "yes": yes, "no": no,
        "votes": votes,
        "panel": len(workers),
        "abstained": len(workers) - total,
        "cost_usd": round(cost, 4),
    }
