"""live_signal — point-in-time signal extraction for one symbol.

Asks the question: "given these recent bars, what would the strategy say
RIGHT NOW?"

No engine state, no portfolio, no broker. Pure read-through of the
strategy's populate_*() chain on a lookahead-safe slice of bars, then
extract_signals() on the last row.

Use cases:
  - Live signal monitoring (poll from a cron + alert via Hermes)
  - Strategy debugging — "why did you emit ENTER_LONG on bar N?"
  - Dashboard widgets — "current signal for [SPY, NVDA, BTC]"
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from winny.common.errors import WinnyValidationError
from winny.common.symbols import Symbol
from winny.engine.signals import extract_signals, validate_signal_columns
from winny.engine.strategy import BarMeta
from winny.mcp.algo.loader import load_strategy_class
from winny.mcp.algo.serialization import to_jsonable
from winny.mcp.algo.tools import _normalize_bars


async def live_signal(
    strategy: str,
    symbol: str,
    bars: list[dict[str, Any]],
    *,
    timeframe: str | None = None,
) -> dict[str, Any]:
    """Compute the signal(s) at the LAST bar of the supplied series.

    Args:
        strategy: dotted spec, e.g. "winny.strategies.buy_and_hold:BuyAndHold".
            Must be in the winny.strategies.* namespace.
        symbol: canonical symbol string (e.g. "EQ:NVDA", "CR:BTC-USDT@binance").
        bars: list of OHLCV row dicts, ordered ascending by ts. The LAST row
            is treated as the "current" bar. MUST contain at least
            strategy.startup_candle_count rows or no signal is computed.
        timeframe: optional override; defaults to strategy.timeframe.

    Returns:
        Dict with:
          symbol:     canonical symbol
          asof:       ISO timestamp of the last bar (the "current" bar)
          bars_used:  number of bars consumed
          signals:    list of 0..4 signal dicts. Each: {type, ts, bar_close, tag}
          insufficient_warmup: true if len(bars) < startup_candle_count

    Raises:
        WinnyValidationError on any malformed input.
    """
    if not bars:
        raise WinnyValidationError("bars cannot be empty")

    # 1. Parse + load
    sym = Symbol.parse(symbol)
    strategy_cls = load_strategy_class(strategy)
    instance = strategy_cls()

    # 2. Build the DataFrame (reuse the helper from tools.py — single source of
    # truth for bar normalization)
    df = _normalize_bars(bars, sym.canonical())

    # 3. Pull the last bar's timestamp (it's a tz-aware datetime after normalization)
    last_ts_value = df["ts"][-1]
    last_ts: datetime = (
        last_ts_value
        if isinstance(last_ts_value, datetime)
        else datetime.fromisoformat(str(last_ts_value))
    )

    bars_used = len(df)

    # 4. Insufficient warmup → no signal possible
    if bars_used < instance.startup_candle_count:
        return {
            "symbol": sym.canonical(),
            "asof": last_ts.isoformat(),
            "bars_used": bars_used,
            "signals": [],
            "insufficient_warmup": True,
            "strategy": type(instance).__name__,
        }

    # 5. Run populate chain — bars are already <= last_ts so lookahead-safe
    meta = BarMeta(symbol=sym, ts=last_ts, timeframe=timeframe or instance.timeframe)
    df = instance.populate_indicators(df, meta)
    df = instance.populate_entry_trend(df, meta)
    df = instance.populate_exit_trend(df, meta)

    validate_signal_columns(df)
    signals = extract_signals(df, sym, last_ts)

    # 6. Serialize for the MCP wire
    return {
        "symbol": sym.canonical(),
        "asof": last_ts.isoformat(),
        "bars_used": bars_used,
        "signals": [to_jsonable(s) for s in signals],
        "insufficient_warmup": False,
        "strategy": type(instance).__name__,
    }
