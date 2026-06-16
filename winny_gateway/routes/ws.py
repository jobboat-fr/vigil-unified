"""WebSocket endpoints — backed by gateway.events.EventBus.

The bus owns the connection set + the broadcaster loop. This route only:
  • registers a new connection on accept
  • forwards client → server messages (chat, ping)
  • deregisters on disconnect

All server → client envelopes are produced by REST routes (publish on action)
and background pollers (portfolio_poller, approvals_poller).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from winny_gateway.auth import ws_authenticate
from winny_gateway.logging import get_logger
from winny_gateway.routes.chat import _HANDLERS, _classify_intent, _handle_buy_sell, _handle_unknown
from winny_gateway.security import WS_MAX_MSG_BYTES, WebSocketRateLimiter
from winny.common.sanitise import check_prompt_injection, sanitise_text

logger = get_logger(__name__)
router = APIRouter(tags=["websocket"])


@router.websocket("/ws/feed")
async def agent_feed(websocket: WebSocket) -> None:
    """Bidirectional WS endpoint.

    Server → client envelopes (see gateway.events for the full list):
      agent_message, agent_response, approval_request, approval_granted,
      approval_revoked, order_submitted, order_cancelled, portfolio_update,
      signal_new, fill, pnl_tick, pong, error, chat_response

    Client → server messages:
      {"type": "chat", "message": "..."}
        -> routes through the same NL intent classifier as POST /api/v1/chat/message
        -> response sent back on this socket + broadcast to all connected clients
      {"type": "ping"}
        -> server replies {"type": "pong"} to this client only (no broadcast)
    """
    # ── Authenticate via query-param token ────────────────────────────────
    token = websocket.query_params.get("token")
    user = await ws_authenticate(token, websocket)
    if user is None:
        await websocket.close(code=4401, reason="Unauthorized")
        return

    bus = websocket.app.state.event_bus
    pool = websocket.app.state.mcp_pool
    ws_limiter = WebSocketRateLimiter()
    # Tag the connection with the authenticated user so the bus can target
    # events to them and never fan out one tenant's data to another.
    user_id = user.get("sub") if isinstance(user, dict) else None
    await bus.connect(websocket, user_id=user_id)

    try:
        while True:
            raw = await websocket.receive_text()

            # Message size guard
            if len(raw) > WS_MAX_MSG_BYTES:
                await websocket.send_text(json.dumps({"type": "error", "message": "Message too large"}))
                continue

            # Per-connection rate limit
            if not ws_limiter.check():
                await websocket.send_text(json.dumps({"type": "error", "message": "Rate limit exceeded"}))
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "message": "Invalid JSON"}))
                continue

            kind = msg.get("type")
            if kind == "ping":
                await websocket.send_text(
                    json.dumps({"type": "pong", "ts": datetime.now(UTC).isoformat()})
                )
            elif kind == "chat":
                # Route through the full NL intent classifier — same logic
                # as POST /api/v1/chat/message but over WebSocket.
                text = sanitise_text(msg.get("message") or "")
                if not text:
                    await websocket.send_text(json.dumps({
                        "type": "chat_response",
                        "intent": "HELP",
                        "reply": "Send me a message! Type *help* to see what I can do.",
                    }))
                    continue

                # Prompt injection detection
                threat = check_prompt_injection(text)
                if threat is not None:
                    logger.warning(
                        "WS prompt injection blocked: %s", threat.pattern_name,
                        extra={
                            "action": "security.ws_prompt_injection",
                            "pattern": threat.pattern_name,
                            "component": "websocket",
                        },
                    )
                    await websocket.send_text(json.dumps({
                        "type": "chat_response",
                        "intent": "BLOCKED",
                        "reply": "I can't process that message. Please rephrase your request.",
                    }))
                    continue

                try:
                    intent = _classify_intent(text)
                    ctx = msg.get("context")

                    if intent == "BUY":
                        resp = await _handle_buy_sell(pool, text, ctx, "BUY")
                    elif intent == "SELL":
                        resp = await _handle_buy_sell(pool, text, ctx, "SELL")
                    else:
                        handler = _HANDLERS.get(intent, _handle_unknown)
                        resp = await handler(pool, text, ctx)

                    envelope = {
                        "type": "chat_response",
                        "intent": resp.intent,
                        "reply": resp.reply,
                        "data": resp.data,
                        "actions": resp.actions,
                        "followup": resp.followup,
                        "ts": datetime.now(UTC).isoformat(),
                    }
                    # Send to this client immediately
                    await websocket.send_text(json.dumps(envelope, default=str))
                    # Mirror to this user's OTHER sockets (multi-tab/mobile) —
                    # NEVER to other tenants. A chat reply can carry the user's
                    # positions / balances, so it must stay scoped to them.
                    if user_id:
                        bus.publish(envelope, user_id=user_id)
                except Exception as exc:
                    logger.exception("Chat handler error: %s", exc)
                    # Never leak internal details to the client
                    await websocket.send_text(
                        json.dumps({"type": "error", "message": "An internal error occurred"})
                    )
            # Unknown types are silently ignored — keeps the surface small.
    except WebSocketDisconnect:
        pass
    finally:
        bus.disconnect(websocket)
