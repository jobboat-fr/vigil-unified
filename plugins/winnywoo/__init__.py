"""VIGIL × WinnyWoo trading-desk plugin — bundled, auto-loaded.

Registers 5 read/observe tools into the ``winnywoo`` toolset, each calling the
in-tree ``winny_gateway`` (default ``http://127.0.0.1:8400``). The tools let the
agent see the live desk — market context, signals, portfolio, pending
approvals, audit chain — so it can reason about and propose actions. Order
execution is deliberately absent: the human approval gate in the dashboard
remains the only path to a real trade.

Bundled + ``kind: backend`` → auto-loads on startup (same pattern as the
spotify / image_gen plugins). No user opt-in needed.
"""

from __future__ import annotations

from plugins.winnywoo.tools import (
    WW_APPROVALS_SCHEMA,
    WW_AUDIT_SCHEMA,
    WW_MARKET_SCHEMA,
    WW_PORTFOLIO_SCHEMA,
    WW_SIGNALS_SCHEMA,
    _handle_approvals,
    _handle_audit,
    _handle_market,
    _handle_portfolio,
    _handle_signals,
)

_TOOLS = (
    ("ww_market",    WW_MARKET_SCHEMA,    _handle_market,    "📈"),
    ("ww_signals",   WW_SIGNALS_SCHEMA,   _handle_signals,   "📡"),
    ("ww_portfolio", WW_PORTFOLIO_SCHEMA, _handle_portfolio, "💼"),
    ("ww_approvals", WW_APPROVALS_SCHEMA, _handle_approvals, "✅"),
    ("ww_audit",     WW_AUDIT_SCHEMA,     _handle_audit,     "🔐"),
)


def _always_available() -> bool:
    # Tools stay visible even if the gateway is down; a failed call returns a
    # clear tool error (with the configured base URL) rather than hiding.
    return True


def register(ctx) -> None:
    """Register all WinnyWoo desk tools. Called once by the plugin loader."""
    for name, schema, handler, emoji in _TOOLS:
        ctx.register_tool(
            name=name,
            toolset="winnywoo",
            schema=schema,
            handler=handler,
            check_fn=_always_available,
            emoji=emoji,
        )
