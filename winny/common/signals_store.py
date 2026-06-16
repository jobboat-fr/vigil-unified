"""Thin read-only Supabase accessor for the `trading_signals` table.

Shared between the timesfm and tradingagents MCP servers so both can surface
the rows written by `gateway/analytics.signal_runner_loop` to MCP callers
(Hermes, dashboard, agent chat).

We intentionally keep this file dependency-light — the MCP servers run in
their own processes and may not have the full `gateway.*` package wired up,
so we read SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY directly from env.

If Supabase isn't reachable or env is unset, the helpers return an empty
list rather than raising — MCP tools degrade gracefully to "no signals
available right now".
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_client: Any = None
_client_init_failed = False


def _get_client() -> Any | None:
    """Lazy-init a service-role Supabase client. Caches; never raises.

    Returns None if env is missing or the supabase package can't be imported
    (e.g. the MCP env image doesn't include it).
    """
    global _client, _client_init_failed
    if _client is not None:
        return _client
    if _client_init_failed:
        return None
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.environ.get("SUPABASE_ANON_KEY", "").strip()
    )
    if not url or not key:
        _client_init_failed = True
        logger.info("signals_store: SUPABASE_URL/KEY missing, returning empty stubs")
        return None
    try:
        from supabase import create_client

        _client = create_client(url, key)
        return _client
    except Exception as exc:
        _client_init_failed = True
        logger.warning("signals_store: supabase client init failed: %s", exc)
        return None


def _normalize_symbol(symbol: str | None) -> str | None:
    """Match the symbol form analytics writes (e.g. 'BTC/USDT').

    Accepts canonical Winny forms ('CR:BTC-USDT@kraken') and best-efforts
    them down to the BASE/QUOTE form that analytics.py inserts.
    """
    if not symbol:
        return None
    s = symbol.strip().upper()
    if ":" in s:
        s = s.split(":", 1)[1]
    if "@" in s:
        s = s.split("@", 1)[0]
    s = s.replace("-", "/")
    return s


def fetch_signals(
    *,
    source: str | None = None,
    symbol: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return up to ``limit`` rows from public.trading_signals.

    Args:
        source: 'forecaster' | 'analyst' | None (no filter).
        symbol: canonical or pair-style symbol; matched after normalization.
        limit:  1..100.

    Never raises — failures log and return [].
    """
    limit = max(1, min(int(limit or 20), 100))
    client = _get_client()
    if client is None:
        return []
    try:
        q = client.table("trading_signals").select("*").order("ts", desc=True).limit(limit)
        if source:
            q = q.eq("source", source)
        norm = _normalize_symbol(symbol)
        if norm:
            q = q.eq("symbol", norm)
        res = q.execute()
        rows = getattr(res, "data", None) or []
        return list(rows) if isinstance(rows, list) else []
    except Exception as exc:
        logger.warning("signals_store.fetch_signals failed: %s", exc)
        return []


def fetch_forecasts(symbol: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Convenience wrapper — source='forecaster'."""
    return fetch_signals(source="forecaster", symbol=symbol, limit=limit)


def fetch_decisions(symbol: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Convenience wrapper — source='analyst'."""
    return fetch_signals(source="analyst", symbol=symbol, limit=limit)
