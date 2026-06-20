"""Studio routes — artifact drafting that enforces the brainstorm-first gate.

This is the end-to-end proof of the VIGIL × WinnyWoo agentic spine: the
`brainstorming` thinking skill (think-first HARD-GATE) wired to a real product
surface. The flow is two explicit stages, mirroring the skill's checklist:

  1. POST /v1/artifacts/brainstorm  → explore intent, propose 2-3 approaches
     with trade-offs + a recommendation + clarifying questions. NO artifact is
     produced. This is the gate.
  2. POST /v1/artifacts              → only after the user picks an approach;
     drafts the structured document and stores it.

Plus list/get/delete and /refine to iterate.

Persistence (Stage 5): the EXISTING `public.artifacts` table (shared with the
prior VIGIL app, RLS on). We map content→text_dump, brief→brief, approach→
approach, the Markdown stays in text_dump, and `version` counts revisions. All
reads/writes are scoped to the authenticated user's id (the db layer's
cross-tenant guard enforces a user_id filter on this table). The LLM call reuses
the council's provider (`winny.council.providers.ask`) which degrades to a
deterministic stub when no API key is set, so the surface never crashes keyless.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from winny.council.providers import ask
from winny.council.registry import worker_registry
from winny.council.canvas_brainstorm import brainstorm_board
from winny_gateway.auth import get_current_user
from winny_gateway.db import db_delete, db_insert, db_select, db_update
from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/v1/artifacts", tags=["studio"])

_TABLE = "artifacts"

# Artifact kinds the Studio understands → a one-line shape hint for the drafter.
KINDS: dict[str, str] = {
    "proposal": "a persuasive business proposal with problem, solution, scope, pricing, and next steps",
    "brief": "a tight brief: objective, background, requirements, success criteria, constraints",
    "contract": "a plain-language agreement: parties, scope, deliverables, terms, payment, termination",
    "memo": "an internal decision memo: context, options considered, recommendation, rationale",
    "report": "a structured report: summary, findings, analysis, recommendations",
}


def _uid(user: dict[str, Any]) -> str:
    uid = user.get("sub")
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no user id in token")
    return str(uid)


def _public(row: dict[str, Any]) -> dict[str, Any]:
    """Map a DB row onto the Artifact shape the web client expects."""
    return {
        "id": row.get("id"),
        "title": row.get("title") or "Untitled artifact",
        "kind": row.get("kind") or "proposal",
        "brief": row.get("brief") or "",
        "approach": row.get("approach") or "",
        "content": row.get("text_dump") or "",
        "canvas": row.get("canvas") or None,
        "tldraw": row.get("tldraw") or None,
        "stub": bool(row.get("stub", False)),
        "revisions": max(int(row.get("version") or 1) - 1, 0),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _primary_worker() -> dict[str, Any]:
    return worker_registry()["primary"]


def _grounding_block(grounding: str | None) -> str:
    if not grounding:
        return ""
    return (
        "\n\nGround your work strictly in these source documents — quote and cite "
        f"them, do not invent facts beyond them:\n\n<<<\n{grounding}\n>>>\n"
    )


async def _owned_row(artifact_id: str, uid: str) -> dict[str, Any]:
    rows = await db_select(_TABLE, filters={"id": artifact_id, "user_id": uid}, limit=1)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "artifact_not_found", "artifact_id": artifact_id},
        )
    return rows[0]


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
    uid = _uid(user)
    user_prompt = (
        f"Draft {KINDS[body.kind]}.\n\n"
        f"Brief:\n{body.brief}\n\n"
        f"Approved approach / design to follow:\n{body.approach}"
        f"{_grounding_block(body.grounding)}\n\n"
        "Write the full document now."
    )
    result = await ask(_primary_worker(), user_prompt, system=_DRAFT_SYSTEM, temperature=0.5, max_tokens=2400)
    row = await db_insert(
        _TABLE,
        {
            "user_id": uid,
            "title": body.title,
            "kind": body.kind,
            "brief": body.brief,
            "approach": body.approach,
            "text_dump": result.get("output", ""),
            "stub": bool(result.get("stub", False)),
            "status": "draft",
            "version": 1,
        },
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "artifact_write_failed"})
    return {"ok": True, "data": _public(row)}


@router.get("")
async def list_artifacts(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rows = await db_select(_TABLE, filters={"user_id": _uid(user)}, order_by="-updated_at", limit=100)
    summaries = []
    for r in rows:
        art = _public(r)
        if len(art["content"]) > 280:
            art["content"] = art["content"][:280] + "…"
        summaries.append(art)
    return {"ok": True, "data": {"artifacts": summaries}}


@router.get("/{artifact_id}")
async def get_artifact(artifact_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    return {"ok": True, "data": _public(await _owned_row(artifact_id, _uid(user)))}


@router.delete("/{artifact_id}")
async def delete_artifact(artifact_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    await _owned_row(artifact_id, uid)  # 404s if not owned
    await db_delete(_TABLE, filters={"id": artifact_id, "user_id": uid})
    return {"ok": True, "data": {"deleted": artifact_id}}


class CanvasSaveBody(BaseModel):
    tldraw: dict[str, Any] | None = Field(default=None, description="The tldraw editor document.")
    canvas: dict[str, Any] | None = Field(default=None, description="The {nodes,edges,table} structure.")


@router.patch("/{artifact_id}/canvas")
async def save_canvas(artifact_id: str, body: CanvasSaveBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Persist the user's edits to the artifact canvas (tldraw doc + structure)."""
    uid = _uid(user)
    await _owned_row(artifact_id, uid)  # 404s if not owned
    patch: dict[str, Any] = {}
    if body.tldraw is not None:
        patch["tldraw"] = body.tldraw
    if body.canvas is not None:
        patch["canvas"] = body.canvas
    if patch:
        await db_update(_TABLE, patch, filters={"id": artifact_id, "user_id": uid})
    return {"ok": True, "data": {"saved": artifact_id}}


class CanvasBrainstormBody(BaseModel):
    prompt: str = Field(default="", description="Free-text brainstorm prompt.")
    board_text: str = Field(default="", description="Text of the current canvas blocks, for context.")
    lens: str = Field(default="ideas", description="ideas|expand|risks|missing|next_steps|critique|summarize|council")
    topic: str = Field(default="")


@router.post("/canvas-brainstorm")
async def canvas_brainstorm(body: CanvasBrainstormBody, _user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Brainstorm on the canvas: the council returns blocks (ideas/risks/takes)
    to drop onto the tldraw board, given the board context + a prompt or lens."""
    res = await brainstorm_board(
        prompt=body.prompt, board_text=body.board_text, lens=body.lens, topic=body.topic
    )
    return {"ok": True, "data": res}


class RefineBody(BaseModel):
    instruction: str = Field(description="How to change the artifact, e.g. 'make it shorter and add a timeline'.")


@router.post("/{artifact_id}/refine")
async def refine_artifact(artifact_id: str, body: RefineBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Iterate on an existing artifact with the agent (the Studio side-chat)."""
    uid = _uid(user)
    art = await _owned_row(artifact_id, uid)
    user_prompt = (
        f"Here is the current {art.get('kind')} (Markdown):\n\n<<<\n{art.get('text_dump') or ''}\n>>>\n\n"
        f"Revise it per this instruction:\n{body.instruction}\n\n"
        "Output only the full revised document."
    )
    result = await ask(_primary_worker(), user_prompt, system=_DRAFT_SYSTEM, temperature=0.5, max_tokens=2400)
    updated = await db_update(
        _TABLE,
        {
            "text_dump": result.get("output", art.get("text_dump") or ""),
            "stub": bool(result.get("stub", False)),
            "version": int(art.get("version") or 1) + 1,
            "updated_at": datetime.now(UTC).isoformat(),
        },
        filters={"id": artifact_id, "user_id": uid},
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "artifact_update_failed"})
    return {"ok": True, "data": _public(updated[0])}


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
