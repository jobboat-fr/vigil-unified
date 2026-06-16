"""WinnyWoo onboarding — broker selection, API keys, Coinbase wallet creation.

Two paths:
  1. Experienced trader → pick a broker → enter API key/secret → done
  2. New to crypto → Coinbase auto-wallet via CDP AgentKit → done

Onboarding state is persisted in-memory per user (production → Supabase).
API keys are stored server-side in env or per-user prefs — never returned
to the frontend after being set (write-only for secrets).

Endpoints:
  GET  /api/v1/onboarding/status     — check if user has completed onboarding
  POST /api/v1/onboarding/complete   — submit broker + keys OR request Coinbase wallet
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from winny_gateway.auth import get_current_user
from winny_gateway.logging import get_logger
from winny_gateway.routes.settings import (
    BROKER_IDS,
    SUPPORTED_BROKERS,
    _get_prefs,
    _load_decrypted_credentials_from_db,
    _save_credentials_to_db,
    _save_prefs_to_db,
)
from winny.brokerage.credentials import credential_store
from winny.brokerage.env_creds import get_env_creds_for
from winny.common.sanitise import validate_api_key, validate_broker_id

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])

# ── Onboarding state (Supabase + in-memory cache) ────────────────────────────

_onboarding_state: dict[str, dict[str, Any]] = {}


def _get_state(user_id: str) -> dict[str, Any]:
    if user_id not in _onboarding_state:
        # Try Supabase first
        state_from_db = _load_state_from_db(user_id)
        if state_from_db:
            _onboarding_state[user_id] = state_from_db
        else:
            _onboarding_state[user_id] = {
                "completed": False,
                "experience": None,     # "experienced" | "beginner"
                "broker_cr": None,
                "has_api_keys": False,
                "coinbase_wallet": None,
            }
    return _onboarding_state[user_id]


def _load_state_from_db(user_id: str) -> dict[str, Any] | None:
    """Load onboarding state from Supabase."""
    try:
        from winny_gateway.db import get_admin_client

        client = get_admin_client()
        result = (
            client.table("onboarding_state")
            .select("completed, experience, broker_cr, has_api_keys, coinbase_wallet")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        return result.data if result.data else None
    except Exception:
        return None


def _has_live_credentials(user: dict[str, Any], broker_id: str | None) -> bool:
    """Return true when live credentials are available for the caller."""
    if not broker_id:
        return False
    user_id = user.get("sub", "anon")
    if credential_store.get_decrypted(user_id, broker_id):
        return True
    if _load_decrypted_credentials_from_db(user_id, broker_id):
        return True
    return bool(get_env_creds_for(user, broker_id))


async def _save_state_to_db(user_id: str, state: dict[str, Any]) -> None:
    """Persist onboarding state to Supabase (upsert)."""
    try:
        from winny_gateway.db import get_admin_client

        client = get_admin_client()
        row = {"user_id": user_id, **{k: v for k, v in state.items() if k != "coinbase_wallet"}}
        if state.get("coinbase_wallet"):
            import json
            row["coinbase_wallet"] = json.dumps(state["coinbase_wallet"])
        if state.get("completed"):
            from datetime import UTC, datetime
            row["completed_at"] = datetime.now(UTC).isoformat()
        client.table("onboarding_state").upsert(row, on_conflict="user_id").execute()
    except Exception as e:
        logger.debug("Failed to save onboarding to DB: %s", e, extra={"component": "onboarding"})


# ── Models ────────────────────────────────────────────────────────────────────


class OnboardingComplete(BaseModel):
    """Payload for completing onboarding."""

    experience: str = Field(
        ...,
        pattern="^(experienced|beginner)$",
        description="User experience level: 'experienced' or 'beginner'",
    )
    broker_cr: str = Field(
        default="coinbase",
        max_length=32,
        description="Selected crypto broker ID",
    )
    passphrase: str = Field(
        default="",
        max_length=256,
        description="Legacy/mobile alias for api_password",
    )
    api_key: str = Field(
        default="",
        max_length=512,
        description="Exchange API key (write-only, never returned)",
    )
    api_secret: str = Field(
        default="",
        max_length=512,
        description="Exchange API secret (write-only, never returned)",
    )
    api_password: str = Field(
        default="",
        max_length=256,
        description="Exchange API password/passphrase (OKX, Coinbase — write-only)",
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/status")
async def onboarding_status(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Check if the user has completed WinnyWoo onboarding."""
    user_id = user.get("sub", "anon")
    state = _get_state(user_id)
    prefs = _get_prefs(user_id)
    preferred_broker = prefs.get("broker_cr") if isinstance(prefs, dict) else None
    broker_id = preferred_broker if preferred_broker in BROKER_IDS else state.get("broker_cr")
    has_api_keys = bool(state.get("has_api_keys") or _has_live_credentials(user, broker_id))
    completed = bool(state.get("completed") or (broker_id and has_api_keys))
    experience = state.get("experience") or ("experienced" if broker_id and has_api_keys else None)

    if (
        state.get("broker_cr") != broker_id
        or state.get("has_api_keys") != has_api_keys
        or state.get("completed") != completed
        or state.get("experience") != experience
    ):
        state["broker_cr"] = broker_id
        state["has_api_keys"] = has_api_keys
        state["completed"] = completed
        state["experience"] = experience
        await _save_state_to_db(user_id, state)

    return {
        "ok": True,
        "data": {
            "completed": completed,
            "experience": experience,
            "broker_cr": broker_id,
            "has_api_keys": has_api_keys,
            "has_coinbase_wallet": state["coinbase_wallet"] is not None,
            "brokers": SUPPORTED_BROKERS,
        },
    }


@router.post("/complete")
async def complete_onboarding(
    body: OnboardingComplete,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Complete the WinnyWoo onboarding process.

    For experienced traders:
      - Saves broker preference and API keys
      - Keys are stored server-side, never returned

    For beginners:
      - Sets broker to coinbase
      - Triggers CDP AgentKit wallet creation (if enabled)
      - Wallet address is returned so user can fund it
    """
    user_id = user.get("sub", "anon")
    state = _get_state(user_id)
    prefs = _get_prefs(user_id)

    experience = body.experience.lower()
    state["experience"] = experience

    # ── Path 1: Experienced trader — external broker + API keys ───────────
    if experience == "experienced":
        try:
            broker_id = validate_broker_id(body.broker_cr)
        except ValueError as e:
            return {"ok": False, "error": str(e)}

        # Validate API keys — reject control chars, cap length
        api_password = body.api_password or body.passphrase

        try:
            validate_api_key(body.api_key, "api_key")
            validate_api_key(body.api_secret, "api_secret")
            validate_api_key(api_password, "api_password")
        except ValueError as e:
            return {"ok": False, "error": str(e)}

        if broker_id not in BROKER_IDS:
            return {
                "ok": False,
                "error": f"Unknown broker '{broker_id}'. Supported: {sorted(BROKER_IDS)}",
            }

        # Save broker preference
        state["broker_cr"] = broker_id
        prefs["broker_cr"] = broker_id

        # Save API keys server-side (env vars for this process; production → vault)
        if body.api_key:
            credential_store.save(
                user_id,
                broker_id,
                api_key=body.api_key,
                api_secret=body.api_secret,
                api_password=api_password,
                is_testnet=False,
                label=f"{broker_id.title()} API Key",
            )
            await _save_credentials_to_db(
                user_id=user_id,
                broker_id=broker_id,
                api_key=body.api_key,
                api_secret=body.api_secret,
                api_password=api_password,
                is_testnet=False,
                label=f"{broker_id.title()} API Key",
            )
            state["has_api_keys"] = True
            logger.info(
                "API keys saved for broker",
                extra={
                    "user_id": user_id,
                    "broker": broker_id,
                    "action": "onboarding.keys_saved",
                    "component": "onboarding",
                },
            )

        state["completed"] = True

        # Persist to Supabase
        await _save_prefs_to_db(user_id, {"broker_cr": broker_id})
        await _save_state_to_db(user_id, state)

        logger.info(
            "Onboarding completed (experienced)",
            extra={
                "user_id": user_id,
                "broker": broker_id,
                "action": "onboarding.complete",
                "component": "onboarding",
            },
        )
        return {
            "ok": True,
            "data": {
                "completed": True,
                "experience": "experienced",
                "broker_cr": broker_id,
                "has_api_keys": state["has_api_keys"],
                "message": (
                    f"You're all set! Trading will route through {broker_id.title()}."
                    + (" API keys saved securely." if state["has_api_keys"] else "")
                ),
            },
        }

    # ── Path 2: Beginner — Coinbase CDP wallet creation ───────────────────
    state["broker_cr"] = "coinbase"
    prefs["broker_cr"] = "coinbase"
    await _save_prefs_to_db(user_id, {"broker_cr": "coinbase"})

    wallet_result = await _create_coinbase_wallet(user_id)

    if wallet_result:
        state["coinbase_wallet"] = wallet_result
        state["has_api_keys"] = True  # CDP handles auth
        state["completed"] = True
        await _save_state_to_db(user_id, state)
        logger.info(
            "Onboarding completed (beginner) — wallet created",
            extra={
                "user_id": user_id,
                "broker": "coinbase",
                "wallet": wallet_result.get("address", ""),
                "action": "onboarding.wallet_created",
                "component": "onboarding",
            },
        )
        return {
            "ok": True,
            "data": {
                "completed": True,
                "experience": "beginner",
                "broker_cr": "coinbase",
                "wallet": wallet_result,
                "message": (
                    "Welcome to crypto! Your Coinbase wallet has been created. "
                    "You can fund it and start exploring the markets."
                ),
            },
        }

    # AgentKit not ready — still mark onboarding as complete
    state["completed"] = True
    await _save_state_to_db(user_id, state)
    logger.info(
        "Onboarding completed (beginner) — wallet pending",
        extra={
            "user_id": user_id,
            "broker": "coinbase",
            "action": "onboarding.complete_no_wallet",
            "component": "onboarding",
        },
    )
    return {
        "ok": True,
        "data": {
            "completed": True,
            "experience": "beginner",
            "broker_cr": "coinbase",
            "wallet": None,
            "message": (
                "Welcome! Coinbase is set as your broker. "
                "Wallet creation via CDP AgentKit is being set up — "
                "you'll be notified when your wallet is ready. "
                "In the meantime, you can explore AI analysis and paper trading."
            ),
        },
    }


async def _create_coinbase_wallet(user_id: str) -> dict[str, Any] | None:
    """Attempt to create a Coinbase wallet via CDP AgentKit.

    Returns wallet info dict on success, None if AgentKit isn't ready.
    """
    try:
        from winny.agents.agentkit_client import AgentKitClient

        client = AgentKitClient()
        if not client.is_authenticated:
            logger.info(
                "AgentKit not authenticated — skipping wallet creation",
                extra={"user_id": user_id, "action": "agentkit.skip", "component": "onboarding"},
            )
            return None

        wallet = await client.create_wallet(agent_id=f"user_{user_id}")
        return {
            "wallet_id": wallet.wallet_id,
            "address": wallet.address,
            "network": wallet.network,
        }
    except NotImplementedError:
        logger.info(
            "AgentKit wallet creation not yet implemented — scaffold mode",
            extra={"user_id": user_id, "action": "agentkit.scaffold", "component": "onboarding"},
        )
        return None
    except Exception as e:
        logger.warning(
            "AgentKit wallet creation failed: %s",
            e,
            extra={"user_id": user_id, "action": "agentkit.error", "error": str(e), "component": "onboarding"},
        )
        return None
