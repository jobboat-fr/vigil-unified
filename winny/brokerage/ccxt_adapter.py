"""CCXT brokerage adapter — SPECS.md §3.3.5 + P5.

Wraps the `ccxt` library to connect to crypto exchanges (Binance, Kraken,
OKX, Coinbase, Bybit, Gate). One adapter handles multiple venues — the
venue is selected per-Symbol via config.

Default venue: Binance (overridable via WINNY_BROKER_CR env var).

Design constraints:
  - Implements the Brokerage ABC faithfully.
  - Thread-safe for single-threaded engine loop.
  - All monetary values remain Decimal until the final ccxt call.
  - Errors map to the typed BrokerageError hierarchy.
  - stream_fills() uses ccxt.pro (websocket) when available.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

try:
    import ccxt
    import ccxt.pro as ccxtpro
except ImportError:  # pragma: no cover
    ccxt = None  # type: ignore[assignment,unused-ignore]
    ccxtpro = None  # type: ignore[assignment,unused-ignore]

from winny.common.errors import (
    BrokerageError,
    InsufficientBalanceError,
    UnknownOrderError,
    UnknownSymbolError,
    UnsupportedOrderTypeError,
)
from winny.common.ids import BrokerOrderId, Currency
from winny.common.symbols import AssetClass, Symbol
from winny.common.types import (
    Fill,
    MarketSpec,
    OrderIntent,
    OrderState,
    OrderStatus,
    OrderType,
    Position,
    Side,
)

from .base import Brokerage

# ---------- venue resolution ----------

_VENUE_MAP: dict[str, str] = {
    "binance": "binance",
    "kraken": "kraken",
    "okx": "okx",
    "coinbase": "coinbasepro",
    "bybit": "bybit",
    "gate": "gateio",
}

_DEFAULT_VENUE = "binance"


def _resolve_venue() -> str:
    """Get venue from env or default."""
    env = os.environ.get("WINNY_BROKER_CR", _DEFAULT_VENUE).lower()
    return _VENUE_MAP.get(env, env)


# ---------- symbol translation ----------


def _to_ccxt_symbol(symbol: Symbol) -> str:
    """Convert our Symbol to ccxt market symbol string.

    e.g. Symbol(CRYPTO, 'BTC', 'USDT') -> 'BTC/USDT'
    """
    if symbol.asset_class != AssetClass.CRYPTO:
        raise UnknownSymbolError(
            f"CcxtBrokerage only handles CRYPTO symbols, got {symbol.canonical()}"
        )
    quote = symbol.quote or "USDT"
    return f"{symbol.base}/{quote}"


def _from_ccxt_symbol(ccxt_symbol: str, exchange: Any) -> Symbol:
    """Convert ccxt market symbol back to our Symbol."""
    pair = str(ccxt_symbol or "").split(":", 1)[0]
    parts = pair.split("/")
    base = parts[0]
    quote = parts[1] if len(parts) > 1 else "USDT"
    venue = (
        getattr(exchange, "id", None)
        or getattr(exchange, "name", None)
        or _DEFAULT_VENUE
    )
    venue = str(venue).lower().replace(" ", "_")
    return Symbol(asset_class=AssetClass.CRYPTO, base=base, quote=quote, venue=venue)


# ---------- status mapping ----------

_STATUS_MAP: dict[str, OrderStatus] = {
    "open": OrderStatus.ACCEPTED,
    "closed": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELLED,
    "cancelled": OrderStatus.CANCELLED,
    "expired": OrderStatus.CANCELLED,
    "rejected": OrderStatus.REJECTED,
}


def _map_status(ccxt_status: str) -> OrderStatus:
    return _STATUS_MAP.get(ccxt_status, OrderStatus.PENDING)


# ---------- adapter ----------


class CcxtBrokerage(Brokerage):
    """Live crypto brokerage via ccxt.

    Requires API key/secret in env:
      - WINNY_CCXT_API_KEY
      - WINNY_CCXT_SECRET
      - WINNY_CCXT_PASSWORD (for exchanges that need it, e.g. OKX)
    """

    def __init__(
        self,
        *,
        venue: str | None = None,
        api_key: str | None = None,
        secret: str | None = None,
        password: str | None = None,
        sandbox: bool = False,
    ) -> None:
        if ccxt is None:
            raise BrokerageError(
                "ccxt is not installed. Install with: pip install ccxt"
            )

        self._venue_name = venue or _resolve_venue()
        self._api_key = api_key or os.environ.get("WINNY_CCXT_API_KEY", "")
        self._secret = secret or os.environ.get("WINNY_CCXT_SECRET", "")
        self._password = password or os.environ.get("WINNY_CCXT_PASSWORD", "")
        self._sandbox = sandbox

        # Initialize sync exchange
        exchange_class = getattr(ccxt, self._venue_name, None)
        if exchange_class is None:
            raise BrokerageError(f"Unknown ccxt exchange: {self._venue_name}")

        config: dict[str, Any] = {
            "apiKey": self._api_key,
            "secret": self._secret,
            "enableRateLimit": True,
        }
        if self._password:
            config["password"] = self._password

        self._exchange: ccxt.Exchange = exchange_class(config)
        if self._sandbox:
            self._exchange.set_sandbox_mode(True)

        # Pro exchange for streaming (lazy init)
        self._pro_exchange: Any | None = None

    def _ensure_markets_loaded(self) -> None:
        """Load markets if not already loaded."""
        if not self._exchange.markets:
            self._exchange.load_markets()

    # ===================================================================
    # Read-only accessors
    # ===================================================================

    def get_balance(self) -> dict[Currency, Decimal]:
        """Fetch account balances from exchange."""
        try:
            balance = self._exchange.fetch_balance()
        except ccxt.BaseError as e:
            raise BrokerageError(f"Failed to fetch balance: {e}") from e

        result: dict[Currency, Decimal] = {}
        total = balance.get("total", {})
        for currency, amount in total.items():
            if amount and float(amount) > 0:
                result[Currency(currency)] = Decimal(str(amount))
        return result

    def get_positions(self) -> list[Position]:
        """Fetch open positions (for futures/margin accounts)."""
        try:
            positions = self._exchange.fetch_positions()
        except (ccxt.BaseError, AttributeError):
            # Spot exchanges may not support positions
            return []

        result: list[Position] = []
        for pos in positions:
            try:
                qty = Decimal(str(pos.get("contracts", 0) or 0))
                if qty == 0:
                    continue
                side_str = pos.get("side", "long")
                signed_qty = qty if side_str == "long" else -qty
                entry_price = Decimal(str(pos.get("entryPrice", 0) or 0))
                unrealized = Decimal(str(pos.get("unrealizedPnl", 0) or 0))

                symbol_str = pos.get("symbol", "")
                symbol = _from_ccxt_symbol(symbol_str, self._exchange)
            except Exception:
                # Exchanges sometimes return non-standard position rows. Keep
                # the rest of the account snapshot usable when one row is bad.
                continue

            result.append(Position(
                symbol=symbol,
                qty=signed_qty,
                avg_entry_price=entry_price,
                unrealized_pnl=unrealized,
                realized_pnl=Decimal("0"),  # ccxt doesn't always provide this
            ))
        return result

    def get_market(self, symbol: Symbol) -> MarketSpec:
        """Get trading rules for a symbol."""
        self._ensure_markets_loaded()
        ccxt_sym = _to_ccxt_symbol(symbol)

        market = self._exchange.market(ccxt_sym)
        if market is None:
            raise UnknownSymbolError(f"No market data for {symbol.canonical()}")

        limits = market.get("limits", {})
        precision = market.get("precision", {})
        # Extract min qty
        amount_limits = limits.get("amount", {})
        min_qty = Decimal(str(amount_limits.get("min", "0.00001") or "0.00001"))

        # Qty step from precision
        amount_precision = precision.get("amount", 8)
        qty_step = Decimal(str(10 ** (-int(amount_precision))))

        # Price tick from precision
        price_precision = precision.get("price", 8)
        price_tick = Decimal(str(10 ** (-int(price_precision))))

        # Min notional
        cost_limits = limits.get("cost", {})
        min_notional_raw = cost_limits.get("min")
        min_notional = Decimal(str(min_notional_raw)) if min_notional_raw else None

        # Fees (default conservative: 10 bps taker, 4 bps maker per spec)
        maker_fee = market.get("maker", 0.0004)
        taker_fee = market.get("taker", 0.001)

        return MarketSpec(
            symbol=symbol,
            min_qty=min_qty,
            qty_step=qty_step,
            price_tick=price_tick,
            min_notional=min_notional,
            maker_fee_bps=int(float(maker_fee or 0.0004) * 10000),
            taker_fee_bps=int(float(taker_fee or 0.001) * 10000),
        )

    # ===================================================================
    # Order placement / management
    # ===================================================================

    def submit(self, intent: OrderIntent) -> BrokerOrderId:
        """Submit an OrderIntent to the exchange."""
        self._ensure_markets_loaded()
        ccxt_sym = _to_ccxt_symbol(intent.symbol)

        # Map order type
        if intent.order_type == OrderType.MARKET:
            ot = "market"
        elif intent.order_type == OrderType.LIMIT:
            ot = "limit"
        elif intent.order_type == OrderType.STOP:
            ot = "stop"
        elif intent.order_type == OrderType.STOP_LIMIT:
            ot = "stopLimit"
        else:
            raise UnsupportedOrderTypeError(
                f"Unsupported order type: {intent.order_type}"
            )

        side = "buy" if intent.side == Side.BUY else "sell"
        amount = float(intent.qty)
        price = float(intent.limit_price) if intent.limit_price else None

        params: dict[str, Any] = {}
        if intent.stop_price:
            params["stopPrice"] = float(intent.stop_price)

        try:
            order = self._exchange.create_order(
                symbol=ccxt_sym,
                type=ot,
                side=side,
                amount=amount,
                price=price,
                params=params,
            )
        except ccxt.InsufficientFunds as e:
            raise InsufficientBalanceError(str(e)) from e
        except ccxt.InvalidOrder as e:
            raise BrokerageError(f"Invalid order: {e}") from e
        except ccxt.BaseError as e:
            raise BrokerageError(f"Order submission failed: {e}") from e

        return BrokerOrderId(str(order["id"]))

    def cancel(self, broker_order_id: BrokerOrderId) -> None:
        """Cancel a pending order."""
        try:
            # We need the symbol for cancel — fetch the order first
            order = self._exchange.fetch_order(str(broker_order_id))
            if order["status"] in ("closed", "canceled", "cancelled", "expired"):
                return  # Already done, no-op
            self._exchange.cancel_order(str(broker_order_id), order.get("symbol"))
        except ccxt.OrderNotFound as e:
            raise UnknownOrderError(f"Order {broker_order_id} not found") from e
        except ccxt.BaseError as e:
            raise BrokerageError(f"Cancel failed: {e}") from e

    def get_order(self, broker_order_id: BrokerOrderId) -> OrderState:
        """Get current state of an order."""
        try:
            order = self._exchange.fetch_order(str(broker_order_id))
        except ccxt.OrderNotFound as e:
            raise UnknownOrderError(f"Order {broker_order_id} not found") from e
        except ccxt.BaseError as e:
            raise BrokerageError(f"Failed to fetch order: {e}") from e

        filled = Decimal(str(order.get("filled", 0) or 0))
        avg_price_raw = order.get("average") or order.get("price")
        avg_price = Decimal(str(avg_price_raw)) if avg_price_raw else None

        ts_raw = order.get("timestamp")
        ts = datetime.fromtimestamp(ts_raw / 1000, tz=UTC) if ts_raw else datetime.now(UTC)

        from winny.common.ids import IntentId

        return OrderState(
            broker_order_id=broker_order_id,
            intent_id=IntentId(intent_id_from_client_order_id(order)),
            status=_map_status(order.get("status", "open")),
            filled_qty=filled,
            avg_fill_price=avg_price,
            last_event_ts=ts,
            raw_broker_state=order,
        )

    # ===================================================================
    # Streaming (ccxt.pro websocket)
    # ===================================================================

    async def stream_fills(self) -> AsyncIterator[Fill]:
        """Stream fill events via ccxt.pro websocket."""
        if self._pro_exchange is None:
            pro_class = getattr(ccxtpro, self._venue_name, None)
            if pro_class is None:
                return  # No pro support — fall back to polling
            config: dict[str, Any] = {
                "apiKey": self._api_key,
                "secret": self._secret,
                "enableRateLimit": True,
            }
            if self._password:
                config["password"] = self._password
            self._pro_exchange = pro_class(config)
            if self._sandbox:
                self._pro_exchange.set_sandbox_mode(True)

        while True:
            try:
                trades = await self._pro_exchange.watch_my_trades()
            except Exception:
                break  # Connection lost, caller should retry

            for trade in trades:
                yield Fill(
                    broker_order_id=BrokerOrderId(str(trade.get("order", ""))),
                    ts=datetime.fromtimestamp(
                        (trade.get("timestamp") or 0) / 1000, tz=UTC
                    ),
                    qty=Decimal(str(trade.get("amount", 0))),
                    price=Decimal(str(trade.get("price", 0))),
                    fees=Decimal(str((trade.get("fee") or {}).get("cost", 0))),
                    liquidity="MAKER" if trade.get("takerOrMaker") == "maker" else "TAKER",
                )

    # ===================================================================
    # Cleanup
    # ===================================================================

    async def close(self) -> None:
        """Close exchange connections."""
        if self._pro_exchange:
            await self._pro_exchange.close()


# ---------- helper ----------


def intent_id_from_client_order_id(order: dict[str, Any]) -> str:
    """Extract intent_id from clientOrderId if set, else use broker id."""
    client_id: str = order.get("clientOrderId", "")
    if client_id and client_id.startswith("int_"):
        return client_id
    order_id: str = str(order.get("id", "unknown"))
    return f"int_{order_id}"
