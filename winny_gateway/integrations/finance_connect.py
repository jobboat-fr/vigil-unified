"""Finance connector — bank/accounting providers feeding the ledger.

`status()` reports which providers are configured (their platform keys present —
stored from the UI or set in env) and the user's live connections; this is the
keys-management view. `sync()` pulls accounts + transactions into the existing
`finance_accounts` / `finance_transactions` tables (idempotent on the provider's
transaction id), so the Finance department has real data to reconcile.

Platform keys are resolved per-request via the keys store (stored value → env
fallback), so the connector works whether keys came from the UI or deploy env.
Plaid (bank) is implemented; QuickBooks/Xero are registered for later adapters.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from winny_gateway.db import db_insert, db_select, db_update
from winny_gateway.integrations import keys
from winny_gateway.integrations import plaid_client as plaid
from winny_gateway.integrations.secrets import decrypt_secret, encrypt_secret, mask_secret
from winny_gateway.logging import get_logger

logger = get_logger(__name__)

PLAID_KEYS = ["PLAID_CLIENT_ID", "PLAID_SECRET", "PLAID_ENV"]

# Provider registry. `implemented` gates the connect flow; `required_keys` are the
# platform keys surfaced (and editable) in keys management.
PROVIDERS: dict[str, dict[str, Any]] = {
    "plaid": {
        "name": "Plaid — bank accounts",
        "kind": "bank",
        "required_keys": PLAID_KEYS,
        "implemented": True,
    },
    "quickbooks": {
        "name": "QuickBooks — accounting",
        "kind": "accounting",
        "required_keys": ["QUICKBOOKS_CLIENT_ID", "QUICKBOOKS_SECRET"],
        "implemented": False,
    },
    "xero": {
        "name": "Xero — accounting",
        "kind": "accounting",
        "required_keys": ["XERO_CLIENT_ID", "XERO_SECRET"],
        "implemented": False,
    },
}

_ACCT_TYPE = {"depository": "asset", "investment": "asset", "credit": "liability", "loan": "liability"}


async def _plaid_creds(uid: str) -> plaid.PlaidCreds:
    k = await keys.get_keys(uid, "plaid", PLAID_KEYS)
    return plaid.PlaidCreds(
        client_id=k.get("PLAID_CLIENT_ID") or "",
        secret=k.get("PLAID_SECRET") or "",
        env=(k.get("PLAID_ENV") or "sandbox"),
    )


def _safe_decrypt(enc: str) -> str:
    try:
        return decrypt_secret(enc) if enc else ""
    except Exception:  # noqa: BLE001 — masking only; never break status on a bad token
        return ""


def _public_connection(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "provider": row.get("provider"),
        "institution": row.get("institution"),
        "status": row.get("status"),
        "accounts_count": row.get("accounts_count") or 0,
        "last_synced_at": row.get("last_synced_at"),
        "token_masked": mask_secret(_safe_decrypt(row.get("access_token_enc") or "")),
        "created_at": row.get("created_at"),
    }


async def status(uid: str) -> dict[str, Any]:
    providers = []
    for pid, spec in PROVIDERS.items():
        ks = await keys.status(uid, pid, spec["required_keys"])
        cred_keys = [k for k in ks if not k["name"].endswith("_ENV")]
        configured = bool(spec["implemented"] and cred_keys and all(k["set"] for k in cred_keys))
        providers.append({
            "id": pid, "name": spec["name"], "kind": spec["kind"],
            "implemented": spec["implemented"], "configured": configured, "required_keys": ks,
        })
    conns = await db_select("finance_connections", filters={"user_id": uid}, limit=100)
    creds = await _plaid_creds(uid)
    return {
        "providers": providers,
        "connections": [_public_connection(r) for r in conns],
        "plaid_env": creds.env,
    }


async def set_keys(uid: str, provider: str, values: dict[str, Any]) -> int:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    return await keys.set_keys(uid, provider, values)


async def link_token(uid: str) -> dict[str, Any]:
    return await plaid.create_link_token(await _plaid_creds(uid), uid)


async def _store_connection(uid: str, provider: str, access_token: str, item_id: str | None, institution: str | None) -> dict[str, Any]:
    row = await db_insert("finance_connections", {
        "user_id": uid, "provider": provider, "item_id": item_id,
        "access_token_enc": encrypt_secret(access_token), "institution": institution,
        "status": "active", "accounts_count": 0,
    })
    return _public_connection(row or {})


async def connect_sandbox(uid: str) -> dict[str, Any]:
    creds = await _plaid_creds(uid)
    pub = await plaid.sandbox_public_token(creds)
    exchanged = await plaid.exchange_public_token(creds, pub["public_token"])
    access = exchanged["access_token"]
    inst = await plaid.institution_name(creds, access)
    return await _store_connection(uid, "plaid", access, exchanged.get("item_id"), inst or "Sandbox bank")


async def connect_exchange(uid: str, public_token: str, institution: str | None = None) -> dict[str, Any]:
    creds = await _plaid_creds(uid)
    exchanged = await plaid.exchange_public_token(creds, public_token)
    access = exchanged["access_token"]
    inst = institution or await plaid.institution_name(creds, access)
    return await _store_connection(uid, "plaid", access, exchanged.get("item_id"), inst)


async def _ensure_account(uid: str, name: str, acct_type: str) -> str | None:
    existing = await db_select("finance_accounts", filters={"user_id": uid, "name": name}, limit=1)
    if existing:
        return existing[0]["id"]
    row = await db_insert("finance_accounts", {"user_id": uid, "name": name, "type": acct_type})
    return (row or {}).get("id")


async def sync(uid: str, connection_id: str | None = None) -> dict[str, Any]:
    """Pull accounts + transactions for the user's Plaid connection(s) into the
    ledger. Idempotent: a Plaid transaction already imported is skipped."""
    filters: dict[str, Any] = {"user_id": uid, "provider": "plaid"}
    if connection_id:
        filters["id"] = connection_id
    conns = await db_select("finance_connections", filters=filters, limit=50)
    if not conns:
        return {"accounts": 0, "transactions_added": 0, "connections": 0}

    creds = await _plaid_creds(uid)
    existing = await db_select("finance_transactions", filters={"user_id": uid}, limit=5000)
    seen_txn = {
        (t.get("metadata") or {}).get("plaid_txn_id")
        for t in existing if isinstance(t.get("metadata"), dict)
    }
    seen_txn.discard(None)

    total_accounts = 0
    total_added = 0
    for conn in conns:
        access = _safe_decrypt(conn.get("access_token_enc") or "")
        if not access:
            continue
        inst = conn.get("institution") or "Bank"
        try:
            accounts = await plaid.accounts_get(creds, access)
            acct_map: dict[str, str | None] = {}
            for a in accounts:
                mask = a.get("mask") or str(a.get("account_id", ""))[-4:]
                name = f"{inst} ••{mask}"
                acct_map[a.get("account_id")] = await _ensure_account(
                    uid, name, _ACCT_TYPE.get(a.get("type", ""), "asset"))
            total_accounts += len(accounts)

            result = await plaid.transactions_sync(creds, access, conn.get("cursor"))
            for t in result.get("added", []):
                tid = t.get("transaction_id")
                if not tid or tid in seen_txn:
                    continue
                seen_txn.add(tid)
                await db_insert("finance_transactions", {
                    "user_id": uid,
                    "txn_date": t.get("date") or datetime.now(UTC).date().isoformat(),
                    "description": t.get("merchant_name") or t.get("name") or "Bank transaction",
                    "amount": -float(t.get("amount") or 0),
                    "currency": t.get("iso_currency_code") or "USD",
                    "category": None,
                    "account_id": acct_map.get(t.get("account_id")),
                    "status": "uncategorized",
                    "source": "bank",
                    "metadata": {
                        "plaid_txn_id": tid,
                        "plaid_account_id": t.get("account_id"),
                        "pfc": (t.get("personal_finance_category") or {}).get("primary"),
                    },
                })
                total_added += 1

            await db_update("finance_connections", {
                "cursor": result.get("next_cursor"), "accounts_count": len(accounts),
                "status": "active", "error": None,
                "last_synced_at": datetime.now(UTC).isoformat(),
            }, filters={"id": conn["id"], "user_id": uid})
        except Exception as exc:  # noqa: BLE001 — record the failure on the connection
            logger.warning("finance_connect.sync_failed conn=%s: %s", conn.get("id"), exc)
            await db_update("finance_connections", {"status": "error", "error": str(exc)[:300]},
                            filters={"id": conn["id"], "user_id": uid})

    return {"accounts": total_accounts, "transactions_added": total_added, "connections": len(conns)}


async def disconnect(uid: str, connection_id: str) -> bool:
    from winny_gateway.db import db_delete
    rows = await db_select("finance_connections", filters={"id": connection_id, "user_id": uid}, limit=1)
    if not rows:
        return False
    await db_delete("finance_connections", filters={"id": connection_id, "user_id": uid})
    return True
