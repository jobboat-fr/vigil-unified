"""Graduation path — dispatch a department job to a pooled Hermes skill (Phase 6).

A department job in the engine can declare `hermes_skill: "<name>"`. When the OVH
Hermes runtime is configured (env below) the engine routes that job to the pooled
skill instead of running its in-gateway handler; on any failure — unconfigured,
unreachable, bad shape — it falls back to the local handler. So graduation is
opt-in and never a regression: a department keeps working even if OVH is down.

The auth chain mirrors web/api/ops.js (the browser-side proxy), but server-side
from the gateway: POST to the OVH dashboard behind its Caddy gate, injecting the
`x-ops-gate` secret plus the dashboard's own ephemeral session token (scraped from
the served HTML exactly as the dashboard SPA reads `window.__HERMES_SESSION_TOKEN__`),
refreshing that token once on a 401.

Required env (server-side, on Railway — NOT VITE_*):
  OPS_DASHBOARD_URL   e.g. https://vigil-ops-57-130-58-222.nip.io
  OPS_GATE_SECRET     shared secret Caddy enforces on that host
  HERMES_SKILL_PATH   optional, the skill-run endpoint (default /api/ops/skill)

The skill MUST return the department-result contract the engine's acceptance
expects: {artifact_id?, summary, metrics:{cost_usd, tool_calls}, handoffs?, ...}.
"""
from __future__ import annotations

import os
import re
from typing import Any

import httpx

from winny_gateway.logging import get_logger

logger = get_logger(__name__)

_TOKEN_RE = re.compile(r"__HERMES_SESSION_TOKEN__\s*=\s*[\"']([^\"']+)[\"']")
_session_token: str | None = None


def _dash() -> str | None:
    return (os.environ.get("OPS_DASHBOARD_URL") or "").rstrip("/") or None


def _gate() -> str | None:
    return os.environ.get("OPS_GATE_SECRET") or None


def available() -> bool:
    """True only when OVH Hermes is configured. Engine falls back to local when False."""
    return bool(_dash() and _gate())


async def _scrape_token(dash: str, gate: str) -> str | None:
    global _session_token
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{dash}/", headers={"x-ops-gate": gate})
        m = _TOKEN_RE.search(r.text)
        _session_token = m.group(1) if m else None
    except httpx.HTTPError as exc:
        logger.info("hermes_dispatch token scrape failed: %s", exc)
        _session_token = None
    return _session_token


async def run_skill(uid: str, skill: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Run a pooled Hermes skill and return its result dict.

    Raises on unavailability/failure so the engine can fall back to the local
    handler — never returns a partial/empty result that could pass acceptance.
    """
    dash, gate = _dash(), _gate()
    if not (dash and gate):
        raise RuntimeError("hermes dispatch not configured")
    path = os.environ.get("HERMES_SKILL_PATH") or "/api/ops/skill"
    url = f"{dash}{path}"
    body = {"skill": skill, "owner": uid, **payload}

    async def _post(tok: str | None) -> httpx.Response:
        async with httpx.AsyncClient(timeout=120) as c:
            return await c.post(url, headers={
                "x-ops-gate": gate,
                "x-hermes-session-token": tok or "",
                "content-type": "application/json",
            }, json=body)

    if _session_token is None:
        await _scrape_token(dash, gate)
    r = await _post(_session_token)
    if r.status_code == 401:                       # token rotates on dashboard restart
        await _scrape_token(dash, gate)
        r = await _post(_session_token)
    if r.status_code >= 400:
        raise RuntimeError(f"hermes skill '{skill}' HTTP {r.status_code}")

    data = r.json()
    result = data.get("result") if isinstance(data, dict) and "result" in data else data
    if not isinstance(result, dict):
        raise RuntimeError(f"hermes skill '{skill}' returned non-dict result")
    return result
