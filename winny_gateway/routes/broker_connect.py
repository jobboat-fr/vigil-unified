"""Live broker connection — real portfolio, orders, positions from exchange.

These endpoints bypass the MCP layer and directly instantiate CcxtBrokerage
with the user's stored credentials. This gives WinnyWoo real-time access to:
  - Account balances
  - Open positions (spot + futures)
  - Open orders
  - Trade history
  - Ticker prices
  - Connection health test

All data is fetched on-demand from the exchange — no caching (for now).
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from winny_gateway.auth import get_current_user, scoped_user
from winny_gateway.cache import snapshot_cache
from winny_gateway.logging import get_logger
from winny_gateway.routes.settings import _get_prefs, _load_decrypted_credentials_from_db
from winny.brokerage.credentials import credential_store
from winny.brokerage.env_creds import get_env_creds_for

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/broker", tags=["broker-connect"])


def _mask_key(value: str | None) -> str:
    """Return a safe-to-log fragment of an API key (first 3 + suffix)."""
    if not value:
        return "(empty)"
    if len(value) <= 6:
        return f"{value[:1]}***"
    return f"{value[:3]}***({len(value)} chars)"


class BrokerTestBody(BaseModel):
    broker_id: str | None = Field(default=None, max_length=50)
    api_key: str = Field(default="", max_length=512)
    api_secret: str = Field(default="", max_length=2048)
    api_password: str = Field(default="", max_length=512)
    is_testnet: bool = False


def _get_live_creds(user: dict[str, Any], broker_id: str) -> dict[str, str] | None:
    """Resolve live credentials in the same order for every broker endpoint.

    Logs the resolution path (which source matched, which failed, masked key)
    so empty dashboards stop being silent. PII safe: only first-3-chars of
    the API key + the caller's email/sub.
    """
    user_id = user.get("sub", "anon")
    user_email = user.get("email", "")

    creds = credential_store.get_decrypted(user_id, broker_id)
    if creds:
        logger.info(
            "creds resolved",
            extra={
                "action": "broker.creds_resolved",
                "broker": broker_id,
                "source": "memory_store",
                "key_hint": _mask_key(creds.get("api_key")),
                "user_id": user_id[:8],
                "component": "broker_connect",
            },
        )
        return creds

    creds = _load_decrypted_credentials_from_db(user_id, broker_id)
    if creds:
        logger.info(
            "creds resolved",
            extra={
                "action": "broker.creds_resolved",
                "broker": broker_id,
                "source": "supabase",
                "key_hint": _mask_key(creds.get("api_key")),
                "user_id": user_id[:8],
                "component": "broker_connect",
            },
        )
        return creds

    creds = get_env_creds_for(user, broker_id)
    if creds:
        logger.info(
            "creds resolved",
            extra={
                "action": "broker.creds_resolved",
                "broker": broker_id,
                "source": "env_owner_gate",
                "key_hint": _mask_key(creds.get("api_key")),
                "user_email": user_email,
                "component": "broker_connect",
            },
        )
        return creds

    logger.warning(
        "no creds available — UI will render empty",
        extra={
            "action": "broker.creds_missing",
            "broker": broker_id,
            "user_email": user_email,
            "user_id": user_id[:8],
            "tried": ["memory_store", "supabase", "env_owner_gate"],
            "hint": (
                "If using env vars, ensure <BROKER>_KEY_OWNER_EMAIL matches "
                "the caller's Supabase email exactly (case-insensitive)."
            ),
            "component": "broker_connect",
        },
    )
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_live_broker(user: dict[str, Any], broker_id: str | None = None) -> Any:
    """Create a CcxtBrokerage instance with the caller's credentials.

    Resolution order:
      1. Per-user encrypted creds in Supabase (Settings UI flow)
      2. Owner-gated env-var fallback (Railway / OVH) — only for the
         email listed in `<BROKER>_KEY_OWNER_EMAIL`
    """
    user_id = user.get("sub", "anon")
    prefs = _get_prefs(user_id)
    target_broker = broker_id or prefs.get("broker_cr", "binance")

    creds = _get_live_creds(user, target_broker)
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No API keys configured for {target_broker}. Add keys in Settings first.",
        )

    try:
        from winny.brokerage.ccxt_adapter import CcxtBrokerage

        return CcxtBrokerage(
            venue=target_broker,
            api_key=creds["api_key"],
            secret=creds.get("api_secret", ""),
            password=creds.get("api_password", ""),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to connect to {target_broker}: {e}",
        ) from e


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/balance")
async def get_balance(
    user: dict[str, Any] = Depends(scoped_user),
) -> dict[str, Any]:
    """Fetch real account balances from the connected exchange."""
    user_id = user.get("sub", "anon")
    broker = _get_live_broker(user)

    try:
        balances = broker.get_balance()
    except Exception as e:
        logger.error(
            "Balance fetch failed",
            extra={"action": "broker.balance_fail", "error": str(e), "component": "broker_connect"},
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e

    # Convert to JSON-safe format
    balance_list = [
        {"currency": str(ccy), "amount": str(amount), "usd_value": None}
        for ccy, amount in balances.items()
    ]
    total_usd = sum(
        float(b["amount"] or 0) for b in balance_list
        if b["currency"] in ("USD", "USDT", "USDC", "BUSD")
    )

    return {
        "ok": True,
        "data": {
            "balances": balance_list,
            "total_usd_estimate": str(Decimal(str(total_usd)).quantize(Decimal("0.01"))),
            "broker": _get_prefs(user_id).get("broker_cr", "binance"),
            "fetched_at": datetime.now(UTC).isoformat(),
        },
    }


@router.get("/positions")
async def get_positions(
    user: dict[str, Any] = Depends(scoped_user),
) -> dict[str, Any]:
    """Fetch open positions from the exchange (futures/margin)."""
    user_id = user.get("sub", "anon")
    broker = _get_live_broker(user)

    try:
        positions = broker.get_positions()
    except Exception as e:
        logger.error(
            "Positions fetch failed",
            extra={"action": "broker.positions_fail", "error": str(e), "component": "broker_connect"},
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e

    position_list = [
        {
            "symbol": pos.symbol.canonical(),
            "qty": str(pos.qty),
            "side": "long" if pos.qty > 0 else "short",
            "avg_entry_price": str(pos.avg_entry_price),
            "unrealized_pnl": str(pos.unrealized_pnl),
            "realized_pnl": str(pos.realized_pnl),
        }
        for pos in positions
    ]

    return {
        "ok": True,
        "data": {
            "positions": position_list,
            "count": len(position_list),
            "broker": _get_prefs(user_id).get("broker_cr", "binance"),
            "fetched_at": datetime.now(UTC).isoformat(),
        },
    }


@router.get("/open-orders")
async def get_open_orders(
    user: dict[str, Any] = Depends(scoped_user),
) -> dict[str, Any]:
    """Fetch open orders from the exchange."""
    user_id = user.get("sub", "anon")
    prefs = _get_prefs(user_id)
    target_broker = prefs.get("broker_cr", "binance")

    creds = _get_live_creds(user, target_broker)
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No API keys configured for {target_broker}.",
        )

    try:
        import ccxt as ccxt_lib

        from winny.brokerage.ccxt_adapter import _VENUE_MAP

        venue = _VENUE_MAP.get(target_broker, target_broker)
        exchange_class = getattr(ccxt_lib, venue)
        # Read-only snapshot path — cache protects us from rate-bans, so
        # CCXT's built-in sleep just adds latency. Disable it here.
        config: dict[str, Any] = {
            "apiKey": creds["api_key"],
            "secret": creds.get("api_secret", ""),
            "enableRateLimit": False,
        }
        if creds.get("api_password"):
            config["password"] = creds["api_password"]

        exchange = exchange_class(config)
        raw_orders = exchange.fetch_open_orders()

    except Exception as e:
        logger.error(
            "Open orders fetch failed",
            extra={"action": "broker.orders_fail", "error": str(e), "component": "broker_connect"},
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e

    orders_list = [
        {
            "id": order.get("id"),
            "symbol": order.get("symbol"),
            "side": order.get("side"),
            "type": order.get("type"),
            "amount": str(order.get("amount", 0)),
            "price": str(order.get("price", 0)) if order.get("price") else None,
            "filled": str(order.get("filled", 0)),
            "remaining": str(order.get("remaining", 0)),
            "status": order.get("status"),
            "timestamp": order.get("timestamp"),
            "datetime": order.get("datetime"),
        }
        for order in raw_orders
    ]

    return {
        "ok": True,
        "data": {
            "orders": orders_list,
            "count": len(orders_list),
            "broker": target_broker,
            "fetched_at": datetime.now(UTC).isoformat(),
        },
    }


@router.get("/trades")
async def get_trade_history(
    limit: int = 50,
    user: dict[str, Any] = Depends(scoped_user),
) -> dict[str, Any]:
    """Fetch recent trade (fill) history from the exchange.

    Delegates to the single live implementation in portfolio.py; rows
    carry both ``qty``/``ts`` and the legacy ``amount``/``datetime`` keys.
    """
    from winny_gateway.routes.portfolio import fetch_live_trades

    result = await fetch_live_trades(user, limit=min(max(limit, 1), 200))
    if isinstance(result.get("data"), dict):
        result["data"].setdefault("fetched_at", datetime.now(UTC).isoformat())
    return result


@router.get("/ticker/{symbol}")
async def get_ticker(
    symbol: str,
    user: dict[str, Any] = Depends(scoped_user),
) -> dict[str, Any]:
    """Fetch current ticker price for a symbol (e.g. BTC/USDT)."""
    user_id = user.get("sub", "anon")
    prefs = _get_prefs(user_id)
    target_broker = prefs.get("broker_cr", "binance")

    creds = _get_live_creds(user, target_broker)
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No API keys configured for {target_broker}.",
        )

    # Normalize symbol format: BTC_USDT or BTCUSDT → BTC/USDT
    ccxt_symbol = symbol.upper()
    if "/" not in ccxt_symbol:
        if "_" in ccxt_symbol:
            ccxt_symbol = ccxt_symbol.replace("_", "/")
        elif len(ccxt_symbol) > 3:
            # Heuristic: split before last 3-4 chars (USDT, USD, BTC)
            for quote in ("USDT", "USDC", "BUSD", "USD", "BTC", "ETH"):
                if ccxt_symbol.endswith(quote):
                    ccxt_symbol = f"{ccxt_symbol[:-len(quote)]}/{quote}"
                    break

    try:
        import ccxt as ccxt_lib

        from winny.brokerage.ccxt_adapter import _VENUE_MAP

        venue = _VENUE_MAP.get(target_broker, target_broker)
        exchange_class = getattr(ccxt_lib, venue)
        # Read-only snapshot path — cache protects us from rate-bans, so
        # CCXT's built-in sleep just adds latency. Disable it here.
        config: dict[str, Any] = {
            "apiKey": creds["api_key"],
            "secret": creds.get("api_secret", ""),
            "enableRateLimit": False,
        }
        if creds.get("api_password"):
            config["password"] = creds["api_password"]

        exchange = exchange_class(config)
        ticker = exchange.fetch_ticker(ccxt_symbol)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch ticker for {ccxt_symbol}: {e}",
        ) from e

    return {
        "ok": True,
        "data": {
            "symbol": ticker.get("symbol"),
            "last": str(ticker.get("last", 0)),
            "bid": str(ticker.get("bid", 0)),
            "ask": str(ticker.get("ask", 0)),
            "high": str(ticker.get("high", 0)),
            "low": str(ticker.get("low", 0)),
            "volume": str(ticker.get("baseVolume", 0)),
            "change_24h": str(ticker.get("change", 0)),
            "change_pct_24h": str(ticker.get("percentage", 0)),
            "timestamp": ticker.get("timestamp"),
            "broker": target_broker,
        },
    }


@router.post("/test-connection")
async def test_connection(
    body: BrokerTestBody | None = None,
    user: dict[str, Any] = Depends(scoped_user),
) -> dict[str, Any]:
    """Test that stored credentials can connect to the exchange.

    Attempts to fetch balances — if it succeeds, the keys are valid.
    """
    user_id = user.get("sub", "anon")
    prefs = _get_prefs(user_id)
    target_broker = (body.broker_id if body and body.broker_id else prefs.get("broker_cr", "binance")).lower()

    creds: dict[str, str] | None = None
    if body and body.api_key:
        creds = {
            "api_key": body.api_key,
            "api_secret": body.api_secret,
            "api_password": body.api_password,
        }
    if not creds:
        creds = _get_live_creds(user, target_broker)
    if not creds:
        return {
            "ok": False,
            "data": {
                "connected": False,
                "broker": target_broker,
                "error": "No API keys configured. Add keys in Settings.",
            },
        }

    try:
        import ccxt as ccxt_lib

        from winny.brokerage.ccxt_adapter import _VENUE_MAP

        venue = _VENUE_MAP.get(target_broker, target_broker)
        exchange_class = getattr(ccxt_lib, venue)
        # Read-only snapshot path — cache protects us from rate-bans, so
        # CCXT's built-in sleep just adds latency. Disable it here.
        config: dict[str, Any] = {
            "apiKey": creds["api_key"],
            "secret": creds.get("api_secret", ""),
            "enableRateLimit": False,
        }
        if creds.get("api_password"):
            config["password"] = creds["api_password"]

        exchange = exchange_class(config)
        balance = exchange.fetch_balance()
        # Count non-zero assets
        total = balance.get("total", {})
        asset_count = sum(1 for v in total.values() if v and float(v) > 0)

        logger.info(
            "Connection test succeeded",
            extra={
                "action": "broker.test_ok",
                "broker": target_broker,
                "asset_count": asset_count,
                "component": "broker_connect",
            },
        )

        return {
            "ok": True,
            "data": {
                "connected": True,
                "broker": target_broker,
                "exchange_name": exchange.name,
                "asset_count": asset_count,
                "permissions": _detect_permissions(exchange),
                "message": f"Connected to {exchange.name} — {asset_count} assets found.",
            },
        }

    except Exception as e:
        error_msg = str(e)
        # Sanitise exchange error messages
        if "key" in error_msg.lower() or "auth" in error_msg.lower():
            error_msg = "Authentication failed — check your API key and secret."
        elif "ip" in error_msg.lower():
            error_msg = "IP not whitelisted — add your server IP to the exchange API settings."

        logger.warning(
            "Connection test failed: %s",
            error_msg,
            extra={"action": "broker.test_fail", "broker": target_broker, "component": "broker_connect"},
        )

        return {
            "ok": False,
            "data": {
                "connected": False,
                "broker": target_broker,
                "error": error_msg,
            },
        }


@router.get("/snapshot")
async def get_full_snapshot(
    user: dict[str, Any] = Depends(scoped_user),
    nocache: bool = False,
) -> dict[str, Any]:
    """Full portfolio snapshot — balances + positions + open orders in one call.

    This is the primary endpoint the frontend dashboard uses to display
    the user's complete trading state.

    Caching is **stale-while-revalidate**:
      * Fresh hit (<30s old) → return immediately, no refresh
      * Stale hit (any age)  → return immediately with ``stale: true``;
                               kick a background CCXT refresh
      * Cold miss            → block on CCXT, populate cache, return
    The cold-miss case is the only one that can take 5–15 s. Every
    subsequent request — including the first one *after* expiry —
    responds in <50 ms.  Pass ``?nocache=1`` to bypass.
    """
    user_id = user.get("sub", "anon")
    prefs = _get_prefs(user_id)
    target_broker = prefs.get("broker_cr", "binance")

    cache_key = ("snapshot", user_id, target_broker)
    if not nocache:
        cached_value, is_stale = snapshot_cache.get_stale_ok(cache_key)
        if cached_value is not None:
            if is_stale:
                # Kick a background refresh; don't await it.
                import asyncio
                asyncio.create_task(_refresh_snapshot_bg(user, target_broker, cache_key))
                logger.debug(
                    "snapshot served stale, refresh kicked",
                    extra={
                        "action": "broker.snapshot_stale_revalidate",
                        "broker": target_broker,
                        "user_id": user_id[:8],
                        "component": "broker_connect",
                    },
                )
                return {**cached_value, "cached": True, "stale": True}
            logger.debug(
                "snapshot cache HIT",
                extra={
                    "action": "broker.snapshot_cache_hit",
                    "broker": target_broker,
                    "user_id": user_id[:8],
                    "component": "broker_connect",
                },
            )
            return {**cached_value, "cached": True}

    creds = _get_live_creds(user, target_broker)
    if not creds:
        empty = {
            "ok": True,
            "data": {
                "connected": False,
                "broker": target_broker,
                "balances": [],
                "positions": [],
                "open_orders": [],
                "nav_estimate": "0",
                "fetched_at": datetime.now(UTC).isoformat(),
                "message": (
                    f"No API keys configured for {target_broker}. "
                    "Add keys in Settings, or set "
                    f"{target_broker.upper()}_KEY_OWNER_EMAIL on Railway "
                    "to enable env-var keys for this account."
                ),
            },
        }
        # Cache the "no creds" envelope with a short TTL so we don't
        # re-hammer the resolver on every page paint while the user is
        # still wiring keys up.
        snapshot_cache.set(cache_key, empty, ttl=15.0)
        return empty

    try:
        import ccxt as ccxt_lib

        from winny.brokerage.ccxt_adapter import _VENUE_MAP

        venue = _VENUE_MAP.get(target_broker, target_broker)
        exchange_class = getattr(ccxt_lib, venue)
        # Read-only snapshot path — cache protects us from rate-bans, so
        # CCXT's built-in sleep just adds latency. Disable it here.
        config: dict[str, Any] = {
            "apiKey": creds["api_key"],
            "secret": creds.get("api_secret", ""),
            "enableRateLimit": False,
        }
        if creds.get("api_password"):
            config["password"] = creds["api_password"]

        exchange = exchange_class(config)

        # Balance is the primary signal; orders/positions are best effort below.
        balance = exchange.fetch_balance()

    except Exception as e:
        logger.error(
            "Full snapshot fetch failed",
            extra={"action": "broker.snapshot_fail", "error": str(e), "component": "broker_connect"},
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e

    open_orders: list[Any] = []
    order_error: str | None = None
    try:
        open_orders = exchange.fetch_open_orders()
    except Exception as e:
        order_error = str(e)
        logger.debug(
            "Open orders unavailable during full snapshot",
            extra={
                "action": "broker.snapshot_orders_fail",
                "error": str(e),
                "component": "broker_connect",
            },
        )

    positions_raw: list[Any] = []
    position_error: str | None = None
    with contextlib.suppress(AttributeError):
        try:
            positions_raw = exchange.fetch_positions()
        except Exception as e:
            position_error = str(e)
            logger.debug(
                "Positions unavailable during full snapshot",
                extra={
                    "action": "broker.snapshot_positions_fail",
                    "error": str(e),
                    "component": "broker_connect",
                },
            )

    # Format balances
    total = balance.get("total", {})
    balance_list = [
        {"currency": ccy, "total": str(amt), "free": str(balance.get("free", {}).get(ccy, 0)), "used": str(balance.get("used", {}).get(ccy, 0))}
        for ccy, amt in total.items()
        if amt and float(amt) > 0
    ]

    # NAV estimate (sum of stablecoins + USD)
    nav = sum(
        float(total.get(c, 0) or 0)
        for c in ("USD", "USDT", "USDC", "BUSD")
    )

    # Format positions
    position_list = [
        {
            "symbol": pos.get("symbol"),
            "side": pos.get("side"),
            "contracts": str(pos.get("contracts", 0)),
            "entry_price": str(pos.get("entryPrice", 0)),
            "unrealized_pnl": str(pos.get("unrealizedPnl", 0)),
            "margin": str(pos.get("initialMargin", 0)),
            "leverage": pos.get("leverage"),
        }
        for pos in positions_raw
        if pos.get("contracts") and float(pos.get("contracts", 0)) > 0
    ]

    # Format orders
    orders_list = [
        {
            "id": o.get("id"),
            "symbol": o.get("symbol"),
            "side": o.get("side"),
            "type": o.get("type"),
            "amount": str(o.get("amount", 0)),
            "price": str(o.get("price", 0)) if o.get("price") else None,
            "filled": str(o.get("filled", 0)),
            "status": o.get("status"),
            "datetime": o.get("datetime"),
        }
        for o in open_orders
    ]

    response = {
        "ok": True,
        "data": {
            "connected": True,
            "broker": target_broker,
            "exchange_name": exchange.name,
            "balances": balance_list,
            "positions": position_list,
            "open_orders": orders_list,
            "nav_estimate": str(Decimal(str(nav)).quantize(Decimal("0.01"))),
            "asset_count": len(balance_list),
            "position_count": len(position_list),
            "order_count": len(orders_list),
            "position_error": position_error,
            "order_error": order_error,
            "fetched_at": datetime.now(UTC).isoformat(),
        },
    }
    # Cache the live snapshot so the next dashboard paint is instant.
    snapshot_cache.set(cache_key, response, ttl=30.0)
    return response


# ── Server-side sizing (scoped sized-submit, §1.3 5%-NAV cap) ───────────────────


def _norm_ccxt_symbol(symbol: str) -> str:
    """BTC_USDT / BTCUSDT / BTC-USDT → BTC/USDT (best-effort)."""
    s = symbol.upper().replace("-", "/")
    if "/" in s:
        return s
    if "_" in s:
        return s.replace("_", "/")
    for quote in ("USDT", "USDC", "BUSD", "USD", "EUR", "BTC", "ETH"):
        if s.endswith(quote) and len(s) > len(quote):
            return f"{s[:-len(quote)]}/{quote}"
    return s


class PrepareOrderBody(BaseModel):
    """Ask the gateway to SIZE an order for the chatting user — never submit.

    The agent (or dashboard) supplies symbol + side + a sizing *policy*, NOT a
    quantity. The gateway derives qty from the user's own live broker NAV and
    the §1.3 5%-NAV hard cap, so multi-tenant execution can never size against
    the operator's book or exceed the ceiling. Output feeds /approvals/request.
    """

    symbol: str = Field(..., min_length=2, max_length=32)
    side: str = Field(..., pattern="^(?i)(buy|sell)$")
    sizing_policy: str = Field(default="fixed_fractional", max_length=32)
    nav_fraction: float | None = Field(default=None, gt=0, le=0.05)
    conviction: int | None = Field(default=None, ge=1, le=10)
    ref_price: str | None = None
    decision_id: str | None = Field(default=None, max_length=128)
    summary: str | None = Field(default=None, max_length=280)


@router.post("/prepare-order")
async def prepare_order_scoped(
    body: PrepareOrderBody,
    user: dict[str, Any] = Depends(scoped_user),
) -> dict[str, Any]:
    """Size an order against the CHATTING user's live broker NAV (§1.3 capped).

    Resolution is identical to every other broker endpoint — scoped_user means
    a service-token caller acts FOR the end user via the X-WinnyWoo-User-Id
    header, so the NAV, the cap, and the resulting qty all belong to THAT user.
    Returns a JSON OrderIntent + sizing provenance; does not touch the broker
    beyond read-only balance + ticker.
    """
    from decimal import Decimal

    from winny.engine.sizing import (
        HARD_NAV_FRACTION_CAP,
        ConvictionScaledSizing,
        FixedFractionalSizing,
        apply_nav_cap,
    )

    user_id = user.get("sub", "anon")
    prefs = _get_prefs(user_id)
    target_broker = prefs.get("broker_cr", "binance")

    creds = _get_live_creds(user, target_broker)
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No API keys configured for {target_broker}. Connect a broker in Settings first.",
        )

    ccxt_symbol = _norm_ccxt_symbol(body.symbol)
    side_str = body.side.lower()

    # Live NAV (quote-currency stablecoin sum) + ref price from the user's venue.
    try:
        import ccxt as ccxt_lib

        from winny.brokerage.ccxt_adapter import _VENUE_MAP

        venue = _VENUE_MAP.get(target_broker, target_broker)
        config: dict[str, Any] = {
            "apiKey": creds["api_key"],
            "secret": creds.get("api_secret", ""),
            "enableRateLimit": False,
        }
        if creds.get("api_password"):
            config["password"] = creds["api_password"]
        exchange = getattr(ccxt_lib, venue)(config)

        import asyncio

        balance = await asyncio.to_thread(exchange.fetch_balance)
        total = balance.get("total", {})
        nav = Decimal(str(sum(
            float(total.get(c, 0) or 0) for c in ("USD", "USDT", "USDC", "BUSD")
        )))

        if body.ref_price:
            ref_price = Decimal(str(body.ref_price))
        else:
            ticker = await asyncio.to_thread(exchange.fetch_ticker, ccxt_symbol)
            ref_price = Decimal(str(ticker.get("last") or ticker.get("close") or 0))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not read NAV/price for sizing: {exc}",
        ) from exc

    if nav <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your broker NAV (stablecoin balance) is zero — cannot size a trade.",
        )
    if ref_price <= 0:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"No live price for {ccxt_symbol} — cannot size.",
        )

    # Build the sizing policy. The user's max_position_pct pref tightens the
    # cap downward; it can NEVER raise it above the §1.3 5% ceiling.
    pref_cap = Decimal(str(prefs.get("max_position_pct", 5) or 5)) / Decimal("100")
    ceiling_fraction = min(pref_cap, HARD_NAV_FRACTION_CAP)

    policy_name = (body.sizing_policy or "fixed_fractional").lower()
    try:
        if policy_name == "conviction":
            conv = int(body.conviction or 5)
            # base*conv/5, capped; choose a base that respects the user ceiling.
            base = (ceiling_fraction / Decimal("2")).quantize(Decimal("0.0001"))
            policy = ConvictionScaledSizing(base_fraction=base, conviction=conv)
        else:
            policy_name = "fixed_fractional"
            frac = Decimal(str(body.nav_fraction)) if body.nav_fraction else ceiling_fraction
            frac = min(frac, ceiling_fraction)
            policy = FixedFractionalSizing(nav_fraction=frac)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"sizing_policy error: {exc}") from exc

    from winny.common.symbols import AssetClass, Symbol
    from winny.common.types import Side

    side_enum = Side.BUY if side_str == "buy" else Side.SELL
    base, quote = (ccxt_symbol.split("/", 1) + ["USDT"])[:2]
    sym = Symbol(asset_class=AssetClass.CRYPTO, base=base, quote=quote, venue=target_broker)

    stake = policy.stake_amount(sym, side_enum, ref_price, nav)
    # Defensive: re-clamp to the user ceiling (not just the 5% hard cap).
    user_ceiling = (nav * ceiling_fraction).quantize(Decimal("0.01"))
    stake = min(stake, user_ceiling)
    qty = (stake / ref_price).quantize(Decimal("0.00000001"))

    if qty <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Sized qty rounds to zero (stake ${stake} / price ${ref_price}). NAV too small.",
        )

    decision_id = body.decision_id or f"winny:{base}:{side_str}"
    summary = body.summary or f"{side_str} {qty} {ccxt_symbol} @ market — {policy_name}"
    intent = {
        "decision_id": decision_id,
        "symbol": ccxt_symbol,
        "side": side_str,
        "qty": str(qty),
        "type": "market",
        "price": None,
        "venue": target_broker,
        "summary": summary,
    }
    cap_ceiling = apply_nav_cap(nav, nav)  # the absolute 5% ceiling for provenance

    logger.info(
        "scoped order sized",
        extra={
            "action": "broker.prepare_order", "broker": target_broker,
            "symbol": ccxt_symbol, "side": side_str, "user_id": user_id[:8],
            "scoped": bool(user.get("scoped")), "policy": policy_name,
            "component": "broker_connect",
        },
    )
    return {
        "ok": True,
        "data": {
            "intent": intent,
            "sizing": {
                "policy": policy_name,
                "nav": str(nav.quantize(Decimal("0.01"))),
                "ref_price": str(ref_price),
                "stake": str(stake),
                "qty": str(qty),
                "user_ceiling_fraction": str(ceiling_fraction),
                "hard_cap_ceiling": str(cap_ceiling),
                "cap_was_applied": stake >= user_ceiling,
            },
        },
    }


@router.post("/cancel-all")
async def cancel_all_scoped(
    user: dict[str, Any] = Depends(scoped_user),
) -> dict[str, Any]:
    """Kill switch, scoped to the chatting user's OWN broker (§1.3 de-risk).

    Cancels every open order on the user's connected exchange — never the
    operator's. No approval gate: the gate is for ADDING risk, this only
    removes it. Best-effort per-order fallback when the venue lacks a bulk
    cancel.
    """
    user_id = user.get("sub", "anon")
    prefs = _get_prefs(user_id)
    target_broker = prefs.get("broker_cr", "binance")

    creds = _get_live_creds(user, target_broker)
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No API keys configured for {target_broker}.",
        )

    try:
        import asyncio

        import ccxt as ccxt_lib

        from winny.brokerage.ccxt_adapter import _VENUE_MAP

        venue = _VENUE_MAP.get(target_broker, target_broker)
        config: dict[str, Any] = {
            "apiKey": creds["api_key"],
            "secret": creds.get("api_secret", ""),
            "enableRateLimit": True,
        }
        if creds.get("api_password"):
            config["password"] = creds["api_password"]
        exchange = getattr(ccxt_lib, venue)(config)

        def _cancel_all_sync() -> int:
            try:
                if getattr(exchange, "has", {}).get("cancelAllOrders"):
                    exchange.cancel_all_orders()
                    return -1  # venue-bulk; count unknown
            except Exception as exc:  # noqa: BLE001
                logger.debug("bulk cancel failed, falling back: %s", exc)
            # Fallback: fetch open orders and cancel one by one.
            n = 0
            for o in exchange.fetch_open_orders():
                try:
                    exchange.cancel_order(o.get("id"), o.get("symbol"))
                    n += 1
                except Exception as exc:  # noqa: BLE001
                    logger.debug("cancel one failed: %s", exc)
            return n

        cancelled = await asyncio.to_thread(_cancel_all_sync)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"cancel-all failed on {target_broker}: {exc}",
        ) from exc

    logger.warning(
        "scoped kill switch fired",
        extra={
            "action": "broker.cancel_all", "broker": target_broker,
            "user_id": user_id[:8], "cancelled": cancelled, "component": "broker_connect",
        },
    )
    return {
        "ok": True,
        "data": {
            "broker": target_broker,
            "cancelled": ("all" if cancelled == -1 else cancelled),
        },
    }


# ── Helpers ───────────────────────────────────────────────────────────────────


def _detect_permissions(exchange: Any) -> list[str]:
    """Try to detect API key permissions by testing operations."""
    perms: list[str] = ["read"]
    # If fetch_balance worked, we at least have read access
    # Trading permissions can only be tested by attempting an order (too risky)
    # So we just report what we can determine
    if hasattr(exchange, "create_order"):
        perms.append("trade")
    if hasattr(exchange, "withdraw"):
        perms.append("withdraw")
    return perms


# ── Background refresh (stale-while-revalidate) ──────────────────────────────


async def _refresh_snapshot_bg(
    user: dict[str, Any],
    broker: str,
    cache_key: tuple,
) -> None:
    """Re-fetch the snapshot and update the cache. Called from a task.

    Errors are swallowed — the cache keeps the old (stale) value, so the
    next request still serves something. A subsequent successful refresh
    overwrites it. We don't try to surface this to the user; the stale
    flag in the response is the signal that an update is in flight.
    """
    try:
        creds = _get_live_creds(user, broker)
        if not creds:
            return  # nothing to refresh against
        import asyncio

        # CCXT is synchronous; offload so we don't pin the event loop.
        def _fetch_sync() -> dict[str, Any]:
            import ccxt as ccxt_lib

            from winny.brokerage.ccxt_adapter import _VENUE_MAP

            venue = _VENUE_MAP.get(broker, broker)
            exchange_class = getattr(ccxt_lib, venue)
            # Background refresh — cache-protected, no need to rate-limit.
            config: dict[str, Any] = {
                "apiKey": creds["api_key"],
                "secret": creds.get("api_secret", ""),
                "enableRateLimit": False,
            }
            if creds.get("api_password"):
                config["password"] = creds["api_password"]
            exchange = exchange_class(config)
            balance = exchange.fetch_balance()

            open_orders: list[Any] = []
            with contextlib.suppress(Exception):
                open_orders = exchange.fetch_open_orders()
            positions_raw: list[Any] = []
            with contextlib.suppress(AttributeError, Exception):
                positions_raw = exchange.fetch_positions()

            total = balance.get("total", {})
            balance_list = [
                {
                    "currency": ccy,
                    "total": str(amt),
                    "free": str(balance.get("free", {}).get(ccy, 0)),
                    "used": str(balance.get("used", {}).get(ccy, 0)),
                }
                for ccy, amt in total.items()
                if amt and float(amt) > 0
            ]
            nav = sum(
                float(total.get(c, 0) or 0)
                for c in ("USD", "USDT", "USDC", "BUSD", "EUR")
            )
            position_list = [
                {
                    "symbol": pos.get("symbol"),
                    "side": pos.get("side"),
                    "contracts": str(pos.get("contracts", 0)),
                    "entry_price": str(pos.get("entryPrice", 0)),
                    "unrealized_pnl": str(pos.get("unrealizedPnl", 0)),
                    "margin": str(pos.get("initialMargin", 0)),
                    "leverage": pos.get("leverage"),
                }
                for pos in positions_raw
                if pos.get("contracts") and float(pos.get("contracts", 0)) > 0
            ]
            orders_list = [
                {
                    "id": o.get("id"),
                    "symbol": o.get("symbol"),
                    "side": o.get("side"),
                    "type": o.get("type"),
                    "amount": str(o.get("amount", 0)),
                    "price": str(o.get("price", 0)) if o.get("price") else None,
                    "filled": str(o.get("filled", 0)),
                    "status": o.get("status"),
                    "datetime": o.get("datetime"),
                }
                for o in open_orders
            ]
            return {
                "ok": True,
                "data": {
                    "connected": True,
                    "broker": broker,
                    "exchange_name": exchange.name,
                    "balances": balance_list,
                    "positions": position_list,
                    "open_orders": orders_list,
                    "nav_estimate": str(
                        Decimal(str(nav)).quantize(Decimal("0.01"))
                    ),
                    "asset_count": len(balance_list),
                    "position_count": len(position_list),
                    "order_count": len(orders_list),
                    "fetched_at": datetime.now(UTC).isoformat(),
                },
            }

        snapshot = await asyncio.to_thread(_fetch_sync)
        snapshot_cache.set(cache_key, snapshot, ttl=30.0)
        logger.debug(
            "background snapshot refresh ok",
            extra={
                "action": "broker.bg_refresh_ok",
                "broker": broker,
                "component": "broker_connect",
            },
        )
    except Exception as exc:
        logger.warning(
            "background snapshot refresh failed: %s",
            exc,
            extra={
                "action": "broker.bg_refresh_fail",
                "broker": broker,
                "error": str(exc),
                "component": "broker_connect",
            },
        )
