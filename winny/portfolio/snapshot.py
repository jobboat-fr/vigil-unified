"""Portfolio snapshot value objects — the wire shape for get_portfolio.

These are pure data containers: no I/O, no mutation, no side effects.
They flow through `to_jsonable` to become JSON over the MCP wire.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from winny.common.ids import Currency
from winny.common.symbols import Symbol


@dataclass(frozen=True, slots=True)
class PositionWithMTM:
    """A position augmented with mark-to-market valuation."""

    symbol: Symbol
    qty: Decimal
    avg_entry_price: Decimal
    current_price: Decimal | None  # None if no price provided
    market_value: Decimal  # qty * current_price (or Decimal("0") if no price)
    unrealized_pnl: Decimal  # (current_price - avg_entry) * qty
    unrealized_pnl_pct: Decimal  # pnl / abs(avg_entry * qty) * 100


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    """Complete portfolio state at a point in time."""

    asof: datetime
    balances: dict[Currency, Decimal]  # cash per currency
    positions: list[PositionWithMTM]
    nav: Decimal  # cash + sum(market_value)
    nav_currency: Currency  # the reporting currency
    open_orders_count: int
    unpriced_positions: list[Symbol]  # positions with no current_price supplied


def build_snapshot(
    *,
    balances: dict[Currency, Decimal],
    positions: list[tuple[Symbol, Decimal, Decimal]],  # (symbol, qty, avg_entry)
    current_prices: dict[str, Decimal] | None,
    nav_currency: Currency,
    open_orders_count: int,
    asof: datetime,
) -> PortfolioSnapshot:
    """Construct a PortfolioSnapshot with mark-to-market calculations.

    Parameters
    ----------
    balances : dict mapping Currency -> amount
    positions : list of (symbol, qty, avg_entry_price) tuples
    current_prices : dict mapping symbol.canonical() -> current price, or None
    nav_currency : currency for NAV reporting
    open_orders_count : number of pending orders
    asof : snapshot timestamp
    """
    prices = current_prices or {}
    mtm_positions: list[PositionWithMTM] = []
    unpriced: list[Symbol] = []
    total_market_value = Decimal("0")

    for symbol, qty, avg_entry in positions:
        canonical = symbol.canonical()
        price_str = prices.get(canonical)

        if price_str is not None:
            current_price = Decimal(str(price_str))
            market_value = qty * current_price
            unrealized_pnl = (current_price - avg_entry) * qty
            cost_basis = abs(avg_entry * qty)
            unrealized_pnl_pct = (
                (unrealized_pnl / cost_basis * Decimal("100"))
                if cost_basis > 0
                else Decimal("0")
            )
            total_market_value += market_value
        else:
            current_price = None
            market_value = Decimal("0")
            unrealized_pnl = Decimal("0")
            unrealized_pnl_pct = Decimal("0")
            unpriced.append(symbol)

        mtm_positions.append(
            PositionWithMTM(
                symbol=symbol,
                qty=qty,
                avg_entry_price=avg_entry,
                current_price=current_price,
                market_value=market_value,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_pct=unrealized_pnl_pct,
            )
        )

    # NAV = sum(balances in nav_currency) + sum(market_value)
    cash_total = balances.get(nav_currency, Decimal("0"))
    nav = cash_total + total_market_value

    return PortfolioSnapshot(
        asof=asof,
        balances=balances,
        positions=mtm_positions,
        nav=nav,
        nav_currency=nav_currency,
        open_orders_count=open_orders_count,
        unpriced_positions=unpriced,
    )
