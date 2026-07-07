"""Billing routes — Stripe Checkout → org subscription provisioning.

This is the revenue path. It bridges Stripe to the SAME tables the Ops
commercial model reads (`ops/billing.py::tenant_plan`: org_members →
subscriptions.plan_tier), so a payment actually changes the tenant's plan,
quotas and feature flags. The previous version wrote `user_preferences.tier`
+ an in-process dict that `tenant_plan()` never looked at — a customer could
pay and nothing would change.

Endpoints (paths unchanged from v1 so existing callers keep working):
  GET  /api/v1/billing           — current plan, usage, subscription, purchasable tiers
  POST /api/v1/billing/checkout  — Stripe Checkout session for starter/pro/team
  POST /api/v1/billing/portal    — Stripe Customer Portal session
  POST /api/v1/billing/cancel    — cancel at period end (real Stripe cancel)
  POST /api/v1/billing/webhook   — Stripe events → upsert `subscriptions`

Env:
  STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
  STRIPE_PRICE_ID_STARTER / STRIPE_PRICE_ID_PRO / STRIPE_PRICE_ID_TEAM
  (legacy STRIPE_PRO_PRICE_ID still honoured for pro)
  APP_URL — checkout return host (default https://vigil-ai.xyz)

Data model notes (verified against prod Supabase 2026-07-07):
  * subscriptions.org_id → organizations.id (FK repointed by migration
    `repoint_subscriptions_org_fk_to_organizations`; the old `orgs` table is
    dead/empty).
  * unique (provider, external_id) → upserts key on the Stripe sub id.
  * organizations.stripe_customer_id persists the customer for portal reuse.
  * Legacy lite/pro flag on user_preferences.tier is still written so older
    UI surfaces keep working (paid+active → "pro", else "lite").
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from winny_gateway.auth import get_current_user
from winny_gateway.db import db_insert, db_select, db_update, db_upsert
from winny_gateway.logging import get_logger
from winny_gateway.ops.billing import OPS_PLANS, plan_limits, tenant_plan, usage_summary

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/billing", tags=["billing"])

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
APP_URL = os.environ.get("APP_URL", "https://vigil-ai.xyz").rstrip("/")

# Tiers a customer can buy self-serve. `free` is the default; `enterprise`
# is contact-sales (no price id on purpose).
PURCHASABLE_TIERS = ("starter", "pro", "team")


def _is_production() -> bool:
    return (
        os.environ.get("WW_ENV") or os.environ.get("RAILWAY_ENVIRONMENT") or ""
    ).lower() in ("production", "prod")


def _price_id_for(tier: str) -> str:
    env_key = f"STRIPE_PRICE_ID_{tier.upper()}"
    price = os.environ.get(env_key, "")
    if not price and tier == "pro":
        price = os.environ.get("STRIPE_PRO_PRICE_ID", "")  # legacy name
    return price


def _iso(epoch: Any) -> str | None:
    """Stripe unix timestamp → ISO-8601, or None."""
    try:
        return datetime.fromtimestamp(int(epoch), UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


# ── Org resolution ────────────────────────────────────────────────────────────

async def _resolve_org(uid: str, email: str = "") -> dict[str, Any] | None:
    """The user's organization row; auto-provisioned on first billing touch.

    Membership lives in org_members (unique org_id+user_id); solo signups have
    no org yet, so checkout creates a personal org and an owner membership —
    the same shape tenant_plan() resolves.
    """
    members = await db_select("org_members", filters={"user_id": uid}, limit=1)
    if members:
        orgs = await db_select("organizations", filters={"id": members[0]["org_id"]}, limit=1)
        if orgs:
            return orgs[0]

    name = (email.split("@")[0] if email else "workspace") or "workspace"
    org = await db_insert(
        "organizations",
        {
            "name": f"{name}'s workspace",
            "slug": f"org-{uuid.uuid4().hex[:12]}",
            "owner_id": uid,
        },
    )
    if not org:
        return None
    await db_insert(
        "org_members",
        {"org_id": org["id"], "user_id": uid, "role": "owner", "email": email or None},
    )
    logger.info(
        "Auto-provisioned org for billing",
        extra={"user_id": uid, "org_id": org["id"], "component": "billing"},
    )
    return org


async def _set_legacy_tier(uid: str, *, paid_active: bool) -> None:
    """Keep the old lite/pro flag in sync for pre-org UI surfaces."""
    await db_upsert(
        "user_preferences",
        {"user_id": uid, "tier": "pro" if paid_active else "lite"},
        on_conflict="user_id",
    )


# ── Provisioning (the piece that makes a payment change the plan) ────────────

async def provision_subscription(
    *,
    uid: str,
    org_id: str,
    tier: str,
    stripe_subscription_id: str,
    stripe_customer_id: str = "",
    sub_status: str = "active",
    period_start: str | None = None,
    period_end: str | None = None,
    cancel_at_period_end: bool = False,
) -> dict[str, Any] | None:
    """Upsert the org's subscription row keyed on the Stripe subscription id."""
    tier = tier if tier in OPS_PLANS else "free"
    row = {
        "org_id": org_id,
        "provider": "stripe",
        "external_id": stripe_subscription_id,
        "external_customer_id": stripe_customer_id or None,
        "product_code": "vigil",
        "plan_tier": tier,
        "status": sub_status,
        "seats_purchased": 1,
        "unit_price_cents": int(plan_limits(tier).get("price_eur_cents") or 0),
        "currency": "EUR",
        "current_period_start": period_start,
        "current_period_end": period_end,
        "cancelled_at": datetime.now(UTC).isoformat() if sub_status == "canceled" else None,
        "metadata": {"user_id": uid, "cancel_at_period_end": cancel_at_period_end},
        "updated_at": datetime.now(UTC).isoformat(),
    }
    sub = await db_upsert("subscriptions", row, on_conflict="provider,external_id")
    if stripe_customer_id:
        await db_update(
            "organizations",
            filters={"id": org_id},
            data={"stripe_customer_id": stripe_customer_id},
        )
    await _set_legacy_tier(
        uid,
        paid_active=tier in PURCHASABLE_TIERS + ("enterprise",)
        and sub_status in ("active", "trialing"),
    )
    logger.info(
        "Subscription provisioned",
        extra={
            "user_id": uid, "org_id": org_id, "tier": tier,
            "status": sub_status, "component": "billing",
        },
    )
    return sub


# ── Routes ────────────────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    tier: str = "pro"


@router.get("")
async def get_billing(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Current plan + usage + subscription + what's purchasable."""
    uid = user["sub"]
    plan = await tenant_plan(uid)
    usage = await usage_summary(uid)
    org = None
    subscription = None
    members = await db_select("org_members", filters={"user_id": uid}, limit=1)
    if members:
        org_id = members[0]["org_id"]
        orgs = await db_select("organizations", filters={"id": org_id}, limit=1)
        org = orgs[0] if orgs else None
        subs = await db_select(
            "subscriptions", filters={"org_id": org_id}, order_by="-updated_at", limit=5
        )
        active = [s for s in subs if s.get("status") in ("active", "trialing")]
        subscription = (active or subs or [None])[0]
    tiers = [
        {
            "id": t,
            **{k: v for k, v in OPS_PLANS[t].items()},
            "purchasable": t in PURCHASABLE_TIERS and bool(_price_id_for(t)),
        }
        for t in OPS_PLANS
    ]
    return {
        "ok": True,
        "data": {
            "plan": plan,
            "limits": plan_limits(plan),
            "usage": usage,
            "org": ({"id": org["id"], "name": org.get("name")} if org else None),
            "subscription": subscription,
            "tiers": tiers,
            "stripe_configured": bool(STRIPE_SECRET_KEY),
        },
    }


@router.post("/checkout")
async def create_checkout_session(
    body: CheckoutRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Stripe Checkout session for a purchasable tier."""
    uid = user["sub"]
    email = user.get("email", "")
    tier = body.tier.lower()
    if tier not in PURCHASABLE_TIERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"tier must be one of {', '.join(PURCHASABLE_TIERS)} (enterprise is contact-sales)",
        )

    org = await _resolve_org(uid, email)
    if not org:
        raise HTTPException(status_code=500, detail="could not resolve billing organization")

    if not STRIPE_SECRET_KEY:
        if _is_production():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="stripe_not_configured",
            )
        # Dev-only mock: provision straight away so the flow is testable.
        await provision_subscription(
            uid=uid, org_id=org["id"], tier=tier,
            stripe_subscription_id=f"dev_{uuid.uuid4().hex[:16]}",
        )
        logger.warning("Stripe not configured — dev mock checkout", extra={"component": "billing"})
        return {"ok": True, "data": {"url": f"{APP_URL}/billing?checkout=success&mock=1"}}

    price_id = _price_id_for(tier)
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"price id for tier '{tier}' is not configured",
        )

    try:
        import stripe

        stripe.api_key = STRIPE_SECRET_KEY
        meta = {"user_id": uid, "org_id": org["id"], "tier": tier}
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=email or None,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{APP_URL}/billing?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{APP_URL}/billing?checkout=cancelled",
            metadata=meta,
            subscription_data={"metadata": meta},
            client_reference_id=uid,
        )
        return {"ok": True, "data": {"url": session.url}}
    except Exception as exc:
        logger.error("Stripe checkout failed: %s", exc, extra={"component": "billing"})
        raise HTTPException(status_code=502, detail=f"stripe checkout failed: {exc}") from exc


@router.post("/portal")
async def create_portal_session(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Stripe Customer Portal session (manage/cancel/update card)."""
    uid = user["sub"]
    if not STRIPE_SECRET_KEY:
        return {"ok": True, "data": {"url": f"{APP_URL}/billing?portal=mock"}}
    try:
        import stripe

        stripe.api_key = STRIPE_SECRET_KEY
        customer_id = ""
        org = await _resolve_org(uid, user.get("email", ""))
        if org:
            customer_id = org.get("stripe_customer_id") or ""
        if not customer_id and user.get("email"):
            found = stripe.Customer.list(email=user["email"], limit=1)
            if found.data:
                customer_id = found.data[0].id
                if org:
                    await db_update(
                        "organizations",
                        filters={"id": org["id"]},
                        data={"stripe_customer_id": customer_id},
                    )
        if not customer_id:
            return {"ok": False, "data": None, "error": "No subscription found"}
        session = stripe.billing_portal.Session.create(
            customer=customer_id, return_url=f"{APP_URL}/billing"
        )
        return {"ok": True, "data": {"url": session.url}}
    except Exception as exc:
        logger.error("Stripe portal failed: %s", exc, extra={"component": "billing"})
        return {"ok": False, "data": None, "error": str(exc)}


@router.post("/cancel")
async def cancel_subscription(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Cancel at period end — a REAL Stripe cancel, mirrored to the DB row."""
    uid = user["sub"]
    members = await db_select("org_members", filters={"user_id": uid}, limit=1)
    if not members:
        raise HTTPException(status_code=404, detail="no billing organization")
    subs = await db_select(
        "subscriptions",
        filters={"org_id": members[0]["org_id"], "provider": "stripe"},
        order_by="-updated_at",
        limit=5,
    )
    active = [s for s in subs if s.get("status") in ("active", "trialing")]
    if not active:
        raise HTTPException(status_code=404, detail="no active subscription")
    sub = active[0]
    if STRIPE_SECRET_KEY and not str(sub["external_id"]).startswith("dev_"):
        try:
            import stripe

            stripe.api_key = STRIPE_SECRET_KEY
            stripe.Subscription.modify(sub["external_id"], cancel_at_period_end=True)
        except Exception as exc:
            logger.error("Stripe cancel failed: %s", exc, extra={"component": "billing"})
            raise HTTPException(status_code=502, detail=f"stripe cancel failed: {exc}") from exc
    meta = dict(sub.get("metadata") or {})
    meta["cancel_at_period_end"] = True
    await db_update(
        "subscriptions",
        filters={"id": sub["id"]},
        data={"metadata": meta, "updated_at": datetime.now(UTC).isoformat()},
    )
    logger.info("Subscription set to cancel at period end", extra={"user_id": uid, "component": "billing"})
    return {"ok": True, "data": {"cancel_at_period_end": True}}


@router.post("/webhook")
async def stripe_webhook(request: Request) -> dict[str, Any]:
    """Stripe events → provision/update the org's subscription row.

    Signature verification is MANDATORY in production: without
    STRIPE_WEBHOOK_SECRET anyone who can reach the endpoint could forge a
    `checkout.session.completed` and grant themselves a paid plan.
    """
    payload = await request.body()
    if STRIPE_WEBHOOK_SECRET:
        try:
            import stripe

            signature = request.headers.get("stripe-signature", "")
            event = stripe.Webhook.construct_event(payload, signature, STRIPE_WEBHOOK_SECRET)
        except Exception as exc:
            logger.warning("Stripe webhook rejected: %s", exc, extra={"component": "billing"})
            raise HTTPException(status_code=400, detail="Invalid Stripe webhook") from exc
    elif _is_production():
        logger.error(
            "Stripe webhook received but STRIPE_WEBHOOK_SECRET is unset — refusing (fail closed)",
            extra={"component": "billing"},
        )
        raise HTTPException(status_code=503, detail="webhook secret not configured")
    else:
        import json

        try:
            event = json.loads(payload.decode("utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid payload") from exc

    event_type = event.get("type", "")
    obj = event.get("data", {}).get("object", {}) or {}
    metadata = obj.get("metadata") or {}
    uid = metadata.get("user_id") or event.get("client_reference_id") or obj.get("client_reference_id")
    org_id = metadata.get("org_id")
    tier = (metadata.get("tier") or "").lower()

    if event_type == "checkout.session.completed" and uid and org_id:
        await provision_subscription(
            uid=uid,
            org_id=org_id,
            tier=tier or "pro",
            stripe_subscription_id=str(obj.get("subscription") or f"cs_{obj.get('id', '')}"),
            stripe_customer_id=str(obj.get("customer") or ""),
            sub_status="active",
        )
    elif event_type in {"customer.subscription.updated", "customer.subscription.deleted"} and uid and org_id:
        sub_status = str(obj.get("status") or ("canceled" if event_type.endswith("deleted") else "inactive"))
        await provision_subscription(
            uid=uid,
            org_id=org_id,
            tier=tier or "pro",
            stripe_subscription_id=str(obj.get("id") or ""),
            stripe_customer_id=str(obj.get("customer") or ""),
            sub_status=sub_status,
            period_start=_iso(obj.get("current_period_start")),
            period_end=_iso(obj.get("current_period_end")),
            cancel_at_period_end=bool(obj.get("cancel_at_period_end")),
        )
    elif event_type.startswith(("checkout.", "customer.subscription.")):
        logger.warning(
            "Stripe event missing user_id/org_id metadata — not provisioned",
            extra={"event_type": event_type, "component": "billing"},
        )

    return {"ok": True, "data": {"received": True, "type": event_type}}
