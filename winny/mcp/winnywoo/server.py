"""mcp-winnywoo server entry point.

Stdio MCP server registering 12 tools that bridge Hermes ↔ WinnyWoo
gateway. The brain (Kimi K2) calls these as JSON-RPC and gets back live
trading state or orchestrates a trade through the approval gate.

Run:
    python -m winny.mcp.winnywoo.server
    # or via the console script:
    mcp-winnywoo
"""

from __future__ import annotations

import asyncio
from typing import Any

import winny.common.config  # noqa: F401 — load .env into os.environ

from winny.mcp.base import McpServer, ToolDescriptor, ToolParam
from winny.mcp.winnywoo.client import BackendClient
from winny.mcp.winnywoo import tools as t


# A single module-level client — connection pool reused across calls.
# Lazy init: constructing it without env vars would crash the server at
# import time, which we want only when the gateway is actually unreachable.
_client: BackendClient | None = None


def _get_client() -> BackendClient:
    global _client
    if _client is None:
        _client = BackendClient()
    return _client


# ── async wrappers — McpServer requires Coroutine handlers ────────────


async def _read(fn, **kwargs: Any) -> Any:
    """Run a sync read tool in the thread pool."""
    return await asyncio.to_thread(fn, _get_client(), **kwargs)


async def _aget_portfolio(user_id: str | None = None) -> Any:
    return await _read(t.get_portfolio, user_id=user_id)


async def _aget_positions(user_id: str | None = None) -> Any:
    return await _read(t.get_positions, user_id=user_id)


async def _aget_open_orders(user_id: str | None = None) -> Any:
    return await _read(t.get_open_orders, user_id=user_id)


async def _aget_market_quote(symbol: str) -> Any:
    return await _read(t.get_market_quote, symbol=symbol)


async def _apropose_order(
    symbol: str,
    side: str,
    qty: float | None = None,
    sizing_policy: str = "fixed_fractional",
    conviction: int | None = None,
    order_type: str = "market",
    price: float | None = None,
    note: str | None = None,
    user_id: str | None = None,
) -> Any:
    return await _read(
        t.propose_order,
        symbol=symbol,
        side=side,
        qty=qty,
        sizing_policy=sizing_policy,
        conviction=conviction,
        order_type=order_type,
        price=price,
        note=note,
        user_id=user_id,
    )


async def _averify_approval(approval_id: str, otc: str, user_id: str | None = None) -> Any:
    return await _read(t.verify_approval, approval_id=approval_id, otc=otc, user_id=user_id)


async def _alist_pending(user_id: str | None = None) -> Any:
    return await _read(t.list_pending_approvals, user_id=user_id)


async def _areject_approval(
    approval_id: str, reason: str = "rejected via Hermes", user_id: str | None = None
) -> Any:
    return await _read(t.reject_approval, approval_id=approval_id, reason=reason, user_id=user_id)


async def _acancel_order(broker_order_id: str) -> Any:
    return await _read(t.cancel_order, broker_order_id=broker_order_id)


async def _avault_list(user_id: str) -> Any:
    return await _read(t.vault_list, user_id=user_id)


async def _avault_search(user_id: str, query: str) -> Any:
    return await _read(t.vault_search, user_id=user_id, query=query)


async def _avault_get(user_id: str, doc_id: str) -> Any:
    return await _read(t.vault_get, user_id=user_id, doc_id=doc_id)


async def _acancel_all(user_id: str | None = None) -> Any:
    return await _read(t.cancel_all_orders, user_id=user_id)


async def _aget_live_signals(symbol: str | None = None, limit: int = 20) -> Any:
    return await _read(t.get_live_signals, symbol=symbol, limit=limit)


async def _abroadcast_event(
    type: str,
    text: str | None = None,
    data: dict[str, Any] | None = None,
    session_id: str | None = None,
    agent: str | None = "winnywoo",
    user_id: str | None = None,
) -> Any:
    return await _read(
        t.broadcast_event,
        type=type,
        text=text,
        data=data,
        session_id=session_id,
        agent=agent,
        user_id=user_id,
    )


# ── server build ──────────────────────────────────────────────────────


def _build_server() -> McpServer:
    s = McpServer(name="mcp-winnywoo", version="1.0.0")

    # READ tools ───────────────────────────────────────────────────────
    _scope_param = ToolParam(
        name="user_id", type="string", required=False,
        description="The user_id from the conversation [context] block — scopes the "
                    "snapshot to the CHATTING user's connected broker. Always pass it "
                    "when context provides one; omit only if there is no user_id.",
    )
    s.register_tool(ToolDescriptor(
        name="get_portfolio",
        description=(
            "Return the CHATTING user's full portfolio snapshot from THEIR connected "
            "broker: NAV in USD, balances, open positions with mark-to-market P&L, open "
            "orders. Pass user_id from the [context] block. Use this for every "
            "'how much / what's my' question before reaching for any other tool. If it "
            "returns empty, the user hasn't connected a broker in Settings yet."
        ),
        parameters=[_scope_param],
        handler=_aget_portfolio,
    ))
    s.register_tool(ToolDescriptor(
        name="get_positions",
        description="The chatting user's open-positions slice — symbol, qty, avg entry, "
                    "unrealised P&L. Pass user_id from [context].",
        parameters=[_scope_param],
        handler=_aget_positions,
    ))
    s.register_tool(ToolDescriptor(
        name="get_open_orders",
        description="The chatting user's pending orders awaiting fill or cancellation. "
                    "Pass user_id from [context].",
        parameters=[_scope_param],
        handler=_aget_open_orders,
    ))
    s.register_tool(ToolDescriptor(
        name="get_market_quote",
        description="Last price + bid/ask for a CCXT symbol like 'BTC/USDT' or 'ETH/EUR'.",
        parameters=[
            ToolParam(name="symbol", type="string",
                      description="CCXT-style market symbol. Case-insensitive."),
        ],
        handler=_aget_market_quote,
    ))

    # ORDER / APPROVAL flow ────────────────────────────────────────────
    s.register_tool(ToolDescriptor(
        name="propose_order",
        description=(
            "Create an ApprovalRequest for a new order. DOES NOT submit. Returns "
            "{approval_id, one_time_code, ...}; the user must reply with the one-time "
            "code, which Hermes then passes to verify_approval. This is the "
            "spec-mandated approval gate — never short-circuit it.\n"
            "LEAVE qty UNSET: the gateway sizes the order against the CHATTING user's "
            "own live broker NAV with the §1.3 5%-NAV hard cap. Pass user_id from the "
            "[context] block so it sizes THEIR book, not the operator's. For "
            "conviction-scaled sizing pass sizing_policy='conviction' + conviction "
            "(1-10). Only pass an explicit qty for a deliberate manual override."
        ),
        parameters=[
            ToolParam(name="symbol", type="string", description="CCXT symbol, e.g. BTC/USDT."),
            ToolParam(name="side", type="string", description="buy or sell.",
                      enum=["buy", "sell"]),
            ToolParam(name="qty", type="number",
                      description="USUALLY OMIT — the gateway sizes it. Only set for a "
                                  "manual override (skips the sizing engine + cap).",
                      required=False),
            ToolParam(name="sizing_policy", type="string",
                      description="How the gateway sizes within the cap.",
                      required=False, default="fixed_fractional",
                      enum=["fixed_fractional", "conviction"]),
            ToolParam(name="conviction", type="number",
                      description="1-10, used when sizing_policy='conviction'. Higher = "
                                  "bigger stake, still capped at §1.3 5% NAV.",
                      required=False),
            ToolParam(name="order_type", type="string",
                      description="market | limit | stop_market | stop_limit.",
                      required=False, default="market",
                      enum=["market", "limit", "stop_market", "stop_limit"]),
            ToolParam(name="price", type="number",
                      description="Required for limit / stop_limit; omit for market.",
                      required=False),
            ToolParam(name="note", type="string",
                      description="One-line trader-facing rationale (becomes the OTC summary).",
                      required=False),
            ToolParam(name="user_id", type="string", required=False,
                      description="The chatting user's id from [context] — sizes + scopes "
                                  "the order to THEIR broker, not the operator's."),
        ],
        handler=_apropose_order,
    ))
    s.register_tool(ToolDescriptor(
        name="verify_approval",
        description=(
            "Complete a pending approval with the user's one-time code AND submit. On "
            "success the frozen order is submitted to the CHATTING user's own broker "
            "and {verified, submitted} is returned. Pass user_id from [context] — the "
            "gateway enforces the approval is owned by that user and routes the fill to "
            "their broker. Failures (wrong OTC, expired, revoked, not-owned) consume "
            "the approval — request a new one."
        ),
        parameters=[
            ToolParam(name="approval_id", type="string",
                      description="ID returned from propose_order."),
            ToolParam(name="otc", type="string",
                      description="The 6-char one-time code the user just typed."),
            ToolParam(name="user_id", type="string", required=False,
                      description="The chatting user's id from [context] — scopes verify "
                                  "+ submit to their broker."),
        ],
        handler=_averify_approval,
    ))
    s.register_tool(ToolDescriptor(
        name="list_pending_approvals",
        description="Show approvals awaiting the user's OTC. Use to recover a dropped "
                    "flow. Pass user_id from [context] — a scoped caller sees only their own.",
        parameters=[
            ToolParam(name="user_id", type="string", required=False,
                      description="The chatting user's id from [context]."),
        ],
        handler=_alist_pending,
    ))
    s.register_tool(ToolDescriptor(
        name="reject_approval",
        description="Discard a pending approval before it expires. Pass user_id from "
                    "[context] — only the owning user may reject it.",
        parameters=[
            ToolParam(name="approval_id", type="string", description="ID to discard."),
            ToolParam(name="reason", type="string", description="Audit reason.",
                      required=False, default="rejected via Hermes"),
            ToolParam(name="user_id", type="string", required=False,
                      description="The chatting user's id from [context]."),
        ],
        handler=_areject_approval,
    ))

    # CANCEL / KILL ────────────────────────────────────────────────────
    s.register_tool(ToolDescriptor(
        name="cancel_order",
        description="Cancel one open order by broker_order_id.",
        parameters=[
            ToolParam(name="broker_order_id", type="string",
                      description="The broker's order id (returned by the broker on placement)."),
        ],
        handler=_acancel_order,
    ))
    s.register_tool(ToolDescriptor(
        name="cancel_all_orders",
        description=(
            "PANIC — cancel every open order on the CHATTING user's broker. Use only "
            "when the user explicitly asks to flatten/panic. Pass user_id from "
            "[context] so it flattens THEIR book. Pairs with winny:kill skill."
        ),
        parameters=[
            ToolParam(name="user_id", type="string", required=False,
                      description="The chatting user's id from [context] — flattens their broker."),
        ],
        handler=_acancel_all,
    ))

    # SIGNALS — gateway-channel signal history ─────────────────────────
    s.register_tool(ToolDescriptor(
        name="get_live_signals",
        description=(
            "Latest trading signals from the platform's signal runner "
            "(forecaster + analyst rows per watchlist symbol, refreshed every "
            "~5 min): side, confidence, entry/stop/target, indicators, thesis. "
            "Use this for 'what does the system think about X' and to ground "
            "any market-direction answer in the platform's own signal history. "
            "Filter with symbol='BTC/USDT' or omit for all watched pairs."
        ),
        parameters=[
            ToolParam(name="symbol", type="string", required=False,
                      description="Optional pair filter, e.g. 'BTC/USDT'."),
            ToolParam(name="limit", type="number", required=False,
                      description="Max rows (1-100, default 20)."),
        ],
        handler=_aget_live_signals,
    ))

    # VAULT — user document grounding ──────────────────────────────────
    s.register_tool(ToolDescriptor(
        name="vault_list",
        description=(
            "List the user's classified document vault (contracts, invoices, legal "
            "papers): id, category, title, summary, risk_flags per document. The "
            "user_id comes from the [context] block of the conversation. Check this "
            "before answering ANY question about the user's documents, obligations, "
            "deadlines, or finances — and proactively mention risk_flags that are "
            "relevant to what the user is discussing."
        ),
        parameters=[
            ToolParam(name="user_id", type="string",
                      description="The user_id provided in the conversation context."),
        ],
        handler=_avault_list,
    ))
    s.register_tool(ToolDescriptor(
        name="vault_search",
        description=(
            "Full-text search across the user's vault documents (titles, summaries, "
            "extracted body text). Use when looking for a specific clause, party, "
            "amount, or topic across many documents."
        ),
        parameters=[
            ToolParam(name="user_id", type="string",
                      description="The user_id provided in the conversation context."),
            ToolParam(name="query", type="string",
                      description="Search terms, e.g. 'auto-renewal', 'Acme GmbH', 'deposit'."),
        ],
        handler=_avault_search,
    ))
    s.register_tool(ToolDescriptor(
        name="vault_get",
        description=(
            "Fetch one vault document INCLUDING its extracted full text. This is the "
            "grounding primitive: when discussing a contract or invoice, read the real "
            "text with this tool and quote from it — NEVER answer from assumptions "
            "about what such a document usually contains."
        ),
        parameters=[
            ToolParam(name="user_id", type="string",
                      description="The user_id provided in the conversation context."),
            ToolParam(name="doc_id", type="string",
                      description="Document id from vault_list / vault_search / the context index."),
        ],
        handler=_avault_get,
    ))

    # PUSH ─────────────────────────────────────────────────────────────
    s.register_tool(ToolDescriptor(
        name="broadcast_event",
        description=(
            "Publish an event onto the gateway EventBus → the CHATTING user's browser "
            "sessions receive it via /ws/feed. Pass user_id from [context] so the ping "
            "reaches only their tabs, not every tenant. Useful for streaming progress, "
            "approval-request notifications, or 'I'm done analysing' pings to the UI."
        ),
        parameters=[
            ToolParam(name="type", type="string",
                      description="Event envelope type. Frontend stream.js handles: "
                                  "agent_message, agent_response, portfolio_update, "
                                  "approval_request, error."),
            ToolParam(name="text", type="string",
                      description="Plain text for the chat panel (alternative to data).",
                      required=False),
            ToolParam(name="data", type="object",
                      description="Type-specific payload.", required=False),
            ToolParam(name="session_id", type="string",
                      description="Optional session correlation.", required=False),
            ToolParam(name="agent", type="string",
                      description="Speaking agent label.", required=False, default="winnywoo"),
            ToolParam(name="user_id", type="string", required=False,
                      description="The chatting user's id from [context] — targets their tabs."),
        ],
        handler=_abroadcast_event,
    ))

    return s


def main() -> None:
    """Entry point for mcp-winnywoo (console script)."""
    server = _build_server()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
