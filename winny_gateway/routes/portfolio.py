"""Portfolio & positions endpoints.

Tries to fetch real data from the user's connected exchange first.
Falls back to MCP tools if no live broker credentials are available.
Fallbacks are shape-correct empty objects/lists so the frontend's normal
render path always works even when both are offline.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from winny_gateway.auth import effective_user as _effective_user, get_current_user
from winny_gateway.logging import get_logger
from winny_gateway.routes.settings import _get_prefs, _load_decrypted_credentials_from_db
from winny.brokerage.credentials import credential_store
from winny.brokerage.env_creds import get_env_creds_for

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])

_EMPTY_SNAPSHOT: dict[str, Any] = {
    "asof": None,
    "balances": {},
    "positions": [],
    "nav": "0",
    "nav_currency": "USD",
    "open_orders_count": 0,
    "unpriced_positions": [],
}


def _resolve_broker_creds(user: dict[str, Any]) -> tuple[str, dict[str, str]] | tuple[str, None]:
    """Resolve the caller's broker + decrypted credentials.

    Credential resolution order:
      1. Per-user encrypted creds in Supabase (the normal path — Settings UI)
      2. Owner-gated env-var fallback (Railway / OVH) when the caller's
         email matches `<BROKER>_KEY_OWNER_EMAIL`. Other users never see
         the env creds.
    """
    user_id = user.get("sub", "anon")
    prefs = _get_prefs(user_id)
    broker_id = prefs.get("broker_cr", "binance")

    creds = credential_store.get_decrypted(user_id, broker_id)
    if not creds:
        creds = _load_decrypted_credentials_from_db(user_id, broker_id)
    if not creds:
        # Owner-gated env-var fallback — only if the caller owns the key.
        creds = get_env_creds_for(user, broker_id)
    return broker_id, creds


def _try_live_snapshot(user: dict[str, Any]) -> dict[str, Any] | None:
    """Attempt to fetch portfolio from the live broker. Returns None if unavailable."""
    broker_id, creds = _resolve_broker_creds(user)
    if not creds:
        return None

    try:
        from winny.brokerage.ccxt_adapter import CcxtBrokerage

        broker = CcxtBrokerage(
            venue=broker_id,
            api_key=creds["api_key"],
            secret=creds.get("api_secret", ""),
            password=creds.get("api_password", ""),
        )
        balances = broker.get_balance()

        position_error: str | None = None
        try:
            positions = broker.get_positions()
        except Exception as e:
            position_error = str(e)
            positions = []
            logger.debug(
                "Live positions unavailable; keeping balances in snapshot: %s",
                e,
                extra={"action": "portfolio.positions_fail", "component": "portfolio"},
            )

        open_orders_count = 0
        order_error: str | None = None
        with contextlib.suppress(AttributeError):
            try:
                open_orders_count = len(broker._exchange.fetch_open_orders())
            except Exception as e:
                order_error = str(e)
                logger.debug(
                    "Live open orders unavailable; keeping balances in snapshot: %s",
                    e,
                    extra={"action": "portfolio.orders_fail", "component": "portfolio"},
                )

        from winny.common.ids import Currency

        balance_dict = {str(k): str(v) for k, v in balances.items()}
        stablecoin_keys = [Currency("USDT"), Currency("USDC"), Currency("USD"), Currency("BUSD")]
        nav = sum(
            float(balances.get(c, 0))
            for c in stablecoin_keys
            if c in balances
        )

        position_list = [
            {
                "symbol": p.symbol.canonical(),
                "qty": str(p.qty),
                "avg_entry_price": str(p.avg_entry_price),
                "unrealized_pnl": str(p.unrealized_pnl),
            }
            for p in positions
        ]

        return {
            "asof": datetime.now(UTC).isoformat(),
            "connected": True,
            "balances": balance_dict,
            "positions": position_list,
            "nav": str(Decimal(str(nav)).quantize(Decimal("0.01"))),
            "nav_currency": "USD",
            "open_orders_count": open_orders_count,
            "unpriced_positions": [],
            "source": "live",
            "broker": broker_id,
            "asset_count": len(balance_dict),
            "position_count": len(position_list),
            "order_count": open_orders_count,
            "position_error": position_error,
            "order_error": order_error,
        }
    except Exception as e:
        logger.debug(
            "Live snapshot failed, falling back to MCP: %s", e,
            extra={"action": "portfolio.live_fail", "component": "portfolio"},
        )
        return None


@router.get("/snapshot")
async def get_portfolio_snapshot(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Return current portfolio snapshot.

    Priority: live broker connection → MCP tools → empty fallback.
    """
    user = _effective_user(request, user)
    user_id = user.get("sub", "anon")

    # Try live broker first
    live = _try_live_snapshot(user)
    if live:
        # Persist snapshot to Supabase (fire-and-forget)
        await _save_snapshot_to_db(user_id, live)
        return {"ok": True, "data": live}

    # Fallback to MCP
    pool = request.app.state.mcp_pool
    result = await pool.get("algo").safe_call_tool("get_portfolio", {}, fallback=_EMPTY_SNAPSHOT)
    return {"ok": True, "data": result}


@router.get("/positions")
async def get_positions(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Return open positions — live broker first, MCP fallback."""
    live = _try_live_snapshot(_effective_user(request, user))
    if live:
        return {"ok": True, "data": {"positions": live.get("positions", [])}}

    pool = request.app.state.mcp_pool
    result = await pool.get("algo").safe_call_tool("get_portfolio", {}, fallback=_EMPTY_SNAPSHOT)
    return {"ok": True, "data": result}


def _normalize_trade(t: dict[str, Any]) -> dict[str, Any]:
    """CCXT unified trade → compact row for the UI.

    ``amount``/``datetime`` mirror ``qty``/``ts`` so older consumers of the
    legacy /broker/trades shape keep working off the same rows.
    """
    fee = t.get("fee") or {}
    ts = t.get("datetime")
    qty = t.get("amount")
    return {
        "id": t.get("id"),
        "order_id": t.get("order"),
        "ts": ts,
        "datetime": ts,
        "symbol": t.get("symbol"),
        "side": t.get("side"),
        "type": t.get("type"),
        "taker_or_maker": t.get("takerOrMaker"),
        "price": t.get("price"),
        "qty": qty,
        "amount": qty,
        "cost": t.get("cost"),
        "fee": fee.get("cost"),
        "fee_currency": fee.get("currency"),
    }


async def fetch_live_trades(
    user: dict[str, Any],
    *,
    limit: int = 50,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Fetch fills straight from the connected exchange (CCXT).

    The single trade-history implementation behind /portfolio/trades,
    /orders/trades, and /broker/trades — the broker is the source of
    truth, we never maintain a shadow ledger. Returns the full response
    envelope so the three routes stay byte-identical.
    """
    import asyncio

    broker_id, creds = _resolve_broker_creds(user)
    if not creds:
        return {
            "ok": True,
            "data": {"trades": [], "broker": broker_id, "connected": False, "count": 0},
        }

    def _sync_fetch() -> list[dict[str, Any]]:
        from winny.brokerage.ccxt_adapter import CcxtBrokerage

        broker = CcxtBrokerage(
            venue=broker_id,
            api_key=creds["api_key"],
            secret=creds.get("api_secret", ""),
            password=creds.get("api_password", ""),
        )
        ex = broker._exchange
        ccxt_symbol = None
        if symbol:
            ccxt_symbol = symbol.upper().replace("-", "/")
            if "/" not in ccxt_symbol and ccxt_symbol.endswith(("USDT", "USDC")):
                ccxt_symbol = f"{ccxt_symbol[:-4]}/{ccxt_symbol[-4:]}"
        try:
            return ex.fetch_my_trades(symbol=ccxt_symbol, limit=limit)
        except Exception:
            if ccxt_symbol is None:
                # Some venues require a symbol; retry with the liquid default.
                return ex.fetch_my_trades(symbol="BTC/USDT", limit=limit)
            raise

    try:
        raw = await asyncio.to_thread(_sync_fetch)
    except Exception as exc:
        msg = str(exc)
        hint = (
            "this venue requires ?symbol=BASE/QUOTE"
            if "symbol" in msg.lower() and "requir" in msg.lower()
            else None
        )
        logger.warning(
            "trade history fetch failed: %s", exc,
            extra={"action": "portfolio.trades_fail", "broker": broker_id,
                   "component": "portfolio"},
        )
        return {
            "ok": False,
            "error": msg,
            "hint": hint,
            "data": {"trades": [], "broker": broker_id, "connected": True, "count": 0},
        }

    trades = [_normalize_trade(t) for t in raw if isinstance(t, dict)]
    trades.sort(key=lambda t: str(t.get("ts") or ""), reverse=True)
    return {
        "ok": True,
        "data": {
            "trades": trades[:limit],
            "broker": broker_id,
            "connected": True,
            "count": len(trades[:limit]),
        },
    }


@router.get("/trades")
async def get_trade_history(
    request: Request,
    limit: int = Query(default=50, le=200),
    symbol: str | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Trade history straight from the connected exchange (scoped to the user)."""
    return await fetch_live_trades(_effective_user(request, user), limit=limit, symbol=symbol)


@router.get("/open-orders")
async def get_open_orders(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Return open orders via mcp-algo get_open_orders tool."""
    pool = request.app.state.mcp_pool
    result = await pool.get("algo").safe_call_tool("get_open_orders", {}, fallback=[])
    return {"ok": True, "data": result}


@router.get("/history")
async def get_portfolio_history(
    user: dict[str, Any] = Depends(get_current_user),
    limit: int = 100,
) -> dict[str, Any]:
    """Return historical portfolio snapshots (equity curve data)."""
    user_id = user.get("sub", "anon")
    try:
        from winny_gateway.db import db_select

        snapshots = await db_select(
            "portfolio_snapshots",
            filters={"user_id": user_id},
            order_by="-captured_at",
            limit=min(limit, 1000),
        )
        return {"ok": True, "data": {"snapshots": snapshots, "count": len(snapshots)}}
    except Exception:
        return {"ok": True, "data": {"snapshots": [], "count": 0}}


# ── Supabase persistence ─────────────────────────────────────────────────────


async def _save_snapshot_to_db(user_id: str, snapshot: dict[str, Any]) -> None:
    """Persist portfolio snapshot to Supabase (fire-and-forget)."""
    try:
        from winny_gateway.db import db_insert

        await db_insert("portfolio_snapshots", {
            "user_id": user_id,
            "broker": snapshot.get("broker", "unknown"),
            "nav_usd": float(snapshot.get("nav", 0)),
            "balances": snapshot.get("balances", {}),
            "positions": snapshot.get("positions", []),
            "open_orders_count": snapshot.get("open_orders_count", 0),
        })
    except Exception as e:
        logger.debug("Snapshot save failed: %s", e, extra={"component": "portfolio"})
