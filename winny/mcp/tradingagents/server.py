"""Entry point for mcp-tradingagents server per §3.2.

Registers analyze_symbol, debate_position, and get_decision_history tools,
then runs the MCP stdio loop.

Environment variables (all optional):
    WINNY_TA_LLM_PROVIDER       LLM provider (default: openai)
    WINNY_TA_DEEP_THINK_LLM     Model for researchers/risk (default: gpt-4o)
    WINNY_TA_QUICK_THINK_LLM    Model for analysts (default: gpt-4o-mini)
    WINNY_TA_TEMPERATURE        Temperature for all LLM calls (default: 0.0)
    WINNY_TA_MAX_DEBATE_ROUNDS  Debate rounds (default: 2)
    WINNY_TA_CHECKPOINT         Enable checkpoint (default: true)
    WINNY_TRADINGAGENTS_CONFIG  Path to tradingagents.yaml
"""

from __future__ import annotations

import asyncio

import winny.common.config  # noqa: F401  — load .env (HF_TOKEN, API keys) before graph init
from winny.mcp.base import McpServer, ToolDescriptor, ToolParam

from .tools import analyze_symbol, debate_position, get_decision_history


def build_server() -> McpServer:
    """Construct the mcp-tradingagents server with tool registrations."""
    server = McpServer(name="mcp-tradingagents", version="0.1.0")

    # ---------- analyze_symbol ----------
    server.register_tool(
        ToolDescriptor(
            name="analyze_symbol",
            description=(
                "Run full multi-agent analysis on a symbol. Uses TradingAgents "
                "framework with 4 analyst roles, bull/bear debate, trader recommendation, "
                "and risk assessment. Returns a DecisionDraft with action, conviction, "
                "and full reasoning trace. Read-only - never places orders."
            ),
            parameters=[
                ToolParam(
                    name="symbol",
                    type="string",
                    description=(
                        "Canonical Winny symbol. Examples: "
                        "'EQ:NVDA', 'CR:BTC-USDT@binance', 'FX:EUR-USD'."
                    ),
                ),
                ToolParam(
                    name="asof",
                    type="string",
                    description=(
                        "Analysis point-in-time as ISO datetime. Must be <= now. "
                        "Defaults to current time if omitted."
                    ),
                    required=False,
                ),
                ToolParam(
                    name="forecast",
                    type="object",
                    description=(
                        "Optional ForecastResult from mcp-timesfm to inject as "
                        "Technical Analyst signal. Enhances analysis quality."
                    ),
                    required=False,
                ),
                ToolParam(
                    name="config_overrides",
                    type="object",
                    description="Runtime config overrides for this analysis.",
                    required=False,
                ),
            ],
            handler=analyze_symbol,
        )
    )

    # ---------- debate_position ----------
    server.register_tool(
        ToolDescriptor(
            name="debate_position",
            description=(
                "Follow-up debate on a prior decision. Reruns a focused agent "
                "from the specified perspective to answer the user's question. "
                "Useful for 'what's the bear case?' or 'are you sure?' follow-ups."
            ),
            parameters=[
                ToolParam(
                    name="decision_id",
                    type="string",
                    description="DecisionId from a prior analyze_symbol call (dec_... format).",
                ),
                ToolParam(
                    name="user_question",
                    type="string",
                    description="The user's question or challenge about the decision.",
                ),
                ToolParam(
                    name="perspective",
                    type="string",
                    description="Agent perspective for the debate.",
                    required=False,
                    default="bull",
                    enum=["bull", "bear", "risk", "trader"],
                ),
            ],
            handler=debate_position,
        )
    )

    # ---------- get_decision_history ----------
    server.register_tool(
        ToolDescriptor(
            name="get_decision_history",
            description=(
                "Retrieve past decisions from the reasoning memory. "
                "Returns structured historical decisions with outcomes."
            ),
            parameters=[
                ToolParam(
                    name="symbol",
                    type="string",
                    description="Filter by symbol (optional). Omit for all symbols.",
                    required=False,
                ),
                ToolParam(
                    name="limit",
                    type="integer",
                    description="Max decisions to return (1-100).",
                    required=False,
                    default=20,
                ),
            ],
            handler=get_decision_history,
        )
    )

    return server


def main() -> None:
    """CLI entry point for mcp-tradingagents."""
    server = build_server()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
