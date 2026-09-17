"""Mon compte (RGPD) et support."""
from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from tests.winny_gateway.test_vigil_studio_rooms import FakeDB
from winny_gateway.auth import get_current_user
from winny_gateway.routes import compte_support as cs


class FakeAdmin:
    def __init__(self):
        self.appels = []
        outer = self

        class Auth:
            class admin:  # noqa: N801
                @staticmethod
                def update_user_by_id(uid, attrs):
                    outer.appels.append(("update_user", uid, attrs))

        self.auth = Auth()

    def rpc(self, nom, params):
        outer = self

        class R:
            def execute(self_inner):
                outer.appels.append((nom, params["p_user"]))
                data = {"profil": "pseudonymise", "conserve": ["emargements"]} if nom == "learn_effacer_profil" else {"profil": {"id": params["p_user"]}}
                return type("D", (), {"data": data})()

        return R()


@pytest.fixture
def c(monkeypatch):
    db = FakeDB()
    db.tables["learn_profiles"] = [
        {"id": "app", "role": "apprenant", "tenant_id": "t1", "email": "a@x.fr", "full_name": "Nadia"},
        {"id": "adm", "role": "admin", "tenant_id": "t1", "email": "d@x.fr", "full_name": "Marie"},
        {"id": "adm2", "role": "admin", "tenant_id": "t2", "email": "o@x.fr", "full_name": "Oscar"},
        {"id": "sa", "role": "super_admin", "tenant_id": None, "email": "e@x.fr", "full_name": "Éditeur"},
    ]
    admin = FakeAdmin()
    for n in ("db_select", "db_insert", "db_update", "db_delete"):
        monkeypatch.setattr(cs, n, getattr(db, n.split("_")[1]))

    async def faux_audit(**kw):
        db.tables.setdefault("audit", []).append(kw)

    monkeypatch.setattr(cs, "audit_log", faux_audit)
    monkeypatch.setattr(cs, "get_admin_client", lambda: admin)
    monkeypatch.setattr(cs, "_fenetres", cs.defaultdict(cs.deque))
    app = FastAPI()
    app.include_router(cs.router)

    async def who(request: Request):
        u = request.headers.get("X-Test-User")
        return {"sub": u} if u else {"sub": "op", "service_token": True}

    app.dependency_overrides[get_current_user] = who
    client = TestClient(app)
    client.db, client.admin = db, admin  # type: ignore[attr-defined]
    return client


def h(u):
    return {"X-Test-User": u}


def test_export_contient_la_plateforme_et_l_espace(c):
    d = c.post("/api/v1/compte/export", headers=h("app")).json()["data"]
    assert d["plateforme"]["profil"]["id"] == "app" and "artifacts" in d["espace_de_travail"]


def test_suppression_exige_la_confirmation(c):
    r = c.post("/api/v1/compte/suppression", json={"confirmation": "oui"}, headers=h("app"))
    assert r.status_code == 422 and not c.admin.appels


def test_suppression_pseudonymise_et_neutralise(c):
    c.db.tables["artifacts"] = [{"id": "a1", "user_id": "app"}, {"id": "a2", "user_id": "adm"}]
    r = c.post("/api/v1/compte/suppression", json={"confirmation": "supprimer"}, headers=h("app"))
    assert r.status_code == 200 and r.json()["data"]["supprime"] is True
    assert ("learn_effacer_profil", "app") in c.admin.appels
    upd = next(a for a in c.admin.appels if a[0] == "update_user")
    assert upd[1] == "app" and upd[2]["ban_duration"] and upd[2]["email"].endswith("@supprime.invalid")
    assert [a["id"] for a in c.db.tables["artifacts"]] == ["a2"]
    assert c.db.tables["audit"][0]["user_id"] is None  # la trace ne garde pas l'identifiant en clair


def test_editeur_et_machines_ne_s_effacent_pas(c):
    assert c.post("/api/v1/compte/suppression", json={"confirmation": "SUPPRIMER"}, headers=h("sa")).status_code == 409
    assert c.post("/api/v1/compte/suppression", json={"confirmation": "SUPPRIMER"}).status_code == 403


def test_contact_public_piege_et_limite(c):
    ok = {"nom": "Léa", "email": "lea@ex.fr", "sujet": "Question", "message": "Bonjour, une question sur la formation."}
    assert c.post("/api/v1/support/public", json={**ok, "site_web": "http://spam"}).json()["data"]["recu"]
    assert "support_tickets" not in c.db.tables
    for _ in range(5):
        assert c.post("/api/v1/support/public", json=ok).status_code == 200
    assert c.post("/api/v1/support/public", json=ok).status_code == 429
    assert len(c.db.tables["support_tickets"]) == 5 and c.db.tables["support_tickets"][0]["user_id"] is None


def test_boite_cloisonnee_par_organisme(c):
    ref = c.post("/api/v1/support/demande", json={"sujet": "Accès", "message": "Je ne vois pas mon planning."}, headers=h("app")).json()["data"]
    assert c.db.tables["support_tickets"][0]["tenant_id"] == "t1"
    assert len(c.get("/api/v1/support/boite", headers=h("adm")).json()["data"]["demandes"]) == 1
    assert c.get("/api/v1/support/boite", headers=h("adm2")).json()["data"]["demandes"] == []
    assert c.get("/api/v1/support/boite", headers=h("app")).status_code == 403
    assert c.post(f"/api/v1/support/boite/{ref['id']}/reponse", json={"message": "C'est corrigé."}, headers=h("adm2")).status_code == 404
    assert c.post(f"/api/v1/support/boite/{ref['id']}/reponse", json={"message": "C'est corrigé."}, headers=h("adm")).status_code == 200
    assert c.db.tables["support_tickets"][0]["status"] == "answered"
    assert len(c.get("/api/v1/support/boite", headers=h("sa")).json()["data"]["demandes"]) == 1
