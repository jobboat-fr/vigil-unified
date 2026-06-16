"""Liquidity Microstructure — order-flow strategy with live L2 confirmation.

Two layers, mirroring services/liquidity_api/README.md:

1. **Bar layer (backtestable, deterministic).** OHLCV proxies of the same
   microstructure concepts the liquidity service computes from L2 books:

   - *sweep proxy*  — volume z-score thrust + close breaking the prior bar's
     extreme (aggressive market orders eating the book show up as exactly
     this signature at bar granularity).
   - *pressure proxy* — EMA of the close's position within the bar range,
     centered to [-1, +1] (bar-level analogue of bid/ask depth imbalance).

   Entries/exits come ONLY from this layer, so backtests and walk-forward
   runs are reproducible without an order-book history.

2. **Live layer (the actual service).** `confirm_trade_entry` queries the
   standalone liquidity API (`/liquidity/{symbol}/signal`) as a last-mile
   veto — the README's integration path #3:

   - veto when composite liquidity label is "poor" (don't trade thin books)
   - veto when the live book signal opposes the trade with strength >= 0.5
   - veto when the spread assessment is "wide" (makers are scared)

   The service is advisory context, never a sole trigger (walls are
   spoofable) — so an unreachable/stale service FAILS OPEN: the bar-layer
   signal proceeds and we log the miss.

Config (env):
    LIQUIDITY_API_URL   base URL of the service (default http://127.0.0.1:8600)
    LIQ_API_KEY         optional shared key, sent as X-Liquidity-Key

Select via the standard loader spec:
    winny.strategies.liquidity_microstructure:LiquidityMicrostructure
"""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from typing import Any

import polars as pl

from winny.engine.strategy import BarMeta, WinnyStrategy
from winny.common.symbols import Symbol
from winny.common.types import Side


def _service_base() -> str:
    return (os.environ.get("LIQUIDITY_API_URL") or "http://127.0.0.1:8600").rstrip("/")


def _service_symbol(symbol: Symbol) -> str:
    """Map canonical Symbol → the service's BTC-USDT path form."""
    quote = symbol.quote or "USDT"
    return f"{symbol.base}-{quote}"


class LiquidityMicrostructure(WinnyStrategy):
    """Sweep-momentum entries with live order-book liquidity confirmation."""

    INTERFACE_VERSION: int = 1
    timeframe: str = "1h"
    startup_candle_count: int = 60
    stoploss: Decimal = Decimal("-0.04")
    minimal_roi: dict[int, Decimal] | None = {  # noqa: RUF012
        0: Decimal("0.03"),
        120: Decimal("0.015"),
        360: Decimal("0.005"),
    }
    can_short: bool = False

    # ── Bar-layer parameters ────────────────────────────────────────────
    vol_window: int = 48
    """Bars in the rolling volume baseline (48 x 1h = 2 days)."""

    sweep_sigma: float = 2.5
    """Volume z-score above which a bar counts as a sweep-proxy thrust."""

    pressure_span: int = 12
    """EMA span for the close-position-in-range pressure proxy."""

    pressure_entry: float = 0.20
    """Minimum centered pressure ([-1, 1]) to allow a long entry."""

    # ── Live-layer parameters ───────────────────────────────────────────
    veto_strength: float = 0.5
    """Live signal strength at/above which an opposing book direction vetoes."""

    service_timeout_s: float = 1.5
    """HTTP budget for the confirmation call — entries shouldn't stall."""

    # ===================================================================
    # Bar layer
    # ===================================================================

    def populate_indicators(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        vol_mean = pl.col("volume").rolling_mean(window_size=self.vol_window)
        vol_std = pl.col("volume").rolling_std(window_size=self.vol_window)
        bar_range = pl.col("high") - pl.col("low")

        return df.with_columns(
            # Volume thrust: how anomalous is this bar's activity?
            ((pl.col("volume") - vol_mean) / vol_std).fill_nan(0.0).alias("liq_vol_z"),
            # Close position in range, centered to [-1, +1]: bar-level
            # imbalance proxy (close at high = +1 buyers dominated).
            pl.when(bar_range > 0)
            .then((pl.col("close") - pl.col("low")) / bar_range * 2.0 - 1.0)
            .otherwise(0.0)
            .ewm_mean(span=self.pressure_span)
            .alias("liq_pressure"),
        ).with_columns(
            # Sweep proxies: anomalous volume + price clearing the prior
            # bar's extreme in one direction.
            (
                (pl.col("liq_vol_z") > self.sweep_sigma)
                & (pl.col("close") > pl.col("high").shift(1))
            )
            .cast(pl.Int8)
            .alias("liq_sweep_up"),
            (
                (pl.col("liq_vol_z") > self.sweep_sigma)
                & (pl.col("close") < pl.col("low").shift(1))
            )
            .cast(pl.Int8)
            .alias("liq_sweep_down"),
        )

    def populate_entry_trend(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        return df.with_columns(
            (
                (pl.col("liq_sweep_up") == 1)
                & (pl.col("liq_pressure") > self.pressure_entry)
            )
            .cast(pl.Int8)
            .alias("enter_long"),
            pl.lit("liq_sweep_momentum").alias("enter_tag"),
        )

    def populate_exit_trend(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        return df.with_columns(
            (
                (pl.col("liq_sweep_down") == 1)
                | (pl.col("liq_pressure") < 0.0)
            )
            .cast(pl.Int8)
            .alias("exit_long"),
            pl.lit("liq_pressure_flip").alias("exit_tag"),
        )

    # ===================================================================
    # Live layer — last-mile veto against the real order book
    # ===================================================================

    def confirm_trade_entry(
        self,
        symbol: Symbol,
        side: Side,
        qty: Decimal,
        rate: Decimal,
        current_ts: datetime,
        enter_tag: str | None,
        **kwargs: Any,
    ) -> bool:
        signal = self._fetch_live_signal(symbol)
        if signal is None:
            # Service down or symbol unwatched — advisory layer fails open.
            return True

        components = signal.get("components") or {}

        # Thin book: composite liquidity too poor to absorb our entry.
        if components.get("liquidity_label") == "poor":
            return False

        # Makers pulled back: spread far wider than its volatility-fair value.
        if components.get("spread_assessment") == "wide":
            return False

        # Book actively leaning against us with conviction.
        direction = signal.get("direction")
        strength = float(signal.get("strength") or 0.0)
        opposing = (side == Side.BUY and direction == "bearish") or (
            side == Side.SELL and direction == "bullish"
        )
        if opposing and strength >= self.veto_strength:
            return False

        return True

    def _fetch_live_signal(self, symbol: Symbol) -> dict[str, Any] | None:
        """GET /liquidity/{symbol}/signal — None on any failure (fail-open)."""
        try:
            import httpx

            headers = {}
            api_key = os.environ.get("LIQ_API_KEY", "")
            if api_key:
                headers["X-Liquidity-Key"] = api_key
            url = f"{_service_base()}/liquidity/{_service_symbol(symbol)}/signal"
            resp = httpx.get(url, headers=headers, timeout=self.service_timeout_s)
            if resp.status_code != 200:
                return None
            data = resp.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None
