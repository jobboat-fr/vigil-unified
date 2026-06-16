"""LiveKit access-token minting for the live Meeting Room.

The user, invited guests, other users, and external (non-account) guests join a
real-time room via short-lived LiveKit JWTs minted server-side. The AI avatar
(Beyond Presence) joins the same room; Tavus brings its own room (its
conversation_url). Tokens are standard LiveKit JWTs signed HS256 with
LIVEKIT_API_SECRET — no extra SDK needed (PyJWT is already a dependency).

Env: LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_URL.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import jwt


def livekit_configured() -> bool:
    return bool(os.getenv("LIVEKIT_API_KEY") and os.getenv("LIVEKIT_API_SECRET") and os.getenv("LIVEKIT_URL"))


def livekit_url() -> str | None:
    return os.getenv("LIVEKIT_URL")


def mint_access_token(
    *,
    room: str,
    identity: str,
    name: str | None = None,
    can_publish: bool = True,
    ttl_seconds: int = 3 * 60 * 60,
    metadata: str | None = None,
) -> str:
    """Mint a LiveKit join JWT. Raises if LiveKit isn't configured."""
    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")
    if not (api_key and api_secret):
        raise RuntimeError("livekit_not_configured: LIVEKIT_API_KEY/SECRET")
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": api_key,
        "sub": identity,
        "nbf": now,
        "exp": now + int(ttl_seconds),
        "name": name or identity,
        "video": {
            "room": room,
            "roomJoin": True,
            "canPublish": bool(can_publish),
            "canSubscribe": True,
            "canPublishData": True,
        },
    }
    if metadata:
        claims["metadata"] = metadata
    return jwt.encode(claims, api_secret, algorithm="HS256")


def join_payload(*, room: str, identity: str, name: str | None = None, can_publish: bool = True,
                 metadata: str | None = None) -> dict[str, Any]:
    """Everything the client needs to connect to the room."""
    return {
        "token": mint_access_token(room=room, identity=identity, name=name, can_publish=can_publish, metadata=metadata),
        "url": livekit_url(),
        "room": room,
        "identity": identity,
    }


def new_share_token() -> str:
    """Opaque share token for inviting external (non-account) guests."""
    return uuid.uuid4().hex
