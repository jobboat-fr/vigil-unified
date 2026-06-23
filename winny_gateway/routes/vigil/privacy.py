"""Privacy / GDPR — a tenant's right to export and to erase their data.

  GET    /v1/privacy/export   all of the tenant's rows across every user-scoped table
                              (secret-bearing columns redacted — never export tokens)
  DELETE /v1/privacy/data     erase all of the tenant's rows (right to be forgotten)

Scoped strictly to the authenticated user. Reuses the db layer's user-scoped table set
so new tables are covered automatically.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from winny_gateway.auth import get_current_user
from winny_gateway.db import _USER_SCOPED_TABLES, db_delete, db_select

router = APIRouter(prefix="/v1/privacy", tags=["privacy"])

# Stable, sorted list of the tenant's data tables.
_TABLES = sorted(_USER_SCOPED_TABLES)
# Columns that hold secrets — redacted on export, never returned in plaintext.
_SECRET_COLS = {"access_token_enc", "refresh_token_enc", "value_enc",
                "api_key_encrypted", "api_secret_encrypted", "api_password_encrypted"}


def _uid(user: dict[str, Any]) -> str:
    uid = user.get("sub")
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no user id in token")
    return str(uid)


def _redact(row: dict[str, Any]) -> dict[str, Any]:
    return {k: ("***" if v and (k in _SECRET_COLS or k.endswith("_enc")) else v) for k, v in row.items()}


@router.get("/export")
async def export_data(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    tables: dict[str, list[dict[str, Any]]] = {}
    total = 0
    for table in _TABLES:
        rows = await db_select(table, filters={"user_id": uid}, limit=5000)
        if rows:
            tables[table] = [_redact(r) for r in rows]
            total += len(rows)
    return {"ok": True, "data": {
        "user_id": uid, "exported_at": datetime.now(UTC).isoformat(),
        "row_count": total, "tables": tables,
    }}


@router.delete("/data")
async def erase_data(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """GDPR erasure — deletes all of the tenant's rows. Irreversible."""
    uid = _uid(user)
    deleted: dict[str, int] = {}
    for table in _TABLES:
        rows = await db_select(table, filters={"user_id": uid}, limit=5000)
        if rows:
            await db_delete(table, filters={"user_id": uid})
            deleted[table] = len(rows)
    return {"ok": True, "data": {"deleted": deleted, "tables_cleared": len(deleted)}}
