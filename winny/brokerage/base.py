"""Brokerage abstraction — SPECS.md §3.3.5.

Vendored from Lean's IBrokerage design pattern: a thin, swappable interface
that lets the same engine loop run against a paper broker (PR #10), a CCXT
crypto venue (PR #15), or IB Gateway for equities/options/futures (PR #16).

Per §3.3.5, this is the ONLY thing that places real orders. Strategies
emit signals (PR #8); the engine converts them to OrderIntent (PR #11);
the approval gate (PR #4) issues a grant; only then does `submit()`
reach a Brokerage.

Symbol routing by asset class (§3.3.5):
    CR: → ccxt:binance (default; user-overridable)
    EQ: → ibkr
    FX: → ibkr
    FU: → ibkr
    OP: → ibkr

Paper brokerage routes everything in-memory regardless of class — used in
backtest and dry-run modes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from decimal import Decimal

from winny.common.ids import BrokerOrderId, Currency
from winny.common.symbols import Symbol
from winny.common.types import Fill, MarketSpec, OrderIntent, OrderState, Position


class Brokerage(ABC):
    """Abstract brokerage interface.

    Implementations MUST be safe to invoke from a single-threaded engine loop.
    Live brokers may use background tasks for fill streams; they SHOULD NOT
    require the caller to drive their event loop manually (use asyncio.Task).
    """

    # ===================================================================
    # Read-only accessors
    # ===================================================================

    @abstractmethod
    def get_balance(self) -> dict[Currency, Decimal]:
        """Current cash balances per currency. Empty dict = no accounts."""

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """All open positions, signed qty (long > 0, short < 0)."""

    @abstractmethod
    def get_market(self, symbol: Symbol) -> MarketSpec:
        """Trading rules for a symbol (tick size, lot size, fees, etc.).

        Raises UnknownSymbolError if the symbol is not tradeable on this broker.
        """

    # ===================================================================
    # Order placement / management
    # ===================================================================

    @abstractmethod
    def submit(self, intent: OrderIntent) -> BrokerOrderId:
        """Submit a validated OrderIntent.

        Returns the broker-assigned order ID. The order may already be FILLED
        (market orders on a paper broker) or PENDING (limit orders).

        Raises:
            InsufficientBalanceError: BUY exceeds available cash.
            InsufficientPositionError: SELL exceeds position (long-only brokers).
            UnknownSymbolError: no MarketSpec for the symbol.
            UnsupportedOrderTypeError: order_type not supported (e.g. STOP_LIMIT
                on a paper broker that only supports MARKET/LIMIT).
        """

    @abstractmethod
    def cancel(self, broker_order_id: BrokerOrderId) -> None:
        """Cancel a still-PENDING/ACCEPTED order.

        No-op if the order is already FILLED, CANCELLED, or REJECTED. Raises
        UnknownOrderError if the id is unrecognized.
        """

    @abstractmethod
    def get_order(self, broker_order_id: BrokerOrderId) -> OrderState:
        """Current state of an order. Raises UnknownOrderError on unknown id."""

    # ===================================================================
    # Optional: fill streaming (live brokers only)
    # ===================================================================

    async def stream_fills(self) -> AsyncIterator[Fill]:
        """Async stream of fill events.

        Default implementation yields nothing — paper/synchronous brokers don't
        need streaming. Live brokers (CCXT websocket, IBKR) override.
        """
        if False:  # pragma: no cover — unreachable; preserves generator typing
            yield Fill.model_construct()
