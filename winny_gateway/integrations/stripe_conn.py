"""Stripe connector — revenue/payments system-of-record, on the connector kit.

Token-based (Stripe restricted/secret key, per-tenant, encrypted via the kit). `sync`
pulls succeeded charges into the ledger as income (idempotent on the Stripe charge id),
so the Finance department reconciles bank (Plaid) + revenue (Stripe) together. Read-only.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from winny_gateway.db import db_insert, db_select
from winny_gateway.integrations.connector import Connector, ConnectorError, register

_API = "https://api.stripe.com/v1"


async def _get(token: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{_API}{path}", headers={"Authorization": f"Bearer {token}"}, params=params or {})
    except httpx.HTTPError as exc:
        raise ConnectorError(f"Stripe unreachable: {exc}", code="network", status=502) from exc
    if r.status_code == 401:
        raise ConnectorError("invalid Stripe key", code="invalid_token", status=400)
    if r.status_code >= 400:
        raise ConnectorError(f"Stripe HTTP {r.status_code}", code="stripe_error", status=502)
    return r.json()


class StripeConnector(Connector):
    provider = "stripe"
    kind = "payments"

    async def verify_token(self, token: str, account: str | None = None) -> dict[str, Any]:
        acct = await _get(token, "/account")
        return {"external_account": str(acct.get("id") or "stripe"),
                "business_name": (acct.get("business_profile") or {}).get("name")}

    async def sync(self, uid: str, conn: dict[str, Any], token: str) -> dict[str, Any]:
        charges = await _get(token, "/charges", {"limit": 100})
        existing = await db_select("finance_transactions", filters={"user_id": uid}, limit=5000)
        seen = {(t.get("metadata") or {}).get("stripe_id") for t in existing if isinstance(t.get("metadata"), dict)}
        added = 0
        for ch in charges.get("data", []):
            sid = ch.get("id")
            if not sid or sid in seen or ch.get("status") != "succeeded" or not ch.get("paid"):
                continue
            seen.add(sid)
            when = datetime.fromtimestamp(int(ch.get("created") or 0), UTC).date().isoformat() if ch.get("created") else None
            if await db_insert("finance_transactions", {
                "user_id": uid,
                "txn_date": when or datetime.now(UTC).date().isoformat(),
                "description": ch.get("description") or "Stripe charge",
                "amount": round(float(ch.get("amount") or 0) / 100.0, 2),  # cents → units, income (+)
                "currency": (ch.get("currency") or "usd").upper(),
                "category": "revenue",
                "status": "uncategorized",
                "source": "stripe",
                "metadata": {"stripe_id": sid},
            }):
                added += 1
        return {"metadata": {"charges": added}, "charges_added": added}


register(StripeConnector())
