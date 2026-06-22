"""Connector kit (Phase 0) — the reusable base every system-of-record connector
shares, generalised from the proven Plaid connector.

Design (commercial / multi-tenant correct):
  • Platform app-credentials (OAuth client id/secret) live in env / secrets-manager —
    one set, ours. They are NEVER stored per-tenant.
  • Per-tenant credentials are ONLY the access/refresh token, encrypted at rest
    (Fernet) in the generic `connections` table, scoped by user_id.
  • Tokens are write-only over the API — status returns a mask + source, never the value.

A provider implements `Connector` (verify_token + sync); the generic store +
orchestration here handle persistence, masking, idempotency, and scoping.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from winny_gateway.db import db_delete, db_insert, db_select, db_update
from winny_gateway.integrations.secrets import decrypt_secret, encrypt_secret, mask_secret
from winny_gateway.logging import get_logger

logger = get_logger(__name__)
_TABLE = "connections"


class ConnectorError(RuntimeError):
    def __init__(self, message: str, *, code: str = "connector_error", status: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class Connector(ABC):
    """One per provider. Stateless — the token is passed in per call."""

    provider: str = ""
    kind: str = "generic"

    @abstractmethod
    async def verify_token(self, token: str, account: str | None = None) -> dict[str, Any]:
        """Validate a tenant token (and optional account, e.g. an email for IMAP);
        return {external_account, ...} or raise ConnectorError."""

    @abstractmethod
    async def sync(self, uid: str, conn: dict[str, Any], token: str) -> dict[str, Any]:
        """Pull data for one connection. Return {metadata, counts...}."""


# ── Registry ──────────────────────────────────────────────────────────────────
_REGISTRY: dict[str, Connector] = {}


def register(connector: Connector) -> None:
    _REGISTRY[connector.provider] = connector


def get_connector(provider: str) -> Connector | None:
    return _REGISTRY.get(provider)


def providers() -> list[dict[str, Any]]:
    return [{"id": c.provider, "kind": c.kind} for c in _REGISTRY.values()]


# ── Generic per-tenant store ───────────────────────────────────────────────────
def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "provider": row.get("provider"),
        "kind": row.get("kind"),
        "external_account": row.get("external_account"),
        "status": row.get("status"),
        "token_masked": mask_secret(_safe_decrypt(row.get("access_token_enc") or "")),
        "last_synced_at": row.get("last_synced_at"),
        "metadata": row.get("metadata") or {},
        "created_at": row.get("created_at"),
    }


def _safe_decrypt(enc: str) -> str:
    try:
        return decrypt_secret(enc) if enc else ""
    except Exception:  # noqa: BLE001 — masking only
        return ""


async def connect(uid: str, provider: str, token: str, account: str | None = None) -> dict[str, Any]:
    """Verify a tenant token with the provider, then store it encrypted."""
    c = get_connector(provider)
    if not c:
        raise ConnectorError(f"unknown provider '{provider}'", code="unknown_provider", status=404)
    if not (token or "").strip():
        raise ConnectorError("token is required", code="missing_token", status=400)
    identity = await c.verify_token(token.strip(), (account or "").strip() or None)
    row = await db_insert(_TABLE, {
        "user_id": uid,
        "provider": provider,
        "kind": c.kind,
        "external_account": identity.get("external_account") or (account or "").strip() or None,
        "access_token_enc": encrypt_secret(token.strip()),
        "refresh_token_enc": encrypt_secret(identity["refresh_token"]) if identity.get("refresh_token") else None,
        "status": "active",
        "metadata": {k: v for k, v in identity.items() if k not in ("refresh_token",)},
    })
    return _public(row or {})


async def list_connections(uid: str, provider: str | None = None) -> list[dict[str, Any]]:
    filters: dict[str, Any] = {"user_id": uid}
    if provider:
        filters["provider"] = provider
    return [_public(r) for r in await db_select(_TABLE, filters=filters, limit=200)]


async def status(uid: str) -> dict[str, Any]:
    return {"providers": providers(), "connections": await list_connections(uid)}


async def run_sync(uid: str, connection_id: str) -> dict[str, Any]:
    rows = await db_select(_TABLE, filters={"id": connection_id, "user_id": uid}, limit=1)
    if not rows:
        raise ConnectorError("connection not found", code="not_found", status=404)
    conn = rows[0]
    c = get_connector(conn["provider"])
    if not c:
        raise ConnectorError(f"unknown provider '{conn['provider']}'", code="unknown_provider", status=404)
    token = _safe_decrypt(conn.get("access_token_enc") or "")
    if not token:
        raise ConnectorError("connection token unreadable", code="bad_token", status=500)
    try:
        result = await c.sync(uid, conn, token)
    except ConnectorError:
        await db_update(_TABLE, {"status": "error"}, filters={"id": connection_id, "user_id": uid})
        raise
    await db_update(_TABLE, {
        "status": "active", "error": None,
        "metadata": {**(conn.get("metadata") or {}), **(result.get("metadata") or {})},
        "last_synced_at": datetime.now(UTC).isoformat(),
    }, filters={"id": connection_id, "user_id": uid})
    return result


async def sync_kind(uid: str, kind: str) -> dict[str, Any]:
    """Best-effort: sync every active connection of a given kind (email|crm|payments|…)
    for a tenant. Used by departments to pull fresh system-of-record data before a run;
    never raises — a provider error is recorded on its connection and skipped."""
    rows = await db_select(_TABLE, filters={"user_id": uid, "kind": kind}, limit=50)
    synced = 0
    for r in rows:
        try:
            await run_sync(uid, r["id"])
            synced += 1
        except ConnectorError as exc:
            logger.info("connector.sync_kind skip %s/%s: %s", kind, r.get("provider"), exc.code)
    return {"synced": synced}


async def disconnect(uid: str, connection_id: str) -> bool:
    rows = await db_select(_TABLE, filters={"id": connection_id, "user_id": uid}, limit=1)
    if not rows:
        return False
    await db_delete(_TABLE, filters={"id": connection_id, "user_id": uid})
    return True
