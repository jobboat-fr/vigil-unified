"""MCP tool handlers for mcp-timesfm — §3.1.3.

Two tools:
    forecast_series  — raw numeric input, no symbol semantics
    forecast_symbol  — convenience: pulls history via data layer, forecasts

Each tool is an async function that the MCP server dispatches to.
They are registered with the McpServer in the server entry point.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import structlog

from winny.common.errors import WinnyValidationError
from winny.common.signals_store import fetch_forecasts
from winny.common.symbols import Symbol
from winny.common.types import ForecastResult, SymbolForecast
from winny.data.factory import create_data_provider
from winny.data.providers.routing import RoutingProvider

from .model import (
    DEFAULT_QUANTILE_LEVELS,
    InvalidHorizonError,
    InvalidInputError,
    TimesFMModel,
)

logger = structlog.get_logger()

# Module-level singletons (initialized on first call)
_model: TimesFMModel | None = None
_data_provider: RoutingProvider | None = None


def get_model() -> TimesFMModel:
    """Get or create the model singleton."""
    global _model
    if _model is None:
        _model = TimesFMModel()
    return _model


def get_data_provider() -> RoutingProvider:
    """Get or create the data provider singleton."""
    global _data_provider
    if _data_provider is None:
        _data_provider = create_data_provider()
    return _data_provider


def _statistical_forecast(
    closes: list[float],
    horizon: int,
    q_levels: tuple[float, ...],
) -> tuple[list[list[float]], list[list[list[float]]], dict[str, Any]]:
    """Drift + volatility forecast — the keyless/torchless fallback.

    Used when the TimesFM package (torch) isn't installed on the host. A
    deliberately simple, honest model: point path extrapolates the mean log
    return of the recent window; quantile bands widen with sqrt(h) scaled by
    the realized per-bar log-return volatility (Gaussian quantiles). The
    output is clearly labeled so the agent never presents it as TimesFM.

    Returns (point_rows, quantile_rows, metadata) shaped exactly like the
    model output: point [batch][horizon], quantiles [batch][horizon][q].
    """
    import math
    from statistics import NormalDist, fmean, stdev

    window = closes[-min(len(closes), 256):]
    log_rets = [
        math.log(b / a)
        for a, b in zip(window, window[1:])
        if a > 0 and b > 0
    ]
    drift = fmean(log_rets) if log_rets else 0.0
    sigma = stdev(log_rets) if len(log_rets) >= 2 else 0.0
    last = float(closes[-1])

    nd = NormalDist()
    z = [nd.inv_cdf(min(max(q, 1e-6), 1 - 1e-6)) for q in q_levels]

    point_row: list[float] = []
    quant_row: list[list[float]] = []
    for h in range(1, horizon + 1):
        mu = last * math.exp(drift * h)
        spread = sigma * math.sqrt(h)
        point_row.append(mu)
        quant_row.append([mu * math.exp(zq * spread) for zq in z])

    meta = {
        "model_id": "statistical-fallback/drift-vol",
        "device": "cpu",
        "note": (
            "TimesFM (torch) is not installed on this host; this is a "
            "transparent drift+volatility extrapolation from real exchange "
            "bars — treat the bands as rough, not model-grade."
        ),
        "drift_per_bar": drift,
        "sigma_per_bar": sigma,
    }
    return [point_row], [quant_row], meta


async def forecast_series(
    inputs: list[list[float]],
    horizon: int = 24,
    quantile_levels: list[float] | None = None,
) -> dict[str, Any]:
    """Raw numeric forecast — §3.1.3 forecast_series.

    Asset-agnostic: input is a batch of numeric series, output is quantile forecasts.
    No knowledge of symbols, exchanges, or trading.

    Args:
        inputs:          B series of variable length, each ≤ 1024 values.
        horizon:         Forecast steps (1 ≤ horizon ≤ 256).
        quantile_levels: Override quantiles (default: 0.1, 0.2, ..., 0.9).

    Returns:
        dict with keys: point, quantiles, quantile_levels, metadata.

    Raises:
        InvalidInputError:   NaN/Inf in input, or empty series.
        InvalidHorizonError: horizon out of [1, 256].
    """
    # Validate inputs
    if not inputs:
        raise InvalidInputError("inputs must be a non-empty list of numeric series")

    if not isinstance(horizon, int) or horizon < 1:
        raise InvalidHorizonError(f"horizon must be a positive integer, got {horizon}")

    q_levels = tuple(quantile_levels) if quantile_levels else DEFAULT_QUANTILE_LEVELS

    # Validate quantile levels
    for q in q_levels:
        if not (0.0 < q < 1.0):
            raise WinnyValidationError(
                f"quantile_levels must be between 0 and 1 exclusive, got {q}"
            )

    model = get_model()
    result = model.predict(inputs=inputs, horizon=horizon, quantile_levels=q_levels)

    # Convert numpy to serializable types
    return {
        "model_id": result.metadata.get("model_id", ""),
        "asof": datetime.now(UTC).isoformat(),
        "horizon": horizon,
        "quantile_levels": list(result.quantile_levels),
        "point": result.point.tolist(),
        "quantiles": result.quantiles.tolist(),
        "metadata": {
            "device": result.metadata.get("device", "unknown"),
            "context_lengths": result.metadata.get("context_lengths", []),
            "batch_size": result.metadata.get("batch_size", 0),
        },
    }


async def forecast_symbol(
    symbol: str,
    horizon_bars: int = 24,
    timeframe: str = "1h",
    lookback_bars: int = 512,
    quantile_levels: list[float] | None = None,
) -> dict[str, Any]:
    """Symbol-aware forecast — §3.1.3 forecast_symbol.

    Convenience wrapper: pulls historical bars from the data layer, extracts
    the close prices, feeds them to the model, and returns a SymbolForecast.

    Args:
        symbol:          Canonical Winny Symbol form, e.g. "EQ:NVDA" or "CR:BTC-USDT@binance".
        horizon_bars:    Number of future bars to forecast (1-256).
        timeframe:       Bar timeframe: 1m, 5m, 15m, 1h, 4h, 1d.
        lookback_bars:   Number of historical bars to use as context (max 1024).
        quantile_levels: Override quantiles.

    Returns:
        SymbolForecast dict with forecast + symbol metadata.

    Raises:
        WinnyValidationError: invalid symbol or timeframe.
        InvalidInputError:    no data available for the symbol.
        InvalidHorizonError:  horizon out of bounds.
    """
    # Parse symbol
    try:
        sym = Symbol.parse(symbol)
    except (ValueError, KeyError, WinnyValidationError) as e:
        raise WinnyValidationError(f"Invalid symbol: {symbol!r} - {e}") from e

    # Validate lookback
    if lookback_bars < 1 or lookback_bars > 1024:
        raise WinnyValidationError(f"lookback_bars must be 1-1024, got {lookback_bars}")

    # Fetch historical bars from data layer
    provider = get_data_provider()
    df = await provider.fetch_bars(sym, timeframe, limit=lookback_bars)

    if df.is_empty():
        raise InvalidInputError(
            f"No historical data available for {symbol} at {timeframe}. "
            "Ensure the data provider has connectivity and the symbol is valid."
        )

    # Extract close prices as the input series
    close_prices: list[float] = df["close"].to_list()
    bars_used = len(close_prices)

    if bars_used < 10:
        raise InvalidInputError(
            f"Insufficient data for {symbol}: only {bars_used} bars. Need at least 10."
        )

    # Compute history hash for cache invalidation (§4.2 SymbolForecast.history_hash)
    history_hash = hashlib.sha256(
        json.dumps(close_prices, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    logger.info(
        "forecast_symbol_input",
        symbol=symbol,
        timeframe=timeframe,
        bars_used=bars_used,
        horizon=horizon_bars,
    )

    # Run forecast — TimesFM when installed, transparent statistical
    # fallback otherwise (torch is heavy; many hosts run without it, and a
    # missing optional dependency must degrade the answer, not kill it).
    q_levels = tuple(quantile_levels) if quantile_levels else DEFAULT_QUANTILE_LEVELS
    try:
        model = get_model()
        prediction = model.predict(
            inputs=[close_prices],
            horizon=horizon_bars,
            quantile_levels=q_levels,
        )
        point_rows = prediction.point.tolist()
        quantile_rows = prediction.quantiles.tolist()
        fc_meta = {
            "model_id": prediction.metadata.get("model_id", ""),
            "device": prediction.metadata.get("device", "unknown"),
        }
        q_levels_out = prediction.quantile_levels
    except Exception as e:
        # The model layer wraps the missing-package ImportError in
        # ForecastError; only the "not installed" case falls back — genuine
        # inference failures (OOM, bad input) must surface, not be papered
        # over with a weaker model.
        if not isinstance(e, ImportError) and "not installed" not in str(e).lower():
            raise
        logger.warning("timesfm_unavailable_fallback", error=str(e))
        point_rows, quantile_rows, fc_meta = _statistical_forecast(
            close_prices, horizon_bars, q_levels
        )
        q_levels_out = q_levels

    forecast_result = ForecastResult(
        model_id=fc_meta.pop("model_id", ""),
        asof=datetime.now(UTC),
        horizon=horizon_bars,
        quantile_levels=q_levels_out,
        point=tuple(tuple(row) for row in point_rows),
        quantiles=tuple(tuple(tuple(q) for q in row) for row in quantile_rows),
        metadata={
            **fc_meta,
            "context_length": bars_used,
            "timeframe": timeframe,
        },
    )

    # Build SymbolForecast
    symbol_forecast = SymbolForecast(
        symbol=sym,
        timeframe=timeframe,
        bars_used=bars_used,
        forecast=forecast_result,
        history_hash=history_hash,
    )

    # Return as serializable dict
    output: dict[str, Any] = json.loads(symbol_forecast.model_dump_json())
    return output


# ─── Supabase-backed forecaster history ───────────────────────────────────────


async def get_active_forecasts(
    symbol: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Return recent forecaster rows from public.trading_signals.

    These rows are produced by `gateway.analytics.signal_runner_loop` on a
    5-minute schedule for the configured watchlist. The forecaster currently
    runs a TA stack (EMA/RSI/MACD/ATR) — not the full TimesFM model — but
    the storage shape is identical, so swapping in a model-backed forecaster
    later is transparent to MCP callers.

    Args:
        symbol: filter (canonical or 'BTC/USDT'); omit for all watched pairs.
        limit:  1..100.
    """
    if limit < 1 or limit > 100:
        raise WinnyValidationError(f"limit must be 1-100, got {limit}")
    rows = fetch_forecasts(symbol=symbol, limit=int(limit))
    return {
        "forecasts": rows,
        "total": len(rows),
        "filter_symbol": symbol,
    }
