"""SMA Crossover — minimal strategy for engine testing.

Uses a fast/slow simple moving average crossover. Not intended for live
trading — this exists to exercise the full engine loop in tests.
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl

from winny.engine.strategy import BarMeta, WinnyStrategy


class SmaCrossover(WinnyStrategy):
    """Simple moving average crossover strategy.

    Enter long when fast SMA crosses above slow SMA.
    Exit long when fast SMA crosses below slow SMA.
    """

    INTERFACE_VERSION: int = 1
    timeframe: str = "1h"
    startup_candle_count: int = 50
    stoploss: Decimal = Decimal("-0.05")
    minimal_roi: dict[int, Decimal] | None = {0: Decimal("0.03"), 60: Decimal("0.01")}  # noqa: RUF012
    can_short: bool = False

    # Strategy parameters
    fast_period: int = 10
    slow_period: int = 30

    def populate_indicators(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        return df.with_columns(
            pl.col("close").rolling_mean(window_size=self.fast_period).alias("sma_fast"),
            pl.col("close").rolling_mean(window_size=self.slow_period).alias("sma_slow"),
        )

    def populate_entry_trend(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        return df.with_columns(
            (
                (pl.col("sma_fast") > pl.col("sma_slow"))
                & (pl.col("sma_fast").shift(1) <= pl.col("sma_slow").shift(1))
            )
            .cast(pl.Int8)
            .alias("enter_long")
        )

    def populate_exit_trend(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        return df.with_columns(
            (
                (pl.col("sma_fast") < pl.col("sma_slow"))
                & (pl.col("sma_fast").shift(1) >= pl.col("sma_slow").shift(1))
            )
            .cast(pl.Int8)
            .alias("exit_long")
        )
