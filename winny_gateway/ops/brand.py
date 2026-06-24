"""Brand-voice QA — a guideline gate for outbound copy.

Mimics the brand-voice content-generation + quality-assurance split: copy is
generated as usual, then a reviewer PANEL votes whether it's on-brand before the
agent may PROPOSE sending it (reusing the Phase 5 council consensus). Off-brand copy
still becomes a draft a human can edit — the gate only blocks the *autonomous*
send-proposal, never the human's own review.

Guidelines default to the product voice; a tenant override can be passed in.
"""
from __future__ import annotations

from typing import Any

from winny.council.consensus import consensus

DEFAULT_GUIDELINES = (
    "Voice: warm, direct, specific, concise. We are a human-in-the-loop AI workspace "
    "that 'thinks before it acts'. Do: be concrete, respect the reader's time, sound "
    "like a thoughtful operator. Don't: hype, hard-sell, over-promise, make unverifiable "
    "claims, use spammy/clickbait phrasing, or imply the AI acts without approval."
)


async def brand_qa(copy: str, *, channel: str = "email", guidelines: str | None = None) -> dict[str, Any]:
    g = guidelines or DEFAULT_GUIDELINES
    result = await consensus(
        f"Does this {channel} copy follow the brand guidelines? Vote yes only if it is "
        "on-brand with no hype, hard-sell, spam, or unverifiable claims.",
        f"Brand guidelines:\n{g}\n\nCopy:\n{copy}",
    )
    conf = result.get("confidence")
    issues = [str(v.get("reason"))[:160] for v in result.get("votes", [])
              if v.get("vote") == "no" and v.get("reason")]
    # Offline / empty panel (conf None) → pass: don't stall the pipeline, the human
    # still reviews the draft. Only an explicit low-consensus blocks the auto-proposal.
    ok = conf is None or bool(result.get("decision"))
    return {"ok": ok, "confidence": conf, "issues": issues[:10], "cost_usd": result.get("cost_usd", 0.0)}
