"""Le verrou d'abonnement des surfaces agentiques (décision d'Azer du 29/09).

Chaque surface qui fait travailler un modèle s'ouvre si l'organisme est abonné à l'agent qui la
porte — salle → AZZMIN, Studio et conseil → AZZCO, assistant → l'un des trois — ou pour le
super_admin. En `observe` rien n'est bloqué ; en `enforce` le refus est un 402 qui nomme l'agent.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from tests.winny_gateway.test_vigil_studio_rooms import FakeDB
from winny_gateway import assistant_vtlvs as av
from winny_gateway import droits_agents as da
from winny_gateway.auth import get_current_user
from winny_gateway.routes import agents_identite as ident_mod
from winny_gateway.routes.vigil import council as council_mod
from winny_gateway.routes.vigil import rooms as rooms_mod
from winny_gateway.routes.vigil import studio as studio_mod

NOW = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    d.tables["learn_profiles"] = [
        {"id": "sa", "role": "super_admin", "tenant_id": "t0"},
        {"id": "adm_min", "role": "admin", "tenant_id": "t_min"},
        {"id": "adm_rien", "role": "admin", "tenant_id": "t_rien"},
        {"id": "form_co", "role": "formateur", "tenant_id": "t_co"},
        {"id": "app_rien", "role": "apprenant", "tenant_id": "t_rien"},
        {"id": "app_min", "role": "apprenant", "tenant_id": "t_min"},
    ]
    d.tables["learn_tenants"] = [
        {"id": "t0", "abonnements": []},
        {"id": "t_min", "abonnements": ["vtlvs", "azzmin"]},
        {"id": "t_co", "abonnements": ["azzco"]},
        {"id": "t_rien", "abonnements": []},
    ]
    # L'apprenant sans abonnement est EN créneau : depuis le 29/09, ça ne suffit plus.
    d.tables["learn_enrollments"] = [{"apprenant_id": "app_rien", "status": "inscrit", "session_id": "s1"}]
    d.tables["learn_session_slots"] = [{"id": "c1", "session_id": "s1", "status": "planned",
                                        "starts_at": (NOW - timedelta(hours=1)).isoformat(),
                                        "ends_at": (NOW + timedelta(hours=2)).isoformat()}]
    monkeypatch.setattr(da, "db_select", d.select)
    monkeypatch.setattr(av, "db_select", d.select)
    return d


@pytest.fixture
def enforce(monkeypatch):
    monkeypatch.setenv("AGENTS_ABONNEMENT_MODE", "enforce")


# ── La règle ────────────────────────────────────────────────────────────────

def test_super_admin_toujours_ouvert(db):
    assert run(da.etat("sa"))["agents"] == {"azzmin": True, "azzco": True, "azzcom": True}


def test_organisme_abonne_a_un_seul_agent(db):
    e = run(da.etat("adm_min"))
    assert e["agents"] == {"azzmin": True, "azzco": False, "azzcom": False}
    assert e["motif"] == "abonnement_organisme"


def test_sans_abonnement_rien(db):
    assert not any(run(da.etat("adm_rien"))["agents"].values())


def test_compte_vigil_garde_sa_regle(db):
    """Sans ligne learn_profiles : c'est un compte vigil-ai.xyz, jugé sur son abonnement Stripe."""
    assert not any(run(da.etat("vigil_u"))["agents"].values())
    db.tables["org_members"] = [{"user_id": "vigil_u", "org_id": "o1"}]
    db.tables["subscriptions"] = [{"org_id": "o1", "status": "active", "current_period_end": None}]
    e = run(da.etat("vigil_u"))
    assert e["compte"] == "vigil" and all(e["agents"].values())


@pytest.mark.parametrize("uid,surface,ouvert", [
    ("adm_min", "salle", True), ("adm_min", "studio", False), ("adm_min", "conseil", False),
    ("form_co", "salle", False), ("form_co", "studio", True), ("form_co", "conseil", True),
    ("adm_min", "assistant", True), ("form_co", "assistant", True), ("adm_rien", "assistant", False),
    ("adm_min", "azzmin", True), ("adm_min", "azzcom", False), ("sa", "azzcom", True),
])
def test_surfaces(db, enforce, uid, surface, ouvert):
    if ouvert:
        run(da.verifier(uid, surface))
    else:
        with pytest.raises(HTTPException) as e:
            run(da.verifier(uid, surface))
        assert e.value.status_code == 402 and e.value.detail["error"] == "abonnement_requis"
        assert e.value.detail["surface"] == surface


# ── Les modes ───────────────────────────────────────────────────────────────

def test_observe_laisse_passer(db, monkeypatch):
    monkeypatch.delenv("AGENTS_ABONNEMENT_MODE", raising=False)
    assert da.mode() == "observe"
    run(da.verifier("adm_rien", "salle"))  # ne lève pas


def test_mode_inconnu_ferme(monkeypatch):
    monkeypatch.setenv("AGENTS_ABONNEMENT_MODE", "enforse")
    assert da.mode() == "enforce"


def test_base_injoignable_ferme_en_enforce_et_laisse_en_observe(monkeypatch, enforce):
    async def panne(*_a, **_kw):
        raise RuntimeError("base injoignable")
    monkeypatch.setattr(da, "db_select", panne)
    with pytest.raises(HTTPException) as e:
        run(da.verifier("x", "salle"))
    assert e.value.status_code == 503
    monkeypatch.setenv("AGENTS_ABONNEMENT_MODE", "observe")
    run(da.verifier("x", "salle"))


# ── L'assistant ─────────────────────────────────────────────────────────────

def test_assistant_enforce_apprenant_en_creneau_sans_abonnement_refuse(db, enforce):
    with pytest.raises(av.AccesRefuse) as e:
        run(av.verifier_acces("app_rien", NOW))
    assert e.value.statut == 402 and e.value.code == "abonnement_requis"


def test_assistant_enforce_staff_sans_abonnement_refuse(db, enforce):
    with pytest.raises(av.AccesRefuse):
        run(av.verifier_acces("adm_rien", NOW))


def test_assistant_enforce_abonne_ouvert(db, enforce):
    assert run(av.verifier_acces("app_min", NOW))["motif"] == "abonnement"
    assert run(av.verifier_acces("sa", NOW))["motif"] == "role"


def test_assistant_observe_garde_l_ancienne_regle(db):
    assert run(av.verifier_acces("app_rien", NOW))["motif"] == "creneau"
    assert run(av.verifier_acces("adm_rien", NOW))["motif"] == "role"


# ── Les routes réelles ──────────────────────────────────────────────────────

@pytest.fixture
def api(db, monkeypatch):
    for mod in (studio_mod, rooms_mod):
        monkeypatch.setattr(mod, "db_select", db.select)
        monkeypatch.setattr(mod, "db_insert", db.insert)
    app = FastAPI()
    for r in (studio_mod.router, rooms_mod.router, council_mod.router, ident_mod.router):
        app.include_router(r)
    qui = {"sub": "adm_rien"}
    app.dependency_overrides[get_current_user] = lambda: dict(qui)
    c = TestClient(app)
    c.qui = qui  # type: ignore[attr-defined]
    return c


def test_routes_refusees_en_402_sans_abonnement(api, enforce):
    appels = [
        ("post", "/v1/artifacts/brainstorm", {"brief": "x", "kind": "memo"}),
        ("post", "/v1/artifacts/canvas-diagram", {"prompt": "x"}),
        ("post", "/v1/council/orchestrate", {"task": "x", "transcript": "y"}),
        ("post", "/v1/rooms/r1/summarize", {}),
        ("post", "/v1/rooms/r1/intervention-check", {}),
        ("post", "/v1/rooms/r1/bring-agent", {"persona": "azzmin"}),
    ]
    for meth, url, corps in appels:
        r = getattr(api, meth)(url, json=corps)
        assert r.status_code == 402, (url, r.status_code, r.text)
        assert r.json()["detail"]["error"] == "abonnement_requis"


def test_surfaces_sans_modele_restent_libres(api, enforce):
    """Sans abonnement, on garde le travail à la main : toile vierge, lecture."""
    assert api.post("/v1/artifacts/blank-canvas", json={"title": "Tableau"}).status_code == 200
    assert api.get("/v1/artifacts").status_code == 200


def test_etat_lu_par_l_application(api, enforce):
    api.qui["sub"] = "adm_min"
    d = api.get("/v1/agents/abonnements").json()["data"]
    assert d["agents"] == {"azzmin": True, "azzco": False, "azzcom": False} and d["mode"] == "enforce"


def test_delegation_exige_l_abonnement(api, enforce, monkeypatch):
    monkeypatch.setattr(ident_mod, "_profil", lambda uid: {"id": uid, "role": "admin", "tenant_id": "t_rien"})
    r = api.post("/v1/agents/delegation", json={"agent": "azzmin"})
    assert r.status_code == 402


# ── Régression du 29/09 : bring-agent servait une délégation signée sans authentification ──

def test_bring_agent_exige_une_personne_connectee(monkeypatch):
    monkeypatch.setenv("VTLVS_DELEGATION_SECRET", "s" * 48)
    app = FastAPI()
    app.include_router(rooms_mod.router)
    r = TestClient(app).post("/v1/rooms/r1/bring-agent?owner_id=victime", json={})
    assert r.status_code in (401, 403), r.text
    assert "delegation" not in r.text.lower()


def test_bring_agent_sert_bien_bring_agent(api, db, monkeypatch):
    monkeypatch.setenv("AGENTS_ABONNEMENT_MODE", "enforce")
    api.qui["sub"] = "adm_min"  # organisme abonné à AZZMIN
    r = api.post("/v1/rooms/inconnue/bring-agent", json={"persona": "AZZMIN"})
    assert r.status_code == 404, r.text  # la vraie fonction répond : salle introuvable
