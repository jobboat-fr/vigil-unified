"""Kraken WebSocket v2 brokerage adapter.

Implements the Brokerage ABC over Kraken's native WS v2 transport:
  • Public channels    — ticker, book, candles, trades (no auth, free)
  • Authenticated chs  — executions, balances (auth required, WS auth token)
  • Trading methods    — add_order, batch_add, amend_order, cancel_order,
                          cancel_all, cancel_on_disconnect

Why a native WS adapter instead of CCXT REST?
  1. Lower latency on order submission (~20-50 ms vs ~150-300 ms for REST)
  2. `batch_add` maps directly to cluster fan-out — one signal, N positions,
     one round-trip.
  3. `cancel_on_disconnect` is a server-side dead-man's switch: if the
     gateway crashes mid-trade, Kraken auto-cancels every open order
     within the heartbeat window. Built-in fail-safe.
  4. Streaming executions / balances eliminates polling.

Feature flags (winny.common.features):
  kraken_charts   — public market data (ENABLED by default)
  kraken_trade    — order submission/cancel (DISABLED, manual flip)
  kraken_streams  — user-data executions + balances (DISABLED)

Config (env):
  KRAKEN_API_KEY            — Kraken API key (string)
  KRAKEN_API_SECRET         — base64-encoded private key
  KRAKEN_WS_PUBLIC_URL      — default "wss://ws.kraken.com/v2"
  KRAKEN_WS_PRIVATE_URL     — default "wss://ws-auth.kraken.com/v2"
  KRAKEN_REST_URL           — default "https://api.kraken.com" (for ws-auth token)
  KRAKEN_CANCEL_ON_DISCONNECT_TIMEOUT — default 15 (seconds)

This module is a SCAFFOLD: structure + flag plumbing is real; the actual
WS connect/send/recv loop is stubbed and lands in a follow-up PR alongside
a CCXT-shadow paper integration test on Kraken's `sandbox` environment.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from decimal import Decimal

from winny.brokerage.base import Brokerage
from winny.common.errors import BrokerageError
from winny.common.features import features
from winny.common.ids import BrokerOrderId, Currency
from winny.common.symbols import Symbol
from winny.common.types import Fill, MarketSpec, OrderIntent, OrderState, Position


class KrakenBrokerage(Brokerage):
    """Native Kraken WebSocket v2 brokerage.

    All trading methods raise FeatureDisabledError until WW_FEATURE_KRAKEN_TRADE
    is flipped on AND KRAKEN_API_KEY / KRAKEN_API_SECRET are populated.
    """

    def __init__(self) -> None:
        self._api_key = os.getenv("KRAKEN_API_KEY", "")
        self._api_secret = os.getenv("KRAKEN_API_SECRET", "")
        self._public_ws = os.getenv("KRAKEN_WS_PUBLIC_URL", "wss://ws.kraken.com/v2")
        self._private_ws = os.getenv("KRAKEN_WS_PRIVATE_URL", "wss://ws-auth.kraken.com/v2")
        self._rest_url = os.getenv("KRAKEN_REST_URL", "https://api.kraken.com")
        self._cod_timeout = int(os.getenv("KRAKEN_CANCEL_ON_DISCONNECT_TIMEOUT", "15"))

        # WS connection handles, populated lazily on first call
        self._pub_conn: object | None = None
        self._priv_conn: object | None = None

    # ─── precondition checks ─────────────────────────────────────────────

    def _require_trade(self) -> None:
        features().require(
            "kraken_trade",
            "set WW_FEATURE_KRAKEN_TRADE=true and populate KRAKEN_API_KEY / KRAKEN_API_SECRET",
        )
        if not (self._api_key and self._api_secret):
            raise BrokerageError(
                "Kraken trade feature is ON but KRAKEN_API_KEY / KRAKEN_API_SECRET are empty."
            )

    def _require_streams(self) -> None:
        features().require("kraken_streams", "set WW_FEATURE_KRAKEN_STREAMS=true")
        if not (self._api_key and self._api_secret):
            raise BrokerageError(
                "Kraken streams feature is ON but KRAKEN_API_KEY / KRAKEN_API_SECRET are empty."
            )

    # ─── Brokerage ABC ───────────────────────────────────────────────────

    def get_balance(self) -> dict[Currency, Decimal]:
        self._require_streams()
        # TODO: WS subscribe channel="balances"; first snapshot is full state.
        return {}

    def get_positions(self) -> list[Position]:
        self._require_streams()
        # Spot venue: positions derive from balances. Margin/perps land later.
        return []

    def get_market(self, symbol: Symbol) -> MarketSpec:
        # Public — uses instruments channel, no auth required.
        features().require("kraken_charts")
        raise NotImplementedError("populated alongside the WS connect loop")

    def submit(self, intent: OrderIntent) -> BrokerOrderId:
        self._require_trade()
        # TODO: WS method="add_order", binds to params per intent.
        # On success: returns order_id. On reject: raises BrokerageError.
        raise NotImplementedError

    def submit_batch(self, intents: list[OrderIntent]) -> list[BrokerOrderId]:
        """Cluster fan-out — one WS round-trip places N orders.

        This is the high-leverage method: it maps directly to the cluster
        router emitting per-cluster intent breakdowns.
        """
        self._require_trade()
        # TODO: WS method="batch_add", returns ordered list of order ids.
        raise NotImplementedError

    def cancel(self, broker_order_id: BrokerOrderId) -> None:
        self._require_trade()
        raise NotImplementedError

    def cancel_batch(self, broker_order_ids: list[BrokerOrderId]) -> None:
        """Cancel N orders in one round-trip."""
        self._require_trade()
        raise NotImplementedError

    def cancel_all(self) -> None:
        """Kraken-side kill-switch via cancel_all method."""
        self._require_trade()
        raise NotImplementedError

    def get_order(self, broker_order_id: BrokerOrderId) -> OrderState:
        self._require_streams()
        raise NotImplementedError

    async def stream_fills(self) -> AsyncIterator[Fill]:
        """Subscribe to authenticated 'executions' channel; yield each fill."""
        self._require_streams()
        # Stub generator
        if False:
            yield  # pragma: no cover
        return

    # ─── Kraken-specific extensions ──────────────────────────────────────

    async def arm_cancel_on_disconnect(self, timeout_seconds: int | None = None) -> None:
        """Tell Kraken to auto-cancel everything if we disconnect.

        Acts as a server-side dead-man's switch — even if mcp-algo / the
        gateway crashes hard, Kraken cancels all our open orders within
        the heartbeat window. Pair with our own §1.3 kill-switch.
        """
        self._require_trade()
        ttl = timeout_seconds if timeout_seconds is not None else self._cod_timeout
        # TODO: WS method="cancel_on_disconnect", params={"timeout": ttl}
        _ = ttl
        raise NotImplementedError
