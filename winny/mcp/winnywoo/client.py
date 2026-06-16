"""HTTP client for the Railway gateway.

A thin synchronous wrapper around httpx — MCP servers are stdio, so we
don't need async. Reads connection info from the environment at import
time so misconfiguration fails loud at server-start, not at first tool
call.

Environment variables (read once at import):
    WW_BACKEND_URL        e.g. "https://winnywoo-production.up.railway.app"
    WW_SERVICE_TOKEN      shared secret matching Railway's WW_SERVICE_TOKEN
    WW_BACKEND_TIMEOUT    request timeout in seconds (default 30)

The client returns parsed JSON for 2xx responses; raises BackendError
for everything else with the gateway's error payload included for
debugging.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class BackendError(RuntimeError):
    """The gateway returned a non-2xx response.

    Carries the HTTP status and the parsed error body so the calling
    tool can surface a helpful message to Hermes.
    """

    def __init__(self, status: int, body: Any, path: str) -> None:
        self.status = status
        self.body = body
        self.path = path
        super().__init__(f"backend {status} on {path}: {body!s:.200}")


class BackendClient:
    """Stateless HTTP client to the WinnyWoo gateway."""

    def __init__(
        self,
        base_url: str | None = None,
        service_token: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("WW_BACKEND_URL", "")).rstrip("/")
        self.service_token = service_token or os.getenv("WW_SERVICE_TOKEN", "")
        self.timeout = float(timeout or os.getenv("WW_BACKEND_TIMEOUT", "30"))
        if not self.base_url:
            raise RuntimeError(
                "WW_BACKEND_URL is unset — mcp-winnywoo cannot reach the gateway."
            )
        if not self.service_token:
            raise RuntimeError(
                "WW_SERVICE_TOKEN is unset — mcp-winnywoo would be unauthorised."
            )
        # Single client instance — connection pooling kicks in across calls.
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={
                "Authorization": f"Bearer {self.service_token}",
                "Accept": "application/json",
                "User-Agent": "mcp-winnywoo/1.0",
            },
        )

    # ── core verbs ─────────────────────────────────────────────────────

    def get(self, path: str, params: dict[str, Any] | None = None,
            scope: dict[str, str] | None = None) -> Any:
        return self._call("GET", path, params=params, scope=scope)

    def post(self, path: str, json_body: dict[str, Any] | None = None,
             scope: dict[str, str] | None = None) -> Any:
        return self._call("POST", path, json_body=json_body, scope=scope)

    def delete(self, path: str, scope: dict[str, str] | None = None) -> Any:
        return self._call("DELETE", path, scope=scope)

    # ── helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _scope_headers(scope: dict[str, str] | None) -> dict[str, str]:
        """Per-request multi-tenant scope: the gateway's effective_user reads
        X-WinnyWoo-User-Id/-Email to act for the chatting user, so an agent
        'show my portfolio' resolves THAT user's broker — not the operator the
        service token maps to. No scope → operator (back-compat)."""
        if not scope:
            return {}
        uid = (scope.get("user_id") or "").strip()
        if not uid:
            return {}
        h = {"X-WinnyWoo-User-Id": uid}
        email = (scope.get("email") or "").strip()
        if email:
            h["X-WinnyWoo-User-Email"] = email
        return h

    def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        scope: dict[str, str] | None = None,
    ) -> Any:
        try:
            resp = self._client.request(
                method, path, params=params, json=json_body,
                headers=self._scope_headers(scope) or None,
            )
        except httpx.HTTPError as e:
            logger.error("backend transport error on %s %s: %s", method, path, e)
            raise BackendError(0, {"transport_error": str(e)}, path) from e
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except json.JSONDecodeError:
                body = resp.text
            raise BackendError(resp.status_code, body, path)
        if not resp.content:
            return None
        try:
            return resp.json()
        except json.JSONDecodeError:
            return resp.text

    def close(self) -> None:
        self._client.close()
