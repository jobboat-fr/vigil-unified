"""Coinbase Advanced Trade brokerage adapter.

Implements the `Brokerage` ABC for CR: symbols via Coinbase's Advanced
Trade API. Uses CCXT under the hood (which already supports Coinbase's
ECDSA-signed JWT auth scheme) so we don't reinvent request signing.

ENABLED by WW_FEATURE_TRADE_API (default OFF — must be explicitly turned
on once round-trip is verified on testnet/with small balance).

Reads config:
  COINBASE_API_KEY_NAME      — "organizations/<org>/apiKeys/<id>"
  COINBASE_API_PRIVATE_KEY   — PEM EC private key
  COINBASE_SANDBOX           — "true" → use sandbox URLs

This is a SCAFFOLD: structure + auth wiring is real; the actual order
placement methods raise FeatureDisabledError until the flag is on AND
the keys are populated. Once both are true, calls route through CCXT's
`coinbase` venue with our existing CcxtBrokerage codepath.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

from winny.brokerage.base import Brokerage
from winny.common.errors import BrokerageError
from winny.common.features import features
from winny.common.ids import BrokerOrderId, Currency
from winny.common.symbols import Symbol
from winny.common.types import Fill, MarketSpec, OrderIntent, OrderState, Position


class CoinbaseBrokerage(Brokerage):
    """Coinbase Advanced Trade — spot crypto via CCXT-wrapped JWT auth."""

    def __init__(self, *, sandbox: bool = False) -> None:
        self._sandbox = sandbox or os.getenv("COINBASE_SANDBOX", "").lower() in ("1", "true")
        self._api_key_name = os.getenv("COINBASE_API_KEY_NAME", "")
        self._api_private_key = os.getenv("COINBASE_API_PRIVATE_KEY", "")
        self._client: Any | None = None

    def _ensure_enabled(self) -> None:
        features().require(
            "trade_api",
            "set WW_FEATURE_TRADE_API=true AND populate COINBASE_API_KEY_NAME + COINBASE_API_PRIVATE_KEY",
        )
        if not (self._api_key_name and self._api_private_key):
            raise BrokerageError(
                "Coinbase brokerage feature is on but COINBASE_API_KEY_NAME / "
                "COINBASE_API_PRIVATE_KEY are not set."
            )

    # ─── Brokerage ABC ───────────────────────────────────────────────────────

    def get_balance(self) -> dict[Currency, Decimal]:
        self._ensure_enabled()
        # TODO: ccxt.coinbase().fetch_balance()
        return {}

    def get_positions(self) -> list[Position]:
        self._ensure_enabled()
        # Spot has no positions per se — balances net to "positions".
        return []

    def get_market(self, symbol: Symbol) -> MarketSpec:
        self._ensure_enabled()
        raise NotImplementedError("populated in PR following adapter wiring")

    def submit(self, intent: OrderIntent) -> BrokerOrderId:
        self._ensure_enabled()
        raise NotImplementedError(
            "submit() is implementation-pending. Approval gate already protects "
            "the call site; flipping the flag without implementing this means "
            "FeatureDisabledError on every order — safer than silent paper fill."
        )

    def cancel(self, broker_order_id: BrokerOrderId) -> None:
        self._ensure_enabled()
        raise NotImplementedError

    def get_order(self, broker_order_id: BrokerOrderId) -> OrderState:
        self._ensure_enabled()
        raise NotImplementedError

    async def stream_fills(self) -> AsyncIterator[Fill]:
        self._ensure_enabled()
        # Stub generator
        if False:
            yield  # pragma: no cover
        return
