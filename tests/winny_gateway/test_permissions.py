"""Droits des pages métier : la passerelle applique learn_capabilities, et rien d'autre.

Hermétique : l'authentification et la table des droits sont remplacées ; les requêtes
traversent la vraie application FastAPI, donc la vraie carte route → action.
"""
from __future__ import annotations

import time

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from winny_gateway import permissions as P

# La grille de la migration LEARN 0039, en abrégé.
GRANTS = {
    ("admin", "room", a) for a in ("read", "create", "update", "delete", "host", "join")
} | {
    ("formateur", "room", a) for a in ("read", "create", "update", "host", "join")
} | {
    ("apprenant", "room", a) for a in ("read", "join")
} | {
    ("auditeur", "room", "read"), ("auditeur", "legal", "read"),
} | {
    ("admin", r, a) for r in ("crm", "mail", "finance", "ops", "legal")
    for a in ("read", "create", "update", "delete")
}

USERS = {
    "tok-admin": "admin",
    "tok-formateur": "formateur",
    "tok-apprenant": "apprenant",
    "tok-auditeur": "auditeur",
    "tok-prospect": "prospect",
    "tok-sans-role": None,
}


@pytest.fixture
def client(monkeypatch):
    async def fake_user(request, credentials=None):
        token = credentials.credentials if credentials else None
        if token not in USERS:
            raise HTTPException(status_code=401, detail="Invalid token")
        meta = {"learn_role": USERS[token]} if USERS[token] else {}
        return {"sub": f"user-{token}", "app_metadata": meta}

    monkeypatch.setattr(P, "get_current_user", fake_user)
    monkeypatch.setattr(P.GRANTS, "_grants", set(GRANTS))
    monkeypatch.setattr(P.GRANTS, "_loaded_at", time.monotonic())

    from winny_gateway.app import create_app

    app = create_app()
    # La dépendance propre aux routes appelle aussi get_current_user : même faux.
    from winny_gateway import auth

    async def route_user(request: Request):
        return await fake_user(request, await auth._bearer(request))

    app.dependency_overrides[auth.get_current_user] = route_user
    return TestClient(app, raise_server_exceptions=False)


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_sans_jeton_401(client):
    assert client.get("/v1/crm/contacts").status_code == 401


@pytest.mark.parametrize("tok", ["tok-formateur", "tok-apprenant", "tok-auditeur", "tok-prospect", "tok-sans-role"])
def test_crm_reserve_aux_admins(client, tok):
    r = client.get("/v1/crm/contacts", headers=_h(tok))
    assert r.status_code == 403
    assert r.json()["detail"]["resource"] == "crm"


def test_admin_passe_le_garde_crm(client):
    assert client.get("/v1/crm/contacts", headers=_h("tok-admin")).status_code != 403


def test_formateur_anime_la_salle(client):
    r = client.post("/v1/rooms/abc/share", headers=_h("tok-formateur"))
    assert r.status_code != 403


def test_apprenant_rejoint_mais_n_anime_pas(client):
    share = client.post("/v1/rooms/abc/share", headers=_h("tok-apprenant"))
    assert share.status_code == 403
    assert share.json()["detail"]["action"] == "host"
    token = client.post("/v1/rooms/abc/livekit-token", headers=_h("tok-apprenant"))
    assert token.status_code != 403


def test_apprenant_ne_cree_pas_de_salle(client):
    r = client.post("/v1/rooms", json={"title": "x"}, headers=_h("tok-apprenant"))
    assert r.status_code == 403
    assert r.json()["detail"]["action"] == "create"


def test_auditeur_lit_le_juridique_sans_ecrire(client):
    assert client.get("/v1/vault/documents", headers=_h("tok-auditeur")).status_code != 403
    r = client.delete("/v1/vault/documents/d1", headers=_h("tok-auditeur"))
    assert r.status_code == 403


def test_invitation_publique_sans_jeton(client):
    # Le garde laisse passer ; la route répond elle-même (404 jeton inconnu, 503 LiveKit…).
    assert client.get("/v1/rooms/meeting/inconnu").status_code not in (401, 403)
    assert client.post("/v1/rooms/guest/inconnu/join", json={}).status_code not in (401, 403)


def test_menu_de_l_app(client):
    r = client.get("/v1/permissions/me", headers=_h("tok-auditeur"))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["role"] == "auditeur"
    assert data["grants"] == {"legal": ["read"], "room": ["read"]}


def test_agent_plafonne_a_admin():
    actor = {"role": "super_admin", "principal": "agent"}
    P.GRANTS._grants = {("admin", "crm", "update")}
    P.GRANTS._loaded_at = time.monotonic()
    assert P.can(actor, "crm", "update")
    assert not P.can({"role": "super_admin", "principal": "agent"}, "crm", "delete")


def test_droits_illisibles_au_demarrage_503(monkeypatch):
    import asyncio

    g = P._Grants()
    monkeypatch.setattr(g, "_fetch", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    with pytest.raises(HTTPException) as e:
        asyncio.run(g.ensure())
    assert e.value.status_code == 503
