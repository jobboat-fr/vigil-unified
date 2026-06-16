"""Billing routes — Stripe integration for Lite/Pro tiers.

Endpoints:
  GET  /api/v1/billing           — get user's subscription info
  POST /api/v1/billing/checkout  — create Stripe Checkout session for Pro
  POST /api/v1/billing/portal    — create Stripe Customer Portal session
  POST /api/v1/billing/cancel    — cancel subscription
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from winny_gateway.auth import get_current_user
from winny_gateway.db import db_select, db_upsert
from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/billing", tags=["billing"])

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PRO_PRICE_ID = os.environ.get("STRIPE_PRO_PRICE_ID", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
APP_URL = os.environ.get("APP_URL", "https://app.winnywoo.com")

# In-memory tier tracking (production: Supabase + Stripe webhooks)
_user_billing: dict[str, dict[str, Any]] = {}


class CheckoutRequest(BaseModel):
    tier: str = "pro"


def _default_billing(tier: str = "lite") -> dict[str, Any]:
    return {
        "tier": tier,
        "status": "active",
        "current_period_end": "",
        "cancel_at_period_end": False,
    }


async def _get_user_tier(uid: str) -> str:
    rows = await db_select("user_preferences", filters={"user_id": uid}, columns="tier", limit=1)
    if not rows:
        return "lite"
    tier = str(rows[0].get("tier") or "lite").lower()
    return "pro" if tier == "pro" else "lite"


async def _set_user_tier(
    uid: str,
    tier: str,
    *,
    status_value: str = "active",
    cancel_at_period_end: bool = False,
    stripe_customer_id: str = "",
    stripe_subscription_id: str = "",
) -> None:
    tier = "pro" if tier.lower() == "pro" else "lite"
    await db_upsert("user_preferences", {"user_id": uid, "tier": tier}, on_conflict="user_id")
    _user_billing[uid] = {
        **_default_billing(tier),
        "status": status_value,
        "cancel_at_period_end": cancel_at_period_end,
        "stripe_customer_id": stripe_customer_id,
        "stripe_subscription_id": stripe_subscription_id,
    }


@router.get("")
async def get_billing(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    uid = user["sub"]
    cached = _user_billing.get(uid, {})
    tier = await _get_user_tier(uid)
    if tier == "lite" and cached.get("tier") == "pro":
        tier = "pro"
    billing = {**_default_billing(tier), **cached, "tier": tier}
    return {"ok": True, "data": billing}


@router.post("/checkout")
async def create_checkout_session(
    body: CheckoutRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a Stripe Checkout session for Pro upgrade."""
    uid = user["sub"]
    email = user.get("email", "")
    tier = body.tier.lower()
    if tier != "pro":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only the Pro tier is supported.")

    if not STRIPE_SECRET_KEY:
        # Free Pro grants are dev-only; production must fail loudly so the
        # frontend can show "billing not configured" instead of a fake upgrade.
        if (os.environ.get("WW_ENV") or os.environ.get("RAILWAY_ENVIRONMENT") or "").lower() in ("production", "prod"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="stripe_not_configured",
            )
        await _set_user_tier(uid, tier)
        logger.warning(
            "Stripe not configured, returning mock checkout (dev only)",
            extra={"component": "billing"},
        )
        return {
            "ok": True,
            "data": {"url": f"{APP_URL}/billing/mock-checkout?tier={tier}"},
        }

    if not STRIPE_PRO_PRICE_ID:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="STRIPE_PRO_PRICE_ID is not configured.",
        )

    try:
        import stripe

        stripe.api_key = STRIPE_SECRET_KEY
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=email,
            line_items=[{"price": STRIPE_PRO_PRICE_ID, "quantity": 1}],
            success_url=f"{APP_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{APP_URL}/billing/cancel",
            metadata={"user_id": uid, "tier": tier},
            subscription_data={"metadata": {"user_id": uid, "tier": tier}},
        )
        return {"ok": True, "data": {"url": session.url}}
    except Exception as exc:
        logger.error("Stripe checkout failed: %s", exc, extra={"component": "billing"})
        return {"ok": False, "data": None, "error": str(exc)}


@router.post("/portal")
async def create_portal_session(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a Stripe Customer Portal session for subscription management."""
    uid = user["sub"]

    if not STRIPE_SECRET_KEY:
        return {
            "ok": True,
            "data": {"url": f"{APP_URL}/billing/mock-portal"},
        }

    try:
        import stripe

        stripe.api_key = STRIPE_SECRET_KEY
        # Cache first; fall back to a Stripe lookup by email so the portal
        # still works after a redeploy wipes the in-process cache.
        customer_id = _user_billing.get(uid, {}).get("stripe_customer_id", "")
        if not customer_id:
            email = user.get("email", "")
            if email:
                found = stripe.Customer.list(email=email, limit=1)
                if found.data:
                    customer_id = found.data[0].id
                    _user_billing.setdefault(uid, _default_billing())[
                        "stripe_customer_id"
                    ] = customer_id
        if not customer_id:
            return {"ok": False, "data": None, "error": "No subscription found"}

        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{APP_URL}/account",
        )
        return {"ok": True, "data": {"url": session.url}}
    except Exception as exc:
        logger.error("Stripe portal failed: %s", exc, extra={"component": "billing"})
        return {"ok": False, "data": None, "error": str(exc)}


@router.post("/cancel")
async def cancel_subscription(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    uid = user["sub"]
    billing = _user_billing.get(uid)
    if billing:
        billing["cancel_at_period_end"] = True
    logger.info("Subscription cancelled", extra={"user_id": uid, "component": "billing"})
    return {"ok": True, "data": {"cancel_at_period_end": True}}


@router.post("/webhook")
async def stripe_webhook(request: Request) -> dict[str, Any]:
    """Receive Stripe events and persist the user's Pro/Lite tier."""
    try:
        import json

        import stripe

        payload = await request.body()
        if STRIPE_WEBHOOK_SECRET:
            signature = request.headers.get("stripe-signature", "")
            event = stripe.Webhook.construct_event(payload, signature, STRIPE_WEBHOOK_SECRET)
        else:
            event = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        logger.warning("Stripe webhook rejected: %s", exc, extra={"component": "billing"})
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Stripe webhook") from exc

    event_type = event.get("type", "")
    obj = event.get("data", {}).get("object", {})
    metadata = obj.get("metadata") or {}
    uid = metadata.get("user_id") or metadata.get("uid")

    if event_type == "checkout.session.completed" and uid:
        await _set_user_tier(
            uid,
            "pro",
            status_value="active",
            stripe_customer_id=str(obj.get("customer") or ""),
            stripe_subscription_id=str(obj.get("subscription") or ""),
        )
    elif event_type in {"customer.subscription.updated", "customer.subscription.deleted"} and uid:
        subscription_status = str(obj.get("status") or "")
        active = subscription_status in {"active", "trialing"}
        await _set_user_tier(
            uid,
            "pro" if active else "lite",
            status_value=subscription_status or "inactive",
            cancel_at_period_end=bool(obj.get("cancel_at_period_end")),
            stripe_customer_id=str(obj.get("customer") or ""),
            stripe_subscription_id=str(obj.get("id") or ""),
        )

    return {"ok": True, "data": {"received": True, "type": event_type}}
