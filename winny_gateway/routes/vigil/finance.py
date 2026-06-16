"""Finance routes — the books/ledger backend the cfo-* skills route into.

Surface (all auth-required, scoped to the caller's user_id via the db
cross-tenant guard):

  GET  /v1/finance/accounts                  → chart of accounts
  POST /v1/finance/accounts                  → add an account
  GET  /v1/finance/transactions              → the ledger (filter by status/category)
  POST /v1/finance/transactions              → capture a transaction
  PATCH/v1/finance/transactions/{id}         → classify / reconcile / edit
  DELETE /v1/finance/transactions/{id}
  GET  /v1/finance/summary                   → P&L-style rollup (income/expense/net,
                                               by category, plus reconcile progress)

This is the data layer; the cfo-* skills supply the methodology (C.L.E.A.R.).
Reports/close packets route on to Studio; jurisdiction/grounding to the Vault.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from winny_gateway.auth import get_current_user
from winny_gateway.db import db_delete, db_insert, db_select, db_update
from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/v1/finance", tags=["finance"])

ACCOUNT_TYPES = {"asset", "liability", "equity", "income", "expense"}
TXN_STATUSES = {"uncategorized", "categorized", "reconciled"}


def _uid(user: dict[str, Any]) -> str:
    uid = user.get("sub")
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no user id in token")
    return str(uid)


# ── Accounts (chart of accounts) ────────────────────────────────────────────
class AccountBody(BaseModel):
    name: str = Field(min_length=1)
    type: str = Field(default="expense")


@router.get("/accounts")
async def list_accounts(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rows = await db_select("finance_accounts", filters={"user_id": _uid(user)}, order_by="name")
    return {"ok": True, "data": {"accounts": rows}}


@router.post("/accounts")
async def create_account(body: AccountBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    if body.type not in ACCOUNT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "bad_type", "type": body.type, "available": sorted(ACCOUNT_TYPES)},
        )
    row = await db_insert(
        "finance_accounts",
        {"user_id": _uid(user), "name": body.name.strip(), "type": body.type},
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": "account_exists_or_write_failed"})
    return {"ok": True, "data": row}


# ── Transactions (the ledger) ───────────────────────────────────────────────
class TxnBody(BaseModel):
    txn_date: str | None = Field(default=None, description="ISO date; defaults to today.")
    description: str = Field(default="")
    amount: float = Field(description="Signed: income positive, expense negative.")
    currency: str = Field(default="USD")
    category: str | None = None
    account_id: str | None = None
    source: str = Field(default="manual")


class TxnPatch(BaseModel):
    description: str | None = None
    amount: float | None = None
    category: str | None = None
    account_id: str | None = None
    status: str | None = None
    txn_date: str | None = None


async def _owned_txn(txn_id: str, uid: str) -> dict[str, Any]:
    rows = await db_select("finance_transactions", filters={"id": txn_id, "user_id": uid}, limit=1)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "transaction_not_found", "transaction_id": txn_id},
        )
    return rows[0]


@router.get("/transactions")
async def list_transactions(
    user: dict = Depends(get_current_user),
    status_filter: str | None = Query(default=None, alias="status"),
    category: str | None = Query(default=None),
    limit: int = Query(default=200, le=1000),
) -> dict[str, Any]:
    filters: dict[str, Any] = {"user_id": _uid(user)}
    if status_filter:
        filters["status"] = status_filter
    if category:
        filters["category"] = category
    rows = await db_select("finance_transactions", filters=filters, order_by="-txn_date", limit=limit)
    return {"ok": True, "data": {"transactions": rows}}


@router.post("/transactions")
async def create_transaction(body: TxnBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    data: dict[str, Any] = {
        "user_id": _uid(user),
        "description": body.description,
        "amount": body.amount,
        "currency": body.currency,
        "source": body.source,
        # capture lands uncategorized unless a category is supplied
        "status": "categorized" if body.category else "uncategorized",
    }
    if body.txn_date:
        data["txn_date"] = body.txn_date
    if body.category:
        data["category"] = body.category
    if body.account_id:
        data["account_id"] = body.account_id
    row = await db_insert("finance_transactions", data)
    if row is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "transaction_write_failed"})
    return {"ok": True, "data": row}


@router.patch("/transactions/{txn_id}")
async def update_transaction(txn_id: str, body: TxnPatch, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    await _owned_txn(txn_id, uid)  # 404s if not owned
    patch = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if "status" in patch and patch["status"] not in TXN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "bad_status", "status": patch["status"], "available": sorted(TXN_STATUSES)},
        )
    # classifying (setting a category) implies at least 'categorized'
    if patch.get("category") and "status" not in patch:
        patch["status"] = "categorized"
    if not patch:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "empty_patch"})
    updated = await db_update("finance_transactions", patch, filters={"id": txn_id, "user_id": uid})
    if not updated:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "transaction_update_failed"})
    return {"ok": True, "data": updated[0]}


@router.delete("/transactions/{txn_id}")
async def delete_transaction(txn_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    await _owned_txn(txn_id, uid)
    await db_delete("finance_transactions", filters={"id": txn_id, "user_id": uid})
    return {"ok": True, "data": {"deleted": txn_id}}


# ── Summary (P&L rollup) ────────────────────────────────────────────────────
@router.get("/summary")
async def summary(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rows = await db_select("finance_transactions", filters={"user_id": _uid(user)}, limit=1000)
    income = 0.0
    expense = 0.0
    by_category: dict[str, float] = {}
    reconciled = 0
    for r in rows:
        amt = float(r.get("amount") or 0)
        if amt >= 0:
            income += amt
        else:
            expense += amt  # negative
        cat = r.get("category") or "uncategorized"
        by_category[cat] = round(by_category.get(cat, 0.0) + amt, 2)
        if r.get("status") == "reconciled":
            reconciled += 1
    n = len(rows)
    return {
        "ok": True,
        "data": {
            "income": round(income, 2),
            "expense": round(expense, 2),
            "net": round(income + expense, 2),
            "by_category": by_category,
            "transaction_count": n,
            "reconciled_count": reconciled,
            "reconcile_progress": round(reconciled / n, 3) if n else 0.0,
        },
    }
