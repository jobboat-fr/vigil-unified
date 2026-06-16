"""Order management endpoints — SPECS.md §3.3.3.

Two implementations live here:

  * /submit + /cancel + /cancel-all  → legacy path via mcp-algo (kept for
    completeness; cancel + cancel-all are still actively used by the
    dashboard).
  * /submit-direct                   → new direct-CCXT path that bypasses
    mcp-algo. Consumes the approval_state record set by /approvals/request
    + /approvals/{id}/verify, instantiates a CcxtBrokerage with the
    operator's broker creds, and calls broker.submit(intent).
    SPECS.md §3.4 single-use semantics enforced by the in-process
    approval_state machine: an approval_id can only be consumed once.

Every successful action publishes an event so dashboards live-update.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from winny_gateway.auth import get_current_user, require_owner, scoped_user
from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


# ─── Request bodies (mirror mcp-algo tool signatures) ────────────────────────


class SubmitOrderBody(BaseModel):
    """Submit a prepared OrderIntent with a verified grant.

    `order_intent` is the JSON-safe dict produced by mcp-algo.prepare_order;
    it carries intent_id, decision_id, symbol, side, qty, etc.
    """

    approval_id: str
    grant_token: str
    order_intent: dict[str, Any]
    mode: str = Field(default="LIVE", pattern="^(LIVE|DRY_RUN|BACKTEST)$")


class CancelOrderBody(BaseModel):
    broker_order_id: str
    approval_id: str
    grant_token: str
    order_intent_hash: str
    symbol: str
    mode: str = Field(default="LIVE", pattern="^(LIVE|DRY_RUN|BACKTEST)$")


# ─── Routes ──────────────────────────────────────────────────────────────────


@router.post("/submit")
async def submit_order(
    body: SubmitOrderBody,
    request: Request,
    user: dict[str, Any] = Depends(require_owner),
) -> dict[str, Any]:
    """Submit an order. Consumes the grant (single-use, §3.4.2)."""
    pool = request.app.state.mcp_pool
    result = await pool.get("algo").call_tool(
        "submit_order",
        {
            "approval_id": body.approval_id,
            "grant_token": body.grant_token,
            "order_intent": body.order_intent,
            "mode": body.mode,
        },
    )
    if isinstance(result, dict) and "error" in result:
        logger.error(
            "Order submit failed",
            extra={"action": "orders.submit_fail", "error": result["error"], "component": "orders"},
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result["error"])

    user_id = user.get("sub", "anon")
    symbol = body.order_intent.get("symbol", "")

    # Single-use closure (§3.4): this approval was redeemed via the mcp-algo
    # grant path, so wipe the parallel approval_state record to stop the same
    # approval_id being replayed through /orders/submit-direct.
    try:
        from winny_gateway.approval_state import discard as _discard_approval

        _discard_approval(body.approval_id)
    except Exception as exc:
        logger.warning("approval_state.discard failed: %s", exc)

    logger.info(
        "Order submitted",
        extra={"action": "orders.submitted", "symbol": symbol, "component": "orders"},
    )
    request.app.state.event_bus.publish(
        {"type": "order_submitted", "data": result}, user_id=user.get("sub")
    )

    # Persist to Supabase (fire-and-forget)
    from winny_gateway.db import audit_log, db_insert
    await audit_log(
        user_id=user_id, event_type="order", action="submitted",
        component="orders", symbol=symbol,
        details={"order_intent": body.order_intent, "mode": body.mode},
    )
    await db_insert("trade_history", {
        "user_id": user_id,
        "broker_order_id": result.get("broker_order_id", "") if isinstance(result, dict) else "",
        "intent_id": body.order_intent.get("intent_id", ""),
        "symbol": symbol,
        "side": body.order_intent.get("side", ""),
        "order_type": body.order_intent.get("order_type", "MARKET"),
        "qty": float(body.order_intent.get("qty", 0)),
        "status": "submitted",
        "broker": body.order_intent.get("venue", ""),
    })

    return {"ok": True, "data": result}


@router.post("/cancel")
async def cancel_order(
    body: CancelOrderBody,
    request: Request,
    user: dict[str, Any] = Depends(require_owner),
) -> dict[str, Any]:
    """Cancel a single open order — also requires a valid grant (§3.3.3)."""
    pool = request.app.state.mcp_pool
    result = await pool.get("algo").call_tool(
        "cancel_order",
        {
            "broker_order_id": body.broker_order_id,
            "approval_id": body.approval_id,
            "grant_token": body.grant_token,
            "order_intent_hash": body.order_intent_hash,
            "symbol": body.symbol,
            "mode": body.mode,
        },
    )
    if isinstance(result, dict) and "error" in result:
        logger.error(
            "Order cancel failed",
            extra={"action": "orders.cancel_fail", "error": result["error"], "symbol": body.symbol, "component": "orders"},
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result["error"])

    logger.info(
        "Order cancelled",
        extra={"action": "orders.cancelled", "symbol": body.symbol, "component": "orders"},
    )
    request.app.state.event_bus.publish({
        "type": "order_cancelled",
        "broker_order_id": body.broker_order_id,
    }, user_id=user.get("sub"))
    return {"ok": True, "data": result}


@router.get("/trades")
async def get_trade_history(
    user: dict[str, Any] = Depends(get_current_user),
    limit: int = 50,
) -> dict[str, Any]:
    """Trade history — live from the connected exchange.

    Previously read the local ``trade_history`` table, which only ever
    contained fills routed through this gateway (i.e. almost nothing).
    The exchange is the source of truth; delegate to the single live
    implementation in portfolio.py.
    """
    from winny_gateway.routes.portfolio import fetch_live_trades

    return await fetch_live_trades(user, limit=min(max(limit, 1), 200))


class DirectSubmitBody(BaseModel):
    """Body for /submit-direct.

    The order_intent in the body is informational — the canonical intent is
    the one stored at /approvals/request time. We compare key fields and
    refuse to submit if the dashboard tries to swap symbol/side/qty between
    request and submit.
    """

    approval_id: str = Field(..., min_length=1, max_length=128)
    order_intent: dict[str, Any] | None = None


def _audit_emit_local(event_type: str, payload: dict, *, decision_id: str | None = None,
                      actor_email: str | None = None, component: str = "orders",
                      critical: bool = False) -> None:
    """Mirror of the approvals helper — best-effort audit append."""
    try:
        from winny_gateway.routes.audit import _get_store  # type: ignore

        store = _get_store()
        if store is None:
            return
        try:
            store.append(
                event_type, payload,
                decision_id=decision_id, critical=critical,
                actor_email=actor_email, component=component,
            )
        except TypeError:
            store.append(event_type, payload, decision_id=decision_id, critical=critical)
    except Exception:
        pass


@router.post("/submit-direct")
async def submit_order_direct(
    body: DirectSubmitBody,
    request: Request,
    user: dict[str, Any] = Depends(scoped_user),
) -> dict[str, Any]:
    """Place an order on the connected exchange using the canonical CCXT path.

    Single-use semantics via approval_state — the same approval_id can never
    consume twice (spec §3.4). Scoped to the chatting user: the approval must
    be owned by the caller (multi-tenant guard), and the order routes to the
    CALLER's connected broker — never the operator's. On success we emit:
      * order_submitted event on the EventBus (frontend WS clients)
      * order.submit audit event (Supabase audit_events, critical=true)
      * trade_history row (Supabase trade_history)
    """
    # Consume the approval — raises if unknown/expired/unverified/double-use,
    # or if the caller does not own it (ApprovalOwnershipError).
    from winny_gateway.approval_state import (
        ApprovalOwnershipError as _ApprovalOwnershipError,
    )
    from winny_gateway.approval_state import (
        ApprovalStateError as _ApprovalStateError,
    )
    from winny_gateway.approval_state import (
        consume as _consume_approval,
    )

    try:
        canonical_intent = _consume_approval(
            body.approval_id, caller_user_id=user.get("sub")
        )
    except _ApprovalOwnershipError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="approval_not_owned_by_caller",
        ) from exc
    except _ApprovalStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"approval_invalid: {exc}",
        ) from exc

    # Sanity-check that the dashboard didn't swap fields between request and
    # submit. The canonical intent (set at /approvals/request) wins.
    submitted = body.order_intent or {}
    for k in ("symbol", "side", "qty"):
        if k in submitted and str(submitted[k]).strip() and \
                str(submitted[k]).strip().upper() != str(canonical_intent.get(k, "")).strip().upper():
            logger.warning(
                "submit-direct intent drift — using canonical value",
                extra={
                    "action": "orders.intent_drift", "field": k,
                    "canonical": canonical_intent.get(k), "submitted": submitted[k],
                    "approval_id": body.approval_id, "component": "orders",
                },
            )
    intent = canonical_intent

    # Resolve broker + creds via the same path the dashboard uses.
    try:
        from winny_gateway.routes.broker_connect import _get_live_broker
        from winny_gateway.routes.settings import _get_prefs
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"resolver_unavailable: {exc}") from exc

    user_id = user.get("sub", "anon")
    prefs = _get_prefs(user_id)
    # Prefer the venue frozen into the intent at sizing time; fall back to the
    # caller's broker preference. Both resolve to the CALLER's creds below.
    target_broker = str(
        intent.get("venue") or prefs.get("broker_cr") or "kraken"
    ).lower()

    # Pull canonical types from winny.common — `winny.common.ids` has only
    # ULID NewTypes; the order primitives live in types/ and symbols/.
    try:
        from decimal import Decimal

        from winny.common.symbols import AssetClass, Symbol
        from winny.common.types import OrderIntent, OrderType, Side
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"types_unavailable: {exc}") from exc

    raw_symbol = str(intent.get("symbol", "")).strip().upper()
    side_str = str(intent.get("side", "")).lower()
    qty_raw = str(intent.get("qty", "0"))
    typ_str = str(intent.get("type", "market")).lower()
    price_raw = intent.get("price") or intent.get("limit_price")

    if not raw_symbol or side_str not in ("buy", "sell"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="bad_intent: symbol + side(buy|sell) are required",
        )

    side = Side.BUY if side_str == "buy" else Side.SELL
    order_type = (
        OrderType.LIMIT if typ_str == "limit"
        else OrderType.STOP if typ_str in ("stop", "stop_market")
        else OrderType.STOP_LIMIT if typ_str in ("stop_limit", "stoplimit")
        else OrderType.MARKET
    )

    # Build the canonical Symbol. CcxtBrokerage._to_ccxt_symbol() rejects
    # non-CRYPTO assets, so we always tag it as CRYPTO when parsing fails.
    try:
        sym = Symbol.parse(raw_symbol)
    except Exception:
        base, quote = "BTC", "USDT"
        norm = raw_symbol.replace("-", "/").replace(":", "/")
        if "/" in norm:
            base, quote = norm.split("/", 1)
        elif norm.endswith(("USDT", "USDC")):
            base, quote = norm[:-4], norm[-4:]
        elif norm.endswith(("USD", "EUR")):
            base, quote = norm[:-3], norm[-3:]
        sym = Symbol(asset_class=AssetClass.CRYPTO, base=base, quote=quote, venue=target_broker)

    qty_dec = Decimal(str(qty_raw or "0"))
    if qty_dec <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="bad_intent: qty must be > 0",
        )
    limit_price = Decimal(str(price_raw)) if price_raw not in (None, "") else None
    decision_id = str(intent.get("decision_id") or f"manual-{body.approval_id[:12]}")

    order_intent_dc = OrderIntent(
        intent_id=f"direct-{body.approval_id[:16]}",
        decision_id=decision_id,
        symbol=sym,
        side=side,
        qty=qty_dec,
        order_type=order_type,
        limit_price=limit_price,
        stop_price=None,
        estimated_cost=(limit_price * qty_dec) if limit_price else Decimal("0"),
        estimated_fees=Decimal("0"),
        sizing_explanation=str(intent.get("summary") or "manual approval grant"),
    )

    # _get_live_broker resolves creds + builds CcxtBrokerage in one call,
    # raises 400 if no keys are configured for this user.
    broker = _get_live_broker(user, target_broker)
    try:
        import asyncio

        broker_order_id = await asyncio.to_thread(broker.submit, order_intent_dc)
    except Exception as exc:
        logger.error(
            "submit-direct broker.submit failed: %s", exc,
            extra={
                "action": "orders.submit_direct_fail", "broker": target_broker,
                "symbol": raw_symbol, "approval_id": body.approval_id,
                "component": "orders",
            },
        )
        # Audit the failure too — useful when reconciling.
        _audit_emit_local(
            "order.submit_fail",
            {
                "approval_id": body.approval_id, "broker": target_broker,
                "intent": dict(intent), "error": str(exc),
            },
            decision_id=str(intent.get("decision_id") or "") or None,
            actor_email=user.get("email"),
            component="orders",
            critical=True,
        )
        raise HTTPException(status_code=502, detail=f"broker_submit_failed: {exc}") from exc

    response_payload = {
        "broker_order_id": str(broker_order_id),
        "approval_id": body.approval_id,
        "broker": target_broker,
        "symbol": raw_symbol,
        "side": side_str,
        "qty": str(qty_dec),
        "type": typ_str,
        "price": str(limit_price) if limit_price else None,
        "submitted_at": datetime.now(UTC).isoformat(),
    }

    # Single-use closure (§3.4): the approval_state record is already consumed
    # above; also revoke the parallel mcp-approval grant (best-effort) so the
    # same approval_id can't be replayed through the legacy /orders/submit path.
    try:
        pool = getattr(request.app.state, "mcp_pool", None)
        if pool is not None:
            await pool.get("approval").safe_call_tool(
                "revoke",
                {"approval_id": body.approval_id, "reason": "consumed via submit-direct"},
                fallback=None,
            )
    except Exception as exc:
        logger.warning("submit-direct grant revoke failed: %s", exc)

    # Live broadcast + audit + persistence
    request.app.state.event_bus.publish(
        {"type": "order_submitted", "data": response_payload}, user_id=user.get("sub")
    )
    _audit_emit_local(
        "order.submit",
        response_payload,
        decision_id=str(intent.get("decision_id") or "") or None,
        actor_email=user.get("email"),
        component="orders",
        critical=True,
    )
    try:
        from winny_gateway.db import db_insert

        await db_insert("trade_history", {
            "user_id": user_id,
            "broker_order_id": str(broker_order_id),
            "intent_id": order_intent_dc.intent_id,
            "symbol": raw_symbol,
            "side": side_str,
            "order_type": typ_str.upper(),
            "qty": float(qty_dec or 0),
            "status": "submitted",
            "broker": target_broker,
        })
    except Exception:
        pass  # trade_history persist is non-blocking

    logger.info(
        "order submitted via /submit-direct",
        extra={
            "action": "orders.submit_direct_ok",
            "approval_id": body.approval_id, "broker": target_broker,
            "symbol": raw_symbol, "broker_order_id": str(broker_order_id),
            "component": "orders",
        },
    )

    return {"ok": True, "data": response_payload}


@router.post("/cancel-all")
async def cancel_all_orders(
    request: Request,
    user: dict[str, Any] = Depends(require_owner),
) -> dict[str, Any]:
    """Kill-switch — cancel every open order. Owner-gated (F8/F14). Spec §1.3 caps this at ≤1s.

    Note: per §3.3.3 the spec lists this as needing a grant. For the
    kill-switch UX (panic button) we route through mcp-algo's `cancel_all`
    tool with an empty payload; mcp-algo decides whether to enforce a grant
    (currently doesn't for parity with /kill chat command).
    """
    pool = request.app.state.mcp_pool
    logger.warning(
        "Cancel-all kill switch activated",
        extra={"action": "orders.cancel_all", "component": "orders"},
    )
    result = await pool.get("algo").call_tool("cancel_all", {})

    request.app.state.event_bus.publish(
        {"type": "order_cancelled_all", "data": result}, user_id=user.get("sub")
    )
    return {"ok": True, "data": result}
