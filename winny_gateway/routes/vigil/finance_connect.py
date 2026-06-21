"""Finance connector routes — connect a bank (Plaid) or accounting platform and
sync its transactions into the ledger.

  GET    /v1/finance/connect/status            providers + key status + connections
  POST   /v1/finance/connect/link-token        init Plaid Link (browser connect flow)
  POST   /v1/finance/connect/sandbox           sandbox one-shot connect (no Link)
  POST   /v1/finance/connect/exchange          exchange a Link public_token
  POST   /v1/finance/connect/sync              pull accounts + transactions
  DELETE /v1/finance/connect/connections/{id}  remove a connection

Platform keys (PLAID_CLIENT_ID/PLAID_SECRET/PLAID_ENV) come from gateway env and
are surfaced — set/unset only, never values — by /status for keys management. The
per-user access token is stored encrypted and never returned.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status as http
from pydantic import BaseModel, Field

from winny_gateway.auth import get_current_user
from winny_gateway.integrations import finance_connect
from winny_gateway.integrations.plaid_client import PlaidError, create_link_token

router = APIRouter(prefix="/v1/finance/connect", tags=["finance"])


def _uid(user: dict[str, Any]) -> str:
    uid = user.get("sub")
    if not uid:
        raise HTTPException(status_code=http.HTTP_401_UNAUTHORIZED, detail="no user id in token")
    return str(uid)


def _plaid_guard(exc: PlaidError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"error": exc.code, "message": str(exc)})


@router.get("/status")
async def connect_status(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    return {"ok": True, "data": await finance_connect.status(_uid(user))}


@router.post("/link-token")
async def link_token(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    try:
        data = await create_link_token(_uid(user))
    except PlaidError as exc:
        raise _plaid_guard(exc)
    return {"ok": True, "data": {"link_token": data.get("link_token"), "expiration": data.get("expiration")}}


@router.post("/sandbox")
async def sandbox_connect(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    try:
        conn = await finance_connect.connect_sandbox(_uid(user))
    except PlaidError as exc:
        raise _plaid_guard(exc)
    return {"ok": True, "data": {"connection": conn}}


class ExchangeBody(BaseModel):
    public_token: str = Field(..., min_length=1)
    institution: str | None = None


@router.post("/exchange")
async def exchange(body: ExchangeBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    try:
        conn = await finance_connect.connect_exchange(_uid(user), body.public_token, body.institution)
    except PlaidError as exc:
        raise _plaid_guard(exc)
    return {"ok": True, "data": {"connection": conn}}


class SyncBody(BaseModel):
    connection_id: str | None = None


@router.post("/sync")
async def sync(body: SyncBody | None = None, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    body = body or SyncBody()
    try:
        result = await finance_connect.sync(_uid(user), body.connection_id)
    except PlaidError as exc:
        raise _plaid_guard(exc)
    return {"ok": True, "data": result}


@router.delete("/connections/{connection_id}")
async def disconnect(connection_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    ok = await finance_connect.disconnect(_uid(user), connection_id)
    if not ok:
        raise HTTPException(status_code=http.HTTP_404_NOT_FOUND, detail={"error": "connection_not_found"})
    return {"ok": True, "data": {"disconnected": connection_id}}
