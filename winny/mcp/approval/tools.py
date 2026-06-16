"""mcp-approval tool handlers — §3.4.3.

Five tools forming the approval gate:
  - request:       create ApprovalRequest for user verdict
  - verify:        validate user_token, issue signed ApprovalGrant
  - consume:       mark grant as used (replay protection)
  - revoke:        cancel a pending approval
  - list_pending:  return non-expired pending requests
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from winny.approval.crypto import (
    ApprovalKeyManager,
    GrantSigner,
    GrantVerifier,
    VerifiedGrant,
    canonical_intent_hash,
)
from winny.approval.store import ApprovalStore
from winny.common.errors import ApprovalError, GrantReplayError
from winny.common.ids import (
    ApprovalId,
    DecisionId,
    new_approval_id,
)
from winny.common.symbols import Symbol
from winny.common.types import (
    ApprovalGrant,
    ApprovalRequest,
    ApprovalStatus,
    OrderIntent,
    OrderType,
    Side,
    TimeInForce,
)

# ---------- default paths ----------

_DEFAULT_KEY_PATH = Path.home() / ".winny" / "keys" / "approval_ed25519"
_DEFAULT_DB_PATH = Path.home() / ".winny" / "approval.db"


# ---------- tool state ----------
# In production these are initialized once per process via the server setup.
# For testing they can be overridden via `configure(...)`.

_store: ApprovalStore | None = None
_signer: GrantSigner | None = None
_verifier: GrantVerifier | None = None


def configure(
    *,
    key_path: Path | str | None = None,
    db_path: Path | str | None = None,
) -> None:
    """Initialize or reinitialize the approval subsystem.

    Called once at server start; also used by tests to inject tmp paths.
    """
    global _store, _signer, _verifier
    kp = Path(key_path) if key_path else _DEFAULT_KEY_PATH
    dp = Path(db_path) if db_path else _DEFAULT_DB_PATH

    km = ApprovalKeyManager(kp)
    _store = ApprovalStore(dp)
    _signer = GrantSigner(km)
    _verifier = GrantVerifier(km)


def _get_store() -> ApprovalStore:
    if _store is None:
        configure()
    assert _store is not None
    return _store


def _get_signer() -> GrantSigner:
    if _signer is None:
        configure()
    assert _signer is not None
    return _signer


def _get_verifier() -> GrantVerifier:
    if _verifier is None:
        configure()
    assert _verifier is not None
    return _verifier


# ===================================================================
# request — create a pending approval
# ===================================================================


def _rebuild_intent(raw: dict[str, Any]) -> OrderIntent:
    """Rebuild an OrderIntent from a JSON-safe dict (wire format)."""
    symbol_data = raw["symbol"]
    if isinstance(symbol_data, str):
        symbol = Symbol.parse(symbol_data)
    else:
        symbol = Symbol.parse(symbol_data.get("canonical", str(symbol_data)))

    return OrderIntent(
        intent_id=raw["intent_id"],
        decision_id=raw["decision_id"],
        symbol=symbol,
        side=Side(raw["side"]),
        qty=Decimal(str(raw["qty"])),
        order_type=OrderType(raw["order_type"]),
        limit_price=Decimal(str(raw["limit_price"])) if raw.get("limit_price") else None,
        stop_price=Decimal(str(raw["stop_price"])) if raw.get("stop_price") else None,
        time_in_force=TimeInForce(raw["time_in_force"]),
        estimated_cost=Decimal(str(raw["estimated_cost"])),
        estimated_fees=Decimal(str(raw["estimated_fees"])),
        sizing_explanation=raw.get("sizing_explanation", ""),
    )


async def request_approval(
    decision_id: str,
    order_intent: dict[str, Any],
    ttl_seconds: int = 300,
    summary: str | None = None,
) -> dict[str, Any]:
    """Create an ApprovalRequest for user verdict.

    Returns the approval_id, one_time_code, summary, and expiry for the
    user to review before approving.
    """
    store = _get_store()

    # Rebuild intent to compute hash
    try:
        intent = _rebuild_intent(order_intent)
    except Exception as e:
        return {"error": f"Invalid order_intent: {e}"}

    intent_hash = canonical_intent_hash(intent)
    did = DecisionId(decision_id)
    aid = new_approval_id()

    # Generate one-time code for user
    code = secrets.token_hex(3).upper()  # 6-char hex code

    now = datetime.now(UTC)
    ttl = timedelta(seconds=ttl_seconds)

    # Build summary for user
    if summary is None:
        summary = (
            f"{intent.side.value} {intent.qty} {intent.symbol.canonical()} "
            f"@ {intent.order_type.value}"
        )
        if intent.limit_price:
            summary += f" limit={intent.limit_price}"

    req = ApprovalRequest(
        approval_id=aid,
        decision_id=did,
        order_intent_hash=intent_hash,
        summary_for_user=summary,
        one_time_code=code,
        issued_at=now,
        expires_at=now + ttl,
    )
    store.create_request(req)

    return {
        "approval_id": str(aid),
        "decision_id": str(did),
        "one_time_code": code,
        "summary": summary,
        "expires_at": req.expires_at.isoformat(),
        "status": "PENDING",
    }


# ===================================================================
# verify — user presents code → get signed grant
# ===================================================================


async def verify_approval(
    approval_id: str,
    user_token: str,
) -> dict[str, Any]:
    """Validate user_token against the stored request, issue ApprovalGrant.

    The user_token is the one_time_code they received. On match, we issue
    a signed Ed25519 grant that can be consumed exactly once by submit_order.
    """
    store = _get_store()
    signer = _get_signer()

    aid = ApprovalId(approval_id)
    req = store.get_request(aid)

    if req is None:
        return {"error": f"No approval request found for {approval_id}"}

    if req.status != ApprovalStatus.PENDING:
        return {"error": f"Approval is no longer pending (status={req.status.value})"}

    # Check expiry
    now = datetime.now(UTC)
    if now >= req.expires_at:
        store.set_status(aid, ApprovalStatus.EXPIRED)
        return {"error": "Approval request has expired."}

    # Validate one-time code
    if user_token.strip().upper() != req.one_time_code.upper():
        return {"error": "Invalid approval code."}

    # Issue grant
    ttl_remaining = req.expires_at - now
    grant_ttl = min(ttl_remaining, timedelta(minutes=5))

    try:
        grant = signer.issue(
            approval_id=aid,
            decision_id=req.decision_id,
            order_intent_hash=req.order_intent_hash,
            ttl=grant_ttl,
        )
    except ApprovalError as e:
        return {"error": f"Failed to issue grant: {e}"}

    # Update status to GRANTED
    store.set_status(aid, ApprovalStatus.GRANTED)

    return {
        "approval_id": str(aid),
        "grant_token": grant.grant_token,
        "expires_at": grant.expires_at.isoformat(),
    }


# ===================================================================
# consume — mark grant as used (called by submit_order)
# ===================================================================


async def consume_grant(
    approval_id: str,
    grant_token: str,
    order_intent_hash: str,
    by_caller: str = "mcp-algo",
) -> dict[str, Any]:
    """Verify + consume a grant atomically. Returns verified payload on success.

    This is what submit_order calls before placing the order with the broker.
    After this returns successfully, the grant cannot be reused.
    """
    store = _get_store()
    verifier = _get_verifier()

    aid = ApprovalId(approval_id)
    grant = ApprovalGrant(
        grant_token=grant_token,
        approval_id=aid,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),  # wrapper field; real check is in token
    )

    # Verify signature + expiry + intent binding
    try:
        verified: VerifiedGrant = verifier.verify(grant, expected_intent_hash=order_intent_hash)
    except ApprovalError as e:
        return {"error": f"Grant verification failed: {e}"}

    # Replay protection
    try:
        store.consume_grant(verified.approval_id, verified.nonce, by_caller)
    except GrantReplayError:
        return {"error": "Grant has already been consumed (replay detected)."}

    # Mark as consumed in requests table
    store.set_status(aid, ApprovalStatus.CONSUMED)

    return {
        "consumed": True,
        "approval_id": str(verified.approval_id),
        "decision_id": str(verified.decision_id),
        "nonce": verified.nonce,
    }


# ===================================================================
# revoke — cancel a pending approval
# ===================================================================


async def revoke_approval(
    approval_id: str,
    reason: str = "",
) -> dict[str, Any]:
    """Revoke a pending approval. Cannot revoke already-consumed grants."""
    store = _get_store()
    aid = ApprovalId(approval_id)
    req = store.get_request(aid)

    if req is None:
        return {"error": f"No approval request found for {approval_id}"}

    if req.status == ApprovalStatus.CONSUMED:
        return {"error": "Cannot revoke an already-consumed approval."}

    store.set_status(aid, ApprovalStatus.REVOKED)
    return {
        "revoked": True,
        "approval_id": str(aid),
        "reason": reason,
        "previous_status": req.status.value,
    }


# ===================================================================
# list_pending — non-expired pending requests
# ===================================================================


async def list_pending_approvals() -> dict[str, Any]:
    """Return all non-expired pending approval requests."""
    store = _get_store()
    pending = store.list_pending()
    return {
        "count": len(pending),
        "requests": [
            {
                "approval_id": str(r.approval_id),
                "decision_id": str(r.decision_id),
                "summary": r.summary_for_user,
                "one_time_code": r.one_time_code,
                "issued_at": r.issued_at.isoformat(),
                "expires_at": r.expires_at.isoformat(),
            }
            for r in pending
        ],
    }
