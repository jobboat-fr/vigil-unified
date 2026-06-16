"""mcp-algo server entry point — SPECS.md §3.3.

Wires the backtest tool to the McpServer stdio dispatch. Future tools
(dry_run, live_signal, prepare_order, submit_order, cancel_*, get_portfolio,
get_open_orders, get_market_context) plug into this same server.

Run:
    python -m winny.mcp.algo.server
    # or
    mcp-algo
"""

from __future__ import annotations

import asyncio

import winny.common.config  # noqa: F401  — load .env into os.environ
from winny.mcp.algo.cancel import cancel_all, cancel_order
from winny.mcp.algo.dry_run import dry_run, get_dry_run_status
from winny.mcp.algo.live_signal import live_signal
from winny.mcp.algo.market_context import get_market_context
from winny.mcp.algo.portfolio import get_open_orders, get_portfolio
from winny.mcp.algo.prepare import prepare_order
from winny.mcp.algo.submit import submit_order
from winny.mcp.algo.tools import backtest
from winny.mcp.base import McpServer, ToolDescriptor, ToolParam


def _build_server() -> McpServer:
    """Construct the mcp-algo server with tool registrations."""
    server = McpServer(name="mcp-algo", version="0.1.0")

    server.register_tool(
        ToolDescriptor(
            name="backtest",
            description=(
                "Run a historical backtest of a Winny strategy against supplied bars. "
                "Strategy must be in the winny.strategies.* namespace. Returns a "
                "BacktestReport with trades, equity curve, and aggregate metrics. "
                "Bars are passed inline (per-symbol-canonical map of OHLCV rows); "
                "store-backed bar loading lands in a follow-up PR."
            ),
            parameters=[
                ToolParam(
                    name="strategy",
                    type="string",
                    description=(
                        "Dotted strategy spec 'module:ClassName'. Module must be in "
                        "winny.strategies.* namespace. Example: "
                        "'winny.strategies.buy_and_hold:BuyAndHold'."
                    ),
                ),
                ToolParam(
                    name="symbols",
                    type="array",
                    description=(
                        "List of canonical symbol strings ('EQ:NVDA', "
                        "'CR:BTC-USDT@binance', 'FX:EURUSD', ...)."
                    ),
                    items={"type": "string"},
                ),
                ToolParam(
                    name="bars",
                    type="object",
                    description=(
                        "Per-symbol-canonical map of OHLCV rows. Each row has "
                        "{ts, open, high, low, close, volume} with ts as ISO 8601 "
                        "and numeric OHLCV."
                    ),
                ),
                ToolParam(
                    name="start",
                    type="string",
                    description="Inclusive ISO 8601 start. None = earliest bar.",
                    required=False,
                ),
                ToolParam(
                    name="end",
                    type="string",
                    description="Inclusive ISO 8601 end. None = latest bar.",
                    required=False,
                ),
                ToolParam(
                    name="timeframe",
                    type="string",
                    description="Bar interval (default '1d').",
                    required=False,
                    default="1d",
                ),
                ToolParam(
                    name="initial_capital",
                    type="string",
                    description="Starting cash as Decimal-safe string (default '100000').",
                    required=False,
                    default="100000",
                ),
                ToolParam(
                    name="quote_currency",
                    type="string",
                    description="Quote currency code (default 'USD').",
                    required=False,
                    default="USD",
                ),
                ToolParam(
                    name="seed",
                    type="integer",
                    description="Deterministic seed (default 42).",
                    required=False,
                    default=42,
                ),
                ToolParam(
                    name="wall_time_budget_seconds",
                    type="number",
                    description=(
                        "Hard wall-clock cap on the run. None = unlimited. "
                        "If exceeded, returns the partial report with what was processed."
                    ),
                    required=False,
                ),
                ToolParam(
                    name="market_specs_overrides",
                    type="object",
                    description=(
                        "Per-symbol-canonical dict overriding MarketSpec defaults "
                        "(e.g. {'EQ:NVDA': {'taker_fee_bps': 5}})."
                    ),
                    required=False,
                ),
            ],
            handler=backtest,
        )
    )

    # ---------- live_signal ----------
    server.register_tool(
        ToolDescriptor(
            name="live_signal",
            description=(
                "Compute the signal(s) at the LAST bar for one symbol. "
                "Returns 0-4 typed signals (ENTER_LONG / ENTER_SHORT / "
                "EXIT_LONG / EXIT_SHORT) with optional tags. Pure read-through "
                "of the strategy's populate_*() chain — no engine state, no "
                "broker, no portfolio."
            ),
            parameters=[
                ToolParam(
                    name="strategy",
                    type="string",
                    description=(
                        "Dotted strategy spec 'module:ClassName'. Must be in "
                        "winny.strategies.* namespace."
                    ),
                ),
                ToolParam(
                    name="symbol",
                    type="string",
                    description="Canonical symbol string (e.g. 'EQ:NVDA', 'CR:BTC-USDT@binance').",
                ),
                ToolParam(
                    name="bars",
                    type="array",
                    description=(
                        "Ascending-by-ts list of OHLCV row dicts. The LAST row "
                        "is treated as 'now'. Must contain at least "
                        "strategy.startup_candle_count rows or signals are skipped."
                    ),
                    items={"type": "object"},
                ),
                ToolParam(
                    name="timeframe",
                    type="string",
                    description="Optional timeframe override; defaults to strategy.timeframe.",
                    required=False,
                ),
            ],
            handler=live_signal,
        )
    )

    # ---------- dry_run ----------
    server.register_tool(
        ToolDescriptor(
            name="dry_run",
            description=(
                "Launch an async backtest and return a handle immediately. "
                "The backtest runs in the background; poll get_dry_run_status "
                "to discover completion. Same input shape as `backtest` — "
                "this is the non-blocking variant."
            ),
            parameters=[
                ToolParam(name="strategy", type="string", description="Dotted strategy spec."),
                ToolParam(
                    name="symbols",
                    type="array",
                    description="List of canonical symbol strings.",
                    items={"type": "string"},
                ),
                ToolParam(
                    name="bars",
                    type="object",
                    description="Per-symbol-canonical map of OHLCV rows (same shape as backtest).",
                ),
                ToolParam(
                    name="start",
                    type="string",
                    description="Optional inclusive ISO 8601 start.",
                    required=False,
                ),
                ToolParam(
                    name="end",
                    type="string",
                    description="Optional inclusive ISO 8601 end.",
                    required=False,
                ),
                ToolParam(
                    name="timeframe",
                    type="string",
                    description="Bar interval (default '1d').",
                    required=False,
                    default="1d",
                ),
                ToolParam(
                    name="initial_capital",
                    type="string",
                    description="Starting cash as Decimal-safe string (default '100000').",
                    required=False,
                    default="100000",
                ),
                ToolParam(
                    name="quote_currency",
                    type="string",
                    description="Quote currency code (default 'USD').",
                    required=False,
                    default="USD",
                ),
                ToolParam(
                    name="seed",
                    type="integer",
                    description="Deterministic seed (default 42).",
                    required=False,
                    default=42,
                ),
                ToolParam(
                    name="wall_time_budget_seconds",
                    type="number",
                    description="Hard wall-clock cap. None = unlimited.",
                    required=False,
                ),
                ToolParam(
                    name="market_specs_overrides",
                    type="object",
                    description="Per-symbol-canonical MarketSpec field overrides.",
                    required=False,
                ),
            ],
            handler=dry_run,
        )
    )

    # ---------- get_dry_run_status ----------
    server.register_tool(
        ToolDescriptor(
            name="get_dry_run_status",
            description=(
                "Look up a dry-run handle. Returns status (PENDING / RUNNING / "
                "COMPLETED / FAILED), timestamps, and (when COMPLETED) the full "
                "BacktestReport, or (when FAILED) the error message."
            ),
            parameters=[
                ToolParam(
                    name="handle_id",
                    type="string",
                    description="Handle returned by a prior `dry_run` call.",
                ),
            ],
            handler=get_dry_run_status,
        )
    )

    # ---------- prepare_order ----------
    server.register_tool(
        ToolDescriptor(
            name="prepare_order",
            description=(
                "Build an OrderIntent for a given signal without submitting it. "
                "Computes sizing via the NAV-cap chokepoint (§1.3), returns the "
                "intent JSON + sizing provenance. Does NOT mutate portfolio state."
            ),
            parameters=[
                ToolParam(
                    name="signal",
                    type="object",
                    description=(
                        "Signal dict with at least 'type' (ENTER_LONG / ENTER_SHORT / "
                        "EXIT_LONG / EXIT_SHORT) and 'symbol' (canonical string)."
                    ),
                ),
                ToolParam(
                    name="ref_price",
                    type="string",
                    description="Reference price as Decimal-safe string for sizing and slippage.",
                ),
                ToolParam(
                    name="current_prices",
                    type="object",
                    description=(
                        "Optional dict mapping canonical symbol strings to current price "
                        "strings. Used for NAV mark-to-market. Unpriced positions excluded."
                    ),
                    required=False,
                ),
                ToolParam(
                    name="sizing_policy",
                    type="string",
                    description="Sizing policy name: 'fixed_fractional' or 'conviction'.",
                    required=False,
                    default="fixed_fractional",
                ),
                ToolParam(
                    name="sizing_params",
                    type="object",
                    description=(
                        "Optional params for the sizing policy. "
                        "E.g. {'nav_fraction': '0.02'} or {'conviction': 7}."
                    ),
                    required=False,
                ),
                ToolParam(
                    name="fee_model",
                    type="string",
                    description="Fee model name. Currently only 'default' supported.",
                    required=False,
                    default="default",
                ),
                ToolParam(
                    name="decision_id",
                    type="string",
                    description="Optional DecisionId back-reference.",
                    required=False,
                ),
            ],
            handler=prepare_order,
        )
    )

    # ---------- get_portfolio ----------
    server.register_tool(
        ToolDescriptor(
            name="get_portfolio",
            description=(
                "Return a PortfolioSnapshot: cash balances, positions with mark-to-market "
                "valuation, NAV, and count of open orders. Pure read — no mutation."
            ),
            parameters=[
                ToolParam(
                    name="current_prices",
                    type="object",
                    description=(
                        "Dict mapping canonical symbol strings to current price strings "
                        "for mark-to-market. Unpriced positions are excluded from NAV."
                    ),
                    required=False,
                ),
                ToolParam(
                    name="nav_currency",
                    type="string",
                    description="Reporting currency code (default 'USD').",
                    required=False,
                    default="USD",
                ),
            ],
            handler=get_portfolio,
        )
    )

    # ---------- get_open_orders ----------
    server.register_tool(
        ToolDescriptor(
            name="get_open_orders",
            description=(
                "Return pending/open orders from the portfolio store. "
                "Optionally filter by broker and/or symbol. Pure read."
            ),
            parameters=[
                ToolParam(
                    name="broker",
                    type="string",
                    description="Filter by broker name (e.g. 'paper', 'ibkr').",
                    required=False,
                ),
                ToolParam(
                    name="symbol",
                    type="string",
                    description="Filter by canonical symbol string.",
                    required=False,
                ),
            ],
            handler=get_open_orders,
        )
    )

    # ---------- get_market_context ----------
    server.register_tool(
        ToolDescriptor(
            name="get_market_context",
            description=(
                "Return recent bars, last price, and summary statistics for a symbol. "
                "Bars are provided inline (no auto-fetch in v1). Pure read."
            ),
            parameters=[
                ToolParam(
                    name="symbol",
                    type="string",
                    description="Canonical symbol string (e.g. 'EQ:NVDA').",
                ),
                ToolParam(
                    name="bars",
                    type="array",
                    description=(
                        "Ascending-by-ts list of OHLCV row dicts. Each row must have "
                        "{ts, open, high, low, close, volume}."
                    ),
                    items={"type": "object"},
                ),
                ToolParam(
                    name="n_recent",
                    type="integer",
                    description="Number of recent bars to include (default 20).",
                    required=False,
                    default=20,
                ),
            ],
            handler=get_market_context,
        )
    )

    # ---------- submit_order ----------
    server.register_tool(
        ToolDescriptor(
            name="submit_order",
            description=(
                "Submit an approved order to the brokerage. Requires a valid, "
                "unconsumed approval grant. This is the ONLY path to real execution."
            ),
            parameters=[
                ToolParam(
                    name="approval_id",
                    type="string",
                    description="The ApprovalId from the approval gate.",
                ),
                ToolParam(
                    name="grant_token",
                    type="string",
                    description="The signed grant_token from mcp-approval.verify.",
                ),
                ToolParam(
                    name="order_intent",
                    type="object",
                    description="The OrderIntent dict (same as was approved).",
                ),
                ToolParam(
                    name="mode",
                    type="string",
                    description="Engine mode: LIVE, DRY_RUN, or BACKTEST.",
                    required=False,
                    default="LIVE",
                ),
            ],
            handler=submit_order,
        )
    )

    # ---------- cancel_order ----------
    server.register_tool(
        ToolDescriptor(
            name="cancel_order",
            description=(
                "Cancel a single open order on the broker. Requires approval grant."
            ),
            parameters=[
                ToolParam(
                    name="broker_order_id",
                    type="string",
                    description="The broker-assigned order ID to cancel.",
                ),
                ToolParam(
                    name="approval_id",
                    type="string",
                    description="ApprovalId for the cancel action.",
                ),
                ToolParam(
                    name="grant_token",
                    type="string",
                    description="Signed grant_token from mcp-approval.verify.",
                ),
                ToolParam(
                    name="order_intent_hash",
                    type="string",
                    description="Intent hash the grant was issued against.",
                ),
                ToolParam(
                    name="symbol",
                    type="string",
                    description="Canonical symbol string for broker routing.",
                ),
                ToolParam(
                    name="mode",
                    type="string",
                    description="Engine mode: LIVE or DRY_RUN.",
                    required=False,
                    default="LIVE",
                ),
            ],
            handler=cancel_order,
        )
    )

    # ---------- cancel_all ----------
    server.register_tool(
        ToolDescriptor(
            name="cancel_all",
            description=(
                "Cancel all open orders for a symbol. Requires approval grant."
            ),
            parameters=[
                ToolParam(
                    name="approval_id",
                    type="string",
                    description="ApprovalId for the cancel_all action.",
                ),
                ToolParam(
                    name="grant_token",
                    type="string",
                    description="Signed grant_token from mcp-approval.verify.",
                ),
                ToolParam(
                    name="order_intent_hash",
                    type="string",
                    description="Intent hash the grant was issued against.",
                ),
                ToolParam(
                    name="symbol",
                    type="string",
                    description="Canonical symbol string for broker routing.",
                ),
                ToolParam(
                    name="mode",
                    type="string",
                    description="Engine mode: LIVE or DRY_RUN.",
                    required=False,
                    default="LIVE",
                ),
            ],
            handler=cancel_all,
        )
    )

    return server


def main() -> None:
    """Entry point for mcp-algo."""
    server = _build_server()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
