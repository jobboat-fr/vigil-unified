"""mcp-timesfm server entry point — §3.1, §15.3.

Starts the MCP server with stdio transport, registers forecast tools,
and loads the TimesFM model on first request (lazy cold start).

Run:
    python -m winny.mcp.timesfm.server

Or via the CLI:
    winny mcp timesfm

Configuration:
    WINNY_TIMESFM_DEVICE=auto|cuda|cpu|mps   (default: auto)
    WINNY_TIMESFM_MAX_CONTEXT=1024           (default: 1024)
    WINNY_TIMESFM_MAX_HORIZON=256            (default: 256)
"""

from __future__ import annotations

import asyncio

import winny.common.config  # noqa: F401  — load .env (HF_TOKEN) before model init
from winny.mcp.base import McpServer, ToolDescriptor, ToolParam
from winny.mcp.timesfm.tools import (
    forecast_series,
    forecast_symbol,
    get_active_forecasts,
)


def _build_server() -> McpServer:
    """Construct the mcp-timesfm server with tool registrations."""
    server = McpServer(name="mcp-timesfm", version="0.1.0")

    # ---------- forecast_series ----------
    server.register_tool(
        ToolDescriptor(
            name="forecast_series",
            description=(
                "Run quantile time-series forecast on raw numeric input. "
                "Asset-agnostic: no symbol semantics. Input is a batch of numeric series "
                "(each ≤1024 values), output is point + quantile forecasts for the "
                "specified horizon (1-256 steps). Model: TimesFM 2.5 200M."
            ),
            parameters=[
                ToolParam(
                    name="inputs",
                    type="array",
                    description=(
                        "Batch of time series. Each element is a list of floats "
                        "(most recent value last). Max length per series: 1024. "
                        "Must not contain NaN or Inf."
                    ),
                    items={"type": "array", "items": {"type": "number"}},
                ),
                ToolParam(
                    name="horizon",
                    type="integer",
                    description="Number of future steps to forecast (1-256).",
                    required=False,
                    default=24,
                ),
                ToolParam(
                    name="quantile_levels",
                    type="array",
                    description=(
                        "Quantile levels to emit (0 < q < 1). "
                        "Default: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]."
                    ),
                    required=False,
                    items={"type": "number"},
                ),
            ],
            handler=forecast_series,
        )
    )

    # ---------- forecast_symbol ----------
    server.register_tool(
        ToolDescriptor(
            name="forecast_symbol",
            description=(
                "Forecast a financial symbol by pulling history from the data layer "
                "and running TimesFM. Returns a SymbolForecast with point + quantile "
                "predictions, history hash, and metadata. Supports EQ:, CR:, FX: symbols."
            ),
            parameters=[
                ToolParam(
                    name="symbol",
                    type="string",
                    description=(
                        "Canonical Winny symbol form. Examples: "
                        "'EQ:NVDA', 'CR:BTC-USDT@binance', 'FX:EUR-USD'."
                    ),
                ),
                ToolParam(
                    name="horizon_bars",
                    type="integer",
                    description="Number of future bars to forecast (1-256).",
                    required=False,
                    default=24,
                ),
                ToolParam(
                    name="timeframe",
                    type="string",
                    description="Bar timeframe for history + forecast.",
                    required=False,
                    default="1h",
                    enum=["1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"],
                ),
                ToolParam(
                    name="lookback_bars",
                    type="integer",
                    description=(
                        "Number of historical bars as model context (1-1024). "
                        "More context generally gives better forecasts."
                    ),
                    required=False,
                    default=512,
                ),
                ToolParam(
                    name="quantile_levels",
                    type="array",
                    description="Override quantile levels (0 < q < 1).",
                    required=False,
                    items={"type": "number"},
                ),
            ],
            handler=forecast_symbol,
        )
    )

    # ---------- get_active_forecasts ----------
    server.register_tool(
        ToolDescriptor(
            name="get_active_forecasts",
            description=(
                "Return recent forecaster rows from Supabase trading_signals. "
                "These are produced every 5 minutes by the gateway's signal "
                "runner for the configured watchlist (default top-7 USDT "
                "crypto pairs). Use this to look at the most recent "
                "side/confidence/entry/stop/target/thesis for a symbol "
                "without re-running the model."
            ),
            parameters=[
                ToolParam(
                    name="symbol",
                    type="string",
                    description=(
                        "Filter by symbol (canonical 'CR:BTC-USDT@kraken' or "
                        "pair 'BTC/USDT'). Omit for all watched pairs."
                    ),
                    required=False,
                ),
                ToolParam(
                    name="limit",
                    type="integer",
                    description="Max rows to return (1-100).",
                    required=False,
                    default=20,
                ),
            ],
            handler=get_active_forecasts,
        )
    )

    return server


def main() -> None:
    """Entry point for mcp-timesfm."""
    server = _build_server()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
