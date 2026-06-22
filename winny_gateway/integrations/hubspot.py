"""HubSpot connector — the CRM system-of-record, on the connector kit.

Token-based (HubSpot private-app access token, per-tenant, encrypted via the kit —
no OAuth-callback infra needed). `sync` pulls the tenant's contacts + deals into our
existing `crm_contacts` / `crm_deals` tables, idempotent on the HubSpot object id, so
the Revenue + Lead Scout departments work the tenant's live pipeline. Read-only.
"""
from __future__ import annotations

from typing import Any

import httpx

from winny_gateway.db import db_insert, db_select
from winny_gateway.integrations.connector import Connector, ConnectorError, register

_API = "https://api.hubapi.com"


async def _get(token: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{_API}{path}", headers={"Authorization": f"Bearer {token}"}, params=params or {})
    except httpx.HTTPError as exc:
        raise ConnectorError(f"HubSpot unreachable: {exc}", code="network", status=502) from exc
    if r.status_code == 401:
        raise ConnectorError("invalid HubSpot token", code="invalid_token", status=400)
    if r.status_code >= 400:
        raise ConnectorError(f"HubSpot HTTP {r.status_code}", code="hubspot_error", status=502)
    return r.json()


def _stage(dealstage: str | None) -> str:
    s = (dealstage or "").lower()
    if "won" in s:
        return "won"
    if "lost" in s:
        return "lost"
    return "qualified"


class HubSpotConnector(Connector):
    provider = "hubspot"
    kind = "crm"

    async def verify_token(self, token: str, account: str | None = None) -> dict[str, Any]:
        info = await _get(token, "/account-info/v3/details")
        return {"external_account": str(info.get("portalId") or info.get("accountType") or "hubspot")}

    async def sync(self, uid: str, conn: dict[str, Any], token: str) -> dict[str, Any]:
        contacts = await _get(token, "/crm/v3/objects/contacts",
                              {"limit": 100, "properties": "email,firstname,lastname,company,jobtitle"})
        deals = await _get(token, "/crm/v3/objects/deals",
                           {"limit": 100, "properties": "dealname,amount,dealstage,pipeline"})

        existing_c = await db_select("crm_contacts", filters={"user_id": uid}, limit=5000)
        have_c = {(r.get("metadata") or {}).get("hubspot_id") for r in existing_c if isinstance(r.get("metadata"), dict)}
        added_c = 0
        for c in contacts.get("results", []):
            hid = str(c.get("id"))
            if hid in have_c:
                continue
            p = c.get("properties") or {}
            name = " ".join(x for x in (p.get("firstname"), p.get("lastname")) if x) or p.get("email") or "Unknown"
            if await db_insert("crm_contacts", {
                "user_id": uid, "name": name, "email": p.get("email"),
                "company": p.get("company"), "title": p.get("jobtitle"),
                "tags": ["hubspot"], "metadata": {"hubspot_id": hid},
            }):
                added_c += 1

        existing_d = await db_select("crm_deals", filters={"user_id": uid}, limit=5000)
        have_d = {(r.get("metadata") or {}).get("hubspot_id") for r in existing_d if isinstance(r.get("metadata"), dict)}
        added_d = 0
        for d in deals.get("results", []):
            hid = str(d.get("id"))
            if hid in have_d:
                continue
            p = d.get("properties") or {}
            try:
                value = float(p.get("amount") or 0)
            except (TypeError, ValueError):
                value = 0.0
            if await db_insert("crm_deals", {
                "user_id": uid, "title": p.get("dealname") or "Untitled deal",
                "stage": _stage(p.get("dealstage")), "value": value,
                "metadata": {"hubspot_id": hid, "hubspot_stage": p.get("dealstage")},
            }):
                added_d += 1

        return {"metadata": {"contacts": added_c, "deals": added_d},
                "contacts_added": added_c, "deals_added": added_d}


register(HubSpotConnector())
