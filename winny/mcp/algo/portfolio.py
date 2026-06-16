"""get_portfolio + get_open_orders tool handlers.

These are pure read-through tools:
  - get_portfolio: reads PortfolioStore, builds a PortfolioSnapshot with
    mark-to-market, returns the JSON-serialized snapshot.
  - get_open_orders: returns list of open orders from PortfolioStore.

Neither tool mutates state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from winny.common.ids import Currency
from winny.common.symbols import Symbol
from winny.portfolio.snapshot import build_snapshot
from winny.portfolio.store import PortfolioStore

# ===================================================================
# get_portfolio
# ===================================================================


async def get_portfolio(
    current_prices: dict[str, str] | None = None,
    nav_currency: str = "USD",
    portfolio_db_path: str | None = None,
) -> dict[str, Any]:
    """Return a full PortfolioSnapshot with mark-to-market.

    Parameters
    ----------
    current_prices : dict mapping canonical symbol string -> price string.
        Used for mark-to-market valuation. Positions without a price are
        flagged in `unpriced_positions`.
    nav_currency : reporting currency (default USD).
    portfolio_db_path : override for PortfolioStore path (testing).
    """
    store = PortfolioStore(db_path=portfolio_db_path) if portfolio_db_path else PortfolioStore()
    try:
        balances = store.get_all_balances()
        positions_raw = store.get_all_positions()
        open_orders_count = store._count_open_orders()
    finally:
        store.close()

    # Convert stored positions for snapshot builder
    positions_for_snap: list[tuple[Symbol, Decimal, Decimal]] = []
    for p in positions_raw:
        try:
            sym = Symbol.parse(p.symbol)
        except Exception:
            # Skip unparseable symbols rather than crash the read tool
            continue
        positions_for_snap.append((sym, p.qty, p.avg_entry_price))

    # Build price map
    prices: dict[str, Decimal] | None = None
    if current_prices:
        prices = {k: Decimal(v) for k, v in current_prices.items()}

    nav_cur = Currency(nav_currency)
    snap = build_snapshot(
        balances=balances,
        positions=positions_for_snap,
        current_prices=prices,
        nav_currency=nav_cur,
        open_orders_count=open_orders_count,
        asof=datetime.now(UTC),
    )

    # Serialize snapshot
    return {
        "asof": snap.asof.isoformat(),
        "nav": str(snap.nav),
        "nav_currency": str(snap.nav_currency),
        "balances": {str(k): str(v) for k, v in snap.balances.items()},
        "positions": [
            {
                "symbol": pos.symbol.canonical(),
                "qty": str(pos.qty),
                "avg_entry_price": str(pos.avg_entry_price),
                "current_price": str(pos.current_price) if pos.current_price is not None else None,
                "market_value": str(pos.market_value),
                "unrealized_pnl": str(pos.unrealized_pnl),
                "unrealized_pnl_pct": str(pos.unrealized_pnl_pct),
            }
            for pos in snap.positions
        ],
        "open_orders_count": snap.open_orders_count,
        "unpriced_positions": [s.canonical() for s in snap.unpriced_positions],
    }


# ===================================================================
# get_open_orders
# ===================================================================


async def get_open_orders(
    broker: str | None = None,
    symbol: str | None = None,
    portfolio_db_path: str | None = None,
) -> dict[str, Any]:
    """Return open orders from PortfolioStore.

    Parameters
    ----------
    broker : optional filter by broker name (e.g. 'paper', 'ibkr').
    symbol : optional canonical symbol string to filter by.
    portfolio_db_path : override for PortfolioStore path (testing).
    """
    store = PortfolioStore(db_path=portfolio_db_path) if portfolio_db_path else PortfolioStore()
    try:
        sym: Symbol | None = None
        if symbol:
            try:
                sym = Symbol.parse(symbol)
            except Exception:
                return {"error": f"Cannot parse symbol {symbol!r}"}

        orders = store.get_open_orders(broker=broker, symbol=sym)
    finally:
        store.close()

    return {
        "count": len(orders),
        "orders": [
            {
                "broker_order_id": o.broker_order_id,
                "intent_id": o.intent_id,
                "decision_id": o.decision_id,
                "symbol": o.symbol,
                "side": o.side,
                "qty": str(o.qty),
                "order_type": o.order_type,
                "limit_price": str(o.limit_price) if o.limit_price is not None else None,
                "stop_price": str(o.stop_price) if o.stop_price is not None else None,
                "status": o.status,
                "submitted_at": o.submitted_at,
                "broker": o.broker,
            }
            for o in orders
        ],
    }
