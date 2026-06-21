"""Integration platform keys — resolve / set, with DB-over-env precedence.

A provider key (e.g. PLAID_SECRET) resolves as: the operator's stored, encrypted
value if present, else the gateway env var of the same name (the platform default).
This lets keys be entered from the UI without touching deploy env, while still
honoring env-configured platform credentials. Values are never returned by the API —
only set/unset + where it came from.
"""
from __future__ import annotations

import os
from typing import Any

from winny_gateway.db import db_insert, db_select, db_update
from winny_gateway.integrations.secrets import decrypt_secret, encrypt_secret

_TABLE = "integration_secrets"


async def get_value(uid: str, provider: str, name: str) -> tuple[str | None, str | None]:
    """Returns (value, source) where source is 'stored' | 'env' | None."""
    rows = await db_select(_TABLE, filters={"user_id": uid, "provider": provider, "name": name}, limit=1)
    if rows:
        try:
            return decrypt_secret(rows[0]["value_enc"]), "stored"
        except Exception:  # noqa: BLE001 — fall through to env on a bad/rotated value
            pass
    env_val = os.getenv(name)
    return (env_val, "env") if env_val else (None, None)


async def get_keys(uid: str, provider: str, names: list[str]) -> dict[str, str | None]:
    return {n: (await get_value(uid, provider, n))[0] for n in names}


async def set_keys(uid: str, provider: str, values: dict[str, Any]) -> int:
    """Store/replace provider keys. Empty/None values are skipped (not cleared)."""
    saved = 0
    for name, val in (values or {}).items():
        if val is None or str(val) == "":
            continue
        data = {"value_enc": encrypt_secret(str(val))}
        existing = await db_select(_TABLE, filters={"user_id": uid, "provider": provider, "name": name}, limit=1)
        if existing:
            await db_update(_TABLE, data, filters={"id": existing[0]["id"], "user_id": uid})
        else:
            await db_insert(_TABLE, {"user_id": uid, "provider": provider, "name": name, **data})
        saved += 1
    return saved


async def status(uid: str, provider: str, names: list[str]) -> list[dict[str, Any]]:
    out = []
    for n in names:
        val, src = await get_value(uid, provider, n)
        out.append({"name": n, "set": bool(val), "source": src})
    return out
