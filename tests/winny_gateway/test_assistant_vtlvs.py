"""Assistant de l'application : qui peut l'utiliser, quand, et avec quelles données."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from tests.winny_gateway.test_vigil_studio_rooms import FakeDB
from winny_gateway import assistant_vtlvs as av
from winny_gateway.auth import get_current_user
from winny_gateway.routes import assistant as route

NOW = datetime(2026, 9, 17, 10, 0, tzinfo=UTC)


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    d.tables["learn_profiles"] = [
        {"id": "form", "role": "formateur", "tenant_id": "t1", "full_name": "Alice"},
        {"id": "app", "role": "apprenant", "tenant_id": "t1", "full_name": "Bruno"},
        {"id": "pros", "role": "prospect", "tenant_id": "t1", "full_name": "Paul"},
        {"id": "aud", "role": "auditeur", "tenant_id": "t1", "full_name": "Anne"},
    ]
    d.tables["learn_enrollments"] = [{"apprenant_id": "app", "status": "inscrit", "session_id": "s1"}]
    d.tables["learn_session_slots"] = [
        {"id": "c1", "session_id": "s1", "status": "planned",
         "starts_at": (NOW + timedelta(minutes=10)).isoformat(), "ends_at": (NOW + timedelta(hours=3)).isoformat()},
        {"id": "c2", "session_id": "s1", "status": "planned",
         "starts_at": (NOW + timedelta(days=2)).isoformat(), "ends_at": (NOW + timedelta(days=2, hours=3)).isoformat()},
    ]
    monkeypatch.setattr(av, "db_select", d.select)
    return d


def run(coro):
    return asyncio.run(coro)


def test_roles_toujours_ouverts(db):
    assert run(av.verifier_acces("form", NOW))["motif"] == "role"
    assert run(av.verifier_acces("aud", NOW))["motif"] == "role"


def test_prospect_refuse(db):
    with pytest.raises(av.AccesRefuse) as e:
        run(av.verifier_acces("pros", NOW))
    assert e.value.statut == 403


def test_apprenant_pendant_son_creneau_y_compris_les_marges(db):
    assert run(av.verifier_acces("app", NOW))["motif"] == "creneau"
    assert run(av.verifier_acces("app", NOW + timedelta(hours=3, minutes=14)))["motif"] == "creneau"


def test_apprenant_hors_formation_sans_abonnement(db):
    with pytest.raises(av.AccesRefuse) as e:
        run(av.verifier_acces("app", NOW + timedelta(hours=5)))
    assert e.value.statut == 402 and e.value.code == "assistant_hors_formation"
    assert e.value.details["prochain_creneau"].startswith("2026-09-19")


def test_apprenant_hors_formation_avec_abonnement(db):
    db.tables["org_members"] = [{"user_id": "app", "org_id": "o1"}]
    db.tables["subscriptions"] = [{"org_id": "o1", "status": "active", "current_period_end": None}]
    assert run(av.verifier_acces("app", NOW + timedelta(hours=5)))["motif"] == "abonnement"


def test_abonnement_expire_ne_compte_pas(db):
    db.tables["org_members"] = [{"user_id": "app", "org_id": "o1"}]
    db.tables["subscriptions"] = [{"org_id": "o1", "status": "active",
                                   "current_period_end": (datetime.now(UTC) - timedelta(days=1)).isoformat()}]
    with pytest.raises(av.AccesRefuse):
        run(av.verifier_acces("app", NOW + timedelta(hours=5)))


def test_inscription_annulee_ne_donne_pas_acces(db):
    db.tables["learn_enrollments"][0]["status"] = "annule"
    with pytest.raises(av.AccesRefuse):
        run(av.verifier_acces("app", NOW))


@pytest.fixture
def api(db, monkeypatch):
    vu = {}

    async def faux_instantane(jeton):
        vu["jeton"] = jeton
        return "Agenda (14 jours) : rien de prévu."

    async def faux_ask(worker, prompt, system="", **kw):
        vu["prompt"], vu["system"] = prompt, system
        return {"output": "- Ouvrez **Calendrier** dans le menu.", "stub": False}

    monkeypatch.setattr(av, "instantane", faux_instantane)
    import winny.council.providers as prov
    monkeypatch.setattr(prov, "ask", faux_ask)
    app = FastAPI()
    app.state.config = type("C", (), {"hermes_url": ""})()
    app.include_router(route.router)
    qui = {"sub": "form"}

    async def who(request: Request):
        return dict(qui)

    app.dependency_overrides[get_current_user] = who
    c = TestClient(app)
    c.qui, c.vu = qui, vu  # type: ignore[attr-defined]
    return c


def test_chat_repond_en_flux_avec_le_jeton_de_la_personne(api):
    r = api.post("/v1/assistant/chat", json={"message": "Où est mon planning ?", "session_id": "s"},
                 headers={"authorization": "Bearer jwt-de-alice"})
    assert r.status_code == 200 and "event: text_delta" in r.text and "event: done" in r.text
    assert "Calendrier" in r.text
    assert api.vu["jeton"] == "jwt-de-alice"
    assert "Alice" in api.vu["system"] and "formateur" in api.vu["system"]
    assert "<<DONNEES-" in api.vu["prompt"]


def test_chat_apprenant_hors_formation_402(api, monkeypatch):
    api.qui["sub"] = "app"
    reel = av.datetime

    class FauxDT(reel):
        @classmethod
        def now(cls, tz=None):
            return NOW + timedelta(hours=5)

    monkeypatch.setattr(av, "datetime", FauxDT)
    r = api.post("/v1/assistant/chat", json={"message": "bonjour"})
    assert r.status_code == 402 and r.json()["detail"]["error"] == "assistant_hors_formation"
    acc = api.get("/v1/assistant/acces").json()["data"]
    assert acc["ouvert"] is False and acc["prochain_creneau"]


def test_agent_ou_service_refuse(api):
    api.qui.update({"sub": "form", "agent_credential": {"agent": "azzcom"}})
    assert api.post("/v1/assistant/chat", json={"message": "x"}).status_code == 403
