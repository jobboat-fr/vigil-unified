"""WAL'd, hash-chained audit log — SPECS.md §7.4 + §14.4.3.

Design (v1):
- SQLite, WAL journal mode, `synchronous=FULL` for safety.
- Every event has a sha256 chain: `this_hash = sha256(canonical_json(ts, type, decision_id, payload, prev_hash))`.
- First event's `prev_hash` is the genesis marker (64 zeros).
- Single in-process writer lock; WAL allows concurrent readers.
- `append(...)` is the only mutator; never expose raw SQL upward.

Group-commit (§14.4.3) is deferred; v1 fsyncs every COMMIT. The schema and
write path are designed so group-commit batching can be added without changing
callers — `append_many(events)` is reserved for that future expansion.

The audit log is the legal/operational source of truth. It MUST outlive any
service restart, and any tampering MUST be detectable via `verify_chain`.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from .errors import (
    AuditChainBrokenError,
    AuditDatabaseError,
    AuditEmptyError,
)

# ---------- constants ----------

GENESIS_HASH = "0" * 64  # placeholder prev_hash for seq_no=1


# ---------- known event types (spec-driven, not exhaustive) ----------


class EventType(StrEnum):
    """Vocabulary of audit event types referenced by the spec.

    Strings are also accepted via `append(event_type=...)` for forward compat,
    but using this enum at call sites is preferred for type safety and grep-ability.
    """

    # service lifecycle
    SERVICE_STARTED = "service.started"
    SERVICE_STOPPED = "service.stopped"

    # decision lifecycle (§5.1)
    DECISION_DRAFTED = "decision.drafted"
    DECISION_VALIDATED = "decision.validated"
    DECISION_PROPOSED = "decision.proposed"
    DECISION_PRESENTED = "decision.presented"
    DECISION_APPROVED = "decision.approved"
    DECISION_REJECTED = "decision.rejected"
    DECISION_EXPIRED = "decision.expired"
    DECISION_SUBMITTED = "decision.submitted"
    DECISION_CLOSED = "decision.closed"

    # order lifecycle (§5.2)
    ORDER_SUBMITTED = "order.submitted"
    ORDER_ACCEPTED = "order.accepted"
    ORDER_PARTIAL = "order.partial"
    ORDER_FILLED = "order.filled"
    ORDER_CANCELLED = "order.cancelled"
    ORDER_REJECTED = "order.rejected"

    # approval lifecycle (§5.3)
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_CONSUMED = "approval.consumed"
    APPROVAL_REVOKED = "approval.revoked"
    APPROVAL_EXPIRED = "approval.expired"

    # tiered analysis (§14.3.1)
    TIER_PROMOTED = "tier.promoted"
    TIER_DROPPED = "tier.dropped"

    # operations
    CANCEL_ALL = "cancel_all"
    RECONCILIATION_DIFF = "reconciliation.diff"
    AUDIT_ANCHOR_WRITTEN = "audit.anchor_written"
    FORECAST_UNAVAILABLE = "forecast.unavailable"
    BROKER_UNREACHABLE = "broker.unreachable"


# ---------- value objects ----------


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """A persisted audit row."""

    seq_no: int
    ts: str  # ISO8601 UTC
    event_type: str
    decision_id: str | None
    payload: dict[str, Any]
    prev_hash: str
    this_hash: str
    critical: bool


@dataclass(frozen=True, slots=True)
class ChainVerification:
    """Result of `verify_chain`."""

    valid: bool
    first_broken_seq: int | None
    reason: str | None
    checked: int


@dataclass(frozen=True, slots=True)
class Anchor:
    """A point-in-time hash anchor written to disk (§7.4)."""

    seq_no: int
    ts: str  # ts of the anchored event
    this_hash: str
    anchored_at: str  # iso8601 UTC of when anchor was written


# ---------- helpers ----------


def _utcnow_iso() -> str:
    """RFC-3339 / ISO-8601 UTC, microseconds, with Z suffix."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(obj: Any) -> str:
    """Stable JSON for hashing — sorted keys, no whitespace, ensure_ascii=False.

    Matches what we'd put on the wire if we ever externalized the audit log,
    so chain verification can be replayed deterministically.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _compute_hash(
    ts: str,
    event_type: str,
    decision_id: str | None,
    payload: dict[str, Any],
    prev_hash: str,
) -> str:
    """sha256 over the canonical-JSON tuple. Does NOT include seq_no.

    Excluding seq_no keeps the hash stable across rebuilds; the chain itself
    (prev_hash) is what proves ordering and absence-of-tamper.
    """
    body = _canonical_json(
        {
            "ts": ts,
            "event_type": event_type,
            "decision_id": decision_id,
            "payload": payload,
            "prev_hash": prev_hash,
        }
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ---------- schema ----------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    seq_no       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT    NOT NULL,
    event_type   TEXT    NOT NULL,
    decision_id  TEXT,
    payload_json TEXT    NOT NULL,
    prev_hash    TEXT    NOT NULL,
    this_hash    TEXT    NOT NULL,
    critical     INTEGER NOT NULL DEFAULT 0
);
"""

_IDX_DECISION = (
    "CREATE INDEX IF NOT EXISTS idx_audit_decision ON audit_events(decision_id) "
    "WHERE decision_id IS NOT NULL;"
)

_IDX_TYPE_TS = "CREATE INDEX IF NOT EXISTS idx_audit_type_ts ON audit_events(event_type, ts);"


# ---------- store ----------


class AuditStore:
    """Thread-safe, append-only, hash-chained event log.

    Open once per process; the connection lives for the process lifetime.
    Use `close()` on shutdown (or rely on GC at process exit).
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # `isolation_level=None` → autocommit mode; we manage transactions explicitly.
        # `check_same_thread=False` is safe because we hold `_lock` on every write.
        try:
            self._conn = sqlite3.connect(
                str(self.db_path),
                isolation_level=None,
                check_same_thread=False,
                timeout=5.0,
            )
        except sqlite3.Error as exc:
            raise AuditDatabaseError(f"cannot open audit db at {self.db_path}: {exc}") from exc
        self._lock = threading.Lock()
        self._init_schema()

    # ------------- lifecycle -------------

    def _init_schema(self) -> None:
        try:
            cur = self._conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=FULL")  # group-commit relaxation deferred to §14.4.3
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute(_SCHEMA)
            cur.execute(_IDX_DECISION)
            cur.execute(_IDX_TYPE_TS)
        except sqlite3.Error as exc:
            raise AuditDatabaseError(f"schema init failed: {exc}") from exc

    def close(self) -> None:
        with self._lock, contextlib.suppress(sqlite3.Error):
            # closing is best-effort on shutdown
            self._conn.close()

    # ------------- write -------------

    def append(
        self,
        event_type: EventType | str,
        payload: dict[str, Any] | None = None,
        *,
        decision_id: str | None = None,
        critical: bool = False,
    ) -> AuditEvent:
        """Append one event. Returns the persisted row (with seq_no and hashes)."""
        evt_type_str = event_type.value if isinstance(event_type, EventType) else str(event_type)
        payload = payload or {}
        ts = _utcnow_iso()

        with self._lock:
            try:
                cur = self._conn.cursor()
                cur.execute("BEGIN IMMEDIATE")
                # latest hash inside the transaction so we serialize on the chain head
                cur.execute("SELECT this_hash FROM audit_events ORDER BY seq_no DESC LIMIT 1")
                row = cur.fetchone()
                prev_hash: str = row[0] if row else GENESIS_HASH

                this_hash = _compute_hash(ts, evt_type_str, decision_id, payload, prev_hash)
                payload_json = _canonical_json(payload)

                cur.execute(
                    "INSERT INTO audit_events "
                    "(ts, event_type, decision_id, payload_json, prev_hash, this_hash, critical) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        ts,
                        evt_type_str,
                        decision_id,
                        payload_json,
                        prev_hash,
                        this_hash,
                        1 if critical else 0,
                    ),
                )
                seq_no = cur.lastrowid
                assert seq_no is not None  # AUTOINCREMENT guarantees this
                cur.execute("COMMIT")
            except sqlite3.Error as exc:
                # best-effort rollback; even if it fails, the AuditDatabaseError below
                # signals the caller that the event did NOT land
                with contextlib.suppress(sqlite3.Error):
                    self._conn.execute("ROLLBACK")
                raise AuditDatabaseError(f"append failed: {exc}") from exc

        return AuditEvent(
            seq_no=seq_no,
            ts=ts,
            event_type=evt_type_str,
            decision_id=decision_id,
            payload=payload,
            prev_hash=prev_hash,
            this_hash=this_hash,
            critical=critical,
        )

    # ------------- read -------------

    def latest(self) -> AuditEvent | None:
        """Return the most recent event, or None if the log is empty."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT seq_no, ts, event_type, decision_id, payload_json, "
                "prev_hash, this_hash, critical FROM audit_events "
                "ORDER BY seq_no DESC LIMIT 1"
            )
            row = cur.fetchone()
        if row is None:
            return None
        return _row_to_event(row)

    def events_since(self, seq_no: int, limit: int = 1000) -> list[AuditEvent]:
        """Events strictly after the given seq_no, up to `limit`, oldest first."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT seq_no, ts, event_type, decision_id, payload_json, "
                "prev_hash, this_hash, critical FROM audit_events "
                "WHERE seq_no > ? ORDER BY seq_no ASC LIMIT ?",
                (seq_no, limit),
            )
            rows = cur.fetchall()
        return [_row_to_event(r) for r in rows]

    def events_by_decision(self, decision_id: str) -> list[AuditEvent]:
        """All events tagged with the given decision_id, oldest first."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT seq_no, ts, event_type, decision_id, payload_json, "
                "prev_hash, this_hash, critical FROM audit_events "
                "WHERE decision_id = ? ORDER BY seq_no ASC",
                (decision_id,),
            )
            rows = cur.fetchall()
        return [_row_to_event(r) for r in rows]

    def count(self) -> int:
        """Total number of events in the log."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT COUNT(*) FROM audit_events")
            return int(cur.fetchone()[0])

    # ------------- verification -------------

    def verify_chain(self, start_seq: int = 1, end_seq: int | None = None) -> ChainVerification:
        """Verify hash chain in [start_seq, end_seq] inclusive.

        On any break, returns immediately with the seq_no of the first bad row.
        Does NOT raise — callers decide how to react (refuse to start, alert, etc.).
        """
        with self._lock:
            cur = self._conn.cursor()
            if start_seq < 1:
                start_seq = 1

            # Establish the expected prev_hash entering the range.
            if start_seq == 1:
                expected_prev = GENESIS_HASH
            else:
                cur.execute("SELECT this_hash FROM audit_events WHERE seq_no = ?", (start_seq - 1,))
                row = cur.fetchone()
                if row is None:
                    return ChainVerification(
                        valid=False,
                        first_broken_seq=start_seq,
                        reason="missing predecessor",
                        checked=0,
                    )
                expected_prev = row[0]

            if end_seq is None:
                cur.execute(
                    "SELECT seq_no, ts, event_type, decision_id, payload_json, "
                    "prev_hash, this_hash FROM audit_events "
                    "WHERE seq_no >= ? ORDER BY seq_no ASC",
                    (start_seq,),
                )
            else:
                cur.execute(
                    "SELECT seq_no, ts, event_type, decision_id, payload_json, "
                    "prev_hash, this_hash FROM audit_events "
                    "WHERE seq_no >= ? AND seq_no <= ? ORDER BY seq_no ASC",
                    (start_seq, end_seq),
                )
            checked = 0
            for seq_no, ts, event_type, decision_id, payload_json, prev_hash, this_hash in cur:
                if prev_hash != expected_prev:
                    return ChainVerification(
                        valid=False,
                        first_broken_seq=int(seq_no),
                        reason="prev_hash mismatch",
                        checked=checked,
                    )
                payload = json.loads(payload_json)
                computed = _compute_hash(ts, event_type, decision_id, payload, prev_hash)
                if computed != this_hash:
                    return ChainVerification(
                        valid=False,
                        first_broken_seq=int(seq_no),
                        reason="this_hash mismatch",
                        checked=checked,
                    )
                expected_prev = this_hash
                checked += 1

        return ChainVerification(valid=True, first_broken_seq=None, reason=None, checked=checked)

    def verify_chain_or_raise(self, start_seq: int = 1, end_seq: int | None = None) -> int:
        """Like `verify_chain` but raises `AuditChainBroken` on failure. Returns rows checked."""
        result = self.verify_chain(start_seq, end_seq)
        if not result.valid:
            assert result.first_broken_seq is not None  # invariant of valid=False
            assert result.reason is not None
            raise AuditChainBrokenError(result.first_broken_seq, result.reason)
        return result.checked

    # ------------- anchor (§7.4) -------------

    def write_anchor(self, path: Path | str) -> Anchor:
        """Write the latest seq_no + this_hash + timestamps to a JSON file.

        Anchors are written daily (or on-demand by `winny anchor`) to a location
        outside the audit DB. They serve as tamper-evidence checkpoints: a future
        operator can replay the chain up to `seq_no` and assert `this_hash` matches.
        """
        latest = self.latest()
        if latest is None:
            raise AuditEmptyError("no events to anchor")
        anchor = Anchor(
            seq_no=latest.seq_no,
            ts=latest.ts,
            this_hash=latest.this_hash,
            anchored_at=_utcnow_iso(),
        )
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            _canonical_json(
                {
                    "seq_no": anchor.seq_no,
                    "ts": anchor.ts,
                    "this_hash": anchor.this_hash,
                    "anchored_at": anchor.anchored_at,
                }
            ),
            encoding="utf-8",
        )
        # Self-referential: anchor-writing is itself an audited event.
        self.append(
            EventType.AUDIT_ANCHOR_WRITTEN,
            {"seq_no": anchor.seq_no, "this_hash": anchor.this_hash, "path": str(out)},
        )
        return anchor

    @staticmethod
    def read_anchor(path: Path | str) -> Anchor:
        """Load an anchor previously written by `write_anchor`."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return Anchor(
            seq_no=int(data["seq_no"]),
            ts=str(data["ts"]),
            this_hash=str(data["this_hash"]),
            anchored_at=str(data["anchored_at"]),
        )


def _row_to_event(row: tuple[Any, ...]) -> AuditEvent:
    seq_no, ts, event_type, decision_id, payload_json, prev_hash, this_hash, critical = row
    return AuditEvent(
        seq_no=int(seq_no),
        ts=str(ts),
        event_type=str(event_type),
        decision_id=None if decision_id is None else str(decision_id),
        payload=json.loads(payload_json),
        prev_hash=str(prev_hash),
        this_hash=str(this_hash),
        critical=bool(critical),
    )
