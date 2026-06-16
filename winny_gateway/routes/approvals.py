"""Approval gate endpoints — SPECS.md §3.4 + VIGIL_INTEGRATION_SPEC §5.

Wraps the five tools registered by `mcp-approval`:
  request | verify | consume | revoke | list_pending

These routes are the only HTTP surface for the approval gate. Authentication
is enforced via Supabase JWT (gateway.auth.get_current_user). The MCP tools
enforce cryptographic single-use semantics on grants.

Flow:
  1) Strategy emits a signal → mcp-algo.prepare_order builds an OrderIntent.
  2) Caller posts /api/v1/approvals/request — gets back {approval_id, one_time_code, ...}.
  3) User reviews the pending request (via /pending or via chat).
  4) User posts /api/v1/approvals/{id}/verify with their one_time_code.
     -> gateway returns the signed grant_token.
  5) Caller posts /api/v1/orders/submit with {intent, grant_token}.
     -> mcp-algo.submit_order consumes the grant (single-use) and submits.

Rejecting a pending request posts /api/v1/approvals/{id}/reject -> revoke.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from winny_gateway.auth import scoped_user
from winny_gateway.logging import get_logger

logger = get_logger(__name__)


def _audit_emit(event_type: str, payload: dict, *, decision_id: str | None = None,
                actor_email: str | None = None, component: str = "approvals",
                critical: bool = False) -> None:
    """Best-effort audit append — never raises, never blocks.

    Tries the Supabase backend signature (with actor_email + component) first;
    falls back to the SQLite backend's minimal signature on TypeError.
    """
    try:
        from winny_gateway.routes.audit import _get_store  # type: ignore

        store = _get_store()
        if store is None:
            return
        try:
            store.append(
                event_type,
                payload,
                decision_id=decision_id,
                critical=critical,
                actor_email=actor_email,
                component=component,
            )
        except TypeError:
            # SQLite store has the older signature without actor_email/component.
            store.append(
                event_type,
                payload,
                decision_id=decision_id,
                critical=critical,
            )
    except Exception:
        # Audit failures must never interrupt the trade path.
        pass


router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])


# ─── Request bodies ──────────────────────────────────────────────────────────


class RequestApprovalBody(BaseModel):
    """Create a pending approval request.

    `order_intent` is the JSON-safe wire form produced by mcp-algo.prepare_order.
    """

    decision_id: str
    order_intent: dict[str, Any]
    ttl_seconds: int = Field(default=300, ge=10, le=900)
    summary: str | None = None


class VerifyBody(BaseModel):
    """Exchange a one-time code for a signed grant token."""

    user_token: str = Field(min_length=4, max_length=12)


class RejectBody(BaseModel):
    reason: str | None = None


# ─── Routes ──────────────────────────────────────────────────────────────────


@router.get("/pending")
async def list_pending(
    request: Request,
    user: dict[str, Any] = Depends(scoped_user),
) -> dict[str, Any]:
    """List non-expired pending approval requests (§3.4.3).

    Multi-tenant: a scoped (non-owner) caller only sees the approvals THEY
    own. Untracked approvals (created before ownership tagging, or via the
    legacy owner path) are shown only to non-scoped callers (the owner).
    """
    pool = request.app.state.mcp_pool
    result = await pool.get("approval").safe_call_tool("list_pending", {}, fallback=[])

    caller_id = user.get("sub")
    is_scoped = bool(user.get("scoped"))
    if is_scoped and isinstance(result, list):
        from winny_gateway.approval_state import owner_of

        result = [
            item for item in result
            if isinstance(item, dict)
            and owner_of(str(item.get("approval_id", ""))) == caller_id
        ]
    return {"ok": True, "data": result}


@router.post("/request", status_code=status.HTTP_201_CREATED)
async def create_approval_request(
    body: RequestApprovalBody,
    request: Request,
    user: dict[str, Any] = Depends(scoped_user),
) -> dict[str, Any]:
    """Create a pending approval — wraps mcp-approval.request.

    Returns the approval_id + one_time_code that the user will supply to
    /verify in order to obtain a signed grant. Scoped to the chatting user:
    the approval is tagged with their id so only they can verify/consume it
    (multi-tenant §3.4). Broadcasts a *redacted* `approval_request` event
    (no OTC) so dashboards refresh without leaking the code cross-tenant; the
    OTC travels only in this HTTP response + the per-session chat reply.
    """
    pool = request.app.state.mcp_pool
    result = await pool.get("approval").call_tool(
        "request",
        {
            "decision_id": body.decision_id,
            "order_intent": body.order_intent,
            "ttl_seconds": body.ttl_seconds,
            "summary": body.summary,
        },
    )
    if isinstance(result, dict) and "error" in result:
        logger.warning(
            "Approval request failed",
            extra={"action": "approvals.request_fail", "error": result["error"], "component": "approvals"},
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])

    logger.info(
        "Approval requested",
        extra={"action": "approvals.requested", "component": "approvals"},
    )
    # Redacted broadcast: never put the one_time_code on the global WS bus —
    # every connected client receives bus events, so the OTC would leak across
    # tenants. The dashboard only needs to know an approval is pending.
    owner_id = user.get("sub")
    if isinstance(result, dict):
        _public = {
            k: v for k, v in result.items()
            if k not in ("one_time_code", "otc", "user_token")
        }
        _public["owner_user_id"] = owner_id
        request.app.state.event_bus.publish(
            {"type": "approval_request", "data": _public}, user_id=owner_id
        )
    else:
        request.app.state.event_bus.publish(
            {"type": "approval_request", "data": result}, user_id=owner_id
        )
    # Persist the order_intent in the redeem state machine — the submit
    # endpoint reads it back when the user verifies. TTL matches the
    # caller's request (≤5 min by default). Tag the owner so only they can
    # verify/consume it.
    if isinstance(result, dict) and result.get("approval_id"):
        try:
            from winny_gateway.approval_state import store as _store_approval

            _store_approval(
                str(result["approval_id"]),
                body.order_intent,
                decision_id=body.decision_id,
                ttl_seconds=float(body.ttl_seconds or 300),
                owner_user_id=owner_id,
            )
        except Exception as exc:
            logger.warning("approval_state.store failed: %s", exc)
    _audit_emit(
        "approval.request",
        {
            "decision_id": body.decision_id,
            "order_intent": body.order_intent,
            "summary": body.summary,
            "approval_id": result.get("approval_id") if isinstance(result, dict) else None,
        },
        decision_id=body.decision_id,
        actor_email=user.get("email") if isinstance(user, dict) else None,
        component="approvals",
    )
    return {"ok": True, "data": result}


@router.post("/{approval_id}/verify")
async def verify_approval(
    approval_id: str,
    body: VerifyBody,
    request: Request,
    user: dict[str, Any] = Depends(scoped_user),
) -> dict[str, Any]:
    """Exchange a one-time code for a signed ApprovalGrant — wraps mcp-approval.verify.

    On success, returns {approval_id, grant_token, expires_at}. The caller must
    present grant_token to /api/v1/orders/submit within its TTL (≤5 min).
    Multi-tenant: rejects with 403 if the caller does not own the approval.
    """
    from winny_gateway.approval_state import ApprovalOwnershipError, owner_of

    _owner = owner_of(approval_id)
    if _owner and _owner != user.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="approval_not_owned_by_caller",
        )
    pool = request.app.state.mcp_pool
    result = await pool.get("approval").call_tool(
        "verify",
        {
            "approval_id": approval_id,
            "user_token": body.user_token,
        },
    )
    if isinstance(result, dict) and "error" in result:
        logger.warning(
            "Approval verify failed: %s", result["error"],
            extra={"action": "approvals.verify_fail", "error": result["error"], "component": "approvals"},
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result["error"])

    logger.info(
        "Approval granted",
        extra={"action": "approvals.granted", "component": "approvals"},
    )
    # Mark the approval verified so /orders/submit-direct can consume it.
    # Best-effort — if the state record has expired we just log; the
    # submit endpoint will reject with a clean error message.
    try:
        from winny_gateway.approval_state import mark_verified as _mark_verified

        if not _mark_verified(approval_id, caller_user_id=user.get("sub")):
            logger.info(
                "approval_state had no pending record for %s — likely expired",
                approval_id,
                extra={"action": "approvals.state_miss", "component": "approvals"},
            )
    except ApprovalOwnershipError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="approval_not_owned_by_caller",
        ) from exc
    except Exception as exc:
        logger.warning("approval_state.mark_verified failed: %s", exc)
    request.app.state.event_bus.publish({
        "type": "approval_granted",
        "approval_id": approval_id,
        "expires_at": result.get("expires_at") if isinstance(result, dict) else None,
    }, user_id=user.get("sub"))
    _audit_emit(
        "approval.verify",
        {
            "approval_id": approval_id,
            "expires_at": result.get("expires_at") if isinstance(result, dict) else None,
        },
        actor_email=user.get("email") if isinstance(user, dict) else None,
        component="approvals",
        critical=True,
    )
    return {"ok": True, "data": result}


@router.post("/{approval_id}/reject")
async def reject_approval(
    approval_id: str,
    body: RejectBody,
    request: Request,
    user: dict[str, Any] = Depends(scoped_user),
) -> dict[str, Any]:
    """Revoke a pending approval — wraps mcp-approval.revoke.

    Multi-tenant: a scoped caller may only revoke an approval they own.
    """
    from winny_gateway.approval_state import owner_of

    _owner = owner_of(approval_id)
    if _owner and _owner != user.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="approval_not_owned_by_caller",
        )
    pool = request.app.state.mcp_pool
    result = await pool.get("approval").call_tool(
        "revoke",
        {
            "approval_id": approval_id,
            "reason": body.reason or "rejected by user",
        },
    )
    if isinstance(result, dict) and "error" in result:
        logger.warning(
            "Approval reject failed: %s", result["error"],
            extra={"action": "approvals.reject_fail", "error": result["error"], "component": "approvals"},
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result["error"])

    logger.info(
        "Approval rejected",
        extra={"action": "approvals.rejected", "component": "approvals"},
    )
    # Wipe the redeem-state record too, so a verified-then-rejected approval
    # can never be consumed by /orders/submit-direct after the grant is gone.
    try:
        from winny_gateway.approval_state import discard as _discard_approval

        _discard_approval(approval_id)
    except Exception as exc:
        logger.warning("approval_state.discard failed: %s", exc)
    request.app.state.event_bus.publish({
        "type": "approval_revoked",
        "approval_id": approval_id,
        "reason": body.reason or "rejected by user",
    }, user_id=user.get("sub"))
    return {"ok": True, "data": result}
