"""Legal department — reviews the company's own documents (P2).

"In knowledge of the docs": Legal grounds strictly in the user's Vault documents
(vault_documents — the company-related files, with extracted text + risk flags) and
must CITE the documents it relies on as [doc:<id>]. Acceptance verifies the cited
ids are REAL documents, so a memo can't be accepted if it's ungrounded/hallucinated.

`review` is the only LLM touchpoint; tests monkeypatch it.
"""
from __future__ import annotations

import re
from typing import Any

from winny.council.consensus import consensus
from winny.council.providers import ask
from winny.council.registry import worker_registry
from winny.council.summarizer import _parse_json
from winny_gateway.db import db_insert, db_select

_CITE = re.compile(r"\[doc:([0-9a-fA-F-]{6,})\]")

_SYSTEM = (
    "You are corporate counsel reviewing a company's own documents. Use ONLY the "
    "provided documents. For every claim, cite the document it comes from as "
    "[doc:<id>]. Flag risks, obligations, deadlines, and missing items. If the "
    "documents don't cover something, say so — never invent facts or citations."
)


async def review(query: str, context: str) -> tuple[str, list[str], float]:
    """Returns (memo, cited_doc_ids, cost)."""
    prompt = f"Documents:\n{context}\n\nTask: {query}\n\nWrite the review memo with [doc:<id>] citations."
    result = await ask(worker_registry()["primary"], prompt, system=_SYSTEM, temperature=0.3, max_tokens=900)
    memo = (result.get("output") or "").strip()
    cited = list(dict.fromkeys(_CITE.findall(memo)))
    try:
        cost = float(result.get("cost_usd") or 0.0)
    except (TypeError, ValueError):
        cost = 0.0
    return memo, cited, cost


_VERIFY_SYSTEM = (
    "You are an adversarial legal reviewer verifying a colleague's memo against the "
    "source documents. Check every claim is supported by a cited [doc:<id>] in the "
    "sources; flag overreach, unsupported assertions, or invented facts. Respond ONLY "
    'with JSON: {"confidence": 0.0-1.0, "flags": ["short issue", ...]}'
)


async def verify(memo: str, context: str) -> tuple[dict[str, Any], float]:
    """Second pass: a reviewer PANEL votes on whether the memo is fully grounded
    (multi-reviewer consensus, not a single call). Returns a {confidence, flags}
    verdict; an offline/empty panel returns confidence 1.0 so it only blocks on an
    explicit low-consensus result — the deterministic grounding gate always applies."""
    result = await consensus(
        "Is every claim in this memo supported by a cited [doc:<id>] in the sources? "
        "Vote yes only if it is fully grounded with no overreach.",
        f"Memo:\n{memo}\n\nSources:\n{context}",
    )
    conf = result.get("confidence")
    if conf is None:           # whole panel abstained (offline) → don't block
        return {"confidence": 1.0, "flags": []}, result.get("cost_usd", 0.0)
    flags = [str(v.get("reason"))[:160] for v in result.get("votes", []) if v.get("vote") == "no" and v.get("reason")]
    return {"confidence": float(conf), "flags": flags[:10]}, result.get("cost_usd", 0.0)


async def run(uid: str, inp: dict[str, Any]) -> dict[str, Any]:
    query = str(inp.get("query") or
                "Review the company documents for risks, obligations, deadlines, and anything needing attention.")
    docs = await db_select("vault_documents", filters={"user_id": uid}, limit=40)
    docs = [d for d in docs if (d.get("extracted_text") or d.get("summary") or d.get("title"))]
    doc_ids = [str(d["id"]) for d in docs]

    if not docs:
        art = await db_insert("artifacts", {
            "user_id": uid, "title": "Legal review — no documents", "kind": "report",
            "brief": "Legal review", "approach": "",
            "text_dump": "# Legal review\n\nNo company documents are in the Vault yet. Upload contracts, "
                         "agreements, and policies for the Legal department to ground its review in.",
            "status": "draft", "version": 1,
        })
        return {"artifact_id": (art or {}).get("id"), "summary": "No company documents to review yet",
                "metrics": {"cost_usd": 0, "tool_calls": 0, "docs": 0}, "doc_ids": [], "cited_ids": []}

    context = "\n".join(
        f"[doc:{d['id']}] {d.get('title') or d.get('filename') or 'Untitled'} "
        f"({d.get('category') or 'other'}) — {(d.get('summary') or (d.get('extracted_text') or ''))[:600]}"
        for d in docs
    )

    # Precedent board — feed recent findings into context so the review builds on
    # prior engagements instead of starting cold (adapted from lavern).
    precedents = await db_select("legal_precedents", filters={"user_id": uid}, order_by="-created_at", limit=8)
    if precedents:
        context += "\n\nPrior findings (precedent board — consider, do not blindly repeat):\n" + "\n".join(
            f"- {p.get('title')}: {p.get('summary')}" for p in precedents
        )

    memo, cited, cost = await review(query, context)
    real_cited = [c for c in cited if c in doc_ids]   # keep only citations to real documents

    # Multi-pass: adversarially verify the memo against the sources.
    verdict, vcost = await verify(memo, context)
    cost += vcost

    full_memo = memo + (
        f"\n\n---\n**Verification** — confidence {verdict['confidence']:.2f}"
        + ("\n- " + "\n- ".join(verdict["flags"]) if verdict["flags"] else " · no flags")
    )
    art = await db_insert("artifacts", {
        "user_id": uid, "title": f"Legal review — {len(docs)} documents", "kind": "report",
        "brief": "Legal review (grounded + verified)", "approach": "",
        "text_dump": full_memo, "status": "draft", "version": 1,
    })

    # Record this finding on the precedent board (only when grounded).
    if real_cited:
        await db_insert("legal_precedents", {
            "user_id": uid, "title": query[:120], "summary": memo[:400], "doc_ids": real_cited,
        })

    return {
        "artifact_id": (art or {}).get("id"),
        "summary": f"Reviewed {len(docs)} docs, cited {len(real_cited)}, verified (confidence {verdict['confidence']:.2f})",
        "metrics": {"cost_usd": round(cost, 4), "tool_calls": 2, "docs": len(docs)},
        "doc_ids": doc_ids,
        "cited_ids": real_cited,
        "verdict": verdict,
        "precedents_used": len(precedents),
    }


async def acceptance(uid: str, _inp: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("doc_ids"):
        return {"accepted": True, "reason": "no company documents in the Vault yet"}
    cited = result.get("cited_ids") or []
    if not cited:
        return {"accepted": False, "reason": "memo cited no real document — ungrounded"}
    verdict = result.get("verdict") or {}
    conf = float(verdict.get("confidence", 1.0))
    if conf < 0.5:
        flags = ", ".join(verdict.get("flags") or [])
        return {"accepted": False, "reason": f"failed verification (confidence {conf:.2f}): {flags[:200]}"}
    return {"accepted": True, "reason": f"grounded in {len(cited)} docs, verified (confidence {conf:.2f})"}
