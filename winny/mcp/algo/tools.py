"""mcp-algo tool handlers — async functions called by McpServer dispatch.

v1 ships one tool:
  - backtest(strategy, symbols, bars, start, end, timeframe, initial_capital)
      → BacktestReport dict (JSON-safe)

Bars are passed inline (not loaded from BarStore) in v1. The PR #13.5 followup
adds a `bars_from_store` mode that reads Parquet via the data layer.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any

import polars as pl

from winny.common.errors import WinnyValidationError
from winny.common.ids import Currency
from winny.common.symbols import Symbol
from winny.common.types import MarketSpec
from winny.engine.loop import EngineConfig, run_backtest
from winny.mcp.algo.loader import load_strategy_class
from winny.mcp.algo.serialization import report_to_dict

# ---------- defaults ----------

# Minimal viable market spec for symbols where the caller didn't override.
# Tight tick + tiny min_qty so we don't accidentally reject sensible test inputs.
_DEFAULT_TICK = Decimal("0.01")
_DEFAULT_MIN_QTY = Decimal("0.001")
_DEFAULT_QTY_STEP = Decimal("0.001")


# ===================================================================
# backtest
# ===================================================================


async def backtest(
    strategy: str,
    symbols: list[str],
    bars: dict[str, list[dict[str, Any]]],
    *,
    start: str | None = None,
    end: str | None = None,
    timeframe: str = "1d",
    initial_capital: str = "100000",
    quote_currency: str = "USD",
    seed: int = 42,
    wall_time_budget_seconds: float | None = None,
    market_specs_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run a backtest of `strategy` on the supplied bars.

    Args:
        strategy: dotted spec, e.g. "winny.strategies.buy_and_hold:BuyAndHold".
            Must be in the winny.strategies.* namespace per loader.py.
        symbols: list of canonical symbol strings ("EQ:NVDA", "CR:BTC-USDT@binance", …).
        bars: per-symbol-canonical list of OHLCV rows.
            Each row is {ts, open, high, low, close, volume} with `ts` as
            ISO 8601 (with timezone) and floats for OHLCV.
        start, end: optional ISO 8601 datetimes to bracket the backtest.
        timeframe: bar interval string (default "1d").
        initial_capital: Decimal-safe string (default "100000").
        quote_currency: e.g. "USD", "USDT" (default "USD").
        seed: deterministic seed for the paper broker.
        wall_time_budget_seconds: hard cap for the backtest run.
        market_specs_overrides: per-symbol-canonical dict of MarketSpec fields
            to override the conservative defaults (e.g. {"EQ:NVDA": {"taker_fee_bps": 5}}).

    Returns:
        JSON-safe BacktestReport dict (see serialization.report_to_dict).

    Raises:
        WinnyValidationError on any malformed input or missing bars.
    """
    # 1. Parse symbols
    if not symbols:
        raise WinnyValidationError("symbols must be a non-empty list")
    parsed_symbols = [Symbol.parse(s) for s in symbols]

    # 2. Build per-symbol Polars DataFrames from the bars input
    bars_by_symbol: dict[Symbol, pl.DataFrame] = {}
    for sym in parsed_symbols:
        sym_key = sym.canonical()
        rows = bars.get(sym_key)
        if not rows:
            raise WinnyValidationError(f"no bars provided for symbol {sym_key!r}")
        bars_by_symbol[sym] = _normalize_bars(rows, sym_key)

    # 3. Build market specs (conservative defaults + per-symbol overrides)
    overrides = market_specs_overrides or {}
    market_specs: dict[Symbol, MarketSpec] = {}
    for sym in parsed_symbols:
        market_specs[sym] = _build_market_spec(sym, overrides.get(sym.canonical(), {}))

    # 4. Parse time bounds
    start_dt = _parse_optional_iso(start, "start")
    end_dt = _parse_optional_iso(end, "end")

    # 5. Load + instantiate strategy
    strategy_cls = load_strategy_class(strategy)
    instance = strategy_cls()

    # 6. Build engine config
    try:
        cfg = EngineConfig(
            initial_capital=Decimal(initial_capital),
            quote_currency=Currency(quote_currency),
            seed=seed,
            wall_time_budget_seconds=wall_time_budget_seconds,
        )
    except (ValueError, ArithmeticError) as e:
        raise WinnyValidationError(f"invalid engine config: {e}") from e

    # 7. Run in a worker thread — run_backtest is sync + CPU-bound + may be slow
    report = await asyncio.to_thread(
        run_backtest,
        strategy=instance,
        symbols=parsed_symbols,
        bars_by_symbol=bars_by_symbol,
        market_specs=market_specs,
        start=start_dt,
        end=end_dt,
        config=cfg,
    )

    return report_to_dict(report)


# ===================================================================
# helpers
# ===================================================================


def _normalize_bars(rows: list[dict[str, Any]], sym_key: str) -> pl.DataFrame:
    """Convert a list of row dicts into a Polars DataFrame with parsed timestamps."""
    required = {"ts", "open", "high", "low", "close", "volume"}
    if not rows:
        raise WinnyValidationError(f"bars for {sym_key!r} is empty")
    missing = required - set(rows[0].keys())
    if missing:
        raise WinnyValidationError(f"bars for {sym_key!r} missing columns: {sorted(missing)}")
    # Parse ts strings to datetime where needed
    parsed_rows = []
    for r in rows:
        ts = r["ts"]
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError as e:
                raise WinnyValidationError(f"bad ts in bars for {sym_key!r}: {ts!r} ({e})") from e
        parsed_rows.append(
            {
                "ts": ts,
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r["volume"]),
            }
        )
    return pl.DataFrame(parsed_rows)


def _build_market_spec(symbol: Symbol, overrides: dict[str, Any]) -> MarketSpec:
    """Construct a MarketSpec for `symbol`, merging conservative defaults + overrides."""
    fields: dict[str, Any] = {
        "symbol": symbol,
        "min_qty": _DEFAULT_MIN_QTY,
        "qty_step": _DEFAULT_QTY_STEP,
        "price_tick": _DEFAULT_TICK,
        "min_notional": None,
        "maker_fee_bps": 0,
        "taker_fee_bps": 0,
        "is_active": True,
    }
    for k, v in overrides.items():
        if k not in fields:
            raise WinnyValidationError(
                f"unknown MarketSpec field in override for {symbol.canonical()}: {k!r}"
            )
        if k in ("min_qty", "qty_step", "price_tick", "min_notional") and v is not None:
            v = Decimal(str(v))
        fields[k] = v
    try:
        return MarketSpec(**fields)
    except Exception as e:
        raise WinnyValidationError(f"invalid MarketSpec for {symbol.canonical()}: {e}") from e


def _parse_optional_iso(value: str | None, field: str) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as e:
        raise WinnyValidationError(f"invalid ISO 8601 in {field}: {value!r} ({e})") from e
