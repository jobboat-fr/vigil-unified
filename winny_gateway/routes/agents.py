"""Agent interaction endpoints — forecast, analysis, chat."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from winny_gateway.agent_contract import canonicalise_agent_symbol, extract_decision_id
from winny_gateway.auth import get_current_user
from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


class ForecastRequest(BaseModel):
    symbol: str
    horizon: int = 24


class AnalyzeRequest(BaseModel):
    symbol: str
    question: str | None = None


class DebateRequest(BaseModel):
    symbol: str | None = None
    decision_id: str | None = None
    question: str | None = None
    perspective: str = "bull"


class ChatRequest(BaseModel):
    message: str
    context: dict[str, Any] | None = None


@router.post("/forecast")
async def get_forecast(
    body: ForecastRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Get price forecast via mcp-timesfm."""
    pool = request.app.state.mcp_pool
    symbol = canonicalise_agent_symbol(body.symbol)
    logger.info(
        "Forecast requested",
        extra={"symbol": symbol, "action": "agents.forecast", "component": "agents"},
    )
    result = await pool.get("timesfm").call_tool(
        "forecast_symbol",
        {
            "symbol": symbol,
            "horizon_bars": body.horizon,
        },
    )
    return {"ok": True, "data": result}


@router.post("/analyze")
async def analyze_symbol(
    body: AnalyzeRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Run multi-agent analysis via mcp-tradingagents."""
    pool = request.app.state.mcp_pool
    symbol = canonicalise_agent_symbol(body.symbol)
    logger.info(
        "Analysis requested",
        extra={"symbol": symbol, "action": "agents.analyze", "component": "agents"},
    )
    result = await pool.get("tradingagents").call_tool(
        "analyze_symbol",
        {
            "symbol": symbol,
        },
    )
    return {"ok": True, "data": result}


@router.post("/debate")
async def debate_position(
    body: DebateRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Run agent debate.

    The MCP debate tool debates a prior decision. For symbol-only UI requests,
    create an analysis decision first, then debate that decision.
    """
    pool = request.app.state.mcp_pool
    question = body.question or "Debate the bullish and bearish case for this decision."
    logger.info(
        "Debate requested",
        extra={
            "symbol": body.symbol,
            "decision_id": body.decision_id,
            "action": "agents.debate",
            "component": "agents",
        },
    )

    if body.decision_id:
        result = await pool.get("tradingagents").call_tool(
            "debate_position",
            {
                "decision_id": body.decision_id,
                "user_question": question,
                "perspective": body.perspective,
            },
        )
        return {"ok": True, "data": result}

    if not body.symbol:
        raise HTTPException(status_code=422, detail="debate requires either decision_id or symbol")

    symbol = canonicalise_agent_symbol(body.symbol)
    analysis = await pool.get("tradingagents").call_tool("analyze_symbol", {"symbol": symbol})
    decision_id = extract_decision_id(analysis)
    if not decision_id:
        return {"ok": True, "data": analysis}

    debate = await pool.get("tradingagents").call_tool(
        "debate_position",
        {
            "decision_id": decision_id,
            "user_question": question,
            "perspective": body.perspective,
        },
    )
    return {"ok": True, "data": {"analysis": analysis, "debate": debate}}


@router.get("/status")
async def get_agent_status(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Return status of all agent MCP servers."""
    pool = request.app.state.mcp_pool
    statuses = {}
    for name in ("algo", "approval", "timesfm", "tradingagents"):
        try:
            bridge = pool.get(name)
            tools = await bridge.list_tools()
            statuses[name] = {"status": "online", "tools": len(tools.get("tools", []))}
        except Exception as exc:
            logger.warning(
                "MCP server offline: %s",
                name,
                extra={"action": "agents.status_check", "error": str(exc), "component": "agents"},
            )
            statuses[name] = {"status": "offline", "error": str(exc)}
    return {"ok": True, "data": statuses}
