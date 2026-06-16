"""submit_order tool — §3.3 + §3.4 integration.

This is the ONLY path from intent to real order. It:
  1. Verifies + consumes the approval grant (single-use, replay-protected)
  2. Submits to the brokerage via the factory (routed by Symbol asset class)
  3. Returns the broker_order_id

If the grant is invalid, expired, or already consumed → rejects without
touching the broker. This guarantees that no LLM can bypass the approval gate.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from winny.approval.crypto import canonical_intent_hash
from winny.brokerage.factory import EngineMode, get_brokerage
from winny.common.symbols import Symbol
from winny.common.types import OrderIntent, OrderType, Side, TimeInForce
from winny.mcp.approval.tools import consume_grant


async def submit_order(
    approval_id: str,
    grant_token: str,
    order_intent: dict[str, Any],
    mode: str = "LIVE",
) -> dict[str, Any]:
    """Submit an approved order to the brokerage.

    This tool:
      1. Rebuilds the OrderIntent from wire format.
      2. Computes the intent hash and validates grant via mcp-approval.consume.
      3. Routes to the correct brokerage (paper for DRY_RUN, ccxt for LIVE crypto).
      4. Returns broker_order_id on success.
    """
    # Rebuild intent
    try:
        intent = _rebuild_intent(order_intent)
    except Exception as e:
        return {"error": f"Invalid order_intent: {e}"}

    # Compute intent hash
    intent_hash = canonical_intent_hash(intent)

    # Consume the approval grant (verify + replay protect)
    consume_result = await consume_grant(
        approval_id=approval_id,
        grant_token=grant_token,
        order_intent_hash=intent_hash,
        by_caller="mcp-algo.submit_order",
    )
    if "error" in consume_result:
        return {"error": f"Approval gate rejected: {consume_result['error']}"}

    # Route to brokerage
    engine_mode: EngineMode = "LIVE"
    if mode.upper() == "DRY_RUN":
        engine_mode = "DRY_RUN"
    elif mode.upper() == "BACKTEST":
        engine_mode = "BACKTEST"

    try:
        broker = get_brokerage(intent.symbol, mode=engine_mode)
        broker_order_id = broker.submit(intent)
    except Exception as e:
        return {"error": f"Brokerage submission failed: {e}"}

    return {
        "broker_order_id": str(broker_order_id),
        "approval_id": approval_id,
        "decision_id": str(intent.decision_id),
        "symbol": intent.symbol.canonical(),
        "side": intent.side.value,
        "qty": str(intent.qty),
        "status": "SUBMITTED",
    }


def _rebuild_intent(raw: dict[str, Any]) -> OrderIntent:
    """Rebuild an OrderIntent from a JSON-safe wire-format dict."""
    symbol_data = raw["symbol"]
    if isinstance(symbol_data, str):
        symbol = Symbol.parse(symbol_data)
    else:
        symbol = Symbol.parse(symbol_data.get("canonical", str(symbol_data)))

    return OrderIntent(
        intent_id=raw["intent_id"],
        decision_id=raw["decision_id"],
        symbol=symbol,
        side=Side(raw["side"]),
        qty=Decimal(str(raw["qty"])),
        order_type=OrderType(raw["order_type"]),
        limit_price=Decimal(str(raw["limit_price"])) if raw.get("limit_price") else None,
        stop_price=Decimal(str(raw["stop_price"])) if raw.get("stop_price") else None,
        time_in_force=TimeInForce(raw["time_in_force"]),
        estimated_cost=Decimal(str(raw["estimated_cost"])),
        estimated_fees=Decimal(str(raw["estimated_fees"])),
        sizing_explanation=raw.get("sizing_explanation", ""),
    )
