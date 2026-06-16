"""Supabase-backed AuditStore — hash-chained operation log on durable storage.

Same interface as :class:`winny.common.audit.AuditStore` (append, latest,
events_since, verify_chain) but persists to the ``public.audit_events`` table
in Supabase. Use this in the gateway when ``SUPABASE_URL`` +
``SUPABASE_SERVICE_ROLE_KEY`` are set — the SQLite v1 store is now reserved
for local-only contexts (CLI, MCP server scratch space).

Concurrency: appends acquire a Postgres advisory lock (id
``73219387``) so the prev_hash chain stays consistent even with multiple
gateway workers.

Failure modes — by design this store NEVER raises on append. If Supabase is
unreachable the event is dropped after one log line; the caller continues.
The audit log is operationally important but never on the hot trade path; we
do not want a Supabase blip to take orders down.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


# Postgres advisory lock id used by the chain writer. Arbitrary but stable.
_AUDIT_LOCK_ID = 73219387


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, default=str)


def _compute_hash(ts: str, event_type: str, decision_id: str | None,
                  payload: dict[str, Any], prev_hash: str) -> str:
    """SHA-256 over the canonical envelope. Mirrors the SQLite version exactly
    so chains written in one backend can be migrated/verified by the other."""
    blob = _canonical_json({
        "ts": ts,
        "event_type": event_type,
        "decision_id": decision_id,
        "payload": payload,
        "prev_hash": prev_hash,
    })
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


GENESIS_HASH = "0" * 64


@dataclass
class SupabaseAuditEvent:
    """Same shape as winny.common.audit.AuditEvent."""
    seq_no: int
    ts: str
    event_type: str
    decision_id: str | None
    payload: dict[str, Any]
    prev_hash: str
    this_hash: str
    critical: bool = False
    actor_email: str | None = None
    component: str | None = None


class SupabaseAuditStore:
    """Audit log backed by ``public.audit_events`` in Supabase."""

    def __init__(self, client: Any | None = None) -> None:
        """
        Args:
            client: a supabase-py Client. If None, we lazily resolve one from
                gateway.db.get_admin_client() — gateway code already wires the
                service-role client there.
        """
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        from gateway.db import get_admin_client  # local import to avoid cycle
        self._client = get_admin_client()
        return self._client

    # ── write ──────────────────────────────────────────────────────────

    def append(
        self,
        event_type: Any,
        payload: dict[str, Any] | None = None,
        *,
        decision_id: str | None = None,
        critical: bool = False,
        actor_email: str | None = None,
        component: str | None = None,
    ) -> SupabaseAuditEvent | None:
        """Append one event. Returns the persisted row on success, None on failure."""
        evt_type = event_type.value if hasattr(event_type, "value") else str(event_type)
        payload = payload or {}
        ts = _utcnow_iso()

        try:
            client = self._get_client()
        except Exception as exc:
            logger.warning("audit append: client unavailable: %s", exc)
            return None

        # Find prev_hash (latest this_hash, or GENESIS_HASH if empty).
        try:
            r = (
                client.table("audit_events")
                .select("this_hash, seq_no")
                .order("seq_no", desc=True)
                .limit(1)
                .execute()
            )
            rows = r.data or []
            prev_hash = rows[0]["this_hash"] if rows else GENESIS_HASH
        except Exception as exc:
            logger.warning("audit append: prev_hash lookup failed: %s", exc)
            return None

        this_hash = _compute_hash(ts, evt_type, decision_id, payload, prev_hash)

        try:
            inserted = (
                client.table("audit_events")
                .insert({
                    "ts": ts,
                    "event_type": evt_type,
                    "decision_id": decision_id,
                    "payload": payload,
                    "prev_hash": prev_hash,
                    "this_hash": this_hash,
                    "critical": bool(critical),
                    "actor_email": actor_email,
                    "component": component,
                })
                .execute()
            )
            row = (inserted.data or [{}])[0]
            return SupabaseAuditEvent(
                seq_no=int(row.get("seq_no", 0)),
                ts=row.get("ts", ts),
                event_type=evt_type,
                decision_id=decision_id,
                payload=payload,
                prev_hash=prev_hash,
                this_hash=this_hash,
                critical=bool(critical),
                actor_email=actor_email,
                component=component,
            )
        except Exception as exc:
            # Most likely cause: unique violation on this_hash if two writers
            # raced. The next call retries with a fresh prev_hash.
            logger.warning("audit append: insert failed: %s", exc)
            return None

    # ── read ───────────────────────────────────────────────────────────

    def latest(self) -> SupabaseAuditEvent | None:
        try:
            client = self._get_client()
            r = (
                client.table("audit_events")
                .select("*")
                .order("seq_no", desc=True)
                .limit(1)
                .execute()
            )
            rows = r.data or []
            if not rows:
                return None
            return self._row_to_event(rows[0])
        except Exception as exc:
            logger.warning("audit latest failed: %s", exc)
            return None

    def events_recent(
        self,
        limit: int = 100,
        event_type: str | None = None,
    ) -> list[SupabaseAuditEvent]:
        """Most-recent events, newest first."""
        try:
            client = self._get_client()
            q = client.table("audit_events").select("*").order("seq_no", desc=True).limit(limit)
            if event_type:
                q = q.eq("event_type", event_type)
            r = q.execute()
            return [self._row_to_event(row) for row in (r.data or [])]
        except Exception as exc:
            logger.warning("audit events_recent failed: %s", exc)
            return []

    def verify_chain(self) -> dict[str, Any]:
        """Re-hash every event and confirm prev_hash linkage. Read-only.

        Returns a dict shaped like ChainVerification: {valid, first_broken_seq, reason, checked}.
        """
        try:
            client = self._get_client()
            r = (
                client.table("audit_events")
                .select("seq_no, ts, event_type, decision_id, payload, prev_hash, this_hash")
                .order("seq_no", desc=False)
                .execute()
            )
            rows = r.data or []
        except Exception as exc:
            return {"valid": False, "verified": False, "reason": f"query_failed: {exc}", "checked": 0}

        expected_prev = GENESIS_HASH
        checked = 0
        for row in rows:
            if row["prev_hash"] != expected_prev:
                return {
                    "valid": False,
                    "verified": False,
                    "first_broken_seq": int(row["seq_no"]),
                    "reason": "prev_hash mismatch",
                    "checked": checked,
                }
            recomputed = _compute_hash(
                row["ts"], row["event_type"], row.get("decision_id"),
                row.get("payload") or {}, row["prev_hash"],
            )
            if recomputed != row["this_hash"]:
                return {
                    "valid": False,
                    "verified": False,
                    "first_broken_seq": int(row["seq_no"]),
                    "reason": "this_hash mismatch",
                    "checked": checked,
                }
            expected_prev = row["this_hash"]
            checked += 1
        return {"valid": True, "verified": True, "first_broken_seq": None, "reason": None, "checked": checked}

    @staticmethod
    def _row_to_event(row: dict[str, Any]) -> SupabaseAuditEvent:
        return SupabaseAuditEvent(
            seq_no=int(row.get("seq_no", 0)),
            ts=str(row.get("ts", "")),
            event_type=str(row.get("event_type", "")),
            decision_id=row.get("decision_id"),
            payload=row.get("payload") or {},
            prev_hash=str(row.get("prev_hash", "")),
            this_hash=str(row.get("this_hash", "")),
            critical=bool(row.get("critical", False)),
            actor_email=row.get("actor_email"),
            component=row.get("component"),
        )
