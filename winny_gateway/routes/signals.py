"""Live signals & risk endpoints.

Reads from ``public.trading_signals`` in Supabase — the durable rolling
ring populated by the background ``signal_runner_loop`` in
``gateway/analytics.py``. The MCP-tool path is kept as a best-effort
fallback for legacy timesfm/tradingagents installations.

Shape:
    GET /api/v1/signals/live    →  {ok, data: [{id, ts, symbol, source,
                                                side, confidence, ...},
                                               …]} sorted newest-first
    GET /api/v1/signals/risk    →  {ok, data: {portfolio: <snapshot>}}
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from winny_gateway.auth import get_current_user
from winny_gateway.logging import get_logger
from winny_gateway.routes.portfolio import _EMPTY_SNAPSHOT

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/signals", tags=["signals"])


def _looks_like_mcp_error(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if "jsonrpc" in value and "error" in value:
        return True
    return bool(value.get("isError"))


def _coerce_to_list(value: Any) -> list[dict[str, Any]]:
    """Best-effort MCP-response → list[dict]."""
    if _looks_like_mcp_error(value) or value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        for k in ("signals", "forecasts", "decisions", "items", "data"):
            if isinstance(value.get(k), list):
                return value[k]
    return []


@router.get("/live")
async def get_live_signals(
    request: Request,
    limit: int = Query(default=50, le=200),
    symbol: str | None = Query(default=None),
    source: str | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Latest signals from every source — flat list, newest first."""
    rows: list[dict[str, Any]] = []

    # Preferred path: Supabase trading_signals (populated by signal_runner_loop).
    try:
        from winny_gateway.db import get_admin_client

        client = get_admin_client()
        if client is not None:
            q = client.table("trading_signals").select("*").order("ts", desc=True).limit(limit)
            if symbol:
                q = q.eq("symbol", symbol.upper())
            if source:
                q = q.eq("source", source)
            r = q.execute()
            for row in (r.data or []):
                rows.append({
                    "id": row.get("id"),
                    "ts": row.get("ts"),
                    "symbol": row.get("symbol"),
                    "source": row.get("source"),
                    "side": row.get("side"),
                    "confidence": row.get("confidence"),
                    "horizon_hours": row.get("horizon_hours"),
                    "entry": row.get("entry"),
                    "stop": row.get("stop"),
                    "target": row.get("target"),
                    "indicators": row.get("indicators") or {},
                    "thesis": row.get("thesis"),
                    "note": row.get("thesis"),
                    "data": row.get("data") or {},
                })
    except Exception as exc:
        logger.warning("signals.live supabase query failed: %s", exc)

    # Fallback path: best-effort MCP, in case some installs have real timesfm.
    if not rows:
        pool = request.app.state.mcp_pool
        for kind, tool in (("forecaster", ("timesfm", "get_active_forecasts")),
                           ("analyst", ("tradingagents", "get_decision_history"))):
            try:
                raw = await pool.get(tool[0]).safe_call_tool(tool[1], {}, fallback=[])
                for entry in _coerce_to_list(raw):
                    entry.setdefault("source", kind)
                    rows.append(entry)
            except Exception:
                pass
        rows.sort(key=lambda x: str(x.get("ts", "")), reverse=True)

    return {"ok": True, "data": rows, "count": len(rows)}


@router.get("/risk")
async def get_risk_summary(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Portfolio risk metrics. Returns the snapshot directly (UI computes)."""
    pool = request.app.state.mcp_pool
    portfolio_raw = await pool.get("algo").safe_call_tool(
        "get_portfolio", {}, fallback=_EMPTY_SNAPSHOT
    )
    portfolio = portfolio_raw if not _looks_like_mcp_error(portfolio_raw) else dict(_EMPTY_SNAPSHOT)
    return {"ok": True, "data": {"portfolio": portfolio}}
