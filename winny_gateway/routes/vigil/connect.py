"""Connector kit routes (Phase 0) — generic connect/sync/disconnect for any
system-of-record provider built on the Connector base.

  GET    /v1/connect/status                       providers + the tenant's connections
  POST   /v1/connect/{provider}/token             store a tenant token (PAT) for a provider
  POST   /v1/connect/{provider}/sync              pull data for a connection
  DELETE /v1/connect/connections/{connection_id}  remove a connection

Per-tenant tokens only (encrypted); platform OAuth app-creds live in env. Importing
this module registers the bundled connectors (GitHub today).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status as http
from pydantic import BaseModel, Field

from winny_gateway.auth import get_current_user
from winny_gateway.integrations import connector
from winny_gateway.integrations import github as _github  # noqa: F401 — registers GitHubConnector
from winny_gateway.integrations import hubspot as _hubspot  # noqa: F401 — registers HubSpotConnector
from winny_gateway.integrations import stripe_conn as _stripe  # noqa: F401 — registers StripeConnector
from winny_gateway.integrations import gmail as _gmail  # noqa: F401 — registers GmailConnector
from winny_gateway.integrations import notion as _notion  # noqa: F401 — registers NotionConnector
from winny_gateway.integrations.connector import ConnectorError
from winny_gateway import db as _db
from winny_gateway.logging import get_logger

logger = get_logger("winny_gw.securite")

router = APIRouter(prefix="/v1/connect", tags=["connect"])


def _uid(user: dict[str, Any]) -> str:
    uid = user.get("sub")
    if not uid:
        raise HTTPException(status_code=http.HTTP_401_UNAUTHORIZED, detail="no user id in token")
    return str(uid)


def _guard(exc: ConnectorError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"error": exc.code, "message": str(exc)})


# Décidé par Azer le 29/09 : Gmail, Notion, HubSpot et GitHub sont ouverts à tous ; Stripe est
# réservé au super_admin — c'est la caisse de la plateforme. Vérifié ici, côté serveur : la
# navigation qui cache la carte n'empêche personne d'appeler l'API.
RESERVES_SUPER_ADMIN = frozenset({"stripe"})


async def _est_super_admin(uid: str) -> bool:
    rows = await _db.db_select("learn_profiles", filters={"id": uid}, columns="role", limit=1, allow_unscoped=True)
    return bool(rows) and rows[0].get("role") == "super_admin"


async def _exiger_si_reserve(uid: str, provider: str | None) -> None:
    if provider in RESERVES_SUPER_ADMIN and not await _est_super_admin(uid):
        logger.warning("Connecteur réservé refusé (%s).", provider,
                       extra={"evenement": "securite.connecteur_reserve", "acteur": uid, "provider": provider})
        raise HTTPException(status_code=http.HTTP_403_FORBIDDEN, detail={
            "error": "connecteur_reserve", "provider": provider,
            "message": "Ce connecteur est réservé à l'administration de la plateforme."})


async def _provider_de_connexion(uid: str, connection_id: str) -> str | None:
    for c in await connector.list_connections(uid):
        if str(c.get("id")) == str(connection_id):
            return c.get("provider")
    return None


@router.get("/status")
async def connect_status(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    data = await connector.status(uid)
    if not await _est_super_admin(uid):
        data = {"providers": [p for p in data["providers"] if p["id"] not in RESERVES_SUPER_ADMIN],
                "connections": [c for c in data["connections"] if c.get("provider") not in RESERVES_SUPER_ADMIN]}
    return {"ok": True, "data": data}


class TokenBody(BaseModel):
    token: str = Field(..., min_length=1)
    account: str | None = Field(default=None, description="Optional account id (e.g. email for IMAP).")


@router.post("/{provider}/token")
async def save_token(provider: str, body: TokenBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    await _exiger_si_reserve(_uid(user), provider)
    try:
        conn = await connector.connect(_uid(user), provider, body.token, body.account)
    except ConnectorError as exc:
        raise _guard(exc)
    return {"ok": True, "data": {"connection": conn}}


class SyncBody(BaseModel):
    connection_id: str = Field(..., min_length=1)


@router.post("/{provider}/sync")
async def sync(provider: str, body: SyncBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    # Le fournisseur de l'URL ne suffit pas : c'est celui de la connexion qui compte.
    await _exiger_si_reserve(uid, await _provider_de_connexion(uid, body.connection_id) or provider)
    try:
        result = await connector.run_sync(_uid(user), body.connection_id)
    except ConnectorError as exc:
        raise _guard(exc)
    return {"ok": True, "data": result}


@router.delete("/connections/{connection_id}")
async def disconnect(connection_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    if not await connector.disconnect(_uid(user), connection_id):
        raise HTTPException(status_code=http.HTTP_404_NOT_FOUND, detail={"error": "connection_not_found"})
    return {"ok": True, "data": {"disconnected": connection_id}}


# ── Outbound write-actions (owner-gated: propose → human approves → execute) ────
class ActionBody(BaseModel):
    connection_id: str = Field(..., min_length=1)
    action: str = Field(..., min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


@router.get("/actions")
async def list_actions(status: str | None = None, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    return {"ok": True, "data": {"actions": await connector.list_actions(_uid(user), status)}}


@router.post("/actions")
async def propose_action(body: ActionBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Queue a pending outbound action (never executes here)."""
    await _exiger_si_reserve(_uid(user), await _provider_de_connexion(_uid(user), body.connection_id))
    try:
        a = await connector.propose_action(_uid(user), body.connection_id, body.action, body.params, requested_by="user")
    except ConnectorError as exc:
        raise _guard(exc)
    return {"ok": True, "data": {"action": a}}


@router.post("/actions/{action_id}/approve")
async def approve_action(action_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Human-in-the-loop: approve → execute the action through its connector."""
    uid = _uid(user)
    en_attente = {str(a.get("id")): a.get("provider") for a in await connector.list_actions(uid)}
    await _exiger_si_reserve(uid, en_attente.get(str(action_id)))
    try:
        a = await connector.approve_action(_uid(user), action_id)
    except ConnectorError as exc:
        raise _guard(exc)
    return {"ok": True, "data": {"action": a}}


@router.post("/actions/{action_id}/reject")
async def reject_action(action_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    try:
        a = await connector.reject_action(_uid(user), action_id)
    except ConnectorError as exc:
        raise _guard(exc)
    return {"ok": True, "data": {"action": a}}
