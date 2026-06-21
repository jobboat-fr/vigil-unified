"""Minimal async Plaid REST client — bank accounts via API.

Credentials are resolved by the caller (winny_gateway.integrations.finance_connect,
via the keys store: stored value → gateway env fallback) and passed in as PlaidCreds,
so keys can come from the UI or from deploy env. Only the endpoints the connector
needs are implemented. Every call is keyless-safe: with no creds, ``creds.configured``
is False and the connector reports "not configured" rather than raising.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from winny_gateway.logging import get_logger

logger = get_logger(__name__)

_HOSTS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
    "development": "https://development.plaid.com",
}


@dataclass
class PlaidCreds:
    client_id: str = ""
    secret: str = ""
    env: str = "sandbox"

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.secret)

    @property
    def host(self) -> str:
        return _HOSTS.get((self.env or "sandbox").lower(), _HOSTS["sandbox"])


class PlaidError(RuntimeError):
    def __init__(self, message: str, *, code: str = "plaid_error", status: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


async def _post(creds: PlaidCreds, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not creds.configured:
        raise PlaidError("Plaid is not configured (set PLAID_CLIENT_ID + PLAID_SECRET)",
                         code="not_configured", status=503)
    body = {"client_id": creds.client_id, "secret": creds.secret, **payload}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{creds.host}{path}", json=body)
    except httpx.HTTPError as exc:
        raise PlaidError(f"Plaid request failed: {exc}", code="network", status=502) from exc
    if resp.status_code >= 400:
        try:
            err = resp.json()
        except ValueError:
            err = {"error_message": resp.text[:300]}
        raise PlaidError(err.get("error_message") or f"HTTP {resp.status_code}",
                         code=err.get("error_code") or "plaid_error", status=502)
    return resp.json()


# ── Endpoints ────────────────────────────────────────────────────────────────
async def create_link_token(creds: PlaidCreds, user_id: str) -> dict[str, Any]:
    return await _post(creds, "/link/token/create", {
        "user": {"client_user_id": user_id},
        "client_name": "VIGIL × WinnyWoo",
        "products": ["transactions"],
        "country_codes": ["US"],
        "language": "en",
    })


async def sandbox_public_token(creds: PlaidCreds, institution_id: str = "ins_109508") -> dict[str, Any]:
    if (creds.env or "sandbox").lower() != "sandbox":
        raise PlaidError("sandbox connect is only available when PLAID_ENV=sandbox",
                         code="not_sandbox", status=400)
    return await _post(creds, "/sandbox/public_token/create", {
        "institution_id": institution_id,
        "initial_products": ["transactions"],
    })


async def exchange_public_token(creds: PlaidCreds, public_token: str) -> dict[str, Any]:
    return await _post(creds, "/item/public_token/exchange", {"public_token": public_token})


async def accounts_get(creds: PlaidCreds, access_token: str) -> list[dict[str, Any]]:
    data = await _post(creds, "/accounts/get", {"access_token": access_token})
    return data.get("accounts") or []


async def institution_name(creds: PlaidCreds, access_token: str) -> str | None:
    try:
        item = await _post(creds, "/item/get", {"access_token": access_token})
        inst_id = (item.get("item") or {}).get("institution_id")
        if not inst_id:
            return None
        info = await _post(creds, "/institutions/get_by_id", {
            "institution_id": inst_id, "country_codes": ["US"],
        })
        return (info.get("institution") or {}).get("name")
    except PlaidError:
        return None


async def transactions_sync(creds: PlaidCreds, access_token: str, cursor: str | None = None) -> dict[str, Any]:
    added: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    cur = cursor
    has_more = True
    pages = 0
    while has_more and pages < 10:
        payload: dict[str, Any] = {"access_token": access_token}
        if cur:
            payload["cursor"] = cur
        data = await _post(creds, "/transactions/sync", payload)
        added += data.get("added") or []
        modified += data.get("modified") or []
        removed += data.get("removed") or []
        cur = data.get("next_cursor") or cur
        has_more = bool(data.get("has_more"))
        pages += 1
    return {"added": added, "modified": modified, "removed": removed, "next_cursor": cur}
