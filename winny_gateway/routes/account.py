"""Account management — GDPR endpoints + support tickets.

Endpoints:
  POST   /api/v1/account/export   — request data export (GDPR Art. 20)
  DELETE /api/v1/account           — delete account (GDPR Art. 17)
  GET    /api/v1/support/tickets   — list support tickets
  POST   /api/v1/support/tickets   — create support ticket
  POST   /api/v1/support/tickets/{id}/reply — reply to ticket

Tickets persist in the existing `support_tickets` table with the thread held in
the related `support_messages` table (one row per message, linked by
`ticket_id`) — the normalized schema the platform's support system already
owns. The data export collects the user's rows across every WinnyWoo table and
returns them inline (and audit-logs the request).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from winny_gateway.auth import get_current_user
from winny_gateway.db import audit_log, db_delete, db_insert, db_select, db_update
from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["account"])

# Tables that hold user-owned rows, keyed by user_id. Used by both the export
# (collect) and delete (erase) flows so the two stay in lock-step.
_USER_DATA_TABLES = [
    "user_preferences",
    "broker_credentials",
    "onboarding_state",
    "audit_events",
    "approval_requests",
    "trade_history",
    "portfolio_snapshots",
    "auto_trade_config",
    "support_tickets",
]

# Columns that must never appear in an export (secrets, even if encrypted).
_EXPORT_REDACT = {"api_key", "api_secret", "api_password", "secret", "encrypted_secret"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TicketCreate(BaseModel):
    subject: str = Field(max_length=200)
    message: str = Field(max_length=5000)


class TicketReply(BaseModel):
    message: str = Field(max_length=5000)


# ─── GDPR ───────────────────────────────────────────────────────────────────────


@router.post("/api/v1/account/export")
async def request_data_export(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """GDPR Art. 20 — Right to data portability.

    Collects the user's rows across every WinnyWoo table and returns them
    inline as a JSON bundle (secrets redacted). Audit-logged.
    """
    uid = user["sub"]
    email = user.get("email", "unknown")
    logger.info(
        "Data export requested",
        extra={"user_id": uid, "email": email, "component": "gdpr"},
    )

    bundle: dict[str, Any] = {}
    for table in _USER_DATA_TABLES:
        try:
            rows = await db_select(table, filters={"user_id": uid}, limit=10000)
        except Exception as exc:  # noqa: BLE001
            logger.warning("export: table %s failed: %s", table, exc)
            rows = []
        # Redact any secret-bearing columns defensively.
        cleaned = [
            {k: ("[redacted]" if k in _EXPORT_REDACT else v) for k, v in row.items()}
            for row in rows
        ]
        bundle[table] = cleaned

    await audit_log(
        user_id=uid,
        event_type="gdpr",
        action="data_export_fulfilled",
        component="account",
        details={"email": email, "tables": list(bundle.keys()),
                 "row_counts": {t: len(r) for t, r in bundle.items()}},
    )
    return {
        "ok": True,
        "data": {
            "status": "complete",
            "generated_at": _now(),
            "user": {"id": uid, "email": email},
            "data": bundle,
        },
    }


@router.delete("/api/v1/account")
async def delete_account(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Retiré : supprimait le compte d'authentification sans rien faire des données de formation
    (le profil LEARN gardait nom et e-mail). Remplacé par POST /api/v1/compte/suppression, qui
    applique la règle RGPD de la plateforme (migration LEARN 0046)."""
    raise HTTPException(status_code=status.HTTP_410_GONE, detail={
        "error": "route_remplacee", "detail": "Utilisez POST /api/v1/compte/suppression avec la confirmation SUPPRIMER."})
    uid = user["sub"]
    logger.warning(
        "Account deletion requested",
        extra={"user_id": uid, "component": "gdpr"},
    )

    # support_messages is keyed by ticket_id, not user_id — erase the threads
    # of the user's tickets first so no orphaned message rows survive.
    try:
        for t in await db_select("support_tickets", filters={"user_id": uid}, limit=1000):
            await db_delete("support_messages", filters={"ticket_id": t.get("id")}, allow_unscoped=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("support_messages erase failed: %s", exc)

    # Cancel any live Stripe subscription BEFORE tearing down the org/rows —
    # otherwise a deleted account keeps getting billed (real money bug).
    stripe_cancelled: list[str] = []
    try:
        members = await db_select("org_members", filters={"user_id": uid}, limit=5)
        org_ids = [m["org_id"] for m in members if m.get("org_id")]
        for org_id in org_ids:
            subs = await db_select(
                "subscriptions", filters={"org_id": org_id, "provider": "stripe"}, limit=10,
            )
            for s in subs:
                ext = str(s.get("external_id") or "")
                if s.get("status") in ("active", "trialing") and ext and not ext.startswith(("dev_", "cs_")):
                    try:
                        import stripe as _stripe

                        key = os.environ.get("STRIPE_SECRET_KEY", "")
                        if key:
                            _stripe.api_key = key
                            _stripe.Subscription.cancel(ext)
                            stripe_cancelled.append(ext)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("stripe cancel-on-delete failed sub=%s: %s", ext, exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("stripe cancel-on-delete lookup failed: %s", exc)

    for table in _USER_DATA_TABLES:
        await db_delete(table, filters={"user_id": uid})

    # Delete the Supabase auth user via the admin API (service-role). Without
    # this the login/identity survives erasure — GDPR Art.17 is incomplete and
    # the email can't be reused.
    auth_deleted = False
    try:
        from winny_gateway.db import get_admin_client

        admin = get_admin_client()
        admin.auth.admin.delete_user(uid)
        auth_deleted = True
    except Exception as exc:  # noqa: BLE001
        logger.error("Supabase auth user delete failed uid=%s: %s", uid, exc,
                     extra={"component": "gdpr"})

    # Log the deletion event (retained for compliance)
    await audit_log(
        user_id=uid,
        event_type="gdpr",
        action="account_deleted",
        component="account",
        details={
            "tables_cleared": _USER_DATA_TABLES,
            "auth_user_deleted": auth_deleted,
            "stripe_subscriptions_cancelled": stripe_cancelled,
        },
    )

    return {
        "ok": True,
        "data": {
            "status": "deleted",
            "auth_user_deleted": auth_deleted,
            "stripe_subscriptions_cancelled": len(stripe_cancelled),
            "message": "Your account and all data have been permanently deleted.",
        },
    }


# ─── Support Tickets (support_tickets + support_messages) ─────────────────────────


async def _fetch_messages(ticket_id: str) -> list[dict[str, Any]]:
    """Load a ticket's thread from support_messages, oldest first."""
    msgs = await db_select(
        "support_messages", filters={"ticket_id": ticket_id},
        order_by="created_at", limit=500, allow_unscoped=True,
    )
    return [
        {
            "role": "agent" if m.get("author_type") in ("agent", "staff", "operator") else "user",
            "author_type": m.get("author_type"),
            "text": m.get("body"),
            "ts": m.get("created_at"),
            "internal": bool(m.get("internal_note")),
        }
        for m in msgs
        if not m.get("internal_note")  # never expose internal staff notes to the user
    ]


def _ticket_view(row: dict[str, Any], messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Shape ticket row + thread into the API object the frontend expects."""
    return {
        "id": row.get("id"),
        "ticket_number": row.get("ticket_number"),
        "subject": row.get("subject"),
        "status": row.get("status", "open"),
        "priority": row.get("priority"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "messages": messages,
    }


@router.get("/api/v1/support/tickets")
async def list_tickets(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    uid = user["sub"]
    rows = await db_select(
        "support_tickets", filters={"user_id": uid}, order_by="-created_at", limit=200
    )
    out = []
    for r in rows:
        msgs = await _fetch_messages(str(r.get("id")))
        out.append(_ticket_view(r, msgs))
    return {"ok": True, "data": out}


@router.post("/api/v1/support/tickets")
async def create_ticket(
    body: TicketCreate,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    uid = user["sub"]
    email = user.get("email") or "unknown@winnywoo.app"  # support_tickets.email is NOT NULL
    saved = await db_insert(
        "support_tickets",
        {"user_id": uid, "email": email, "subject": body.subject,
         "status": "open", "source": "web"},
    )
    if saved is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not save your ticket right now — please try again.",
        )
    ticket_id = str(saved.get("id"))
    await db_insert(
        "support_messages",
        {"ticket_id": ticket_id, "author_type": "user", "author_id": uid,
         "author_email": email, "body": body.message},
        allow_unscoped=True,  # support_messages is scoped by ticket_id, not user_id
    )
    logger.info(
        "Support ticket created",
        extra={"user_id": uid, "ticket_id": ticket_id, "component": "support"},
    )
    await audit_log(
        user_id=uid, event_type="support", action="ticket_created",
        component="account", details={"ticket_id": ticket_id, "subject": body.subject},
    )
    msgs = await _fetch_messages(ticket_id)
    return {"ok": True, "data": _ticket_view(saved, msgs)}


@router.post("/api/v1/support/tickets/{ticket_id}/reply")
async def reply_to_ticket(
    ticket_id: str,
    body: TicketReply,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    uid = user["sub"]
    # Ownership check: the ticket must belong to the caller.
    rows = await db_select("support_tickets", filters={"user_id": uid, "id": ticket_id}, limit=1)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    appended = await db_insert(
        "support_messages",
        {"ticket_id": ticket_id, "author_type": "user", "author_id": uid,
         "author_email": user.get("email"), "body": body.message},
        allow_unscoped=True,
    )
    if appended is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not save your reply right now — please try again.",
        )
    # Re-open for staff attention; updated_at trigger fires on the UPDATE.
    await db_update(
        "support_tickets", {"status": "pending"},
        filters={"id": ticket_id, "user_id": uid},
    )
    msgs = await _fetch_messages(ticket_id)
    return {"ok": True, "data": _ticket_view(rows[0], msgs)}
