"""Une base qui refuse ne ressemble plus à une page vide (phase 0.4)."""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

import winny_gateway.db as db


class _Boom:
    def table(self, _name):
        raise RuntimeError("relation \"public.crm_contacts\" does not exist")


def test_select_leve_au_lieu_de_renvoyer_vide(monkeypatch):
    monkeypatch.setattr(db, "get_admin_client", lambda: _Boom())
    with pytest.raises(db.DatabaseError) as e:
        asyncio.run(db.db_select("crm_contacts", filters={"user_id": "u1"}))
    assert e.value.table == "crm_contacts" and e.value.operation == "select"
    assert "does not exist" in e.value.reason


@pytest.mark.parametrize("call", [
    lambda: db.db_insert("crm_contacts", {"name": "x"}),
    lambda: db.db_select("crm_contacts"),
    lambda: db.db_update("crm_contacts", {"name": "x"}, filters={"id": "1"}),
    lambda: db.db_delete("crm_contacts", filters={"id": "1"}),
])
def test_requete_sans_proprietaire_refusee(call):
    with pytest.raises(db.DatabaseError) as e:
        asyncio.run(call())
    assert e.value.reason == "cross_tenant_blocked"


def test_reponse_503_lisible(monkeypatch):
    from winny_gateway.app import create_app
    from winny_gateway.auth import get_current_user
    from winny_gateway import permissions as P

    monkeypatch.setattr(db, "get_admin_client", lambda: _Boom())
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {"sub": "u1", "app_metadata": {"learn_role": "admin"}}
    client = TestClient(app, raise_server_exceptions=False)
    # Le garde des pages métier laisse passer un admin sur le CRM.
    monkeypatch.setattr(P.GRANTS, "_grants", {("admin", "crm", "read")})
    monkeypatch.setattr(P.GRANTS, "_loaded_at", time.monotonic())

    async def fake_user(_request, _creds=None):
        return {"sub": "u1", "app_metadata": {"learn_role": "admin"}}

    monkeypatch.setattr(P, "get_current_user", fake_user)
    r = client.get("/v1/crm/contacts", headers={"Authorization": "Bearer x"})
    assert r.status_code == 503
    body = r.json()
    assert body["ok"] is False and body["error"] == "database_unavailable"
    assert body["detail"]["table"] == "crm_contacts"
