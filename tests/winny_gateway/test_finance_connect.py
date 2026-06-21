"""Tests for the finance connector (Plaid bank-account-via-API + provider registry).

Hermetic: the Plaid HTTP client is monkeypatched with sandbox-like payloads and the
DB is an in-memory fake, so the connect → store(encrypted) → sync(→ ledger) loop is
proven without network or real keys. Encryption uses the real Fernet (ephemeral key).
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

import winny_gateway.db as db_mod
from winny_gateway.integrations import finance_connect as fc
from winny_gateway.integrations import plaid_client as plaid


class FakeDB:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}

    def _t(self, n): return self.tables.setdefault(n, [])

    @staticmethod
    def _m(r, f): return all(r.get(k) == v for k, v in (f or {}).items())

    async def insert(self, table, data, **_k):
        row = dict(data); row.setdefault("id", str(uuid.uuid4()))
        self._t(table).append(row); return dict(row)

    async def select(self, table, *, filters=None, limit=None, order_by=None, **_k):
        rows = [dict(r) for r in self._t(table) if self._m(r, filters)]
        return rows[:limit] if limit else rows

    async def update(self, table, data, *, filters, **_k):
        out = []
        for r in self._t(table):
            if self._m(r, filters):
                r.update(data); out.append(dict(r))
        return out

    async def delete(self, table, *, filters, **_k):
        self.tables[table] = [r for r in self._t(table) if not self._m(r, filters)]
        return True


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    for mod in (fc, db_mod):
        monkeypatch.setattr(mod, "db_insert", fake.insert, raising=False)
        monkeypatch.setattr(mod, "db_select", fake.select, raising=False)
        monkeypatch.setattr(mod, "db_update", fake.update, raising=False)
        monkeypatch.setattr(mod, "db_delete", fake.delete, raising=False)
    return fake


def _wire_plaid_sandbox(monkeypatch):
    monkeypatch.setattr(plaid, "configured", lambda: True)
    monkeypatch.setattr(plaid, "env", lambda: "sandbox")

    async def sandbox_public_token(*_a, **_k): return {"public_token": "public-sandbox-xyz"}
    async def exchange(_pt): return {"access_token": "access-sandbox-abc", "item_id": "item-1"}
    async def inst(_at): return "First Platypus Bank"
    async def accounts(_at): return [{"account_id": "acc-1", "mask": "0000", "type": "depository"}]

    calls = {"n": 0}

    async def txns(_at, _cursor=None):
        # First call returns one txn; subsequent calls return none (idempotency check).
        calls["n"] += 1
        if calls["n"] > 1:
            return {"added": [], "modified": [], "removed": [], "next_cursor": "c2"}
        return {"added": [{
            "transaction_id": "txn-1", "account_id": "acc-1", "name": "AWS",
            "merchant_name": "Amazon Web Services", "amount": 42.50,
            "iso_currency_code": "USD", "date": "2026-06-20",
            "personal_finance_category": {"primary": "SOFTWARE"},
        }], "modified": [], "removed": [], "next_cursor": "c1"}

    monkeypatch.setattr(plaid, "sandbox_public_token", sandbox_public_token)
    monkeypatch.setattr(plaid, "exchange_public_token", exchange)
    monkeypatch.setattr(plaid, "institution_name", inst)
    monkeypatch.setattr(plaid, "accounts_get", accounts)
    monkeypatch.setattr(plaid, "transactions_sync", txns)


def test_status_surfaces_provider_keys(db):
    data = asyncio.run(fc.status("user-1"))
    plaid_p = next(p for p in data["providers"] if p["id"] == "plaid")
    assert plaid_p["kind"] == "bank" and plaid_p["implemented"] is True
    names = {k["name"] for k in plaid_p["required_keys"]}
    assert {"PLAID_CLIENT_ID", "PLAID_SECRET", "PLAID_ENV"} <= names
    assert data["connections"] == []
    # accounting providers are registered but not yet implemented
    assert any(p["id"] == "quickbooks" and not p["implemented"] for p in data["providers"])


def test_sandbox_connect_stores_encrypted_token(db, monkeypatch):
    _wire_plaid_sandbox(monkeypatch)
    conn = asyncio.run(fc.connect_sandbox("user-1"))
    assert conn["provider"] == "plaid"
    assert conn["institution"] == "First Platypus Bank"
    assert conn["token_masked"].startswith("acce")  # masked, not plaintext
    stored = db.tables["finance_connections"][0]
    assert stored["access_token_enc"] != "access-sandbox-abc"  # encrypted at rest


def test_sync_maps_transactions_into_ledger_idempotently(db, monkeypatch):
    _wire_plaid_sandbox(monkeypatch)
    asyncio.run(fc.connect_sandbox("user-1"))

    first = asyncio.run(fc.sync("user-1"))
    assert first["accounts"] == 1 and first["transactions_added"] == 1
    txns = db.tables["finance_transactions"]
    assert len(txns) == 1
    t = txns[0]
    assert t["amount"] == -42.50          # Plaid outflow → negative (expense)
    assert t["source"] == "bank"
    assert t["account_id"]                # linked to a finance_account
    assert t["metadata"]["plaid_txn_id"] == "txn-1"
    assert db.tables["finance_accounts"][0]["name"] == "First Platypus Bank ••0000"

    second = asyncio.run(fc.sync("user-1"))
    assert second["transactions_added"] == 0   # idempotent — already imported


def test_disconnect_removes_connection(db, monkeypatch):
    _wire_plaid_sandbox(monkeypatch)
    conn = asyncio.run(fc.connect_sandbox("user-1"))
    assert asyncio.run(fc.disconnect("user-1", conn["id"])) is True
    assert db.tables["finance_connections"] == []
