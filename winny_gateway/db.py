"""Supabase database client for WinnyWoo Gateway.

Provides a singleton Supabase client used by all routes for persistence.
Uses service_role key for server-side operations (bypasses RLS for writes).
Uses anon key + user JWT for user-scoped reads.

Environment:
    SUPABASE_URL         — project URL (https://xxx.supabase.co)
    SUPABASE_SERVICE_ROLE_KEY — service role key (server-side, bypasses RLS)
    SUPABASE_ANON_KEY    — anon/publishable key (client-side, respects RLS)
"""

from __future__ import annotations

import os
from typing import Any

from winny_gateway.logging import get_logger

logger = get_logger(__name__)

_client: Any = None
_admin_client: Any = None


def get_supabase_client() -> Any:
    """Get the Supabase client (anon key — respects RLS)."""
    global _client
    if _client is None:
        from supabase import create_client

        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_ANON_KEY", "")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env"
            )
        _client = create_client(url, key)
        logger.info("Supabase client initialized", extra={"component": "db"})
    return _client


def get_admin_client() -> Any:
    """Get the Supabase admin client (service_role key — bypasses RLS).

    Use this for server-side operations like writing audit events,
    storing encrypted credentials, etc.
    """
    global _admin_client
    if _admin_client is None:
        from supabase import create_client

        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env"
            )
        _admin_client = create_client(url, key)
        logger.info("Supabase admin client initialized", extra={"component": "db"})
    return _admin_client


def get_user_client(access_token: str) -> Any:
    """Get a Supabase client authenticated as a specific user.

    This respects RLS policies scoped to the user's JWT.
    """
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY must be set")

    client = create_client(url, key)
    client.auth.set_session(access_token, "")
    return client


# ── Cross-tenant guard (audit F4) ─────────────────────────────────────────────
#
# Every helper below defaults to the service-role client, which BYPASSES
# Postgres RLS. That makes correct user_id scoping the gateway's sole line of
# defence against cross-tenant reads/writes. To stop a single forgotten filter
# from leaking another user's data, queries against user-owned tables must be
# scoped by user_id. Pass `allow_unscoped=True` only for vetted server jobs
# that legitimately scan across users, or pass `access_token=...` to run the
# query through the user-scoped (RLS-enforced) client instead.

_USER_SCOPED_TABLES = frozenset({
    "trade_history",
    "portfolio_snapshots",
    "user_preferences",
    "auto_trade_config",
    "broker_credentials",
    "audit_events",
    "vault_documents",
    "decisions",
    "positions",
    "orders",
    "support_tickets",
    "artifacts",
    "rooms",
    "finance_accounts",
    "finance_transactions",
    "finance_connections",
    "integration_secrets",
    "connections",
    "outbound_actions",
    "crm_contacts",
    "crm_deals",
    "mail_messages",
    "mail_drafts",
    "ai_interventions",
    "departments",
    "ops_jobs",
    "ops_tasks",
    "ops_events",
})


def _client_for(access_token: str | None) -> Any:
    """User-scoped (RLS) client when a token is supplied, else service-role."""
    return get_user_client(access_token) if access_token else get_admin_client()


def _scope_ok_filters(
    table: str, filters: dict[str, Any] | None, *, access_token: str | None, allow_unscoped: bool
) -> bool:
    """False if an admin-client query on a user table lacks a user_id scope."""
    if access_token is not None or allow_unscoped:
        return True  # RLS client enforces scope, or caller opted out explicitly.
    if table not in _USER_SCOPED_TABLES:
        return True
    if filters and filters.get("user_id"):
        return True
    logger.error(
        "Blocked unscoped query on user-owned table — missing user_id filter",
        extra={"action": "db.cross_tenant_blocked", "table": table, "component": "db"},
    )
    return False


def _scope_ok_row(
    table: str, data: dict[str, Any], *, access_token: str | None, allow_unscoped: bool
) -> bool:
    """False if an admin-client write to a user table lacks a user_id value."""
    if access_token is not None or allow_unscoped:
        return True
    if table not in _USER_SCOPED_TABLES:
        return True
    if data.get("user_id"):
        return True
    logger.error(
        "Blocked unscoped write to user-owned table — missing user_id",
        extra={"action": "db.cross_tenant_blocked", "table": table, "component": "db"},
    )
    return False


# ── Helper functions ──────────────────────────────────────────────────────────


async def db_upsert(
    table: str,
    data: dict[str, Any],
    *,
    on_conflict: str = "user_id",
    access_token: str | None = None,
    allow_unscoped: bool = False,
) -> dict[str, Any] | None:
    """Upsert a row into a table. Returns the inserted/updated row."""
    if not _scope_ok_row(table, data, access_token=access_token, allow_unscoped=allow_unscoped):
        return None
    try:
        client = _client_for(access_token)
        result = client.table(table).upsert(data, on_conflict=on_conflict).execute()
        if result.data:
            return dict(result.data[0])
        return None
    except Exception as e:
        logger.error(
            "DB upsert failed: %s",
            e,
            extra={"action": "db.upsert_fail", "table": table, "error": str(e), "component": "db"},
        )
        return None


async def db_select(
    table: str,
    *,
    filters: dict[str, Any] | None = None,
    columns: str = "*",
    limit: int | None = None,
    order_by: str | None = None,
    access_token: str | None = None,
    allow_unscoped: bool = False,
) -> list[dict[str, Any]]:
    """Select rows from a table with optional filters."""
    if not _scope_ok_filters(table, filters, access_token=access_token, allow_unscoped=allow_unscoped):
        return []
    try:
        client = _client_for(access_token)
        query = client.table(table).select(columns)

        if filters:
            for key, value in filters.items():
                query = query.eq(key, value)

        if order_by:
            desc = order_by.startswith("-")
            col = order_by.lstrip("-")
            query = query.order(col, desc=desc)

        if limit:
            query = query.limit(limit)

        result = query.execute()
        return result.data or []
    except Exception as e:
        logger.error(
            "DB select failed: %s",
            e,
            extra={"action": "db.select_fail", "table": table, "error": str(e), "component": "db"},
        )
        return []


async def db_insert(
    table: str,
    data: dict[str, Any],
    *,
    access_token: str | None = None,
    allow_unscoped: bool = False,
) -> dict[str, Any] | None:
    """Insert a row into a table."""
    if not _scope_ok_row(table, data, access_token=access_token, allow_unscoped=allow_unscoped):
        return None
    try:
        client = _client_for(access_token)
        result = client.table(table).insert(data).execute()
        if result.data:
            return dict(result.data[0])
        return None
    except Exception as e:
        logger.error(
            "DB insert failed: %s",
            e,
            extra={"action": "db.insert_fail", "table": table, "error": str(e), "component": "db"},
        )
        return None


async def audit_log(
    *,
    user_id: str | None,
    event_type: str,
    action: str,
    component: str = "system",
    details: dict[str, Any] | None = None,
    symbol: str | None = None,
    broker: str | None = None,
) -> None:
    """Write an audit event to the audit_events table.

    Fire-and-forget — failures are logged but never propagated.
    """
    try:
        client = get_admin_client()
        client.table("audit_events").insert({
            "user_id": user_id,
            "event_type": event_type,
            "action": action,
            "component": component,
            "details": details or {},
            "symbol": symbol,
            "broker": broker,
        }).execute()
    except Exception as e:
        logger.debug("Audit log write failed: %s", e, extra={"component": "db"})


async def db_update(
    table: str,
    data: dict[str, Any],
    *,
    filters: dict[str, Any],
    access_token: str | None = None,
    allow_unscoped: bool = False,
) -> list[dict[str, Any]]:
    """Update rows matching filters. Returns the updated rows.

    Unlike upsert, this never attempts an insert — so a partial column set is
    safe against NOT NULL columns on an existing row. The same scope guard as
    select/delete applies (a user-owned table needs a user_id filter).
    """
    if not _scope_ok_filters(table, filters, access_token=access_token, allow_unscoped=allow_unscoped):
        return []
    try:
        client = _client_for(access_token)
        query = client.table(table).update(data)
        for key, value in filters.items():
            query = query.eq(key, value)
        result = query.execute()
        return result.data or []
    except Exception as e:
        logger.error(
            "DB update failed: %s",
            e,
            extra={"action": "db.update_fail", "table": table, "error": str(e), "component": "db"},
        )
        return []


async def db_delete(
    table: str,
    *,
    filters: dict[str, Any],
    access_token: str | None = None,
    allow_unscoped: bool = False,
) -> bool:
    """Delete rows from a table matching filters."""
    if not _scope_ok_filters(table, filters, access_token=access_token, allow_unscoped=allow_unscoped):
        return False
    try:
        client = _client_for(access_token)
        query = client.table(table).delete()
        for key, value in filters.items():
            query = query.eq(key, value)
        query.execute()
        return True
    except Exception as e:
        logger.error(
            "DB delete failed: %s",
            e,
            extra={"action": "db.delete_fail", "table": table, "error": str(e), "component": "db"},
        )
        return False
