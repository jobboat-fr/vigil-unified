"""In-process approval-redeem state machine.

The approval gate (SPECS.md §3.4) requires that every order ship through a
single-use cryptographic grant. mcp-approval handles the OTC issuance + grant
signing, but the gateway also needs to track which approvals have been
verified (so /orders/submit can refuse to consume a grant twice) and which
order_intent was attached at request time (so the submit endpoint doesn't
have to re-trust caller-supplied order metadata).

State is per-process (one Railway worker). For multi-replica we'd promote
this to Supabase, but at v1 the single-writer model is fine.

Lifecycle:
    request   → store(approval_id, order_intent, ttl_s)
    verify    → mark_verified(approval_id)
    submit    → consume(approval_id) → returns the stored intent; subsequent
                consumes raise.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class _ApprovalRecord:
    order_intent: dict[str, Any]
    decision_id: str | None
    expires_at: float
    verified: bool = False
    consumed: bool = False
    owner_user_id: str | None = None


class ApprovalStateError(RuntimeError):
    """Raised when consume() finds the approval expired/unverified/double-used."""


class ApprovalOwnershipError(ApprovalStateError):
    """Raised when a caller tries to act on an approval they do not own.

    Multi-tenant guard (§3.4): an approval created for user-A can only be
    verified/consumed by user-A. Without this, a service-token caller acting
    for user-B could redeem user-A's pending order against user-A's broker.
    """


_lock = threading.Lock()
_records: dict[str, _ApprovalRecord] = {}


def _now() -> float:
    return time.time()


def _gc_expired_locked() -> None:
    now = _now()
    for aid, rec in list(_records.items()):
        if rec.expires_at < now and not rec.consumed:
            _records.pop(aid, None)


def store(approval_id: str, order_intent: dict[str, Any],
          *, decision_id: str | None = None, ttl_seconds: float = 300.0,
          owner_user_id: str | None = None) -> None:
    with _lock:
        _gc_expired_locked()
        _records[approval_id] = _ApprovalRecord(
            order_intent=dict(order_intent or {}),
            decision_id=decision_id,
            expires_at=_now() + float(ttl_seconds),
            owner_user_id=owner_user_id,
        )


def _check_owner_locked(rec: _ApprovalRecord, caller_user_id: str | None) -> None:
    """Enforce that the caller owns the approval (multi-tenant §3.4 guard).

    Only enforced when BOTH the record carries an owner and the caller passes
    an id — back-compat for the owner-only flow that never tagged ownership.
    """
    if rec.owner_user_id and caller_user_id and rec.owner_user_id != caller_user_id:
        raise ApprovalOwnershipError("approval_not_owned_by_caller")


def mark_verified(approval_id: str, *, caller_user_id: str | None = None) -> bool:
    """Returns True if the approval is known, owned by the caller, and live.

    Raises ApprovalOwnershipError if the caller is not the approval's owner.
    """
    with _lock:
        rec = _records.get(approval_id)
        if rec is None:
            return False
        if rec.consumed or rec.expires_at < _now():
            return False
        _check_owner_locked(rec, caller_user_id)
        rec.verified = True
        return True


def consume(approval_id: str, *, caller_user_id: str | None = None) -> dict[str, Any]:
    """Marks the approval used (single-use). Returns the original order_intent.

    Raises ApprovalStateError on any of:
      - unknown approval_id
      - already-consumed
      - expired
      - not-yet-verified
      - not owned by the caller (ApprovalOwnershipError)
    """
    with _lock:
        _gc_expired_locked()
        rec = _records.get(approval_id)
        if rec is None:
            raise ApprovalStateError("unknown_approval_id")
        if rec.consumed:
            raise ApprovalStateError("approval_already_consumed")
        if rec.expires_at < _now():
            raise ApprovalStateError("approval_expired")
        if not rec.verified:
            raise ApprovalStateError("approval_not_verified")
        _check_owner_locked(rec, caller_user_id)
        rec.consumed = True
        return dict(rec.order_intent)


def owner_of(approval_id: str) -> str | None:
    """Return the user_id that owns this approval, or None if untracked."""
    with _lock:
        rec = _records.get(approval_id)
        return rec.owner_user_id if rec else None


def discard(approval_id: str) -> None:
    """Used by reject flow — wipe state without consuming."""
    with _lock:
        _records.pop(approval_id, None)
