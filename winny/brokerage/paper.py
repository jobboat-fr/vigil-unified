"""PaperBrokerage — in-memory deterministic broker.

Used in BACKTEST and DRY_RUN engine modes. No network, no real money. Every
fill is a function of (intent, market_spec, fee_model, slippage_model, current_bar)
— same inputs always produce the same outputs (the `seed` parameter only
matters when future slippage models add randomness).

v1 design (intentionally minimal):
  - LONG-ONLY positions. Short logic deferred to PR #10.1.
  - MARKET orders fill IMMEDIATELY at slipped(last_close) price.
  - LIMIT orders queue and fill when a subsequent `tick(bar)` shows the
    price crossing the limit.
  - STOP / STOP_LIMIT orders raise UnsupportedOrderTypeError (deferred).
  - Fees deducted from cash on fill; positions tracked with weighted-avg entry.

Engine integration (PR #11):
  1. Engine constructs PaperBrokerage with initial cash + market specs.
  2. Per bar:
      a. broker.tick(symbol, bar)   ← updates last price, fires pending LIMITs
      b. engine runs strategy populate_*() and extracts signals
      c. engine calls broker.submit(intent) for each signal
"""

from __future__ import annotations

import random
import threading
from datetime import UTC, datetime
from decimal import Decimal

from winny.common.errors import (
    InsufficientBalanceError,
    InsufficientPositionError,
    UnknownOrderError,
    UnknownSymbolError,
    UnsupportedOrderTypeError,
    WinnyValidationError,
)
from winny.common.ids import BrokerOrderId, Currency
from winny.common.symbols import Symbol
from winny.common.types import (
    Bar,
    Fill,
    MarketSpec,
    OrderIntent,
    OrderState,
    OrderStatus,
    OrderType,
    Position,
    Side,
    TimeInForce,
)
from winny.engine.fees import DefaultFeeModel, FeeModel
from winny.engine.slippage import BpsSlippageModel, SlippageModel

from .base import Brokerage

_FEE_QUANTIZE = Decimal("0.0001")
_QTY_QUANTIZE = Decimal("0.00000001")


class PaperBrokerage(Brokerage):
    """Deterministic in-memory broker.

    Parameters
    ----------
    initial_cash : per-currency starting balance, e.g. {Currency("USD"): Decimal("100000")}
    market_specs : per-symbol tick/lot/fee config; engine fills this from data layer
    fee_model    : defaults to DefaultFeeModel() (§3.3.6 conservative)
    slippage_model : defaults to BpsSlippageModel() (§3.3.6)
    seed         : RNG seed for any stochastic future model (BpsSlippageModel
                   ignores it; reserved for OrderBookAwareSlippageModel later)
    """

    def __init__(
        self,
        *,
        initial_cash: dict[Currency, Decimal],
        market_specs: dict[Symbol, MarketSpec],
        fee_model: FeeModel | None = None,
        slippage_model: SlippageModel | None = None,
        seed: int = 42,
    ) -> None:
        self._balances: dict[Currency, Decimal] = dict(initial_cash)
        self._market_specs: dict[Symbol, MarketSpec] = dict(market_specs)
        self._fees = fee_model or DefaultFeeModel()
        self._slip = slippage_model or BpsSlippageModel()
        # Deterministic seed for paper sim; not used for cryptography.
        self._rng = random.Random(seed)

        self._orders: dict[BrokerOrderId, OrderState] = {}
        self._intents: dict[BrokerOrderId, OrderIntent] = {}  # for replay/inspection
        self._positions: dict[Symbol, Position] = {}
        self._fills: list[Fill] = []
        self._last_close: dict[Symbol, Decimal] = {}
        self._last_bar_ts: dict[Symbol, datetime] = {}

        self._lock = threading.Lock()
        self._next_id = 1

    # ===================================================================
    # Brokerage ABC implementation
    # ===================================================================

    def get_balance(self) -> dict[Currency, Decimal]:
        return dict(self._balances)

    def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    def get_market(self, symbol: Symbol) -> MarketSpec:
        spec = self._market_specs.get(symbol)
        if spec is None:
            raise UnknownSymbolError(
                f"no MarketSpec registered for {symbol.canonical()} on paper broker"
            )
        return spec

    def submit(self, intent: OrderIntent) -> BrokerOrderId:
        if intent.order_type in (OrderType.STOP, OrderType.STOP_LIMIT):
            raise UnsupportedOrderTypeError(
                f"PaperBrokerage v1 does not support {intent.order_type.value}; use MARKET or LIMIT"
            )

        spec = self.get_market(intent.symbol)
        if intent.qty < spec.min_qty:
            raise WinnyValidationError(
                f"qty {intent.qty} < min_qty {spec.min_qty} for {intent.symbol.canonical()}"
            )

        oid = self._mint_order_id()
        with self._lock:
            self._intents[oid] = intent
            if intent.order_type is OrderType.MARKET:
                self._fill_market(oid, intent, spec)
            else:
                # LIMIT — record as PENDING; tick() will fill when price crosses
                self._orders[oid] = OrderState(
                    broker_order_id=oid,
                    intent_id=intent.intent_id,
                    status=OrderStatus.PENDING,
                    filled_qty=Decimal("0"),
                    avg_fill_price=None,
                    last_event_ts=_utcnow(),
                    raw_broker_state={"venue": "paper", "order_type": intent.order_type.value},
                )
        return oid

    def cancel(self, broker_order_id: BrokerOrderId) -> None:
        with self._lock:
            state = self._orders.get(broker_order_id)
            if state is None:
                raise UnknownOrderError(f"no order {broker_order_id!r} on paper broker")
            if state.status in (
                OrderStatus.FILLED,
                OrderStatus.CANCELLED,
                OrderStatus.REJECTED,
            ):
                return  # idempotent no-op on terminal states
            self._orders[broker_order_id] = state.model_copy(
                update={
                    "status": OrderStatus.CANCELLED,
                    "last_event_ts": _utcnow(),
                }
            )

    def get_order(self, broker_order_id: BrokerOrderId) -> OrderState:
        state = self._orders.get(broker_order_id)
        if state is None:
            raise UnknownOrderError(f"no order {broker_order_id!r} on paper broker")
        return state

    # ===================================================================
    # Paper-specific helpers (engine calls these)
    # ===================================================================

    def tick(self, symbol: Symbol, bar: Bar) -> list[BrokerOrderId]:
        """Update last-known price from a bar and fire any pending LIMITs.

        Returns the list of order ids that filled on this tick.
        """
        with self._lock:
            self._last_close[symbol] = Decimal(str(bar.close))
            self._last_bar_ts[symbol] = bar.ts
            filled: list[BrokerOrderId] = []
            for oid, state in list(self._orders.items()):
                if state.status is not OrderStatus.PENDING:
                    continue
                intent = self._intents[oid]
                if intent.symbol != symbol:
                    continue
                if self._limit_crosses(intent, bar):
                    spec = self._market_specs.get(symbol)
                    if spec is None:  # pragma: no cover — registered at submit time
                        continue
                    assert intent.limit_price is not None
                    # Fill at the limit price (or better — but paper is conservative
                    # and fills at the limit exactly, never inside the spread).
                    self._fill_at_price(oid, intent, spec, intent.limit_price)
                    filled.append(oid)
            return filled

    def recent_fills(self, since_index: int = 0) -> list[Fill]:
        """All fills with index >= since_index. Useful for tests + engine reconciliation."""
        return self._fills[since_index:]

    # ===================================================================
    # Internals
    # ===================================================================

    def _mint_order_id(self) -> BrokerOrderId:
        with self._lock:
            oid = BrokerOrderId(f"paper-{self._next_id:08d}")
            self._next_id += 1
        return oid

    def _fill_market(self, oid: BrokerOrderId, intent: OrderIntent, spec: MarketSpec) -> None:
        """MARKET path: must have a last_close to slip from."""
        ref = self._last_close.get(intent.symbol)
        if ref is None:
            raise WinnyValidationError(
                f"no reference price for {intent.symbol.canonical()}; "
                "call broker.tick(symbol, bar) before submit() in paper mode"
            )
        fill_price = self._slip.apply(intent.symbol, intent.side, intent.qty, ref)
        self._fill_at_price(oid, intent, spec, fill_price)

    def _fill_at_price(
        self,
        oid: BrokerOrderId,
        intent: OrderIntent,
        spec: MarketSpec,
        fill_price: Decimal,
    ) -> None:
        """Common fill path used by MARKET (immediate) and LIMIT (on crossing tick)."""
        # Validate balance / position
        notional = (intent.qty * fill_price).quantize(_FEE_QUANTIZE)
        fee_quote = self._fees.quote(
            intent.symbol, intent.side, intent.qty, notional, liquidity="taker"
        )
        total_fees = fee_quote.total

        quote_ccy = _quote_currency(intent.symbol)

        if intent.side is Side.BUY:
            cost = (notional + total_fees).quantize(_FEE_QUANTIZE)
            current = self._balances.get(quote_ccy, Decimal("0"))
            if current < cost:
                self._reject(oid, intent, f"insufficient {quote_ccy} balance: {current} < {cost}")
                raise InsufficientBalanceError(
                    f"need {cost} {quote_ccy}, have {current} for {intent.symbol.canonical()}"
                )
            self._balances[quote_ccy] = current - cost
            self._apply_buy(intent.symbol, intent.qty, fill_price)
        else:  # SELL
            pos = self._positions.get(intent.symbol)
            if pos is None or pos.qty < intent.qty:
                have = pos.qty if pos else Decimal("0")
                self._reject(
                    oid,
                    intent,
                    f"insufficient long position for SELL: have {have}, want {intent.qty}",
                )
                raise InsufficientPositionError(
                    f"cannot SELL {intent.qty} {intent.symbol.canonical()}: have {have} "
                    f"(short selling not supported in paper v1)"
                )
            proceeds = (notional - total_fees).quantize(_FEE_QUANTIZE)
            self._balances[quote_ccy] = self._balances.get(quote_ccy, Decimal("0")) + proceeds
            self._apply_sell(intent.symbol, intent.qty, fill_price)

        # Record fill + final OrderState
        fill = Fill(
            broker_order_id=oid,
            ts=_utcnow(),
            qty=intent.qty,
            price=fill_price,
            fees=total_fees,
            liquidity="TAKER" if intent.order_type is OrderType.MARKET else "MAKER",
        )
        self._fills.append(fill)
        self._orders[oid] = OrderState(
            broker_order_id=oid,
            intent_id=intent.intent_id,
            status=OrderStatus.FILLED,
            filled_qty=intent.qty,
            avg_fill_price=fill_price,
            last_event_ts=fill.ts,
            raw_broker_state={
                "venue": "paper",
                "order_type": intent.order_type.value,
                "tif": intent.time_in_force.value
                if intent.time_in_force
                else TimeInForce.DAY.value,
                "fee_total": str(total_fees),
            },
        )

    def _reject(self, oid: BrokerOrderId, intent: OrderIntent, reason: str) -> None:
        self._orders[oid] = OrderState(
            broker_order_id=oid,
            intent_id=intent.intent_id,
            status=OrderStatus.REJECTED,
            filled_qty=Decimal("0"),
            avg_fill_price=None,
            last_event_ts=_utcnow(),
            raw_broker_state={"venue": "paper", "reject_reason": reason},
        )

    def _apply_buy(self, symbol: Symbol, qty: Decimal, price: Decimal) -> None:
        pos = self._positions.get(symbol)
        if pos is None:
            self._positions[symbol] = Position(
                symbol=symbol,
                qty=qty,
                avg_entry_price=price,
                unrealized_pnl=Decimal("0"),
                realized_pnl=Decimal("0"),
            )
            return
        # Weighted average of existing + new
        new_qty = pos.qty + qty
        new_avg = ((pos.avg_entry_price * pos.qty) + (price * qty)) / new_qty
        self._positions[symbol] = pos.model_copy(
            update={
                "qty": new_qty,
                "avg_entry_price": new_avg.quantize(Decimal("0.00000001")),
            }
        )

    def _apply_sell(self, symbol: Symbol, qty: Decimal, price: Decimal) -> None:
        pos = self._positions[symbol]  # caller validated existence + sufficiency
        realized = ((price - pos.avg_entry_price) * qty).quantize(Decimal("0.0001"))
        remaining = pos.qty - qty
        if remaining == 0:
            del self._positions[symbol]
        else:
            self._positions[symbol] = pos.model_copy(
                update={
                    "qty": remaining,
                    "realized_pnl": pos.realized_pnl + realized,
                }
            )

    @staticmethod
    def _limit_crosses(intent: OrderIntent, bar: Bar) -> bool:
        """True if a LIMIT order should fill on this bar."""
        if intent.limit_price is None:
            return False
        if intent.side is Side.BUY:
            return Decimal(str(bar.low)) <= intent.limit_price
        return Decimal(str(bar.high)) >= intent.limit_price


# ---------- helpers ----------


def _quote_currency(symbol: Symbol) -> Currency:
    """Best-effort currency derivation from a Symbol.

    For CR pairs, use Symbol.quote (USDT, USDC, ...). For EQ/FX/FU/OP we
    default to USD (the dominant quote for our v1 markets). Brokers MAY
    register MarketSpec.quote_currency in a future spec rev to override.
    """
    if symbol.quote is not None:
        return Currency(symbol.quote)
    return Currency("USD")


def _utcnow() -> datetime:
    return datetime.now(UTC)
