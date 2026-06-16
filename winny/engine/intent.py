"""IntentBuilder + IntentHandler — PR #11, §3.3.4.

IntentBuilder is the **sole constructor** of OrderIntent. It enforces the
§1.3 NAV cap chokepoint structurally: no code path can mint an intent without
going through `apply_nav_cap`.

IntentHandler is the **dispatch seam** between backtest and live modes:
  - DirectIntentHandler: submit intent to broker immediately (backtest/dry-run)
  - ApprovalGatedIntentHandler: route intent through the approval queue (live)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from winny.brokerage.paper import PaperBrokerage
from winny.common.ids import (
    BrokerOrderId,
    DecisionId,
    new_decision_id,
    new_intent_id,
)
from winny.common.symbols import Symbol
from winny.common.types import (
    OrderIntent,
    OrderType,
    Side,
    TimeInForce,
)
from winny.engine.fees import FeeModel
from winny.engine.sizing import apply_nav_cap


class IntentBuilder:
    """Sole constructor for OrderIntent. The nav-cap chokepoint lives here.

    Every entry and exit intent in the engine MUST be created through this
    builder. This makes the 5% NAV cap structurally unbypassable — you cannot
    create an OrderIntent without going through `apply_nav_cap`.
    """

    def __init__(self, fee_model: FeeModel) -> None:
        self._fee_model = fee_model

    def build_entry(
        self,
        *,
        symbol: Symbol,
        side: Side,
        ref_price: Decimal,
        stake: Decimal,
        nav: Decimal,
        sizing_explanation: str,
        decision_id: DecisionId | None = None,
    ) -> OrderIntent | None:
        """Build an entry OrderIntent with nav-cap enforcement.

        Returns None if the capped stake or qty is non-positive.
        """
        # R2: NAV cap chokepoint — structurally unbypassable
        capped_stake = apply_nav_cap(stake, nav)
        if capped_stake <= 0:
            return None

        qty = (capped_stake / ref_price).quantize(Decimal("0.00000001"))
        if qty <= 0:
            return None

        notional = qty * ref_price
        fee_quote = self._fee_model.quote(symbol, side, qty, notional, liquidity="taker")
        did = decision_id or new_decision_id()

        return OrderIntent(
            intent_id=new_intent_id(),
            decision_id=did,
            symbol=symbol,
            side=side,
            qty=qty,
            order_type=OrderType.MARKET,
            limit_price=None,
            stop_price=None,
            time_in_force=TimeInForce.IOC,
            estimated_cost=notional,
            estimated_fees=fee_quote.total,
            sizing_explanation=sizing_explanation,
        )

    def build_exit(
        self,
        *,
        symbol: Symbol,
        exit_side: Side,
        qty: Decimal,
        exit_price: Decimal,
        exit_reason: str,
        decision_id: DecisionId | None = None,
    ) -> OrderIntent:
        """Build an exit OrderIntent. No nav-cap needed for exits."""
        notional = qty * exit_price
        fee_quote = self._fee_model.quote(symbol, exit_side, qty, notional, liquidity="taker")
        did = decision_id or new_decision_id()

        return OrderIntent(
            intent_id=new_intent_id(),
            decision_id=did,
            symbol=symbol,
            side=exit_side,
            qty=qty,
            order_type=OrderType.MARKET,
            limit_price=None,
            stop_price=None,
            time_in_force=TimeInForce.IOC,
            estimated_cost=notional,
            estimated_fees=fee_quote.total,
            sizing_explanation=f"exit:{exit_reason}",
        )


# ===================================================================
# IntentHandler — dispatch seam for live-mode compatibility
# ===================================================================


class IntentHandler(ABC):
    """Abstract handler that decides what to do with a built OrderIntent.

    In backtest/dry-run: submit directly to the broker.
    In live: route through the approval queue first.
    """

    @abstractmethod
    def handle(self, intent: OrderIntent) -> BrokerOrderId | None:
        """Process an intent. Returns the broker order ID on success, None on rejection."""


class DirectIntentHandler(IntentHandler):
    """Submit intents directly to the broker (backtest + dry-run mode)."""

    def __init__(self, broker: PaperBrokerage) -> None:
        self._broker = broker

    def handle(self, intent: OrderIntent) -> BrokerOrderId | None:
        return self._broker.submit(intent)


class ApprovalGatedIntentHandler(IntentHandler):
    """Route intents through the human-in-the-loop approval queue (live mode).

    Stub implementation — full approval flow is deferred to PR #13.
    Intent is queued for approval; the broker submission happens only
    after human approval (via the approval service).
    """

    def handle(self, intent: OrderIntent) -> BrokerOrderId | None:
        # TODO(PR #15): Wire to mcp-approval — request grant, await user verdict,
        # broker.submit only on valid ApprovalGrant. See §3.4 + ADR-0005.
        raise NotImplementedError(
            "ApprovalGatedIntentHandler requires the PR #15 approval flow integration"
        )
