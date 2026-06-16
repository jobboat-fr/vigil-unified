"""Owner-gated environment-variable broker credentials.

Railway / OVH env vars are GLOBAL — they're not per-user. If we let any
authenticated user call broker tools that read `os.getenv("KRAKEN_API_KEY")`
etc., we'd be letting every signed-in user execute trades on the owner's
account. That's the opposite of the spec's single-user model.

This module provides ONE function: `get_env_creds_for(user, broker_id)`.
It returns env-var creds *only* when the caller's email matches the
configured owner for that broker. All other users get None and must use
the per-user credential_store path.

Per-broker owner env vars (set on Railway / OVH .env):
    KRAKEN_KEY_OWNER_EMAIL
    BINANCE_KEY_OWNER_EMAIL
    COINBASE_KEY_OWNER_EMAIL
    OKX_KEY_OWNER_EMAIL
    BYBIT_KEY_OWNER_EMAIL
    GATE_KEY_OWNER_EMAIL

Per-broker credential env vars:
    KRAKEN_API_KEY / KRAKEN_API_SECRET
    BINANCE_API_KEY / BINANCE_API_SECRET
    COINBASE_API_KEY / COINBASE_API_SECRET / COINBASE_API_PASSWORD
    OKX_API_KEY / OKX_API_SECRET / OKX_API_PASSWORD
    BYBIT_API_KEY / BYBIT_API_SECRET
    GATE_API_KEY / GATE_API_SECRET
"""

from __future__ import annotations

import os

# Map broker_id -> (api_key_var, api_secret_var, api_password_var, owner_var)
_BROKER_ENV: dict[str, tuple[str, str, str, str]] = {
    "kraken":   ("KRAKEN_API_KEY",   "KRAKEN_API_SECRET",   "",                     "KRAKEN_KEY_OWNER_EMAIL"),
    "binance":  ("BINANCE_API_KEY",  "BINANCE_API_SECRET",  "",                     "BINANCE_KEY_OWNER_EMAIL"),
    "coinbase": ("COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_API_PASSWORD", "COINBASE_KEY_OWNER_EMAIL"),
    "okx":      ("OKX_API_KEY",      "OKX_API_SECRET",      "OKX_API_PASSWORD",      "OKX_KEY_OWNER_EMAIL"),
    "bybit":    ("BYBIT_API_KEY",    "BYBIT_API_SECRET",    "",                     "BYBIT_KEY_OWNER_EMAIL"),
    "gate":     ("GATE_API_KEY",     "GATE_API_SECRET",     "",                     "GATE_KEY_OWNER_EMAIL"),
}


def get_env_creds_for(user: dict, broker_id: str) -> dict[str, str] | None:
    """Return env-var credentials for ``broker_id`` if the user owns them.

    Args:
        user: the dict from ``get_current_user`` (Supabase JWT payload).
              Must carry an ``email`` claim.
        broker_id: e.g. ``"kraken"``.

    Returns:
        ``{api_key, api_secret, api_password?}`` when:
          1. The broker has an env var mapping, AND
          2. ``<BROKER>_KEY_OWNER_EMAIL`` is set, AND
          3. That value matches the caller's email (case-insensitive), AND
          4. The api_key + api_secret env vars are populated.

        ``None`` otherwise. The caller MUST then fall back to the
        per-user Supabase credential_store path.
    """
    if broker_id not in _BROKER_ENV:
        return None

    key_var, secret_var, pwd_var, owner_var = _BROKER_ENV[broker_id]

    owner_email = (os.getenv(owner_var, "") or "").strip().lower()
    if not owner_email:
        return None  # owner not configured → never use env creds

    user_email = (user.get("email", "") or "").strip().lower()
    if not user_email or user_email != owner_email:
        return None  # caller is not the owner

    api_key = os.getenv(key_var, "").strip()
    api_secret = os.getenv(secret_var, "").strip()
    if not (api_key and api_secret):
        return None  # configured but empty

    creds = {"api_key": api_key, "api_secret": api_secret}
    if pwd_var:
        pwd = os.getenv(pwd_var, "").strip()
        if pwd:
            creds["api_password"] = pwd
    return creds


def is_owner(user: dict, broker_id: str) -> bool:
    """Cheap predicate: does this user own the env-var creds for the broker?"""
    if broker_id not in _BROKER_ENV:
        return False
    _, _, _, owner_var = _BROKER_ENV[broker_id]
    owner_email = (os.getenv(owner_var, "") or "").strip().lower()
    user_email = (user.get("email", "") or "").strip().lower()
    return bool(owner_email) and user_email == owner_email
