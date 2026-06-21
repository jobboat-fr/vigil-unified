"""Minimal async Plaid REST client — bank accounts via API.

Reads platform credentials from gateway env:
  PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ENV (sandbox|production; default sandbox).

Only the handful of endpoints the connector needs are implemented. Every call is
keyless-safe: when the platform keys are unset, ``configured()`` is False and the
connector reports "not configured" rather than raising — so the rest of the system
runs fine without Plaid set up.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from winny_gateway.logging import get_logger

logger = get_logger(__name__)

_HOSTS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
    "development": "https://development.plaid.com",  # deprecated by Plaid but accepted
}


class PlaidError(RuntimeError):
    def __init__(self, message: str, *, code: str = "plaid_error", status: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def env() -> str:
    return (os.getenv("PLAID_ENV") or "sandbox").strip().lower()


def _client_id() -> str:
    return (os.getenv("PLAID_CLIENT_ID") or "").strip()


def _secret() -> str:
    return (os.getenv("PLAID_SECRET") or "").strip()


def configured() -> bool:
    return bool(_client_id() and _secret())


def _base() -> str:
    return _HOSTS.get(env(), _HOSTS["sandbox"])


async def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not configured():
        raise PlaidError("Plaid is not configured (set PLAID_CLIENT_ID + PLAID_SECRET)",
                         code="not_configured", status=503)
    body = {"client_id": _client_id(), "secret": _secret(), **payload}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{_base()}{path}", json=body)
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
async def create_link_token(user_id: str) -> dict[str, Any]:
    """Init a Plaid Link session (the real production connect flow runs Link in the
    browser, then exchanges the resulting public_token)."""
    return await _post("/link/token/create", {
        "user": {"client_user_id": user_id},
        "client_name": "VIGIL × WinnyWoo",
        "products": ["transactions"],
        "country_codes": ["US"],
        "language": "en",
    })


async def sandbox_public_token(institution_id: str = "ins_109508") -> dict[str, Any]:
    """Sandbox-only: mint a public_token without Link, so the connect→sync loop is
    exercisable end-to-end in tests / sandbox. (ins_109508 = First Platypus Bank.)"""
    if env() != "sandbox":
        raise PlaidError("sandbox connect is only available when PLAID_ENV=sandbox",
                         code="not_sandbox", status=400)
    return await _post("/sandbox/public_token/create", {
        "institution_id": institution_id,
        "initial_products": ["transactions"],
    })


async def exchange_public_token(public_token: str) -> dict[str, Any]:
    return await _post("/item/public_token/exchange", {"public_token": public_token})


async def accounts_get(access_token: str) -> list[dict[str, Any]]:
    data = await _post("/accounts/get", {"access_token": access_token})
    return data.get("accounts") or []


async def institution_name(access_token: str) -> str | None:
    """Best-effort display name for the linked institution."""
    try:
        item = await _post("/item/get", {"access_token": access_token})
        inst_id = (item.get("item") or {}).get("institution_id")
        if not inst_id:
            return None
        info = await _post("/institutions/get_by_id", {
            "institution_id": inst_id, "country_codes": ["US"],
        })
        return (info.get("institution") or {}).get("name")
    except PlaidError:
        return None


async def transactions_sync(access_token: str, cursor: str | None = None) -> dict[str, Any]:
    """Incremental pull. Returns {added, modified, removed, next_cursor, has_more}."""
    added: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    cur = cursor
    has_more = True
    pages = 0
    while has_more and pages < 10:  # bound the loop
        payload: dict[str, Any] = {"access_token": access_token}
        if cur:
            payload["cursor"] = cur
        data = await _post("/transactions/sync", payload)
        added += data.get("added") or []
        modified += data.get("modified") or []
        removed += data.get("removed") or []
        cur = data.get("next_cursor") or cur
        has_more = bool(data.get("has_more"))
        pages += 1
    return {"added": added, "modified": modified, "removed": removed, "next_cursor": cur}
