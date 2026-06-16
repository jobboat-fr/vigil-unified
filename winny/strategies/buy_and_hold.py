"""BuyAndHold — the simplest possible strategy.

Per SPECS.md §15.11 + the promotion-gate baseline (§10.1): every backtest
result should be compared against buy-and-hold on the same period.

Behavior:
  - On the first bar where there's no open position, emit enter_long=1.
  - Never emit exit_long (the engine force-closes at end of backtest).
  - Disables stoploss + minimal_roi by setting stoploss to -100% and
    minimal_roi to None — the position survives drawdowns and rallies.

Used as:
  1. The reference baseline for any strategy promotion gate (§10.1):
     a "winning" strategy must outperform buy-and-hold on the same period
     net of fees + slippage.
  2. The fixture for the AC2 known-answer test: backtesting buy-and-hold
     on SPY 2020-2024 should reproduce SPY total return ± fees.
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl

from winny.engine.strategy import BarMeta, WinnyStrategy


class BuyAndHold(WinnyStrategy):
    """Buy on the first eligible bar, hold forever.

    The engine handles the "already in position → skip duplicate entry" logic,
    so we can safely emit enter_long=1 on every bar. The first one wins.
    """

    INTERFACE_VERSION: int = 1
    timeframe: str = "1d"
    startup_candle_count: int = 1  # no warm-up needed
    stoploss: Decimal = Decimal("-1.00")  # -100% = effectively disabled
    minimal_roi: dict[int, Decimal] | None = None  # no take-profit
    can_short: bool = False

    def populate_indicators(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        # No indicators — pure price-driven baseline.
        return df

    def populate_entry_trend(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        # Always signal "want to be long". The engine's max_open_trades + the
        # "already in position" check prevent duplicate entries.
        return df.with_columns(pl.lit(1, dtype=pl.Int8).alias("enter_long"))

    def populate_exit_trend(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        # Never signal an exit — engine force-closes at end of backtest.
        return df.with_columns(pl.lit(0, dtype=pl.Int8).alias("exit_long"))
