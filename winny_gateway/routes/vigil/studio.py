"""Studio routes — artifact drafting that enforces the brainstorm-first gate.

This is the end-to-end proof of the VIGIL × WinnyWoo agentic spine: the
`brainstorming` thinking skill (think-first HARD-GATE) wired to a real product
surface. The flow is two explicit stages, mirroring the skill's checklist:

  1. POST /v1/artifacts/brainstorm  → explore intent, propose 2-3 approaches
     with trade-offs + a recommendation + clarifying questions. NO artifact is
     produced. This is the gate.
  2. POST /v1/artifacts              → only after the user picks an approach;
     drafts the structured document and stores it.

Plus list/get/delete and /refine to iterate. Storage is in-memory and scoped to
the authenticated user (same model as rooms.py); Supabase persistence layers on
later. The LLM call reuses the council's provider (`winny.council.providers.ask`)
which degrades to a deterministic stub when no API key is set, so the surface
never crashes in a keyless deploy.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from winny.council.providers import ask
from winny.council.registry import worker_registry
from winny_gateway.auth import get_current_user
from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/v1/artifacts", tags=["studio"])

# In-memory artifact store: artifact_id -> dict (carries owner_sub for scoping).
_ARTIFACTS: dict[str, dict[str, Any]] = {}

# Artifact kinds the Studio understands → a one-line shape hint for the drafter.
KINDS: dict[str, str] = {
    "proposal": "a persuasive business proposal with problem, solution, scope, pricing, and next steps",
    "brief": "a tight brief: objective, background, requirements, success criteria, constraints",
    "contract": "a plain-language agreement: parties, scope, deliverables, terms, payment, termination",
    "memo": "an internal decision memo: context, options considered, recommendation, rationale",
    "report": "a structured report: summary, findings, analysis, recommendations",
}


def _sub(user: dict[str, Any]) -> str:
    return str(user.get("sub") or user.get("email") or "anon")


def _owned(artifact_id: str, user: dict[str, Any]) -> dict[str, Any]:
    art = _ARTIFACTS.get(artifact_id)
    if art is None or art["owner_sub"] != _sub(user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "artifact_not_found", "artifact_id": artifact_id},
        )
    return art


def _public(art: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in art.items() if k != "owner_sub"}


def _primary_worker() -> dict[str, Any]:
    return worker_registry()["primary"]


def _grounding_block(grounding: str | None) -> str:
    if not grounding:
        return ""
    return (
        "\n\nGround your work strictly in these source documents — quote and cite "
        f"them, do not invent facts beyond them:\n\n<<<\n{grounding}\n>>>\n"
    )


# ── Stage 1: brainstorm (the gate) ──────────────────────────────────────────
class BrainstormBody(BaseModel):
    brief: str = Field(description="What the user wants to create, in their words.")
    kind: str = Field(default="proposal", description="Artifact kind: " + " | ".join(KINDS))
    grounding: str | None = Field(default=None, description="Optional Vault/source text to ground in.")


_BRAINSTORM_SYSTEM = (
    "You are the VIGIL × WinnyWoo Studio strategist running the `brainstorming` "
    "discipline. You DO NOT write the final artifact yet. First you think: explore "
    "intent, surface assumptions, and propose distinct approaches with honest "
    "trade-offs and a clear recommendation. 'Too simple to need a design' is a trap "
    "— always think first. Respond ONLY with a JSON object, no prose around it, "
    "matching exactly:\n"
    '{"understanding": "1-2 sentences on what they actually need",'
    ' "clarifying_questions": ["...", "..."],'
    ' "approaches": [{"name": "...", "summary": "...", "tradeoffs": "...", "recommended": true|false}],'
    ' "recommended_design": "a few sentences describing the recommended shape of the artifact"}'
)


@router.post("/brainstorm")
async def brainstorm(body: BrainstormBody, _user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Stage 1 — think before drafting. Returns approaches + a design, never an artifact."""
    if body.kind not in KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "unknown_kind", "kind": body.kind, "available": list(KINDS)},
        )
    user_prompt = (
        f"The user wants to create {KINDS[body.kind]}.\n\n"
        f"Their brief:\n{body.brief}{_grounding_block(body.grounding)}\n\n"
        "Think it through and respond ONLY with the JSON object."
    )
    result = await ask(_primary_worker(), user_prompt, system=_BRAINSTORM_SYSTEM, temperature=0.4, max_tokens=1200)
    plan = _parse_json(result.get("output", ""))
    return {
        "ok": True,
        "data": {
            "kind": body.kind,
            "brief": body.brief,
            "stub": result.get("stub", False),
            "plan": plan,
        },
    }


# ── Stage 2: draft (only after an approach is chosen) ───────────────────────
class CreateArtifactBody(BaseModel):
    title: str = Field(default="Untitled artifact")
    kind: str = Field(default="proposal")
    brief: str = Field(description="The original brief.")
    approach: str = Field(description="The approved approach/design to draft against (the gate output).")
    grounding: str | None = Field(default=None)


_DRAFT_SYSTEM = (
    "You are the VIGIL × WinnyWoo Studio drafter. The thinking is done and an "
    "approach was approved — now produce the artifact. Write it in clean Markdown, "
    "well structured with headings, concrete and specific. No preamble, no 'here is "
    "your draft' — output only the document body."
)


@router.post("")
async def create_artifact(body: CreateArtifactBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Stage 2 — draft the artifact against an approved approach and store it."""
    if body.kind not in KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "unknown_kind", "kind": body.kind, "available": list(KINDS)},
        )
    user_prompt = (
        f"Draft {KINDS[body.kind]}.\n\n"
        f"Brief:\n{body.brief}\n\n"
        f"Approved approach / design to follow:\n{body.approach}"
        f"{_grounding_block(body.grounding)}\n\n"
        "Write the full document now."
    )
    result = await ask(_primary_worker(), user_prompt, system=_DRAFT_SYSTEM, temperature=0.5, max_tokens=2400)
    now = datetime.now(UTC).isoformat()
    artifact_id = str(uuid.uuid4())
    art = {
        "id": artifact_id,
        "owner_sub": _sub(user),
        "title": body.title,
        "kind": body.kind,
        "brief": body.brief,
        "approach": body.approach,
        "content": result.get("output", ""),
        "stub": result.get("stub", False),
        "revisions": 0,
        "created_at": now,
        "updated_at": now,
    }
    _ARTIFACTS[artifact_id] = art
    return {"ok": True, "data": _public(art)}


@router.get("")
async def list_artifacts(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    sub = _sub(user)
    arts = [_public(a) for a in _ARTIFACTS.values() if a["owner_sub"] == sub]
    arts.sort(key=lambda a: a["updated_at"], reverse=True)
    # Trim content in the list view; full content via GET /{id}.
    summaries = [{**a, "content": (a["content"][:280] + "…") if len(a["content"]) > 280 else a["content"]} for a in arts]
    return {"ok": True, "data": {"artifacts": summaries}}


@router.get("/{artifact_id}")
async def get_artifact(artifact_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    return {"ok": True, "data": _public(_owned(artifact_id, user))}


@router.delete("/{artifact_id}")
async def delete_artifact(artifact_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    _owned(artifact_id, user)
    _ARTIFACTS.pop(artifact_id, None)
    return {"ok": True, "data": {"deleted": artifact_id}}


class RefineBody(BaseModel):
    instruction: str = Field(description="How to change the artifact, e.g. 'make it shorter and add a timeline'.")


@router.post("/{artifact_id}/refine")
async def refine_artifact(artifact_id: str, body: RefineBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Iterate on an existing artifact with the agent (the Studio side-chat)."""
    art = _owned(artifact_id, user)
    user_prompt = (
        f"Here is the current {art['kind']} (Markdown):\n\n<<<\n{art['content']}\n>>>\n\n"
        f"Revise it per this instruction:\n{body.instruction}\n\n"
        "Output only the full revised document."
    )
    result = await ask(_primary_worker(), user_prompt, system=_DRAFT_SYSTEM, temperature=0.5, max_tokens=2400)
    art["content"] = result.get("output", art["content"])
    art["stub"] = result.get("stub", False)
    art["revisions"] += 1
    art["updated_at"] = datetime.now(UTC).isoformat()
    return {"ok": True, "data": _public(art)}


def _parse_json(text: str) -> dict[str, Any]:
    """Best-effort JSON parse of a model reply that should be a single object."""
    text = text.strip()
    if text.startswith("```"):
        # strip a ```json fence if the model added one
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except (json.JSONDecodeError, ValueError):
                pass
    return {"understanding": "", "clarifying_questions": [], "approaches": [], "recommended_design": text}
