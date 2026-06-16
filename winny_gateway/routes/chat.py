"""AI Chat orchestrator — server-side NL intent routing to MCP tools.

The frontend sends natural language; this endpoint classifies intent,
calls the correct MCP tool(s), and returns a structured response the
Chat UI can render.

Supported intents:
  PORTFOLIO   — show positions / balance / NAV
  OPEN_ORDERS — list open orders
  FORECAST    — run TimesFM forecast on a symbol
  ANALYZE     — run multi-agent analysis
  DEBATE      — run agent debate on a symbol
  BUY / SELL  — prepare an OrderIntent (enters approval flow)
  CANCEL      — cancel a specific order
  CANCEL_ALL  — kill switch — cancel all open orders
  RISK        — portfolio risk summary
  SIGNALS     — live signals overview
  AGENT_STATUS— check MCP server health
  BACKTEST    — list available strategies or describe backtest
  BROKER      — show/switch crypto broker
  HELP        — list capabilities
  UNKNOWN     — fallback — route to tradingagents for best-effort analysis
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from winny_gateway.agent_contract import extract_decision_id
from winny_gateway.auth import get_current_user
from winny_gateway.logging import get_logger
from winny.common.sanitise import (
    MAX_CHAT_LENGTH,
    check_prompt_injection,
    sanitise_text,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


# ─── Request / Response ──────────────────────────────────────────────────────


class ChatMessage(BaseModel):
    message: str = Field(max_length=MAX_CHAT_LENGTH)
    context: dict[str, Any] | None = None


class ChatResponse(BaseModel):
    intent: str
    reply: str
    data: Any | None = None
    actions: list[dict[str, Any]] | None = None
    followup: str | None = None


# ─── Symbol extraction patterns ──────────────────────────────────────────────

_CRYPTO_PAT = re.compile(r"\b([A-Z]{2,10})\s*/\s*([A-Z]{2,10})\b", re.IGNORECASE)
_EQUITY_PAT = re.compile(r"\b(?:stock|equity|ticker)\s+([A-Z]{1,6})\b", re.IGNORECASE)
_SYMBOL_WORD = re.compile(
    r"\b(BTC|ETH|SOL|XRP|DOGE|ADA|AVAX|DOT|LINK|MATIC|NVDA|AAPL|TSLA|MSFT|GOOG|AMZN|META)\b",
    re.IGNORECASE,
)

# ─── Intent classifier ───────────────────────────────────────────────────────

_INTENT_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("CANCEL_ALL", re.compile(r"\b(cancel\s*all|kill\s*switch|kill\s*all|panic)\b", re.I)),
    ("CANCEL", re.compile(r"\b(cancel)\b.*\b(order|position)\b", re.I)),
    ("BUY", re.compile(r"\b(buy|long|enter\s*long|go\s*long|open\s*long)\b", re.I)),
    ("SELL", re.compile(r"\b(sell|short|enter\s*short|go\s*short|exit|close)\b", re.I)),
    (
        "FORECAST",
        re.compile(r"\b(forecast|predict|prediction|price\s*target|where.*going)\b", re.I),
    ),
    ("DEBATE", re.compile(r"\b(debate|should\s*i|bull.*bear|pros?\s*(and|&)\s*cons?)\b", re.I)),
    ("ANALYZE", re.compile(r"\b(analy[zs]e|analysis|assess|evaluate|research)\b", re.I)),
    ("RISK", re.compile(r"\b(risk|exposure|var|drawdown|volatil)\b", re.I)),
    (
        "PORTFOLIO",
        re.compile(r"\b(portfolio|balance|nav|holdings|my\s*positions?|show\s*positions?)\b", re.I),
    ),
    ("OPEN_ORDERS", re.compile(r"\b(open\s*orders?|pending\s*orders?|active\s*orders?)\b", re.I)),
    ("SIGNALS", re.compile(r"\b(signal|signals|live\s*signal|latest\s*signal)\b", re.I)),
    ("AGENT_STATUS", re.compile(r"\b(agent\s*status|server\s*status|health|mcp\s*status)\b", re.I)),
    ("BACKTEST", re.compile(r"\b(backtest|back\s*test|strateg(y|ies))\b", re.I)),
    (
        "BROKER",
        re.compile(
            r"\b(broker|exchange|switch\s*(to\s*)?broker|which\s*broker|current\s*broker|use\s*kraken|use\s*binance|use\s*coinbase|use\s*okx|use\s*bybit|use\s*gate)\b",
            re.I,
        ),
    ),
    ("HELP", re.compile(r"\b(help|what\s*can\s*you|capabilities|commands)\b", re.I)),
]


def _classify_intent(text: str) -> str:
    for intent, pattern in _INTENT_RULES:
        if pattern.search(text):
            return intent
    return "UNKNOWN"


def _extract_symbol(text: str) -> str | None:
    """Extract a canonical symbol from freeform text."""
    m = _CRYPTO_PAT.search(text)
    if m:
        base, quote = m.group(1).upper(), m.group(2).upper()
        return f"CR:{base}-{quote}@binance"

    m = _EQUITY_PAT.search(text)
    if m:
        return f"EQ:{m.group(1).upper()}"

    m = _SYMBOL_WORD.search(text)
    if m:
        ticker = m.group(1).upper()
        cryptos = {"BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "DOT", "LINK", "MATIC"}
        if ticker in cryptos:
            return f"CR:{ticker}-USDT@binance"
        return f"EQ:{ticker}"

    return None


def _extract_quantity(text: str) -> str | None:
    """Extract a numeric quantity from text."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:shares?|units?|coins?|tokens?)?", text, re.I)
    if m:
        return m.group(1)
    return None


def _extract_horizon(text: str) -> int:
    m = re.search(r"(\d+)\s*(?:hour|hr|h)\b", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*(?:day|d)\b", text, re.I)
    if m:
        return int(m.group(1)) * 24
    return 24


# ─── Intent handlers ─────────────────────────────────────────────────────────


async def _handle_portfolio(pool: Any, _msg: str, _ctx: dict[str, Any] | None) -> ChatResponse:
    snapshot = await pool.get("algo").safe_call_tool(
        "get_portfolio",
        {},
        fallback={
            "nav": "0",
            "positions": [],
            "balances": {},
            "open_orders_count": 0,
        },
    )
    positions = snapshot.get("positions", []) if isinstance(snapshot, dict) else []
    nav = snapshot.get("nav", "0") if isinstance(snapshot, dict) else "0"
    n = len(positions)
    reply = f"Your portfolio NAV is **${nav}** with **{n}** open position{'s' if n != 1 else ''}."
    if n > 0:
        lines = []
        for p in positions[:10]:
            sym = p.get("symbol", "?")
            qty = p.get("qty", "?")
            pnl = p.get("unrealized_pnl", "?")
            lines.append(f"  • {sym}: {qty} units (PnL: {pnl})")
        reply += "\n" + "\n".join(lines)
    return ChatResponse(intent="PORTFOLIO", reply=reply, data=snapshot)


async def _handle_open_orders(pool: Any, _msg: str, _ctx: dict[str, Any] | None) -> ChatResponse:
    orders = await pool.get("algo").safe_call_tool("get_open_orders", {}, fallback=[])
    if isinstance(orders, dict) and "error" in orders:
        orders = []
    n = len(orders) if isinstance(orders, list) else 0
    if n == 0:
        reply = "No open orders."
    else:
        reply = f"You have **{n}** open order{'s' if n != 1 else ''}:\n"
        for o in orders[:10]:
            reply += f"  • {o.get('symbol', '?')} {o.get('side', '?')} {o.get('qty', '?')} — {o.get('status', '?')}\n"
    return ChatResponse(intent="OPEN_ORDERS", reply=reply, data=orders)


async def _handle_forecast(pool: Any, msg: str, _ctx: dict[str, Any] | None) -> ChatResponse:
    symbol = _extract_symbol(msg)
    if not symbol:
        return ChatResponse(
            intent="FORECAST",
            reply="Which symbol should I forecast? Example: *forecast BTC/USDT 24h*",
        )
    horizon = _extract_horizon(msg)
    result = await pool.get("timesfm").call_tool(
        "forecast_symbol",
        {
            "symbol": symbol,
            "horizon_bars": horizon,
        },
    )
    if isinstance(result, dict) and "error" in result:
        return ChatResponse(
            intent="FORECAST",
            reply=f"Forecast failed: {result['error']}",
            data=result,
        )
    return ChatResponse(
        intent="FORECAST",
        reply=f"**{symbol}** forecast ({horizon} bars):\n\nTimesFM model returned predictions. See data below.",
        data=result,
        followup=f"Want me to analyze {symbol} with the multi-agent debate?",
    )


async def _handle_analyze(pool: Any, msg: str, _ctx: dict[str, Any] | None) -> ChatResponse:
    symbol = _extract_symbol(msg)
    if not symbol:
        return ChatResponse(
            intent="ANALYZE",
            reply="Which symbol should I analyze? Example: *analyze ETH/USDT*",
        )
    result = await pool.get("tradingagents").call_tool("analyze_symbol", {"symbol": symbol})
    if isinstance(result, dict) and "error" in result:
        return ChatResponse(
            intent="ANALYZE", reply=f"Analysis failed: {result['error']}", data=result
        )
    return ChatResponse(
        intent="ANALYZE",
        reply=f"**Multi-agent analysis for {symbol}** complete. See detailed report below.",
        data=result,
        followup="Want me to prepare an order based on this analysis?",
    )


async def _handle_debate(pool: Any, msg: str, _ctx: dict[str, Any] | None) -> ChatResponse:
    symbol = _extract_symbol(msg)
    if not symbol:
        return ChatResponse(
            intent="DEBATE",
            reply="Which symbol should I debate? Example: *should I go long BTC/USDT?*",
        )
    analysis = await pool.get("tradingagents").call_tool("analyze_symbol", {"symbol": symbol})
    decision_id = extract_decision_id(analysis)
    if not decision_id:
        return ChatResponse(
            intent="DEBATE",
            reply="Debate failed: I could not create an analysis decision to debate.",
            data=analysis,
        )

    result = await pool.get("tradingagents").call_tool(
        "debate_position",
        {
            "decision_id": decision_id,
            "user_question": msg,
            "perspective": "bull",
        },
    )
    if isinstance(result, dict) and "error" in result:
        return ChatResponse(intent="DEBATE", reply=f"Debate failed: {result['error']}", data=result)
    return ChatResponse(
        intent="DEBATE",
        reply=f"**Agent debate for {symbol}** — bull vs bear analysis complete.",
        data={"analysis": analysis, "debate": result},
        followup="Ready to take action? Say *buy* or *sell* to prepare an order.",
    )


async def _handle_buy_sell(
    pool: Any, msg: str, ctx: dict[str, Any] | None, side: str
) -> ChatResponse:
    """Prepare an OrderIntent through the approval flow.

    This does NOT execute immediately — it creates a pending approval
    that the user must verify before the order hits the broker.
    """
    symbol = _extract_symbol(msg)
    if not symbol:
        return ChatResponse(
            intent=side,
            reply=f"Which symbol do you want to {side.lower()}? Example: *{side.lower()} 0.5 BTC/USDT*",
        )

    qty = _extract_quantity(msg)
    if not qty:
        return ChatResponse(
            intent=side,
            reply=f"How much {symbol} do you want to {side.lower()}? Example: *{side.lower()} 0.1 {symbol}*",
        )

    # Step 1: Prepare the order via mcp-algo (sizing, NAV cap)
    signal_type = "ENTER_LONG" if side == "BUY" else "ENTER_SHORT"
    if re.search(r"\b(exit|close|sell\s*all|sell\s*position)\b", msg, re.I):
        signal_type = "EXIT_LONG" if side == "SELL" else "EXIT_SHORT"

    prepare_result = await pool.get("algo").call_tool(
        "prepare_order",
        {
            "signal": {"type": signal_type, "symbol": symbol},
            "ref_price": "0",  # will use market price
            "sizing_params": {"qty_override": qty},
        },
    )
    if isinstance(prepare_result, dict) and "error" in prepare_result:
        return ChatResponse(
            intent=side,
            reply=f"Order preparation failed: {prepare_result['error']}",
            data=prepare_result,
        )

    # Step 2: Create approval request
    intent_data = prepare_result if isinstance(prepare_result, dict) else {}
    decision_id = intent_data.get("decision_id", "")
    summary = f"{side} {qty} {symbol} @ MARKET"

    approval_result = await pool.get("approval").call_tool(
        "request",
        {
            "decision_id": decision_id or "dec_chat",
            "order_intent": intent_data,
            "ttl_seconds": 300,
            "summary": summary,
        },
    )

    if isinstance(approval_result, dict) and "error" in approval_result:
        return ChatResponse(
            intent=side,
            reply=f"Approval request failed: {approval_result['error']}",
            data=approval_result,
        )

    approval_id = (
        approval_result.get("approval_id", "") if isinstance(approval_result, dict) else ""
    )
    code = approval_result.get("one_time_code", "") if isinstance(approval_result, dict) else ""
    expires = approval_result.get("expires_at", "") if isinstance(approval_result, dict) else ""

    return ChatResponse(
        intent=side,
        reply=(
            f"**Order prepared:** {summary}\n\n"
            f"**Approval required.** Enter code **`{code}`** to confirm.\n"
            f"Approval ID: `{approval_id}`\n"
            f"Expires: {expires}\n\n"
            f"_Go to the Approve page or reply with the code to execute._"
        ),
        data={
            "order_intent": intent_data,
            "approval": approval_result,
        },
        actions=[
            {
                "type": "approval_pending",
                "approval_id": approval_id,
                "one_time_code": code,
                "summary": summary,
            }
        ],
        followup="Reply with the 6-character code to confirm, or say *cancel* to abort.",
    )


async def _handle_cancel(pool: Any, msg: str, _ctx: dict[str, Any] | None) -> ChatResponse:
    # Try to extract an order ID from the message
    m = re.search(r"\b(ord_[a-zA-Z0-9]+)\b", msg)
    if not m:
        return ChatResponse(
            intent="CANCEL",
            reply="Which order should I cancel? Provide the order ID, or say *cancel all* to cancel everything.",
        )
    return ChatResponse(
        intent="CANCEL",
        reply=(
            f"To cancel order `{m.group(1)}`, you need to go through the approval flow.\n"
            "Navigate to **Orders** page and cancel from there, or say *cancel all*."
        ),
    )


async def _handle_cancel_all(pool: Any, _msg: str, _ctx: dict[str, Any] | None) -> ChatResponse:
    result = await pool.get("algo").call_tool("cancel_all", {})
    if isinstance(result, dict) and "error" in result:
        return ChatResponse(
            intent="CANCEL_ALL", reply=f"Cancel-all failed: {result['error']}", data=result
        )
    return ChatResponse(
        intent="CANCEL_ALL",
        reply="**Kill switch activated.** All open orders have been cancelled.",
        data=result,
    )


async def _handle_risk(pool: Any, _msg: str, _ctx: dict[str, Any] | None) -> ChatResponse:
    portfolio = await pool.get("algo").safe_call_tool(
        "get_portfolio",
        {},
        fallback={
            "nav": "0",
            "positions": [],
            "balances": {},
        },
    )
    return ChatResponse(
        intent="RISK",
        reply="**Risk summary** based on current portfolio. See data below.",
        data={"portfolio": portfolio},
    )


async def _handle_signals(pool: Any, _msg: str, _ctx: dict[str, Any] | None) -> ChatResponse:
    forecasts = await pool.get("timesfm").safe_call_tool("get_active_forecasts", {}, fallback=[])
    analyses = await pool.get("tradingagents").safe_call_tool(
        "get_decision_history", {}, fallback=[]
    )
    n_f = len(forecasts) if isinstance(forecasts, list) else 0
    n_a = len(analyses.get("decisions", [])) if isinstance(analyses, dict) else 0
    return ChatResponse(
        intent="SIGNALS",
        reply=f"**Live signals:** {n_f} active forecast{'s' if n_f != 1 else ''}, {n_a} agent decision{'s' if n_a != 1 else ''}.",
        data={"forecasts": forecasts, "analyses": analyses},
    )


async def _handle_agent_status(pool: Any, _msg: str, _ctx: dict[str, Any] | None) -> ChatResponse:
    statuses: dict[str, Any] = {}
    for name in ("algo", "approval", "timesfm", "tradingagents"):
        try:
            bridge = pool.get(name)
            tools = await bridge.list_tools()
            statuses[name] = {"status": "online", "tools": len(tools.get("tools", []))}
        except Exception as exc:
            statuses[name] = {"status": "offline", "error": str(exc)}
    online = sum(1 for s in statuses.values() if s["status"] == "online")
    reply = f"**{online}/4 MCP servers online:**\n"
    for name, s in statuses.items():
        icon = "🟢" if s["status"] == "online" else "🔴"
        reply += f"  {icon} **{name}** — {s['status']}"
        if s["status"] == "online":
            reply += f" ({s['tools']} tools)"
        reply += "\n"
    return ChatResponse(intent="AGENT_STATUS", reply=reply, data=statuses)


async def _handle_backtest(pool: Any, _msg: str, _ctx: dict[str, Any] | None) -> ChatResponse:
    return ChatResponse(
        intent="BACKTEST",
        reply=(
            "**Available strategies:**\n"
            "  1. **SMA Crossover** — Classic dual-MA trend following\n"
            "  2. **Markov Radiation** — Spectral regime + probability diffusion\n\n"
            "Go to the **Backtest** page to configure and run, "
            "or tell me a symbol and strategy to set up."
        ),
    )


async def _handle_broker(_pool: Any, msg: str, _ctx: dict[str, Any] | None) -> ChatResponse:
    """Handle broker queries — show current or switch."""
    import os

    from winny_gateway.routes.settings import BROKER_IDS, SUPPORTED_BROKERS

    # Check if user wants to switch
    switch_match = re.search(
        r"\b(?:switch|change|use|set)\s*(?:to\s*)?(?:broker\s*)?"
        r"(binance|kraken|coinbase|okx|bybit|gate)\b",
        msg,
        re.I,
    )
    if switch_match:
        target = switch_match.group(1).lower()
        if target in BROKER_IDS:
            old = os.environ.get("WINNY_BROKER_CR", "binance").lower()
            os.environ["WINNY_BROKER_CR"] = target
            return ChatResponse(
                intent="BROKER",
                reply=f"Switched crypto broker from **{old}** to **{target}**. All future CR: orders will route through {target}.",
                data={"broker_cr": target, "previous": old},
                followup="You can verify on the **Settings** page.",
            )

    current = os.environ.get("WINNY_BROKER_CR", "binance").lower()
    broker_list = ", ".join(b["id"] for b in SUPPORTED_BROKERS)
    return ChatResponse(
        intent="BROKER",
        reply=(
            f"Your current crypto broker is **{current}**.\n\n"
            f"Available brokers: {broker_list}\n\n"
            f"To switch, say *use kraken* or *switch to coinbase*, "
            f"or go to the **Settings** page to select one."
        ),
        data={"broker_cr": current, "supported": [b["id"] for b in SUPPORTED_BROKERS]},
    )


async def _handle_help(_pool: Any, _msg: str, _ctx: dict[str, Any] | None) -> ChatResponse:
    return ChatResponse(
        intent="HELP",
        reply=(
            "**I can help you with:**\n\n"
            "**Trading:**\n"
            "  - *buy 0.5 BTC/USDT* — prepare a buy order (goes through approval)\n"
            "  - *sell 100 NVDA* — prepare a sell order\n"
            "  - *cancel all* — kill switch, cancel all open orders\n\n"
            "**Analysis:**\n"
            "  - *forecast ETH/USDT 48h* — TimesFM price prediction\n"
            "  - *analyze SOL/USDT* — full multi-agent analysis\n"
            "  - *should I go long BTC?* — bull vs bear debate\n\n"
            "**Portfolio:**\n"
            "  - *show my positions* — current holdings & NAV\n"
            "  - *open orders* — pending orders\n"
            "  - *risk exposure* — portfolio risk summary\n"
            "  - *live signals* — active forecasts & decisions\n\n"
            "**System:**\n"
            "  - *agent status* — check MCP server health\n"
            "  - *backtest strategies* — available strategies\n"
            "  - *which broker* — show current crypto broker\n"
            "  - *use kraken* — switch crypto broker\n"
        ),
    )


async def _handle_unknown(pool: Any, msg: str, _ctx: dict[str, Any] | None) -> ChatResponse:
    """Fallback: try tradingagents analyze_symbol if a symbol is present,
    otherwise return a helpful prompt."""
    symbol = _extract_symbol(msg)
    if symbol:
        result = await pool.get("tradingagents").call_tool("analyze_symbol", {"symbol": symbol})
        if isinstance(result, dict) and "error" not in result:
            return ChatResponse(
                intent="ANALYZE",
                reply=f"I interpreted that as an analysis request for **{symbol}**. Here are the results:",
                data=result,
            )
    return ChatResponse(
        intent="UNKNOWN",
        reply=(
            "I'm not sure what you mean. Try one of these:\n"
            "  - *buy / sell* — place orders\n"
            "  - *forecast / analyze* — AI analysis\n"
            "  - *show positions* — portfolio overview\n"
            "  - *help* — full list of commands"
        ),
    )


# ─── Handler dispatch ─────────────────────────────────────────────────────────

_HANDLERS: dict[str, Any] = {
    "PORTFOLIO": _handle_portfolio,
    "OPEN_ORDERS": _handle_open_orders,
    "FORECAST": _handle_forecast,
    "ANALYZE": _handle_analyze,
    "DEBATE": _handle_debate,
    "CANCEL": _handle_cancel,
    "CANCEL_ALL": _handle_cancel_all,
    "RISK": _handle_risk,
    "SIGNALS": _handle_signals,
    "AGENT_STATUS": _handle_agent_status,
    "BACKTEST": _handle_backtest,
    "BROKER": _handle_broker,
    "HELP": _handle_help,
    "UNKNOWN": _handle_unknown,
}


# ─── Route ────────────────────────────────────────────────────────────────────


@router.post("/message")
async def chat_message(
    body: ChatMessage,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Process a natural language chat message.

    Classifies intent, routes to the correct MCP tool(s), and returns a
    structured response with reply text + optional structured data.
    """
    pool = request.app.state.mcp_pool
    text = sanitise_text(body.message)

    if not text:
        return {
            "ok": True,
            "data": ChatResponse(
                intent="HELP", reply="Send me a message! Type *help* to see what I can do."
            ).model_dump(),
        }

    # Prompt injection detection
    threat = check_prompt_injection(text)
    if threat is not None:
        logger.warning(
            "Prompt injection blocked: %s",
            threat.pattern_name,
            extra={
                "action": "security.prompt_injection",
                "pattern": threat.pattern_name,
                "matched": threat.matched_text[:80],
                "component": "chat",
            },
        )
        return {
            "ok": True,
            "data": ChatResponse(
                intent="BLOCKED",
                reply="I can't process that message. Please rephrase your request.",
            ).model_dump(),
        }

    intent = _classify_intent(text)
    logger.info(
        "Chat intent: %s",
        intent,
        extra={"action": "chat.intent", "component": "chat"},
    )

    # BUY and SELL share a handler
    if intent == "BUY":
        resp = await _handle_buy_sell(pool, text, body.context, "BUY")
    elif intent == "SELL":
        resp = await _handle_buy_sell(pool, text, body.context, "SELL")
    else:
        handler = _HANDLERS.get(intent, _handle_unknown)
        resp = await handler(pool, text, body.context)

    # Mirror to this user's other live sockets only — a chat reply can carry
    # their positions/balances, so it must never fan out to other tenants.
    request.app.state.event_bus.publish(
        {
            "type": "chat_response",
            "intent": resp.intent,
            "reply": resp.reply,
        },
        user_id=user.get("sub") if isinstance(user, dict) else None,
    )

    return {"ok": True, "data": resp.model_dump()}
