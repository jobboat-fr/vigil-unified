"""GET/PUT /api/v1/settings — user preferences (broker selection, API keys).

Persistence: Supabase (user_preferences + broker_credentials tables).
Falls back to in-memory dict if Supabase is unavailable (dev mode).

Supported brokers for CR (crypto):
    binance, kraken, coinbase, okx, bybit, gate

EQ/FX/FU/OP routing is fixed to IBKR (future P6).
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from winny_gateway.auth import effective_user as _effective_user, get_current_user
from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

# ── Supported brokers ────────────────────────────────────────────────────────

SUPPORTED_BROKERS: list[dict[str, Any]] = [
    {
        "id": "binance",
        "name": "Binance",
        "logo": "https://cryptologos.cc/logos/binance-coin-bnb-logo.svg",
        "asset_classes": ["CR"],
        "features": ["spot", "futures", "margin"],
        "status": "live",
    },
    {
        "id": "kraken",
        "name": "Kraken",
        "logo": "https://cryptologos.cc/logos/kraken-logo.svg",
        "asset_classes": ["CR"],
        "features": ["spot", "futures", "ws_v2"],
        "status": "live",
    },
    {
        "id": "coinbase",
        "name": "Coinbase",
        "logo": "https://cryptologos.cc/logos/coinbase-logo.svg",
        "asset_classes": ["CR"],
        "features": ["spot"],
        "status": "scaffold",
    },
    {
        "id": "okx",
        "name": "OKX",
        "logo": "https://cryptologos.cc/logos/okx-logo.svg",
        "asset_classes": ["CR"],
        "features": ["spot", "futures", "margin"],
        "status": "live",
    },
    {
        "id": "bybit",
        "name": "Bybit",
        "logo": "https://cryptologos.cc/logos/bybit-logo.svg",
        "asset_classes": ["CR"],
        "features": ["spot", "futures"],
        "status": "live",
    },
    {
        "id": "gate",
        "name": "Gate.io",
        "logo": "https://cryptologos.cc/logos/gate-logo.svg",
        "asset_classes": ["CR"],
        "features": ["spot", "futures"],
        "status": "live",
    },
]

BROKER_IDS = {b["id"] for b in SUPPORTED_BROKERS}

# ── User preferences (Supabase + in-memory cache) ────────────────────────────

_user_prefs: dict[str, dict[str, Any]] = {}


def _get_prefs(user_id: str) -> dict[str, Any]:
    """Get user preferences — cached in-memory, sourced from Supabase."""
    if user_id not in _user_prefs:
        # Try loading from Supabase
        prefs_from_db = _load_prefs_from_db(user_id)
        if prefs_from_db:
            _user_prefs[user_id] = prefs_from_db
        else:
            _user_prefs[user_id] = {
                "broker_cr": os.environ.get("WINNY_BROKER_CR", "binance").lower(),
            }
    return _user_prefs[user_id]


def _load_prefs_from_db(user_id: str) -> dict[str, Any] | None:
    """Load preferences from Supabase. Returns None if unavailable."""
    try:
        from winny_gateway.db import get_admin_client

        client = get_admin_client()
        result = (
            client.table("user_preferences")
            .select("broker_cr, theme, risk_level, max_position_pct, auto_approval_enabled, notifications_enabled, tier")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        if result.data:
            return dict(result.data)
        return None
    except Exception:
        try:
            from winny_gateway.db import get_admin_client

            client = get_admin_client()
            result = (
                client.table("user_preferences")
                .select("broker_cr, theme, risk_level, max_position_pct, auto_approval_enabled")
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            return dict(result.data) if result.data else None
        except Exception:
            return None


async def _save_prefs_to_db(user_id: str, prefs: dict[str, Any]) -> None:
    """Persist preferences to Supabase (upsert)."""
    try:
        from winny_gateway.db import get_admin_client

        client = get_admin_client()
        client.table("user_preferences").upsert(
            {"user_id": user_id, **prefs},
            on_conflict="user_id",
        ).execute()
    except Exception as e:
        logger.debug("Failed to save prefs to DB: %s", e, extra={"component": "settings"})


# ── Models ────────────────────────────────────────────────────────────────────


class BrokerPreference(BaseModel):
    broker_cr: str = Field(
        ...,
        description="Crypto broker ID (binance, kraken, coinbase, okx, bybit, gate)",
    )


class BrokerPreferenceResponse(BaseModel):
    broker_cr: str
    supported: list[dict[str, Any]]


class NotificationSettings(BaseModel):
    notifications_enabled: bool | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/brokers")
async def list_brokers(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """List all supported brokers with their capabilities."""
    prefs = _get_prefs(user.get("sub", "anon"))
    return {
        "ok": True,
        "data": {
            "brokers": SUPPORTED_BROKERS,
            "selected": prefs["broker_cr"],
        },
    }


@router.get("/broker")
async def get_broker_pref(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Get user's current broker preference."""
    prefs = _get_prefs(user.get("sub", "anon"))
    return {
        "ok": True,
        "data": {
            "broker_cr": prefs["broker_cr"],
            "supported": SUPPORTED_BROKERS,
        },
    }


@router.put("/broker")
async def set_broker_pref(
    body: BrokerPreference,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Set user's preferred crypto broker.

    This changes the routing for all future CR: orders. Existing open
    orders on the old broker are NOT migrated — the user must close them
    manually first.
    """
    user = _effective_user(request, user)
    broker_id = body.broker_cr.lower()
    if broker_id not in BROKER_IDS:
        logger.warning(
            "Unknown broker requested: %s", broker_id,
            extra={"action": "settings.broker_invalid", "broker": broker_id, "component": "settings"},
        )
        return {
            "ok": False,
            "error": f"Unknown broker '{broker_id}'. Supported: {sorted(BROKER_IDS)}",
        }

    user_id = user.get("sub", "anon")
    prefs = _get_prefs(user_id)
    old = prefs["broker_cr"]
    prefs["broker_cr"] = broker_id

    logger.info(
        "Broker switched: %s → %s", old, broker_id,
        extra={"action": "settings.broker_switch", "broker": broker_id, "component": "settings"},
    )

    # Also update os.environ so the factory picks it up for this process
    os.environ["WINNY_BROKER_CR"] = broker_id

    # Persist to Supabase
    await _save_prefs_to_db(user_id, {"broker_cr": broker_id})

    # Audit
    from winny_gateway.db import audit_log
    await audit_log(
        user_id=user_id, event_type="settings", action="broker_switch",
        component="settings", broker=broker_id,
        details={"previous": old, "new": broker_id},
    )

    return {
        "ok": True,
        "data": {
            "broker_cr": broker_id,
            "previous": old,
            "message": f"Crypto broker changed from {old} to {broker_id}",
        },
    }


# ── API Key Management ────────────────────────────────────────────────────────


@router.put("/notifications")
async def set_notifications(
    body: NotificationSettings,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Update notification preferences supported by the schema."""
    user_id = user.get("sub", "anon")
    prefs = _get_prefs(user_id)
    updates: dict[str, Any] = {}
    if body.notifications_enabled is not None:
        updates["notifications_enabled"] = body.notifications_enabled

    if updates:
        prefs.update(updates)
        await _save_prefs_to_db(user_id, updates)

    return {"ok": True, "data": {**prefs, **updates}}


class ApiKeyBody(BaseModel):
    """Payload for saving API keys."""

    broker_id: str = Field(..., max_length=32, description="Broker ID")
    api_key: str = Field(..., min_length=1, max_length=512, description="API Key")
    api_secret: str = Field(default="", max_length=512, description="API Secret")
    api_password: str = Field(default="", max_length=256, description="API Password/Passphrase")
    is_testnet: bool = Field(default=False, description="Use testnet/sandbox mode")
    label: str = Field(default="", max_length=100, description="User-friendly label")


@router.post("/api-keys")
async def save_api_keys(
    body: ApiKeyBody,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Save (or update) API keys for a broker. Keys are encrypted at rest.

    After saving, keys are NEVER returned in plaintext.
    Only a masked version is available.
    """
    from winny.brokerage.credentials import credential_store
    from winny.common.sanitise import validate_api_key, validate_broker_id

    user = _effective_user(request, user)
    user_id = user.get("sub", "anon")

    # Validate
    try:
        broker_id = validate_broker_id(body.broker_id)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    if broker_id not in BROKER_IDS:
        return {"ok": False, "error": f"Unknown broker '{broker_id}'."}

    try:
        validate_api_key(body.api_key, "api_key")
        validate_api_key(body.api_secret, "api_secret")
        if body.api_password:
            validate_api_key(body.api_password, "api_password")
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    # Store encrypted (in-memory + file)
    mask = credential_store.save(
        user_id,
        broker_id,
        api_key=body.api_key,
        api_secret=body.api_secret,
        api_password=body.api_password,
        is_testnet=body.is_testnet,
        label=body.label,
    )

    # Also update this user's broker preference (per-user only — never a
    # global os.environ write, which would bleed one user's choice to the
    # signal runner and every other tenant).
    prefs = _get_prefs(user_id)
    prefs["broker_cr"] = broker_id

    # Persist to Supabase
    await _save_credentials_to_db(
        user_id=user_id,
        broker_id=broker_id,
        api_key=body.api_key,
        api_secret=body.api_secret,
        api_password=body.api_password,
        is_testnet=body.is_testnet,
        label=body.label,
    )
    await _save_prefs_to_db(user_id, {"broker_cr": broker_id})

    logger.info(
        "API keys saved",
        extra={
            "action": "settings.keys_saved",
            "broker": broker_id,
            "user_id": user_id,
            "component": "settings",
        },
    )

    # Audit
    from winny_gateway.db import audit_log
    await audit_log(
        user_id=user_id, event_type="credentials", action="api_keys_saved",
        component="settings", broker=broker_id,
    )

    return {
        "ok": True,
        "data": {
            "saved": True,
            "credentials": mask.to_dict(),
            "message": f"API keys saved for {broker_id.title()}. Connection ready.",
        },
    }


@router.get("/api-keys")
async def list_api_keys(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """List all stored API keys for the user (masked — no plaintext)."""
    from winny.brokerage.credentials import credential_store

    user = _effective_user(request, user)
    user_id = user.get("sub", "anon")
    masks = credential_store.get_all_masked(user_id)

    # Also try Supabase if in-memory is empty
    if not masks:
        masks_from_db = await _load_credentials_from_db(user_id)
        if masks_from_db:
            return {"ok": True, "data": {"credentials": masks_from_db, "count": len(masks_from_db)}}

    return {
        "ok": True,
        "data": {
            "credentials": [m.to_dict() for m in masks],
            "count": len(masks),
        },
    }


@router.delete("/api-keys/{broker_id}")
async def delete_api_keys(
    broker_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Delete stored API keys for a specific broker."""
    from winny.brokerage.credentials import credential_store

    user = _effective_user(request, user)
    user_id = user.get("sub", "anon")
    deleted = credential_store.delete(user_id, broker_id)

    # Also delete from Supabase
    await _delete_credentials_from_db(user_id, broker_id)

    if not deleted:
        return {"ok": False, "error": f"No keys found for broker '{broker_id}'."}

    logger.info(
        "API keys deleted",
        extra={
            "action": "settings.keys_deleted",
            "broker": broker_id,
            "user_id": user_id,
            "component": "settings",
        },
    )

    return {
        "ok": True,
        "data": {
            "deleted": True,
            "broker_id": broker_id,
            "message": f"API keys for {broker_id.title()} have been removed.",
        },
    }


# ── Supabase credential persistence ──────────────────────────────────────────


async def _save_credentials_to_db(
    *,
    user_id: str,
    broker_id: str,
    api_key: str,
    api_secret: str,
    api_password: str,
    is_testnet: bool,
    label: str,
) -> None:
    """Encrypt and persist credentials to Supabase."""
    try:
        from winny_gateway.db import get_admin_client
        from winny.brokerage.credentials import _get_fernet

        f = _get_fernet()
        client = get_admin_client()
        client.table("broker_credentials").upsert(
            {
                "user_id": user_id,
                "broker_id": broker_id,
                "api_key_enc": f.encrypt(api_key.encode()).decode(),
                "api_secret_enc": f.encrypt(api_secret.encode()).decode() if api_secret else "",
                "api_password_enc": f.encrypt(api_password.encode()).decode() if api_password else "",
                "is_testnet": is_testnet,
                "label": label or f"{broker_id.title()} API Key",
                "permissions": ["read", "trade"],
                "is_active": True,
            },
            on_conflict="user_id,broker_id",
        ).execute()
    except Exception as e:
        logger.debug("Failed to save credentials to DB: %s", e, extra={"component": "settings"})


async def _load_credentials_from_db(user_id: str) -> list[dict[str, Any]]:
    """Load masked credentials from Supabase."""
    try:
        from winny_gateway.db import get_admin_client
        from winny.brokerage.credentials import _get_fernet, _mask_key

        client = get_admin_client()
        result = (
            client.table("broker_credentials")
            .select("broker_id, api_key_enc, api_secret_enc, api_password_enc, is_testnet, label, permissions")
            .eq("user_id", user_id)
            .eq("is_active", True)
            .execute()
        )
        if not result.data:
            return []

        f = _get_fernet()
        masks: list[dict[str, Any]] = []
        for row in result.data:
            try:
                api_key_plain = f.decrypt(row["api_key_enc"].encode()).decode()
                masks.append({
                    "broker_id": row["broker_id"],
                    "api_key_masked": _mask_key(api_key_plain),
                    "has_secret": bool(row.get("api_secret_enc")),
                    "has_password": bool(row.get("api_password_enc")),
                    "is_testnet": row.get("is_testnet", False),
                    "label": row.get("label", ""),
                    "permissions": row.get("permissions", []),
                })
            except Exception:
                # Key can't be decrypted (different WINNY_CRED_KEY) — skip
                continue
        return masks
    except Exception:
        return []


def _load_decrypted_credentials_from_db(user_id: str, broker_id: str) -> dict[str, str] | None:
    """Load and decrypt one active credential row from Supabase.

    This is used by live broker routes after a deploy/restart, when the
    process-local credential_store may be empty but encrypted credentials still
    exist in Supabase. It requires the same WINNY_CRED_KEY that encrypted the row.
    """
    try:
        from winny_gateway.db import get_admin_client
        from winny.brokerage.credentials import _get_fernet

        client = get_admin_client()
        result = (
            client.table("broker_credentials")
            .select("api_key_enc, api_secret_enc, api_password_enc")
            .eq("user_id", user_id)
            .eq("broker_id", broker_id)
            .eq("is_active", True)
            .maybe_single()
            .execute()
        )
        row = result.data
        if not row or not row.get("api_key_enc"):
            return None

        f = _get_fernet()
        creds: dict[str, str] = {
            "api_key": f.decrypt(row["api_key_enc"].encode()).decode(),
        }
        if row.get("api_secret_enc"):
            creds["api_secret"] = f.decrypt(row["api_secret_enc"].encode()).decode()
        if row.get("api_password_enc"):
            creds["api_password"] = f.decrypt(row["api_password_enc"].encode()).decode()
        return creds
    except Exception as e:
        logger.debug(
            "Failed to decrypt credentials from DB: %s",
            e,
            extra={"component": "settings", "broker": broker_id, "user_id": user_id},
        )
        return None


async def _delete_credentials_from_db(user_id: str, broker_id: str) -> None:
    """Delete credentials from Supabase."""
    try:
        from winny_gateway.db import get_admin_client

        client = get_admin_client()
        client.table("broker_credentials").delete().eq("user_id", user_id).eq("broker_id", broker_id).execute()
    except Exception as e:
        logger.debug("Failed to delete credentials from DB: %s", e, extra={"component": "settings"})
