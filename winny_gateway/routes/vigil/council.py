"""Council routes — ports VIGIL's /v1/council surface to the unified gateway.

Endpoints (auth required, like the VIGIL original):
  GET  /v1/council/tasks               → the 4 role lenses + thresholds
  POST /v1/council/orchestrate         → run the full council, return the record
  POST /v1/council/orchestrate/stream  → SSE: stream each stage as it completes

Request body accepts either a full ``scenario`` (VIGIL-compatible) OR a plain
``transcript`` (+ optional ``question``), in which case we synthesize a scenario
from the role lens's default prompts.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from winny.council import (
    REVIEWER_SYSTEM_PROMPT,
    ROLE_SYSTEM_PROMPTS,
    TASK_MATRIX,
    AIWorkerCollective,
)
from winny_gateway.auth import get_current_user
from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/v1/council", tags=["council"])


class OrchestrateBody(BaseModel):
    task: str = Field(description="Lens key: cfo_review | tech_review | legal_review | product_review")
    transcript: str | None = Field(default=None, description="Meeting transcript to review.")
    question: str | None = Field(default=None, description="Optional focus question for the primary advisor.")
    scenario: dict[str, Any] | None = Field(default=None, description="Full VIGIL scenario override.")


def _build_scenario(body: OrchestrateBody) -> dict[str, Any]:
    if body.scenario:
        scenario = dict(body.scenario)
        scenario.setdefault("id", "inline")
        scenario.setdefault("primarySystemPrompt", ROLE_SYSTEM_PROMPTS.get(body.task, ""))
        scenario.setdefault("reviewerSystemPrompt", REVIEWER_SYSTEM_PROMPT)
        return scenario
    transcript = body.transcript or ""
    primary_user = transcript
    if body.question:
        primary_user = f"{transcript}\n\nFocus question: {body.question}"
    return {
        "id": "inline",
        "transcript": transcript,
        "primarySystemPrompt": ROLE_SYSTEM_PROMPTS.get(body.task, ""),
        "primaryUserPrompt": (
            f"Meeting transcript:\n\n{primary_user}\n\n"
            "What is your intervention? Respond ONLY with the JSON object."
        ),
        "reviewerSystemPrompt": REVIEWER_SYSTEM_PROMPT,
    }


def _collective() -> AIWorkerCollective:
    return AIWorkerCollective()


@router.get("/tasks")
async def list_tasks(_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    tasks = {
        key: {
            "description": cfg["description"],
            "categories": cfg["categories"],
            "requirements": cfg["requirements"],
            "pattern_focus": cfg["pattern_focus"],
            "consensus_threshold": cfg["consensusThreshold"],
            "readiness_threshold": cfg["readinessThreshold"],
            "sla_ms": cfg["slaMs"],
        }
        for key, cfg in TASK_MATRIX.items()
    }
    return {"ok": True, "data": {"tasks": tasks}}


@router.post("/orchestrate")
async def orchestrate(body: OrchestrateBody, _user: dict = Depends(get_current_user)) -> dict[str, Any]:
    if body.task not in TASK_MATRIX:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "unknown_task", "task": body.task, "available": list(TASK_MATRIX)},
        )
    scenario = _build_scenario(body)
    try:
        record = await _collective().orchestrate(body.task, scenario)
    except Exception as exc:  # noqa: BLE001 — surface as 502 like the VIGIL original
        logger.error("council.orchestrate.fail task=%s err=%s", body.task, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "orchestration_failed", "message": str(exc)}) from exc
    return {"ok": True, "data": record}


@router.post("/orchestrate/stream")
async def orchestrate_stream(body: OrchestrateBody, _user: dict = Depends(get_current_user)) -> StreamingResponse:
    if body.task not in TASK_MATRIX:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "unknown_task", "task": body.task, "available": list(TASK_MATRIX)},
        )
    scenario = _build_scenario(body)
    return StreamingResponse(_run_council_sse(body.task, scenario), media_type="text/event-stream")


async def _run_council_sse(task: str, scenario: dict[str, Any]):
    """Shared SSE generator: stream council stage events then the final record."""
    queue: asyncio.Queue[tuple[str | None, dict[str, Any] | None]] = asyncio.Queue()

    async def emit(stage: str, data: dict[str, Any]) -> None:
        await queue.put((stage, data))

    async def run() -> None:
        try:
            record = await _collective().orchestrate(task, scenario, emit=emit)
            await queue.put(("complete", {"ok": True, "record": record}))
        except Exception as exc:  # noqa: BLE001
            await queue.put(("error", {"error": str(exc)}))
        finally:
            await queue.put((None, None))

    runner = asyncio.create_task(run())
    try:
        while True:
            stage, data = await queue.get()
            if stage is None:
                break
            yield f"event: {stage}\ndata: {json.dumps(data, default=str)}\n\n"
    finally:
        if not runner.done():
            runner.cancel()
