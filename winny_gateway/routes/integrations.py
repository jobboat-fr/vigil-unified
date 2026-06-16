"""Integrations surface for the VIGIL frontend.

VIGIL's Integrations page shows what the agent runtime can actually do.
Rather than maintaining a parallel registry, this proxies the Hermes
runtime on OVH — the same MCP servers the WinnyWoo dashboard manages are
what ground the VIGIL assistant, so there is exactly one source of truth.

Endpoints (VIGIL-facing prefix, same dialect as /v1/assistant + /v1/vault):
  GET /v1/integrations/mcp/servers — MCP servers configured on the runtime
  GET /v1/integrations/runtime     — runtime health + model info

Management (add/remove/test servers) intentionally stays in the Hermes
dashboard; the response carries ``manage_url`` so the UI can deep-link.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status

from winny_gateway.auth import get_current_user
from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/v1/integrations", tags=["integrations"])

MANAGE_URL = "https://winnywoo.vigil-ai.xyz"

# 30-second response cache — the MCP config changes rarely and every VIGIL
# Integrations page view shouldn't cost an OVH round-trip.
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL = 30.0


def _cfg_or_503(request: Request) -> Any:
    cfg = request.app.state.config
    if not cfg.hermes_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hermes not configured (set HERMES_URL).",
        )
    return cfg


async def _shim_get(cfg: Any, path: str) -> dict[str, Any]:
    cached = _cache.get(path)
    if cached and (time.monotonic() - cached[0]) < _CACHE_TTL:
        return cached[1]

    url = cfg.hermes_url.rstrip("/") + path
    headers = {"x-hermes-proxy-auth": cfg.hermes_proxy_secret or ""}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except ValueError as exc:
        # Non-JSON body — e.g. an HTML login page when routing misfires.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="runtime returned non-JSON (routing misconfigured?)",
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"runtime returned {exc.response.status_code}",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"runtime unreachable: {exc}",
        ) from exc

    _cache[path] = (time.monotonic(), data)
    return data


@router.get("/mcp/servers")
async def list_runtime_mcp_servers(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """MCP servers wired into the agent runtime (read-only, secrets stripped)."""
    cfg = _cfg_or_503(request)
    data = await _shim_get(cfg, "/mcp/servers")
    return {
        "ok": bool(data.get("ok", True)),
        "data": {
            "servers": data.get("servers", []),
            "count": data.get("count", len(data.get("servers", []))),
            "manage_url": MANAGE_URL,
        },
    }


@router.get("/runtime")
async def runtime_status(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Agent runtime health — model, provider, warm sessions."""
    cfg = _cfg_or_503(request)
    # /health is answered by Caddy itself (plain "ok"); /mcp/runtime is the
    # shim-reachable health alias on the proxy-auth'd lane.
    data = await _shim_get(cfg, "/mcp/runtime")
    return {
        "ok": bool(data.get("ok", False)),
        "data": {
            "service": data.get("service"),
            "model": data.get("model"),
            "provider": data.get("provider"),
            "warm_sessions": data.get("warm_sessions"),
            "manage_url": MANAGE_URL,
        },
    }
