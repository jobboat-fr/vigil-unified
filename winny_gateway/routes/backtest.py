"""Backtesting endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from winny_gateway.auth import get_current_user
from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/backtest", tags=["backtest"])


class BacktestRequest(BaseModel):
    strategy: str
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float = 100_000.0
    timeframe: str = "1d"
    params: dict[str, Any] | None = None


@router.post("/run")
async def run_backtest(
    body: BacktestRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Launch a backtest via mcp-algo run_backtest tool."""
    pool = request.app.state.mcp_pool
    logger.info(
        "Backtest launched",
        extra={
            "action": "backtest.run", "symbol": body.symbol,
            "component": "backtest",
        },
    )
    result = await pool.get("algo").call_tool("run_backtest", {
        "strategy": body.strategy,
        "symbol": body.symbol,
        "start_date": body.start_date,
        "end_date": body.end_date,
        "initial_capital": body.initial_capital,
        "timeframe": body.timeframe,
        "params": body.params or {},
    })
    return {"ok": True, "data": result}


@router.get("/strategies")
async def list_strategies(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """List available strategies."""
    return {
        "ok": True,
        "data": [
            {"id": "sma_cross", "name": "SMA Crossover", "description": "Classic dual-MA trend following"},
            {"id": "markov_rad", "name": "Markov Radiation", "description": "Spectral regime + probability diffusion"},
        ],
    }
