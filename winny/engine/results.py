"""Backtest and dry-run result types — PR #11, §3.3.4.

BacktestReport is the primary output of `engine.run()` in BACKTEST mode.
It carries all trade records, metrics, and equity curve data needed for
performance evaluation and strategy promotion gates (§10.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from winny.common.ids import BrokerOrderId
from winny.common.symbols import Symbol
from winny.common.types import Side


@dataclass(frozen=True, slots=True)
class TradeRecord:
    """One completed round-trip trade (entry + exit).

    Open trades at backtest end have exit_ts=None and are marked
    as forced-closed at the last bar's close in the report summary.
    """

    symbol: Symbol
    side: Side
    entry_price: Decimal
    exit_price: Decimal | None
    qty: Decimal
    entry_ts: datetime
    exit_ts: datetime | None
    entry_tag: str | None = None
    exit_reason: str | None = None  # "signal", "stoploss", "roi", "end_of_backtest"
    pnl: Decimal = Decimal("0")
    pnl_pct: Decimal = Decimal("0")
    fees_paid: Decimal = Decimal("0")
    duration: timedelta | None = None
    entry_order_id: BrokerOrderId | None = None
    exit_order_id: BrokerOrderId | None = None


@dataclass(frozen=True, slots=True)
class EquityPoint:
    """One point on the equity curve (end-of-bar NAV snapshot)."""

    ts: datetime
    nav: Decimal  # cash + mark-to-market positions
    cash: Decimal
    positions_value: Decimal
    drawdown_pct: Decimal = Decimal("0")  # from peak NAV


@dataclass(slots=True)
class BacktestMetrics:
    """Aggregate performance metrics for a completed backtest."""

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: Decimal = Decimal("0")
    avg_profit_pct: Decimal = Decimal("0")
    max_drawdown_pct: Decimal = Decimal("0")
    sharpe_ratio: Decimal | None = None  # None if < 2 trades
    profit_factor: Decimal | None = None  # gross_profit / gross_loss
    total_pnl: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")
    avg_trade_duration: timedelta | None = None
    max_open_trades: int = 0
    final_nav: Decimal = Decimal("0")
    initial_nav: Decimal = Decimal("0")
    return_pct: Decimal = Decimal("0")
    bars_processed: int = 0
    symbols_traded: int = 0
    wall_time_seconds: float = 0.0


@dataclass(slots=True)
class BacktestReport:
    """Full output of a backtest run.

    Contains everything needed to evaluate and compare strategies:
    trade log, equity curve, metrics, and config provenance.
    """

    strategy_name: str
    timeframe: str
    start: datetime
    end: datetime
    initial_capital: Decimal
    symbols: list[Symbol] = field(default_factory=list)
    trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    metrics: BacktestMetrics = field(default_factory=BacktestMetrics)
    open_trades_at_end: int = 0
    config_hash: str = ""  # sha256 of engine config for reproducibility
