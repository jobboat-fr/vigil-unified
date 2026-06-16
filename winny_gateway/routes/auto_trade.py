"""Auto-trade mode — PRO tier strategy automation.

Endpoints:
  GET  /api/v1/auto-trade          — get user's auto-trade configuration
  PUT  /api/v1/auto-trade          — update auto-trade configuration
  POST /api/v1/auto-trade/toggle   — enable/disable auto-trade
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from winny_gateway.auth import get_current_user
from winny_gateway.db import db_select, db_upsert
from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/auto-trade", tags=["auto-trade"])

# In-memory store (backed by Supabase in production)
_auto_trade_configs: dict[str, dict[str, Any]] = {}


async def _require_pro(uid: str) -> None:
    """Raise 403 if user is not on the Pro tier."""
    rows = await db_select("user_preferences", filters={"user_id": uid}, columns="tier", limit=1)
    tier = (rows[0].get("tier", "lite") if rows else "lite").lower()
    if tier != "pro":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Auto-trade requires a Pro subscription.",
        )


class AutoTradeConfig(BaseModel):
    enabled: bool = False
    strategy_id: str = ""
    max_daily_trades: int = Field(default=5, ge=1, le=50)
    max_position_pct: float = Field(default=5.0, ge=0.5, le=25.0)
    stop_loss_pct: float = Field(default=5.0, ge=1.0, le=50.0)
    take_profit_pct: float = Field(default=10.0, ge=1.0, le=100.0)
    risk_level: str = "moderate"
    symbols: list[str] = Field(default_factory=lambda: ["BTC-USDT", "ETH-USDT"])


class ToggleRequest(BaseModel):
    enabled: bool


@router.get("")
async def get_auto_trade_config(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    uid = user["sub"]
    config = _auto_trade_configs.get(uid)
    if not config:
        # Try DB
        rows = await db_select("auto_trade_config", filters={"user_id": uid})
        row = rows[0] if rows else None
        if row:
            config = row
            _auto_trade_configs[uid] = row
        else:
            config = AutoTradeConfig().model_dump()
    return {"ok": True, "data": config}


@router.put("")
async def update_auto_trade_config(
    body: AutoTradeConfig,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    uid = user["sub"]
    await _require_pro(uid)
    data = body.model_dump()
    data["user_id"] = uid
    _auto_trade_configs[uid] = data
    await db_upsert("auto_trade_config", data, on_conflict="user_id")
    logger.info(
        "Auto-trade config updated",
        extra={"user_id": uid, "enabled": data["enabled"], "component": "auto_trade"},
    )
    return {"ok": True, "data": data}


@router.post("/toggle")
async def toggle_auto_trade(
    body: ToggleRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    uid = user["sub"]
    if body.enabled:
        await _require_pro(uid)
    config = _auto_trade_configs.get(uid, AutoTradeConfig().model_dump())
    config["enabled"] = body.enabled
    config["user_id"] = uid
    _auto_trade_configs[uid] = config
    await db_upsert("auto_trade_config", config, on_conflict="user_id")
    logger.info(
        "Auto-trade toggled",
        extra={"user_id": uid, "enabled": body.enabled, "component": "auto_trade"},
    )
    return {"ok": True, "data": {"enabled": body.enabled}}
