"""Events broadcast endpoint — service-token-gated.

mcp-winnywoo (running inside Hermes on OVH) POSTs here to publish events
onto the gateway's EventBus, which fans out to every connected WebSocket
client on the frontend. The chain is:

    Hermes brain (Kimi K2)
        → mcp-winnywoo.broadcast_event(type, data)
        → POST /api/v1/events/broadcast    (this route)
        → app.state.event_bus.publish({...})
        → /ws/feed clients see the envelope

Why a dedicated endpoint instead of letting Hermes hit the WS directly:
  * The WS fan-out is per-user via Supabase JWT; Hermes doesn't hold one.
  * Centralising publishes here means audit + rate-limit hooks land
    cleanly later.
  * Frontend already has `lib/stream.js` handling the envelope shape —
    no new client wiring needed.

Envelope types Hermes typically pushes (see gateway/events.py):
    agent_message       — Hermes spoke during a session
    agent_response      — multi-line analysis or tool output summary
    portfolio_update    — Hermes refreshed portfolio state
    approval_request    — Hermes proposed a trade pending approval
    error               — Hermes wants to surface a problem
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from winny_gateway.auth import effective_user, get_current_user
from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/events", tags=["events"])


class EventBroadcastBody(BaseModel):
    """Inbound event envelope.

    `type` is one of the strings the frontend's stream.js recognises
    (agent_message, agent_response, portfolio_update, approval_request,
    error, etc.). `data` is the type-specific payload.

    `session_id` is optional but recommended — when the frontend later
    grows per-session WS channels we'll filter on it.
    """

    type: str = Field(..., min_length=1, max_length=64)
    data: dict[str, Any] | str | None = None
    session_id: str | None = Field(default=None, max_length=128)
    agent: str | None = Field(default=None, max_length=64)


@router.post("/broadcast", status_code=status.HTTP_202_ACCEPTED)
async def broadcast_event(
    body: EventBroadcastBody,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Publish one event onto the EventBus.

    Service-token callers (Hermes / mcp-winnywoo) are the intended user.
    The route deliberately accepts any authenticated user so a future
    feature can let the frontend push notifications too — RLS-style
    filtering is the bus's responsibility, not the route's.
    """
    if not getattr(user, "get", lambda *_: None)("service_token"):
        # Non-service callers can push, but log it — we don't expect them.
        logger.warning(
            "non-service-token broadcast",
            extra={
                "action": "events.broadcast_external",
                "user_email": user.get("email") if isinstance(user, dict) else None,
                "type": body.type,
                "component": "events",
            },
        )

    bus = getattr(request.app.state, "event_bus", None)
    if bus is None:
        # Should never happen in production, but fail loud if it does.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="event bus not initialised",
        )

    envelope: dict[str, Any] = {"type": body.type}
    if body.agent:
        envelope["agent"] = body.agent
    if body.session_id:
        envelope["session_id"] = body.session_id
    if body.data is not None:
        # Top-level payload keys (matches frontend stream.js handler)
        if isinstance(body.data, dict):
            # Pull `text` / `message` up to the envelope for legacy events
            for k in ("text", "message"):
                if k in body.data:
                    envelope[k] = body.data[k]
            envelope["data"] = body.data
        else:
            envelope["text"] = str(body.data)

    # Multi-tenant target: when a service-token caller (Hermes/mcp-winnywoo)
    # forwards X-WinnyWoo-User-Id, the event is for THAT user — target only
    # their sockets. A direct user JWT targets themselves. Only an unscoped
    # operator/system broadcast (no forwarded id) fans out to everyone.
    eff = effective_user(request, user)
    target_user_id = eff.get("sub") if eff.get("scoped") else None
    if target_user_id is None and isinstance(user, dict) and not user.get("service_token"):
        target_user_id = user.get("sub")

    bus.publish(envelope, user_id=target_user_id)
    logger.info(
        "event broadcast",
        extra={
            "action": "events.broadcast",
            "type": body.type,
            "session_id": body.session_id,
            "agent": body.agent,
            "targeted": bool(target_user_id),
            "component": "events",
        },
    )
    return {"ok": True, "queued": True, "subscribers": bus.connection_count}
