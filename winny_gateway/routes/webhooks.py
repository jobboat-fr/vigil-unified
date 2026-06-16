"""External webhook receivers — Coinbase CDP today, extensible.

Coinbase Developer Platform posts JSON events to a Target URL we configure
in the CDP dashboard. Each request is signed with HMAC-SHA256 over the raw
body using a shared webhook secret shown once at webhook creation time.

Flow:
  1) CDP/Coinbase POSTs to /api/v1/webhooks/coinbase
  2) We verify the signature (constant-time) against `COINBASE_WEBHOOK_SECRET`
  3) We publish the event to the gateway EventBus
  4) Every WS client gets `{type: "coinbase_event", event_type, data}` live
  5) We return 200 fast so Coinbase doesn't retry-storm us

If the secret env var is empty we accept the payload but log a warning —
useful for first-curl testing before locking it down.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


def _is_production() -> bool:
    """True on any prod-shaped deployment.

    Don't rely on WINNY_ENV alone — it's easy to forget to set. Any Railway
    environment marker (the gateway's actual host) also counts as production,
    so an unset WINNY_ENV can't silently downgrade us to the fail-open path.
    """
    if os.getenv("WINNY_ENV", os.getenv("ENV", "")).strip().lower() in ("production", "prod"):
        return True
    return any(
        os.getenv(k)
        for k in ("RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME",
                  "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID")
    )


# Explicit opt-in to accept UNVERIFIED webhooks (local dev only). Default off.
def _allow_unverified_webhooks() -> bool:
    return os.getenv("WINNY_ALLOW_UNVERIFIED_WEBHOOKS", "").strip().lower() in ("1", "true", "yes")

# Header names Coinbase has shipped over the years. Accept all; pick the first present.
_SIG_HEADERS = (
    "x-cc-webhook-signature",       # Coinbase Commerce
    "x-coinbase-signature",         # CDP / Onchain
    "x-cb-signature",               # legacy
    "x-webhook-signature",          # generic
)


def _verify_signature(raw_body: bytes, header_sig: str | None, secret: str) -> bool:
    """Constant-time HMAC-SHA256 verification against the raw body."""
    if not header_sig:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    # Coinbase may send the digest as hex, or as base64; we compare both.
    if hmac.compare_digest(expected, header_sig.strip()):
        return True
    # also tolerate the `sha256=...` prefix some webhook frameworks emit
    return header_sig.startswith("sha256=") and hmac.compare_digest(expected, header_sig[7:].strip())


@router.post("/coinbase", status_code=status.HTTP_200_OK)
async def coinbase_webhook(request: Request) -> dict[str, Any]:
    """Receive a Coinbase CDP webhook event.

    No auth dependency — Coinbase has no JWT. Authenticity comes from the
    HMAC signature header. Returns 200 fast so the platform doesn't retry.
    """
    raw_body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    sig = next((headers[h] for h in _SIG_HEADERS if h in headers), None)

    secret = os.getenv("COINBASE_WEBHOOK_SECRET", "")
    if secret:
        if not _verify_signature(raw_body, sig, secret):
            logger.warning("Rejected Coinbase webhook: bad signature (sig=%s)", (sig or "")[:24])
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bad_signature")
    elif _allow_unverified_webhooks() and not _is_production():
        # Explicit local-dev opt-in only.
        logger.warning(
            "COINBASE_WEBHOOK_SECRET not set — accepting webhook UNVERIFIED "
            "(%d bytes) because WINNY_ALLOW_UNVERIFIED_WEBHOOKS is set (dev only)",
            len(raw_body),
        )
    else:
        # Fail closed (F12): without a secret we can't authenticate the sender,
        # so an unverified payload could spoof transaction/payment events to
        # dashboard WS clients. Refuse unless explicitly opted-in for dev.
        logger.error(
            "COINBASE_WEBHOOK_SECRET unset — rejecting unverified webhook "
            "(set the secret, or WINNY_ALLOW_UNVERIFIED_WEBHOOKS=1 for local dev)"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="webhook_secret_not_configured",
        )

    # Parse JSON. Coinbase always sends JSON; if it doesn't, return 200 to drop.
    try:
        payload = await request.json()
    except Exception:
        logger.warning("Coinbase webhook body was not JSON; dropping")
        return {"ok": True, "ignored": "non_json"}

    # Best-effort envelope extraction. CDP shape varies by event type — common
    # fields are `event_type`, `type`, `data`, `eventType`. We pass through.
    event_type = (
        payload.get("event_type")
        or payload.get("eventType")
        or payload.get("type")
        or "unknown"
    )

    bus = request.app.state.event_bus
    bus.publish({
        "type": "coinbase_event",
        "event_type": event_type,
        "data": payload,
    })

    # Also surface a human-readable agent_message so the dashboard chat feed shows it.
    summary = _summarize(event_type, payload)
    if summary:
        bus.publish({
            "type": "agent_message",
            "agent": "coinbase",
            "text": summary,
        })

    logger.info("Coinbase webhook accepted: event_type=%s", event_type)
    return {"ok": True, "event_type": event_type}


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _summarize(event_type: str, payload: dict[str, Any]) -> str:
    """One-line human summary for the agent feed.

    Keeps the noise low — only fires for the event types worth surfacing.
    """
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return ""

    et = event_type.lower()

    if "transaction" in et or "transfer" in et:
        amount = data.get("amount") or data.get("value") or "?"
        currency = data.get("currency") or data.get("asset") or ""
        direction = data.get("direction") or data.get("type") or "tx"
        return f"{direction.upper()} {amount} {currency}".strip()

    if "wallet" in et:
        addr = data.get("address") or data.get("wallet_address") or ""
        return f"wallet event {et} {addr[:10]}…" if addr else f"wallet event {et}"

    if "payment" in et:
        status_str = data.get("status") or "?"
        amount = data.get("amount") or ""
        currency = data.get("currency") or ""
        return f"payment {status_str} {amount} {currency}".strip()

    return f"event: {event_type}"
