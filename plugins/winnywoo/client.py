"""HTTP client for the in-tree WinnyWoo gateway (``winny_gateway``).

Mirrors the env convention of ``winny.mcp.winnywoo.client.BackendClient``
(``WW_BACKEND_URL`` / ``WW_SERVICE_TOKEN`` / ``WW_BACKEND_TIMEOUT``) but is
lenient for local dev:

  * The base URL defaults to the localhost dev port (the gateway binds 8400)
    and also honours ``WINNYWOO_GATEWAY_URL`` for parity with the web client.
  * The service token is OPTIONAL. Public endpoints (e.g. ``/api/v1/market/*``)
    work without it; authed endpoints require either ``WW_SERVICE_TOKEN`` set
    here OR ``WW_ALLOW_DEV_AUTH=true`` on the gateway. Missing auth surfaces as
    a clean tool error rather than an exception at import.

Synchronous httpx is intentional — Hermes tool handlers run synchronously.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

DEFAULT_BASE = "http://127.0.0.1:8400"


class GatewayError(RuntimeError):
    """The gateway returned a non-2xx response (or transport failed)."""

    def __init__(self, status: int, body: Any, path: str) -> None:
        self.status = status
        self.body = body
        self.path = path
        super().__init__(f"gateway {status} on {path}: {body!s:.200}")


def gateway_base_url() -> str:
    return (
        os.getenv("WW_BACKEND_URL")
        or os.getenv("WINNYWOO_GATEWAY_URL")
        or DEFAULT_BASE
    ).rstrip("/")


def _headers(scope: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "hermes-winnywoo-plugin/1.0",
    }
    token = os.getenv("WW_SERVICE_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # Multi-tenant scope: act for the chatting user, not the operator the
    # service token maps to (same headers the gateway's effective_user reads).
    if scope:
        uid = (scope.get("user_id") or "").strip()
        if uid:
            headers["X-WinnyWoo-User-Id"] = uid
            email = (scope.get("email") or "").strip()
            if email:
                headers["X-WinnyWoo-User-Email"] = email
    return headers


def gateway_get(
    path: str,
    params: dict[str, Any] | None = None,
    scope: dict[str, str] | None = None,
) -> Any:
    """GET ``path`` on the gateway; return parsed JSON or raise GatewayError."""
    timeout = float(os.getenv("WW_BACKEND_TIMEOUT", "30"))
    try:
        with httpx.Client(
            base_url=gateway_base_url(), timeout=timeout, headers=_headers(scope)
        ) as client:
            resp = client.get(path, params=params)
    except httpx.HTTPError as exc:
        raise GatewayError(0, {"transport_error": str(exc)}, path) from exc
    if resp.status_code >= 400:
        try:
            body = resp.json()
        except json.JSONDecodeError:
            body = resp.text
        raise GatewayError(resp.status_code, body, path)
    if not resp.content:
        return None
    try:
        return resp.json()
    except json.JSONDecodeError:
        return resp.text


def unwrap(payload: Any) -> Any:
    """Normalize a gateway response to clean data for the agent.

    Two envelopes are peeled:
      1. The gateway's ``{ok, data}`` REST envelope → its ``data`` body.
      2. The MCP tool-result passthrough ``{content: [{type: 'text', text}], isError}``
         that some routes return verbatim from an MCP server → the parsed inner
         JSON (so portfolio/orders read as objects, not nested text blobs).
    """
    if isinstance(payload, dict) and "ok" in payload:
        if payload.get("ok"):
            payload = payload.get("data")
        else:
            return {"error": payload.get("error") or "gateway error", "_raw": payload}
    if isinstance(payload, dict) and isinstance(payload.get("content"), list):
        texts = [
            c.get("text")
            for c in payload["content"]
            if isinstance(c, dict) and c.get("type") == "text" and c.get("text")
        ]
        if texts:
            joined = "\n".join(texts)
            try:
                return json.loads(joined)
            except json.JSONDecodeError:
                return joined
    return payload
