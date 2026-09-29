"""Les formules d'accès (décision d'Azer du 29/09).

HBS a tout par contrat (Accord de collaboration, Art. 2.1, 2.5, 2.7) — codé en dur, révocable
pour les agents seulement (Art. 2.6). Un autre organisme a toute la plateforme dès qu'il
détient une formule payante, et les agents qu'il a souscrits. Sans rien de payé : l'offre
gratuite, sans agent et plafonnée. Chaque refus est un 402 qui dit quoi et combien.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from tests.winny_gateway.test_vigil_studio_rooms import FakeDB
from winny_gateway import droits_agents as da
from winny_gateway.auth import get_current_user
from winny_gateway.routes.vigil import projets as projets_mod
from winny_gateway.routes.vigil import studio as studio_mod

TOUS = {"azzmin": True, "azzco": True, "azzcom": True}


@pytest.fixture
def c(monkeypatch):
    db = FakeDB()
    db.tables["learn_profiles"] = [
        {"id": "sa", "role": "super_admin", "tenant_id": None},
        {"id": "hbs_app", "role": "apprenant", "tenant_id": "t_hbs"},
        {"id": "hbs_adm", "role": "admin", "tenant_id": "t_hbs"},
        {"id": "paye", "role": "admin", "tenant_id": "t_paye"},
        {"id": "gratuit", "role": "admin", "tenant_id": "t_gratuit"},
    ]
    db.tables["learn_tenants"] = [
        # HBS sans aucune ligne d'abonnement : le contrat suffit.
        {"id": "t_hbs", "slug": "hbs", "abonnements": []},
        {"id": "t_paye", "slug": "cabinet-x", "abonnements": ["azzcom"]},
        {"id": "t_gratuit", "slug": "ecole-y", "abonnements": []},
    ]
    for mod in (projets_mod, studio_mod, da):
        monkeypatch.setattr(mod, "db_select", db.select)
    for mod in (projets_mod, studio_mod):
        monkeypatch.setattr(mod, "db_insert", db.insert)
        monkeypatch.setattr(mod, "db_update", db.update)
    monkeypatch.setenv("AGENTS_ABONNEMENT_MODE", "enforce")

    async def who(request: Request):
        return {"sub": request.headers["X-Test-User"], "role": "authenticated"}

    app = FastAPI()
    app.include_router(projets_mod.router)
    app.include_router(studio_mod.router)
    app.dependency_overrides[get_current_user] = who
    client = TestClient(app)
    client.db = db  # type: ignore[attr-defined]
    return client


def etat(uid):
    return asyncio.run(da.etat(uid))


def test_hbs_a_tout_par_contrat_pour_tous_ses_comptes(c):
    for uid in ("hbs_app", "hbs_adm"):
        e = etat(uid)
        assert e["formule"] == "contrat_hbs" and e["motif"] == "contrat_hbs"
        assert e["agents"] == TOUS and e["plafonds"] == {}


def test_privilege_agents_hbs_revocable_sans_toucher_au_reste(c, monkeypatch):
    monkeypatch.setenv("CONTRAT_HBS_AGENTS", "revoque")
    e = etat("hbs_adm")
    assert e["formule"] == "contrat_hbs" and e["plafonds"] == {}  # la plateforme reste (Art. 2.2)
    assert e["agents"] == {"azzmin": False, "azzco": False, "azzcom": False}  # retour aux abonnements réels


def test_organisme_payant_toute_la_plateforme_et_ses_agents_seulement(c):
    e = etat("paye")
    assert e["formule"] == "payant" and e["plafonds"] == {}
    assert e["agents"] == {"azzmin": False, "azzco": False, "azzcom": True}


def test_organisme_gratuit_sans_agent_et_plafonne(c):
    e = etat("gratuit")
    assert e["formule"] == "gratuit" and not any(e["agents"].values())
    assert e["plafonds"] == da.PLAFONDS_GRATUITS


def test_super_admin_sans_plafond(c):
    e = etat("sa")
    assert e["formule"] == "super_admin" and e["agents"] == TOUS and e["plafonds"] == {}


def test_offre_gratuite_un_projet_puis_402_explicite(c):
    h = {"X-Test-User": "gratuit"}
    assert c.post("/v1/projets", json={"titre": "Premier"}, headers=h).status_code == 200
    r = c.post("/v1/projets", json={"titre": "Second"}, headers=h)
    assert r.status_code == 402
    d = r.json()["detail"]
    assert d["error"] == "plafond_offre_gratuite" and d["ressource"] == "projets" and d["limite"] == 1
    assert "formule payante" in d["message"]
    assert len(c.db.tables["studio_projects"]) == 1


def test_offre_gratuite_documents_vierges_plafonnes(c):
    h = {"X-Test-User": "gratuit"}
    for i in range(da.PLAFONDS_GRATUITS["artefacts"]):
        assert c.post("/v1/artifacts/blank-canvas", json={"title": f"T{i}"}, headers=h).status_code == 200
    r = c.post("/v1/artifacts/blank-canvas", json={"title": "de trop"}, headers=h)
    assert r.status_code == 402 and r.json()["detail"]["ressource"] == "artefacts"


@pytest.mark.parametrize("uid", ["hbs_app", "paye", "sa"])
def test_formules_payantes_sans_plafond(c, uid):
    h = {"X-Test-User": uid}
    for i in range(3):
        assert c.post("/v1/projets", json={"titre": f"P{i}"}, headers=h).status_code == 200
    for i in range(da.PLAFONDS_GRATUITS["artefacts"] + 1):
        assert c.post("/v1/artifacts/blank-canvas", json={"title": f"T{i}"}, headers=h).status_code == 200


def test_agent_non_souscrit_refuse_meme_pour_un_payant(c):
    """Payer AZZCOM n'ouvre pas AZZCO : les agents se souscrivent un par un."""
    from fastapi import HTTPException
    asyncio.run(da.verifier("paye", "azzcom"))
    with pytest.raises(HTTPException) as refus:
        asyncio.run(da.verifier("paye", "studio"))
    assert refus.value.status_code == 402 and refus.value.detail["agent"] == "azzco"
