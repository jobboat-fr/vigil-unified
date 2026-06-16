"""VIGIL Assistant adapter — bridges the VIGIL SPA to Hermes-on-OVH.

VIGIL's AssistantWidget (vigil-web/src/lib/assistantApi.js) speaks a
named-event SSE dialect:

    event: text_delta   data: {"content": "..."}
    event: tool_event   data: {...}
    event: done         data: {}
    event: error        data: {"message": "..."}

The Hermes shim on OVH (deploy/ovh/hermes_server.py /chat/stream) emits
unnamed envelopes instead:

    data: {"type": "token", "text": "..."}
    data: {"type": "done", "reply": "..."}
    data: {"type": "error", "error": "..."}

This router translates between the two so the VIGIL frontend gets a real
agent without vigil-core having to grow an LLM stack. Auth is the same
Supabase JWT both products already share; CSP on vigil-ai.xyz already
allow-lists this gateway's origin.

History: the Hermes shim keeps per-session AIAgent state in-process, but
exposes no transcript read-back. /history therefore returns empty — the
widget renders from its own local state during a session and starts
fresh on reload. Wire Supabase persistence later if continuity matters.

TTS: not implemented — 503. assistantApi.requestTTS() treats any
non-OK as "no audio" and degrades silently.
"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from winny_gateway.auth import get_current_user
from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/v1/assistant", tags=["assistant"])


class AssistantChatIn(BaseModel):
    message: str
    session_id: str | None = None
    page_context: dict[str, Any] | None = None


def _sse(event: str, payload: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n".encode()


@router.post("/chat")
async def assistant_chat(
    body: AssistantChatIn,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> StreamingResponse:
    """Stream a VIGIL assistant turn through Hermes, translating SSE dialects."""
    cfg = request.app.state.config
    if not cfg.hermes_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hermes not configured (set HERMES_URL).",
        )

    target = cfg.hermes_url.rstrip("/") + "/chat/stream"
    # Scope sessions per VIGIL user; the widget's session_id keeps multiple
    # conversations distinct within one account.
    user_id = str(user.get("sub", "anon"))
    session_id = f"vigil:{user_id}:{body.session_id or 'default'}"

    # Ground the agent in the user's vault: a compact index of classified
    # documents (titles, categories, risk flags) rides along in context.
    # The agent pulls full text on demand via the mcp-winnywoo vault tools.
    from winny_gateway.routes.vault import build_vault_index

    vault_index = await build_vault_index(user_id)

    payload = {
        "message": body.message,
        "context": {
            "page": body.page_context or {},
            "surface": "vigil-assistant",
            "user_id": user_id,
            "vault_index": vault_index,
        },
        "session_id": session_id,
    }
    headers = {
        "content-type": "application/json",
        "x-hermes-proxy-auth": cfg.hermes_proxy_secret or "",
        "x-winnywoo-user-id": str(user.get("sub", "anon")),
        "x-winnywoo-user-email": str(user.get("email", "")),
    }
    timeout = cfg.hermes_timeout_seconds

    async def relay() -> AsyncGenerator[bytes, None]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
            try:
                async with client.stream("POST", target, headers=headers, json=payload) as resp:
                    if resp.status_code >= 400:
                        err = (await resp.aread()).decode(errors="replace")[:512]
                        yield _sse("error", {"message": f"hermes {resp.status_code}: {err}"})
                        return
                    buffer = ""
                    streamed_chars = 0
                    async for chunk in resp.aiter_text():
                        buffer += chunk
                        lines = buffer.split("\n")
                        buffer = lines.pop()
                        for line in lines:
                            if not line.startswith("data:"):
                                continue
                            raw = line[5:].strip()
                            if not raw:
                                continue
                            try:
                                evt = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            kind = evt.get("type")
                            if kind == "token":
                                text = evt.get("text", "")
                                streamed_chars += len(text)
                                yield _sse("text_delta", {"content": text})
                            elif kind == "done":
                                # Some provider paths don't fire the token
                                # callback — the full reply only arrives here.
                                # Flush whatever the deltas didn't cover.
                                reply = evt.get("reply") or ""
                                if len(reply) > streamed_chars:
                                    yield _sse("text_delta", {"content": reply[streamed_chars:]})
                                yield _sse("done", {"ok": True})
                                return
                            elif kind == "error":
                                yield _sse("error", {"message": evt.get("error", "unknown")})
                                return
                            elif kind in ("tool_call", "tool_start", "tool_result"):
                                yield _sse("tool_event", evt)
                    # Upstream closed without a done envelope — still signal done
                    # so the widget stops its spinner.
                    yield _sse("done", {"ok": True})
            except httpx.RequestError as exc:
                logger.warning(
                    "assistant: hermes unreachable: %s", exc,
                    extra={"action": "assistant.hermes_unreachable", "component": "assistant"},
                )
                yield _sse("error", {"message": "assistant backend unreachable"})

    return StreamingResponse(
        relay(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/history")
async def assistant_history(
    session_id: str = "default",
    limit: int = 30,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Transcript read-back — not yet persisted (see module docstring)."""
    return {"messages": [], "session_id": session_id}


@router.delete("/history")
async def assistant_clear_history(
    session_id: str = "default",
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Best-effort session reset. The shim keys agents by session_id, so a
    cleared widget simply starts sending under a fresh local session_id;
    nothing to delete server-side yet."""
    return {"ok": True}


@router.post("/tts")
async def assistant_tts(
    user: dict[str, Any] = Depends(get_current_user),
) -> None:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="tts_not_configured",
    )
