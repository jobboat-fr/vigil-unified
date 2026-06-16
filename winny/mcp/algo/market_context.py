"""get_market_context tool handler.

Returns recent bars, last price, and summary statistics for a symbol.
In v1, bars are provided inline by the caller — no auto-fetch from
the data layer. This keeps the tool deterministic and testable without
network access.

Pure read — no mutation.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


async def get_market_context(
    symbol: str,
    bars: list[dict[str, Any]],
    n_recent: int = 20,
) -> dict[str, Any]:
    """Return market context for a symbol from caller-provided bars.

    Parameters
    ----------
    symbol : canonical symbol string (e.g. 'EQ:NVDA').
    bars : ascending-by-ts list of OHLCV row dicts. Each must have at
        least {ts, open, high, low, close, volume}.
    n_recent : how many recent bars to include in the response (default 20).
    """
    if not symbol:
        return {"error": "symbol is required."}

    if not bars:
        return {"error": "bars list is empty — provide at least 1 bar."}

    # Validate minimum bar structure
    required_fields = {"ts", "open", "high", "low", "close", "volume"}
    first_bar = bars[0]
    missing = required_fields - set(first_bar.keys())
    if missing:
        return {"error": f"Bars must have fields {sorted(required_fields)}. Missing: {sorted(missing)}"}

    # Take the most recent n bars
    recent = bars[-n_recent:] if n_recent < len(bars) else bars

    # Last price = close of the last bar
    last_bar = bars[-1]
    last_price = Decimal(str(last_bar["close"]))

    # Compute summary stats from all provided bars
    closes = [Decimal(str(b["close"])) for b in bars]
    highs = [Decimal(str(b["high"])) for b in bars]
    lows = [Decimal(str(b["low"])) for b in bars]
    volumes = [Decimal(str(b["volume"])) for b in bars]

    n = len(closes)
    high_of_range = max(highs)
    low_of_range = min(lows)
    avg_close = sum(closes) / n
    avg_volume = sum(volumes) / n

    # Simple realized volatility: stdev of returns
    if n >= 2:
        returns: list[Decimal] = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, n)
            if closes[i - 1] != 0
        ]
        if returns:
            mean_ret = sum(returns) / Decimal(len(returns))
            variance = sum((r - mean_ret) ** 2 for r in returns) / Decimal(len(returns))
            volatility = Decimal(str(float(variance) ** 0.5))
        else:
            volatility = Decimal("0")
    else:
        volatility = Decimal("0")

    return {
        "symbol": symbol,
        "last_price": str(last_price),
        "last_bar_ts": str(last_bar["ts"]),
        "total_bars_provided": len(bars),
        "recent_bars": recent,
        "stats": {
            "high_of_range": str(high_of_range),
            "low_of_range": str(low_of_range),
            "avg_close": str(avg_close),
            "avg_volume": str(avg_volume),
            "realized_volatility": str(volatility),
            "bar_count": n,
        },
    }
