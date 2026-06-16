"""Tool implementations for mcp-winnywoo.

Each function is registered with the MCP dispatcher in server.py. They
all return JSON-serialisable dicts so the MCP transport (stdio JSON-RPC)
can ship them straight through to Hermes.

The Hermes brain sees tools by name + JSON-schema. Function names here
become tool names in the agent's tool catalog, so keep them stable —
SOUL.md / persona docs reference them.
"""

from __future__ import annotations

import logging
from typing import Any

from winny.mcp.winnywoo.client import BackendClient, BackendError

logger = logging.getLogger(__name__)


def _envelope(client: BackendClient, raw: Any) -> dict[str, Any]:
    """Unwrap the gateway's `{ok, data}` envelope; return data or pass through."""
    if isinstance(raw, dict) and "ok" in raw and "data" in raw:
        return raw["data"] if raw["ok"] else {"error": raw.get("error", "unknown"), "ok": False}
    return raw if isinstance(raw, dict) else {"value": raw}


def _err(e: BackendError) -> dict[str, Any]:
    return {"ok": False, "status": e.status, "error": e.body, "path": e.path}


# ── READ tools ────────────────────────────────────────────────────────


def _scope(user_id: str | None) -> dict[str, str] | None:
    """Build the per-request scope from the user_id the agent passes in.

    The chatting user's id comes from the [context] block. Forwarding it
    means the gateway resolves THAT user's broker — not the operator the
    service token defaults to (multi-tenant). Omitted → operator (the owner's
    own chat / signal runner).
    """
    uid = (user_id or "").strip()
    return {"user_id": uid} if uid else None


def get_portfolio(client: BackendClient, user_id: str | None = None) -> dict[str, Any]:
    """Single-shot snapshot of NAV + balances + positions + open orders.

    Pass ``user_id`` from the conversation [context] so the snapshot is the
    CHATTING user's connected broker — not the operator's. Without it, no
    account is shown unless the caller is the operator.
    """
    try:
        return _envelope(client, client.get("/api/v1/broker/snapshot", scope=_scope(user_id)))
    except BackendError as e:
        return _err(e)


def get_positions(client: BackendClient, user_id: str | None = None) -> dict[str, Any]:
    """Just the positions slice — no balances, no orders. Pass user_id from context."""
    try:
        snap = _envelope(client, client.get("/api/v1/broker/snapshot", scope=_scope(user_id)))
        return {"positions": snap.get("positions", []), "broker": snap.get("broker")}
    except BackendError as e:
        return _err(e)


def get_open_orders(client: BackendClient, user_id: str | None = None) -> dict[str, Any]:
    """Pending orders awaiting fill / cancellation. Pass user_id from context."""
    try:
        snap = _envelope(client, client.get("/api/v1/broker/snapshot", scope=_scope(user_id)))
        return {"open_orders": snap.get("open_orders", []), "broker": snap.get("broker")}
    except BackendError as e:
        return _err(e)


def get_market_quote(client: BackendClient, symbol: str) -> dict[str, Any]:
    """Last price + bid/ask for a symbol like 'BTC/USDT' or 'ETH/EUR'.

    Args:
        symbol: CCXT-style market symbol. Case-insensitive; uppercased
                before sending.
    """
    try:
        return _envelope(client, client.get(f"/api/v1/broker/ticker/{symbol.upper()}"))
    except BackendError as e:
        return _err(e)


# ── ORDER / APPROVAL flow ─────────────────────────────────────────────


def propose_order(
    client: BackendClient,
    symbol: str,
    side: str,
    qty: float | None = None,
    order_type: str = "market",
    price: float | None = None,
    note: str | None = None,
    sizing_policy: str = "fixed_fractional",
    conviction: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Create an ApprovalRequest for a new order. DOES NOT submit.

    Spec-mandated approval gate: every order goes through
        size → approval.request → user types OTC → verify → submit

    SIZING IS THE GATEWAY'S JOB. Leave ``qty`` unset and the gateway sizes the
    order against the CHATTING user's own live broker NAV with the §1.3 5%-NAV
    hard cap (pass ``user_id`` from the [context] block so it's THEIR book, not
    the operator's). Use ``sizing_policy='conviction'`` + ``conviction`` (1-10)
    to scale within the cap. Only pass an explicit ``qty`` for a deliberate
    manual override — it skips the sizing engine.

    Returns {approval_id, one_time_code, ...} (+ sizing provenance when the
    gateway sized it). Surface the OTC to the user; they reply with it to
    verify_approval.
    """
    side_norm = side.lower().strip()
    if side_norm not in {"buy", "sell"}:
        return {"ok": False, "error": f"invalid side {side!r}; expected buy|sell"}

    scope = _scope(user_id)
    sym = symbol.upper().replace("-", "/")
    sizing_info: dict[str, Any] | None = None

    if qty is None:
        # Server-side sizing against the chatting user's live NAV (capped).
        size_body: dict[str, Any] = {
            "symbol": sym,
            "side": side_norm,
            "sizing_policy": sizing_policy,
        }
        if conviction is not None:
            size_body["conviction"] = int(conviction)
        if note:
            size_body["summary"] = note
        try:
            sized = _envelope(
                client,
                client.post("/api/v1/broker/prepare-order", json_body=size_body, scope=scope),
            )
        except BackendError as e:
            return _err(e)
        if isinstance(sized, dict) and sized.get("ok") is False:
            return sized
        order_intent = dict(sized.get("intent") or {})
        sizing_info = sized.get("sizing")
        if not order_intent.get("qty"):
            return {"ok": False, "error": "gateway sizing returned no qty", "detail": sized}
    else:
        order_intent = {
            "decision_id": f"hermes:{sym}:{side_norm}",
            "symbol": sym,
            "side": side_norm,
            "qty": str(qty),
            "type": order_type.lower(),
        }
        if price is not None:
            order_intent["price"] = str(price)

    payload: dict[str, Any] = {
        "decision_id": order_intent.get("decision_id") or f"hermes:{sym}:{side_norm}",
        "order_intent": order_intent,
        "ttl_seconds": 300,
        "summary": note or order_intent.get("summary") or f"proposed {side_norm} {order_intent.get('qty')} {sym}",
    }
    try:
        result = _envelope(
            client,
            client.post("/api/v1/approvals/request", json_body=payload, scope=scope),
        )
    except BackendError as e:
        return _err(e)
    if isinstance(result, dict) and sizing_info is not None:
        result["sizing"] = sizing_info
    return result


def verify_approval(
    client: BackendClient,
    approval_id: str,
    otc: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Complete a pending approval with the user's one-time code, then submit.

    Two-step §3.4 redemption: verify the OTC to obtain the single-use grant,
    then submit the frozen OrderIntent to the CHATTING user's own broker via
    the scoped direct-CCXT path. Pass ``user_id`` from [context] — the gateway
    enforces that the approval is owned by that user and routes the fill to
    their broker, never the operator's. On any failure the approval is spent;
    request a fresh one.
    """
    scope = _scope(user_id)
    try:
        verified = _envelope(
            client,
            client.post(
                f"/api/v1/approvals/{approval_id}/verify",
                json_body={"user_token": otc},
                scope=scope,
            ),
        )
    except BackendError as e:
        return _err(e)
    if isinstance(verified, dict) and verified.get("ok") is False:
        return verified

    try:
        submitted = _envelope(
            client,
            client.post(
                "/api/v1/orders/submit-direct",
                json_body={"approval_id": approval_id},
                scope=scope,
            ),
        )
    except BackendError as e:
        return {"ok": False, "stage": "submit", "verified": verified, "error": e.body, "status": e.status}
    return {"ok": True, "verified": verified, "submitted": submitted}


def list_pending_approvals(
    client: BackendClient, user_id: str | None = None
) -> dict[str, Any]:
    """Show approvals waiting on the user's OTC. Pass user_id from [context] —
    a scoped caller only sees their own pending approvals."""
    try:
        raw = client.get("/api/v1/approvals/pending", scope=_scope(user_id))
        if isinstance(raw, list):
            return {"pending": raw, "count": len(raw)}
        return _envelope(client, raw)
    except BackendError as e:
        return _err(e)


def reject_approval(
    client: BackendClient,
    approval_id: str,
    reason: str = "rejected by user via Hermes",
    user_id: str | None = None,
) -> dict[str, Any]:
    """Discard a pending approval before it expires. Pass user_id from
    [context]; the gateway only lets the owning user reject it."""
    try:
        return _envelope(
            client,
            client.post(
                f"/api/v1/approvals/{approval_id}/reject",
                json_body={"reason": reason},
                scope=_scope(user_id),
            ),
        )
    except BackendError as e:
        return _err(e)


# ── CANCEL / KILL ─────────────────────────────────────────────────────


def cancel_order(client: BackendClient, broker_order_id: str) -> dict[str, Any]:
    """Cancel one open order on the connected broker."""
    try:
        return _envelope(
            client,
            client.post(
                "/api/v1/orders/cancel",
                json_body={"broker_order_id": broker_order_id},
            ),
        )
    except BackendError as e:
        return _err(e)


def cancel_all_orders(
    client: BackendClient, user_id: str | None = None
) -> dict[str, Any]:
    """PANIC — cancel every open order on the CHATTING user's broker.

    This is what `winny:kill` invokes. Pass ``user_id`` from [context] so the
    flatten hits THAT user's exchange, not the operator's. No spec violation —
    the gate is for adding risk; this only removes it, with no funds movement.
    """
    try:
        return _envelope(
            client,
            client.post("/api/v1/broker/cancel-all", scope=_scope(user_id)),
        )
    except BackendError as e:
        return _err(e)


# ── PUSH to frontend ──────────────────────────────────────────────────


def broadcast_event(
    client: BackendClient,
    type: str,
    text: str | None = None,
    data: dict[str, Any] | None = None,
    session_id: str | None = None,
    agent: str | None = "winnywoo",
    user_id: str | None = None,
) -> dict[str, Any]:
    """Publish an event onto the gateway EventBus → the user's WS clients.

    Pass ``user_id`` from the [context] block so the notification reaches only
    the CHATTING user's open tabs — not every connected tenant. Good for:
    'I just refreshed your portfolio', 'I'm done analysing', or surfacing an
    approval notification in the UI. Omit user_id only for a genuine
    system-wide notice.
    """
    payload: dict[str, Any] = {"type": type}
    if agent:
        payload["agent"] = agent
    if session_id:
        payload["session_id"] = session_id
    if data is not None:
        payload["data"] = data
    if text is not None:
        payload.setdefault("data", {})
        if isinstance(payload["data"], dict):
            payload["data"].setdefault("text", text)
    try:
        return _envelope(
            client,
            client.post("/api/v1/events/broadcast", json_body=payload, scope=_scope(user_id)),
        )
    except BackendError as e:
        return _err(e)


# ── VAULT tools — user document grounding ─────────────────────────────


def vault_list(client: BackendClient, user_id: str) -> dict[str, Any]:
    """List the user's classified vault documents (no full text).

    Returns id/filename/category/title/summary/risk_flags per document.
    Surface any risk_flags relevant to the conversation proactively.
    """
    try:
        return _envelope(
            client, client.get("/v1/vault/documents", params={"user_id": user_id})
        )
    except BackendError as e:
        return _err(e)


def vault_search(client: BackendClient, user_id: str, query: str) -> dict[str, Any]:
    """Full-text search across the user's documents (title/summary/body)."""
    try:
        return _envelope(
            client,
            client.get("/v1/vault/search", params={"user_id": user_id, "q": query}),
        )
    except BackendError as e:
        return _err(e)


def vault_get(client: BackendClient, user_id: str, doc_id: str) -> dict[str, Any]:
    """Fetch one document INCLUDING its extracted full text.

    This is the grounding primitive: quote and reason from this text,
    never from memory of what a contract 'usually' says.
    """
    try:
        return _envelope(
            client,
            client.get(
                f"/v1/vault/documents/{doc_id}",
                params={"user_id": user_id, "include_text": "true"},
            ),
        )
    except BackendError as e:
        return _err(e)


def get_live_signals(
    client: BackendClient,
    symbol: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Latest trading signals from the gateway's signal runner.

    Reads /api/v1/signals/live — the Supabase-backed rolling ring the
    gateway populates every ~5 minutes (forecaster + analyst rows per
    watchlist symbol). This is the gateway-channel path: it works from any
    host holding the service token, with no direct database credentials.
    """
    params: dict[str, Any] = {"limit": max(1, min(int(limit), 100))}
    if symbol:
        params["symbol"] = symbol.upper().replace("-", "/")
    try:
        return _envelope(client, client.get("/api/v1/signals/live", params=params))
    except BackendError as e:
        return _err(e)
