"""TimesfmMomentum — TimesFM-forecast-driven momentum strategy.

Per SPECS.md §15.11 + §14.3.1 (tiered analysis): the cheapest "real" use of
TimesFM is to detect when the model's quantile band excludes the current
price, which is a high-confidence directional signal.

Signal logic:
  - For the current bar, look up the pre-computed forecast band
    (median, lower, upper quantiles) for `meta.symbol` at `meta.ts`.
  - LONG entry: forecast_lower > current_close * (1 + entry_threshold)
              → "the model is confident price will rise at least entry_threshold"
  - LONG exit:  forecast_upper < current_close * (1 - exit_threshold)
              → "the model is confident price will fall"
  - SHORT entry/exit symmetric (only when can_short=True).

Forecasts are PRE-COMPUTED and passed via constructor. Strategies don't do
I/O during populate_* by contract — production usage wraps this strategy
with a ForecastInjector that batches mcp-timesfm.forecast_batch() calls
before the engine loop iterates bars.

The strategy MUST work with missing forecasts (warm-up bars, cache misses):
it simply emits no signal for those bars.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import polars as pl

from winny.common.symbols import Symbol
from winny.engine.strategy import BarMeta, WinnyStrategy


@dataclass(frozen=True, slots=True)
class ForecastBand:
    """One quantile forecast point. Median + lower/upper confidence bands.

    Conventions:
      - `median` is the central tendency (e.g. 0.5 quantile).
      - `lower` is the bottom of the confidence band (e.g. 0.1 quantile).
      - `upper` is the top (e.g. 0.9 quantile).
      - lower <= median <= upper enforced at construction.
    """

    median: Decimal
    lower: Decimal
    upper: Decimal

    def __post_init__(self) -> None:
        if not (self.lower <= self.median <= self.upper):
            raise ValueError(
                f"ForecastBand requires lower<=median<=upper, "
                f"got lower={self.lower} median={self.median} upper={self.upper}"
            )


# Per-symbol map of ts → forecast. Populated by the forecast injector
# before the engine loop runs.
ForecastsBySymbol = dict[Symbol, dict[datetime, ForecastBand]]


class TimesfmMomentum(WinnyStrategy):
    """High-confidence directional momentum from TimesFM quantile forecasts.

    Enter long only when the lower forecast quantile sits above the current
    price by more than `entry_threshold` — a structurally confident signal,
    not a point-estimate guess. Same for shorts in the opposite direction.
    """

    INTERFACE_VERSION: int = 1
    timeframe: str = "1h"
    startup_candle_count: int = 1  # forecast is pre-computed; no in-strategy warm-up
    stoploss: Decimal = Decimal("-0.05")
    minimal_roi: dict[int, Decimal] | None = None
    can_short: bool = False

    # Tunable parameters
    entry_threshold: Decimal = Decimal("0.01")  # 1% expected upside required
    exit_threshold: Decimal = Decimal("0.005")  # 0.5% downside triggers exit

    def __init__(
        self,
        forecasts: ForecastsBySymbol | None = None,
        *,
        entry_threshold: Decimal | None = None,
        exit_threshold: Decimal | None = None,
    ) -> None:
        """Construct with a pre-computed forecast map.

        Args:
            forecasts: per-symbol map of ts → ForecastBand. Missing entries
                mean "no signal for that bar" (warm-up or cache miss).
            entry_threshold: override class-level entry threshold.
            exit_threshold: override class-level exit threshold.
        """
        self._forecasts: ForecastsBySymbol = forecasts or {}
        if entry_threshold is not None:
            self.entry_threshold = entry_threshold
        if exit_threshold is not None:
            self.exit_threshold = exit_threshold

    def populate_indicators(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        """Inject forecast columns for the current bar.

        Adds three columns: `forecast_median`, `forecast_lower`, `forecast_upper`.
        Rows without a corresponding forecast get NULL — the entry/exit
        populators treat NULLs as "no signal".
        """
        sym_map = self._forecasts.get(meta.symbol, {})
        if not sym_map:
            # No forecasts at all — populate NULL columns so the schema is stable
            return df.with_columns(
                pl.lit(None, dtype=pl.Float64).alias("forecast_median"),
                pl.lit(None, dtype=pl.Float64).alias("forecast_lower"),
                pl.lit(None, dtype=pl.Float64).alias("forecast_upper"),
            )

        # Build a small lookup DataFrame and left-join on ts.
        ts_list = list(sym_map.keys())
        forecast_df = pl.DataFrame(
            {
                "ts": ts_list,
                "forecast_median": [float(sym_map[t].median) for t in ts_list],
                "forecast_lower": [float(sym_map[t].lower) for t in ts_list],
                "forecast_upper": [float(sym_map[t].upper) for t in ts_list],
            }
        )
        return df.join(forecast_df, on="ts", how="left")

    def populate_entry_trend(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        """LONG: enter when forecast_lower > close * (1 + entry_threshold).

        The strict inequality on the LOWER band (not the median) is the
        "confidence" filter — we only enter when even the pessimistic
        forecast still beats our threshold.
        """
        entry_mult = 1.0 + float(self.entry_threshold)
        cond_long = (pl.col("forecast_lower").is_not_null()) & (
            pl.col("forecast_lower") > pl.col("close") * entry_mult
        )
        out = df.with_columns(cond_long.cast(pl.Int8).alias("enter_long"))

        if self.can_short:
            exit_mult_short = 1.0 - float(self.entry_threshold)
            cond_short = (pl.col("forecast_upper").is_not_null()) & (
                pl.col("forecast_upper") < pl.col("close") * exit_mult_short
            )
            out = out.with_columns(cond_short.cast(pl.Int8).alias("enter_short"))

        return out

    def populate_exit_trend(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        """LONG exit: forecast_upper < close * (1 - exit_threshold).

        Mirror of entry: even the optimistic forecast no longer beats our
        downside threshold → take the loss/profit and step aside.
        """
        exit_mult_long = 1.0 - float(self.exit_threshold)
        cond_exit_long = (pl.col("forecast_upper").is_not_null()) & (
            pl.col("forecast_upper") < pl.col("close") * exit_mult_long
        )
        out = df.with_columns(cond_exit_long.cast(pl.Int8).alias("exit_long"))

        if self.can_short:
            exit_mult_short = 1.0 + float(self.exit_threshold)
            cond_exit_short = (pl.col("forecast_lower").is_not_null()) & (
                pl.col("forecast_lower") > pl.col("close") * exit_mult_short
            )
            out = out.with_columns(cond_exit_short.cast(pl.Int8).alias("exit_short"))

        return out
