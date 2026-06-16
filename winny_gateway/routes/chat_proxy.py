"""Hermes-on-OVH proxy.

Forwards POST /api/v1/chat/message (and /stream) to the OVH-hosted
Hermes runtime. The user's Supabase JWT is preserved so Hermes can
look them up; we add HERMES_PROXY_SECRET as a shared-secret header
so only this gateway can reach the OVH endpoint (Caddy enforces it
on the OVH side).

If `HERMES_URL` is empty we fall back to the in-process orchestrator
in `gateway/routes/chat.py`. That lets us flip via env var without a
code change if the OVH side is down.
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
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class ChatMessageIn(BaseModel):
    message: str
    context: dict[str, Any] | None = None
    session_id: str | None = None  # optional client-supplied; we override with user_id


def _hermes_headers(request: Request, user: dict[str, Any]) -> dict[str, str]:
    cfg = request.app.state.config
    return {
        "content-type": "application/json",
        "accept": "application/json",
        # Caddy on OVH only forwards to Hermes if this matches.
        "x-hermes-proxy-auth": cfg.hermes_proxy_secret or "",
        # Preserve the user's identity. Hermes uses this as session_id
        # and as the actor for any tool calls that touch user state.
        "x-winnywoo-user-id": str(user.get("sub", "anon")),
        "x-winnywoo-user-email": str(user.get("email", "")),
    }


@router.post("/message")
async def chat_message(
    body: ChatMessageIn,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Forward a single-turn chat message to Hermes-on-OVH."""
    cfg = request.app.state.config
    if not cfg.hermes_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hermes proxy not configured (set HERMES_URL).",
        )

    target = cfg.hermes_url.rstrip("/") + "/chat/message"
    payload = {
        "message": body.message,
        "context": body.context or {},
        "session_id": body.session_id or f"user:{user.get('sub', 'anon')}",
    }

    async with httpx.AsyncClient(timeout=cfg.hermes_timeout_seconds) as client:
        try:
            resp = await client.post(
                target,
                headers=_hermes_headers(request, user),
                json=payload,
            )
        except httpx.RequestError as exc:
            logger.warning(
                "hermes proxy unreachable: %s", exc,
                extra={"action": "chat.hermes_unreachable", "component": "chat_proxy"},
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="hermes_unreachable",
            ) from exc

    if resp.status_code >= 400:
        # Surface upstream error verbatim — Hermes formats this carefully
        # ("OTC expired", "broker rejected", etc.) and we don't want to mangle it.
        try:
            body_json = resp.json()
        except Exception:
            body_json = {"error": resp.text[:512]}
        raise HTTPException(
            status_code=resp.status_code,
            detail=body_json,
        )

    try:
        data = resp.json()
    except Exception:
        data = {"reply": resp.text}

    # Mirror to this user's OWN open tabs only — a chat reply can carry their
    # positions/balances, so it must stay scoped to them, not all tenants.
    try:
        request.app.state.event_bus.publish({
            "type": "chat_response",
            "user_id": user.get("sub"),
            "data": data,
        }, user_id=user.get("sub") if isinstance(user, dict) else None)
    except Exception:
        pass

    return {"ok": True, "data": data}


@router.post("/stream")
async def chat_stream(
    body: ChatMessageIn,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> StreamingResponse:
    """Server-sent-events stream of Hermes tokens.

    Frontend opens an EventSource; each line is a JSON envelope:
      data: {"type": "token", "text": "Hello"}
      data: {"type": "tool_call", "name": "mcp_winny_algo_get_portfolio", ...}
      data: {"type": "done"}
    """
    cfg = request.app.state.config
    if not cfg.hermes_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hermes proxy not configured (set HERMES_URL).",
        )

    target = cfg.hermes_url.rstrip("/") + "/chat/stream"
    payload = {
        "message": body.message,
        "context": body.context or {},
        "session_id": body.session_id or f"user:{user.get('sub', 'anon')}",
    }
    headers = _hermes_headers(request, user)
    timeout = cfg.hermes_timeout_seconds

    async def relay() -> AsyncGenerator[bytes, None]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
            try:
                async with client.stream(
                    "POST", target, headers=headers, json=payload,
                ) as resp:
                    if resp.status_code >= 400:
                        err = await resp.aread()
                        yield f"event: error\ndata: {json.dumps({'status': resp.status_code, 'body': err.decode(errors='replace')[:512]})}\n\n".encode()
                        return
                    async for chunk in resp.aiter_bytes():
                        yield chunk
            except httpx.RequestError as exc:
                yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n".encode()

    return StreamingResponse(
        relay(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # tell nginx-like proxies not to buffer
        },
    )


@router.get("/health")
async def chat_health(request: Request) -> dict[str, Any]:
    """Probe the upstream Hermes /health — useful for the dashboard 'Brain' tile."""
    cfg = request.app.state.config
    if not cfg.hermes_url:
        return {"ok": True, "data": {"hermes": "not_configured"}}

    target = cfg.hermes_url.rstrip("/") + "/health"
    headers = {
        "x-hermes-proxy-auth": cfg.hermes_proxy_secret or "",
    }
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(target, headers=headers)
            return {
                "ok": True,
                "data": {
                    "hermes": "ok" if resp.status_code == 200 else f"status_{resp.status_code}",
                    "url": cfg.hermes_url,
                },
            }
        except httpx.RequestError as exc:
            return {"ok": True, "data": {"hermes": "unreachable", "error": str(exc)[:200]}}
