"""prepare_order tool — build an OrderIntent without submitting.

This is the bridge from "strategy said ENTER_LONG" to "OrderIntent ready for
human approval". The §1.3 5%-NAV cap is enforced here via IntentBuilder.

INVARIANTS:
  - Uses IntentBuilder as the sole OrderIntent constructor
  - Does NOT submit to any broker
  - Does NOT mutate PortfolioStore
  - Returns sizing provenance for audit/debugging
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from winny.common.ids import Currency, DecisionId
from winny.common.symbols import Symbol
from winny.common.types import OrderIntent, Side
from winny.engine.fees import DefaultFeeModel, FeeModel
from winny.engine.intent import IntentBuilder
from winny.engine.sizing import (
    ConvictionScaledSizing,
    FixedFractionalSizing,
    SizingPolicy,
    apply_nav_cap,
)
from winny.mcp.algo.serialization import to_jsonable
from winny.portfolio.snapshot import build_snapshot
from winny.portfolio.store import PortfolioStore

# ---------- signal type → side mapping ----------

_SIGNAL_SIDE_MAP: dict[str, Side] = {
    "ENTER_LONG": Side.BUY,
    "ENTER_SHORT": Side.SELL,
    "EXIT_LONG": Side.SELL,
    "EXIT_SHORT": Side.BUY,
}


# ---------- sizing policy factory ----------


def _build_sizing_policy(
    name: str, params: dict[str, Any] | None
) -> SizingPolicy:
    """Construct a SizingPolicy from a name + optional params dict."""
    params = params or {}
    if name == "fixed_fractional":
        frac = Decimal(params.get("nav_fraction", "0.05"))
        return FixedFractionalSizing(nav_fraction=frac)
    if name == "conviction":
        base = Decimal(params.get("base_fraction", "0.025"))
        conv = int(params.get("conviction", 5))
        return ConvictionScaledSizing(base_fraction=base, conviction=conv)
    raise ValueError(f"Unknown sizing_policy: {name!r}. Use 'fixed_fractional' or 'conviction'.")


# ---------- uncapped stake calculator ----------


def _compute_uncapped_stake(
    sizing_policy: str,
    sizing_params: dict[str, Any] | None,
    nav: Decimal,
) -> Decimal:
    """Compute what the stake WOULD be without the 5% NAV cap.

    This is used purely for the 'cap_was_applied' flag in the sizing
    provenance. It duplicates the policy math intentionally so we can
    compare pre-cap vs post-cap without modifying the policy classes.
    """
    params = sizing_params or {}
    if sizing_policy == "conviction":
        base = Decimal(params.get("base_fraction", "0.025"))
        conv = int(params.get("conviction", 5))
        multiplier = Decimal(conv) / Decimal("5")
        return nav * base * multiplier
    # fixed_fractional or default
    frac = Decimal(params.get("nav_fraction", "0.05"))
    return nav * frac


# ---------- tool handler ----------


async def prepare_order(
    signal: dict[str, Any],
    ref_price: str,
    current_prices: dict[str, str] | None = None,
    sizing_policy: str = "fixed_fractional",
    sizing_params: dict[str, Any] | None = None,
    fee_model: str = "default",
    decision_id: str | None = None,
    portfolio_db_path: str | None = None,
) -> dict[str, Any]:
    """Build an OrderIntent for the given Signal.

    Does NOT submit. Does NOT mutate portfolio state. Returns the JSON-
    serialized OrderIntent along with sizing provenance.

    Parameters
    ----------
    signal : dict with at least 'type' and 'symbol' keys
    ref_price : Decimal-safe string — the price to size against
    current_prices : optional dict mapping canonical symbol -> price string (for NAV)
    sizing_policy : "fixed_fractional" or "conviction"
    sizing_params : optional params for the sizing policy
    fee_model : "default" (only option for now)
    decision_id : optional back-reference to a DecisionDraft
    portfolio_db_path : override for PortfolioStore path (testing)
    """
    # 1. Validate inputs
    signal_type = signal.get("type")
    if not signal_type or signal_type not in _SIGNAL_SIDE_MAP:
        return {"error": f"Invalid signal type: {signal_type!r}. Must be one of {list(_SIGNAL_SIDE_MAP.keys())}"}

    symbol_str = signal.get("symbol")
    if not symbol_str:
        return {"error": "Signal must contain a 'symbol' field (canonical string)."}

    try:
        price = Decimal(ref_price)
        if price <= 0:
            return {"error": f"ref_price must be positive, got {ref_price!r}"}
    except (InvalidOperation, TypeError):
        return {"error": f"ref_price must be a valid Decimal string, got {ref_price!r}"}

    # 2. Parse symbol
    try:
        symbol = Symbol.parse(symbol_str)
    except (ValueError, Exception) as exc:
        return {"error": f"Cannot parse symbol {symbol_str!r}: {exc}"}

    # 3. Determine side
    side = _SIGNAL_SIDE_MAP[signal_type]
    is_exit = signal_type.startswith("EXIT_")

    # 4. Build sizing policy + fee model
    try:
        policy = _build_sizing_policy(sizing_policy, sizing_params)
    except (ValueError, Exception) as exc:
        return {"error": f"Sizing policy error: {exc}"}

    fm: FeeModel = DefaultFeeModel()

    # 5. Load portfolio state (read-only)
    store = PortfolioStore(db_path=portfolio_db_path) if portfolio_db_path else PortfolioStore()
    try:
        balances = store.get_all_balances()
        positions_raw = store.get_all_positions()
    finally:
        store.close()

    # 6. Compute NAV via mark-to-market
    positions_for_snap = [
        (Symbol.parse(p.symbol), p.qty, p.avg_entry_price)
        for p in positions_raw
    ]

    # Determine nav_currency from balances or default USD
    nav_currency = Currency("USD")
    if balances:
        # Use the first (or largest) balance currency as nav currency
        nav_currency = max(balances, key=lambda c: balances[c])

    from datetime import UTC, datetime

    snap = build_snapshot(
        balances=balances,
        positions=positions_for_snap,
        current_prices={k: Decimal(v) for k, v in (current_prices or {}).items()},
        nav_currency=nav_currency,
        open_orders_count=0,
        asof=datetime.now(UTC),
    )

    nav = snap.nav
    if nav <= 0:
        return {"error": f"Portfolio NAV is non-positive ({nav}). Cannot size."}

    # 7. Compute stake
    did = DecisionId(decision_id) if decision_id else None
    builder = IntentBuilder(fee_model=fm)
    intent: OrderIntent | None = None
    sizing_info: dict[str, Any] = {}

    if is_exit:
        # For exits, qty comes from existing position
        pos = next(
            (p for p in positions_raw if p.symbol == symbol_str),
            None,
        )
        if pos is None:
            return {"error": f"No open position for {symbol_str} — cannot exit."}

        exit_qty = abs(pos.qty)
        intent = builder.build_exit(
            symbol=symbol,
            exit_side=side,
            qty=exit_qty,
            exit_price=price,
            exit_reason=signal.get("reason", signal_type),
            decision_id=did,
        )
        sizing_info = {
            "policy": "exit",
            "nav_at_decision": str(nav),
            "exit_qty": str(exit_qty),
            "cap_was_applied": False,
            "cap_ceiling": str(apply_nav_cap(nav, nav)),
        }
    else:
        # Entry: compute stake via policy (already internally capped)
        stake_from_policy = policy.stake_amount(symbol, side, price, nav)
        # The cap ceiling is 5% of NAV
        cap_ceiling = apply_nav_cap(nav, nav)
        # Detect if the cap was binding by comparing to what the policy
        # would have produced without it. Since the policy returns the
        # already-capped value, the cap was applied iff result == ceiling
        # AND the policy's raw math would have exceeded it.
        # We compute the uncapped value ourselves for transparency.
        uncapped_stake = _compute_uncapped_stake(
            sizing_policy, sizing_params, nav
        )
        cap_was_applied = uncapped_stake > cap_ceiling

        sizing_explanation = (
            f"{sizing_policy}@{sizing_params or {}}: "
            f"stake={stake_from_policy}"
        )

        intent = builder.build_entry(
            symbol=symbol,
            side=side,
            ref_price=price,
            stake=stake_from_policy,
            nav=nav,
            sizing_explanation=sizing_explanation,
            decision_id=did,
        )

        sizing_info = {
            "policy": sizing_policy,
            "nav_at_decision": str(nav),
            "stake_raw": str(stake_from_policy),
            "stake_after_cap": str(stake_from_policy),
            "cap_was_applied": cap_was_applied,
            "cap_ceiling": str(cap_ceiling),
        }

    if intent is None:
        return {
            "error": "IntentBuilder returned None — stake/qty too small after cap.",
            "sizing": sizing_info,
        }

    # 8. Serialize and return
    intent_dict = to_jsonable(intent)
    # Ensure symbol is canonical string, not nested dict
    if isinstance(intent_dict, dict) and isinstance(intent_dict.get("symbol"), dict):
        intent_dict["symbol"] = intent.symbol.canonical()
    return {
        "intent": intent_dict,
        "sizing": sizing_info,
        "ref_price_used": str(price),
    }
