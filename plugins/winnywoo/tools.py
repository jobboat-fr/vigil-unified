"""WinnyWoo trading-desk tools for Hermes.

Read/observe tools over the in-tree ``winny_gateway``. Order *execution* is
intentionally NOT exposed: the architecture keeps trade approval human-driven
in the dashboard (mcp-approval is the only path to real execution). The agent
can see the live desk and pending approvals so it can *propose*, while the
human *disposes*.
"""

from __future__ import annotations

from typing import Any

from plugins.winnywoo.client import GatewayError, gateway_base_url, gateway_get, unwrap
from tools.registry import tool_error, tool_result


def _scope(args: dict) -> dict[str, str] | None:
    uid = str(args.get("user_id") or "").strip()
    return {"user_id": uid, "email": str(args.get("email") or "").strip()} if uid else None


def _err(exc: GatewayError) -> str:
    if exc.status == 0:
        return tool_error(
            f"Could not reach the WinnyWoo gateway ({exc.body}). Is winny_gateway "
            f"running on {gateway_base_url()}?"
        )
    if exc.status in (401, 403):
        return tool_error(
            f"Gateway auth failed ({exc.status}). Authed desk reads need WW_SERVICE_TOKEN "
            "set for the agent, or WW_ALLOW_DEV_AUTH=true on the gateway for local dev.",
            status_code=exc.status,
        )
    return tool_error(f"Gateway error {exc.status} on {exc.path}", body=exc.body, status_code=exc.status)


# --------------------------------------------------------------------------- #
# handlers
# --------------------------------------------------------------------------- #

def _handle_market(args: dict, **_kw) -> str:
    action = str(args.get("action") or "overview").strip().lower()
    try:
        if action == "overview":
            return tool_result(unwrap(gateway_get("/api/v1/market/overview")))
        if action == "news":
            return tool_result(unwrap(gateway_get("/api/v1/market/news")))
        if action in ("ohlcv", "enrich"):
            symbol = str(args.get("symbol") or "").strip()
            if not symbol:
                return tool_error(f"symbol is required for action='{action}'")
            return tool_result(unwrap(gateway_get(f"/api/v1/market/{action}/{symbol}")))
        return tool_error(f"Unknown ww_market action: {action}")
    except GatewayError as exc:
        return _err(exc)


def _handle_signals(args: dict, **_kw) -> str:
    action = str(args.get("action") or "live").strip().lower()
    try:
        if action == "live":
            return tool_result(unwrap(gateway_get("/api/v1/signals/live", scope=_scope(args))))
        if action == "risk":
            return tool_result(unwrap(gateway_get("/api/v1/signals/risk", scope=_scope(args))))
        return tool_error(f"Unknown ww_signals action: {action}")
    except GatewayError as exc:
        return _err(exc)


_PORTFOLIO_PATHS = {
    "snapshot": "/api/v1/portfolio/snapshot",
    "positions": "/api/v1/portfolio/positions",
    "trades": "/api/v1/portfolio/trades",
    "open_orders": "/api/v1/portfolio/open-orders",
    "history": "/api/v1/portfolio/history",
}


def _handle_portfolio(args: dict, **_kw) -> str:
    action = str(args.get("action") or "snapshot").strip().lower()
    path = _PORTFOLIO_PATHS.get(action)
    if path is None:
        return tool_error(f"Unknown ww_portfolio action: {action} (expected {sorted(_PORTFOLIO_PATHS)})")
    try:
        return tool_result(unwrap(gateway_get(path, scope=_scope(args))))
    except GatewayError as exc:
        return _err(exc)


def _handle_approvals(args: dict, **_kw) -> str:
    try:
        return tool_result(unwrap(gateway_get("/api/v1/approvals/pending", scope=_scope(args))))
    except GatewayError as exc:
        return _err(exc)


def _handle_audit(args: dict, **_kw) -> str:
    action = str(args.get("action") or "verify").strip().lower()
    try:
        if action == "verify":
            return tool_result(unwrap(gateway_get("/api/v1/audit/verify", scope=_scope(args))))
        if action == "events":
            params: dict[str, Any] = {}
            if args.get("limit"):
                params["limit"] = int(args["limit"])
            return tool_result(unwrap(gateway_get("/api/v1/audit/events", params=params, scope=_scope(args))))
        return tool_error(f"Unknown ww_audit action: {action}")
    except GatewayError as exc:
        return _err(exc)


# --------------------------------------------------------------------------- #
# schemas
# --------------------------------------------------------------------------- #

_STR = {"type": "string"}

WW_MARKET_SCHEMA = {
    "name": "ww_market",
    "description": "Live crypto market context from the WinnyWoo desk: overview (BTC/ETH price, Fear & Greed), headlines, or per-symbol OHLCV / enriched stats. Public — no auth required.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["overview", "news", "ohlcv", "enrich"], "default": "overview"},
            "symbol": {"type": "string", "description": "Symbol for ohlcv/enrich, e.g. 'BTC/USDT'."},
        },
        "required": [],
    },
}

WW_SIGNALS_SCHEMA = {
    "name": "ww_signals",
    "description": "Live trading signals from the WinnyWoo strategy runner (forecaster + analyst). action='live' for the current signal feed, 'risk' for the risk/exposure view.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["live", "risk"], "default": "live"},
            "user_id": _STR,
            "email": _STR,
        },
        "required": [],
    },
}

WW_PORTFOLIO_SCHEMA = {
    "name": "ww_portfolio",
    "description": "Read the trading portfolio: snapshot (cash/NAV), positions, trades, open-orders, or history. Authed — needs WW_SERVICE_TOKEN or gateway dev-auth. Pass user_id to scope to a specific user.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["snapshot", "positions", "trades", "open_orders", "history"], "default": "snapshot"},
            "user_id": _STR,
            "email": _STR,
        },
        "required": [],
    },
}

WW_APPROVALS_SCHEMA = {
    "name": "ww_approvals",
    "description": "List pending trade approvals awaiting a human decision. The agent can summarize/triage these; it cannot approve or execute (that stays human-driven in the dashboard).",
    "parameters": {
        "type": "object",
        "properties": {"user_id": _STR, "email": _STR},
        "required": [],
    },
}

WW_AUDIT_SCHEMA = {
    "name": "ww_audit",
    "description": "Inspect the tamper-evident audit trail: action='verify' checks the hash chain integrity, 'events' lists recent audit events.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["verify", "events"], "default": "verify"},
            "limit": {"type": "integer", "description": "For events: max rows."},
            "user_id": _STR,
            "email": _STR,
        },
        "required": [],
    },
}
