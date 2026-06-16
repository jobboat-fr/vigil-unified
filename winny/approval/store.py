"""SQLite-backed approval lifecycle + replay protection — §3.4 + §5.3.

This is the persistence layer behind `mcp-approval`. The verifier (crypto.py)
proves a grant is well-formed and intended; this store enforces that it can
only be consumed once.

Schema:
- approval_requests:  the user-visible pending verdicts
- consumed_grants:    write-once nonce ledger; UNIQUE(approval_id, nonce)
                      is the replay-protection primitive

Concurrent submitter races are handled by SQLite's UNIQUE constraint —
two threads trying to consume the same nonce will both attempt INSERT and
exactly one will succeed.
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from winny.common.errors import (
    AuditDatabaseError,
    GrantReplayError,
)
from winny.common.ids import ApprovalId, DecisionId
from winny.common.types import ApprovalRequest, ApprovalStatus

_SCHEMA_REQUESTS = """
CREATE TABLE IF NOT EXISTS approval_requests (
    approval_id        TEXT PRIMARY KEY,
    decision_id        TEXT NOT NULL,
    order_intent_hash  TEXT NOT NULL,
    summary_for_user   TEXT NOT NULL,
    one_time_code      TEXT NOT NULL,
    issued_at          TEXT NOT NULL,
    expires_at         TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'PENDING'
);
"""

_SCHEMA_CONSUMED = """
CREATE TABLE IF NOT EXISTS consumed_grants (
    approval_id  TEXT NOT NULL,
    nonce        TEXT NOT NULL,
    consumed_at  TEXT NOT NULL,
    by_caller    TEXT NOT NULL,
    PRIMARY KEY (approval_id, nonce)
);
"""

_IDX_STATUS = (
    "CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status, expires_at);"
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ApprovalStore:
    """Persistent approval lifecycle + replay ledger.

    Open once per process. WAL journal + busy_timeout match the audit log
    pattern (SPECS.md §7.4) so the two databases behave consistently.
    """

    def __init__(self, db_path: Path | str, *, clock: Callable[[], datetime] = _utcnow) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(
                str(self.db_path),
                isolation_level=None,  # autocommit; we manage transactions
                check_same_thread=False,
                timeout=5.0,
            )
        except sqlite3.Error as e:
            raise AuditDatabaseError(f"cannot open approval db: {e}") from e
        self._lock = threading.Lock()
        self._clock = clock
        self._init_schema()

    def _init_schema(self) -> None:
        try:
            cur = self._conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=FULL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute(_SCHEMA_REQUESTS)
            cur.execute(_SCHEMA_CONSUMED)
            cur.execute(_IDX_STATUS)
        except sqlite3.Error as e:
            raise AuditDatabaseError(f"approval schema init failed: {e}") from e

    def close(self) -> None:
        with self._lock, contextlib.suppress(sqlite3.Error):
            self._conn.close()

    # ------------- requests -------------

    def create_request(self, request: ApprovalRequest) -> None:
        """Persist a freshly-issued ApprovalRequest. PRIMARY KEY conflict = bug upstream."""
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO approval_requests "
                    "(approval_id, decision_id, order_intent_hash, summary_for_user, "
                    "one_time_code, issued_at, expires_at, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(request.approval_id),
                        str(request.decision_id),
                        request.order_intent_hash,
                        request.summary_for_user,
                        request.one_time_code,
                        request.issued_at.isoformat(),
                        request.expires_at.isoformat(),
                        request.status.value,
                    ),
                )
            except sqlite3.Error as e:
                raise AuditDatabaseError(f"create_request failed: {e}") from e

    def get_request(self, approval_id: ApprovalId) -> ApprovalRequest | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT approval_id, decision_id, order_intent_hash, summary_for_user, "
                "one_time_code, issued_at, expires_at, status FROM approval_requests "
                "WHERE approval_id = ?",
                (str(approval_id),),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return ApprovalRequest(
            approval_id=ApprovalId(row[0]),
            decision_id=DecisionId(row[1]),
            order_intent_hash=row[2],
            summary_for_user=row[3],
            one_time_code=row[4],
            issued_at=datetime.fromisoformat(row[5]),
            expires_at=datetime.fromisoformat(row[6]),
            status=ApprovalStatus(row[7]),
        )

    def set_status(self, approval_id: ApprovalId, status: ApprovalStatus) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE approval_requests SET status = ? WHERE approval_id = ?",
                (status.value, str(approval_id)),
            )

    def list_pending(self) -> list[ApprovalRequest]:
        now = self._clock().isoformat()
        with self._lock:
            cur = self._conn.execute(
                "SELECT approval_id, decision_id, order_intent_hash, summary_for_user, "
                "one_time_code, issued_at, expires_at, status FROM approval_requests "
                "WHERE status = 'PENDING' AND expires_at > ? ORDER BY issued_at ASC",
                (now,),
            )
            rows = cur.fetchall()
        return [
            ApprovalRequest(
                approval_id=ApprovalId(r[0]),
                decision_id=DecisionId(r[1]),
                order_intent_hash=r[2],
                summary_for_user=r[3],
                one_time_code=r[4],
                issued_at=datetime.fromisoformat(r[5]),
                expires_at=datetime.fromisoformat(r[6]),
                status=ApprovalStatus(r[7]),
            )
            for r in rows
        ]

    # ------------- replay-protected consume -------------

    def consume_grant(self, approval_id: ApprovalId, nonce: str, by_caller: str) -> None:
        """Atomically record (approval_id, nonce) as consumed.

        Second call with the same (approval_id, nonce) raises GrantReplayError.
        Caller MUST invoke this before performing any irreversible side effect
        (i.e. before placing the order with the broker).
        """
        consumed_at = self._clock().isoformat()
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO consumed_grants (approval_id, nonce, consumed_at, by_caller) "
                    "VALUES (?, ?, ?, ?)",
                    (str(approval_id), nonce, consumed_at, by_caller),
                )
            except sqlite3.IntegrityError as e:
                # PRIMARY KEY (approval_id, nonce) — duplicate = replay
                raise GrantReplayError(
                    f"grant nonce already consumed for approval_id={approval_id}"
                ) from e
            except sqlite3.Error as e:
                raise AuditDatabaseError(f"consume_grant failed: {e}") from e

    def is_consumed(self, approval_id: ApprovalId, nonce: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM consumed_grants WHERE approval_id = ? AND nonce = ?",
                (str(approval_id), nonce),
            )
            return cur.fetchone() is not None
