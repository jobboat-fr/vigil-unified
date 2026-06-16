"""Brokerage factory — routes Symbol to the correct adapter per §3.3.5.

Routing table:
    CR: (crypto)     → CcxtBrokerage (default: binance; env: WINNY_BROKER_CR)
    EQ: (equities)   → IbkrBrokerage (env: WINNY_BROKER_EQ)
    FX: (forex)      → IbkrBrokerage (env: WINNY_BROKER_FX)
    FU: (futures)    → IbkrBrokerage (env: WINNY_BROKER_FU)
    OP: (options)    → IbkrBrokerage (env: WINNY_BROKER_OP)

Paper brokerage overrides everything if mode is BACKTEST or DRY_RUN.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Literal

from winny.common.errors import BrokerageError, UnknownSymbolError
from winny.common.symbols import AssetClass, Symbol

from .base import Brokerage

EngineMode = Literal["BACKTEST", "DRY_RUN", "LIVE"]


def get_brokerage(
    symbol: Symbol,
    *,
    mode: EngineMode = "LIVE",
    sandbox: bool = False,
) -> Brokerage:
    """Return the appropriate brokerage for a symbol + mode combination.

    In BACKTEST and DRY_RUN modes, always returns PaperBrokerage.
    In LIVE mode, routes by asset class.
    """
    if mode in ("BACKTEST", "DRY_RUN"):
        from datetime import UTC, datetime

        from winny.common.ids import Currency
        from winny.common.types import Bar, MarketSpec

        from .paper import PaperBrokerage

        # Auto-generate a permissive MarketSpec for the requested symbol
        default_spec = MarketSpec(
            symbol=symbol,
            min_qty=Decimal("0.00001"),
            qty_step=Decimal("0.00001"),
            price_tick=Decimal("0.01"),
            min_notional=Decimal("10"),
            maker_fee_bps=4,
            taker_fee_bps=10,
        )
        # Determine quote currency from symbol
        quote_ccy = Currency(symbol.quote or "USD")
        broker = PaperBrokerage(
            initial_cash={quote_ccy: Decimal("100000")},
            market_specs={symbol: default_spec},
        )
        # Seed a reference price so MARKET orders can fill immediately.
        # Use a nominal price of $1; real DRY_RUN integrations should feed
        # actual bars via the engine loop.
        seed_bar = Bar(
            symbol=symbol,
            ts=datetime.now(UTC),
            open=Decimal("1"),
            high=Decimal("1"),
            low=Decimal("1"),
            close=Decimal("1"),
            volume=Decimal("1000"),
        )
        broker.tick(symbol, seed_bar)
        return broker

    return _live_broker_for(symbol, sandbox=sandbox)


def _live_broker_for(symbol: Symbol, *, sandbox: bool = False) -> Brokerage:
    """Resolve live broker by asset class prefix."""
    if symbol.asset_class == AssetClass.CRYPTO:
        from .ccxt_adapter import CcxtBrokerage

        venue = os.environ.get("WINNY_BROKER_CR", "binance").lower()
        return CcxtBrokerage(venue=venue, sandbox=sandbox)

    if symbol.asset_class in (
        AssetClass.EQUITY,
        AssetClass.FOREX,
        AssetClass.FUTURE,
        AssetClass.OPTION,
    ):
        # IBKR adapter — deferred to P6
        raise BrokerageError(
            f"IBKR adapter not yet implemented for {symbol.asset_class.value}. "
            f"Use mode='DRY_RUN' or wait for P6."
        )

    raise UnknownSymbolError(
        f"No brokerage mapping for asset class {symbol.asset_class.value}"
    )
