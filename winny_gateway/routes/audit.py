"""Audit trail endpoints.

Reads from whichever audit backend is configured:

  * Supabase ``public.audit_events`` table (preferred, durable across
    Railway deploys) — used when ``SUPABASE_URL`` + ``SUPABASE_SERVICE_ROLE_KEY``
    resolve a working admin client.
  * SQLite at ``WINNY_AUDIT_PATH`` (legacy fallback, ephemeral on Railway).

Both backends share the same hash-chain shape (SPECS.md §7.4) — events
written in one can be verified in the other. The route just picks whichever
backend has a live handle at request time.

The MCP layer is intentionally bypassed; ``mcp-algo`` never registered a
``get_audit_events`` tool, and routing through MCP added a layer of error
envelopes for no benefit.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from winny_gateway.auth import get_current_user
from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


# Lazy-init store handle; one per-process. Supabase preferred, SQLite fallback.
_store: Any = None
_store_kind: str = "uninitialised"


def _get_store() -> Any:
    global _store, _store_kind
    if _store is not None:
        return _store
    # Try Supabase first.
    try:
        from winny_gateway.db import get_admin_client
        from winny.common.audit_supabase import SupabaseAuditStore

        client = get_admin_client()
        if client is not None:
            _store = SupabaseAuditStore(client)
            _store_kind = "supabase"
            logger.info(
                "audit store opened — supabase",
                extra={"action": "audit.open_ok", "backend": "supabase", "component": "audit"},
            )
            return _store
    except Exception as exc:
        logger.warning(
            "supabase audit store unavailable, falling back to sqlite: %s", exc,
            extra={"action": "audit.supabase_fail", "error": str(exc), "component": "audit"},
        )
    # Fallback — SQLite.
    try:
        from winny.common.audit import AuditStore

        db_path = (
            os.getenv("WINNY_AUDIT_PATH")
            or os.getenv("WINNY_AUDIT_DB")
            or "/app/data/.winny/audit.db"
        )
        if not Path(db_path).parent.exists():
            logger.warning(
                "audit dir missing — events list will return empty",
                extra={"action": "audit.dir_missing", "path": str(db_path), "component": "audit"},
            )
            return None
        _store = AuditStore(db_path)
        _store_kind = "sqlite"
        logger.info(
            "audit store opened — sqlite",
            extra={"action": "audit.open_ok", "backend": "sqlite", "path": str(db_path),
                   "component": "audit"},
        )
    except Exception as exc:
        logger.warning(
            "audit store open failed — events list will return empty: %s", exc,
            extra={"action": "audit.open_fail", "error": str(exc), "component": "audit"},
        )
        _store = None
    return _store


def _event_to_dict(evt: Any) -> dict[str, Any]:
    """Coerce an AuditEvent dataclass to the shape the UI expects."""
    return {
        "id": getattr(evt, "seq_no", None),
        "seq_no": getattr(evt, "seq_no", None),
        "ts": getattr(evt, "ts", None),
        "action": getattr(evt, "event_type", None),
        "event_type": getattr(evt, "event_type", None),
        "decision_id": getattr(evt, "decision_id", None),
        "data": getattr(evt, "payload", None),
        "prev_hash": getattr(evt, "prev_hash", None),
        "this_hash": getattr(evt, "this_hash", None),
        "critical": getattr(evt, "critical", False),
        "component": getattr(evt, "component", None) or "winny",
        "actor_email": getattr(evt, "actor_email", None),
    }


@router.get("/events")
async def get_audit_events(
    request: Request,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    event_type: str | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Return audit trail events from the hash-chained log.

    Pagination: ``offset`` is a seq_no cursor; events_since returns events
    *strictly after* that seq_no. We compute the absolute starting seq_no
    as ``(latest_seq - limit - offset)`` so the default response is the
    most recent ``limit`` events, oldest-first within that window.
    """
    store = _get_store()
    if store is None:
        return {"ok": True, "data": [], "items": [], "count": 0, "backend": _store_kind}

    try:
        # Supabase store has events_recent (efficient direct query).
        # SQLite store uses events_since + latest (walk back from head).
        events_recent = getattr(store, "events_recent", None)
        if callable(events_recent):
            events = events_recent(limit=limit + offset, event_type=event_type)
            page = events[offset:offset + limit] if offset else events[:limit]
        else:
            latest = store.latest()
            if latest is None:
                return {"ok": True, "data": [], "items": [], "count": 0, "backend": _store_kind}
            start_seq = max(0, latest.seq_no - limit - offset)
            events = store.events_since(start_seq, limit + offset)
            page = events[offset:offset + limit] if offset else events[:limit]
            page = list(reversed(page))
            if event_type:
                page = [e for e in page if str(getattr(e, "event_type", "")) == event_type]
        out = [_event_to_dict(e) for e in page]
        return {"ok": True, "data": out, "items": out, "count": len(out), "backend": _store_kind}
    except Exception as exc:
        logger.error(
            "audit events query failed: %s", exc,
            extra={"action": "audit.events_fail", "error": str(exc), "component": "audit"},
        )
        return {"ok": True, "data": [], "items": [], "count": 0, "error": str(exc), "backend": _store_kind}


@router.get("/verify")
async def verify_chain(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Verify the integrity of the audit hash chain (SPECS.md §7.4)."""
    store = _get_store()
    if store is None:
        return {
            "ok": True,
            "data": {"valid": False, "verified": False, "reason": "audit_store_unavailable"},
        }
    try:
        result = store.verify_chain()
        # Supabase store returns dict; SQLite returns ChainVerification dataclass.
        if isinstance(result, dict):
            return {"ok": True, "data": result, "backend": _store_kind}
        return {
            "ok": True,
            "data": {
                "valid": result.valid,
                "verified": result.valid,
                "first_broken_seq": result.first_broken_seq,
                "reason": result.reason,
                "checked": result.checked,
            },
            "backend": _store_kind,
        }
    except Exception as exc:
        logger.error(
            "audit verify failed: %s", exc,
            extra={"action": "audit.verify_fail", "error": str(exc), "component": "audit"},
        )
        return {
            "ok": True,
            "data": {"valid": False, "verified": False, "reason": f"verify_error: {exc}"},
        }
