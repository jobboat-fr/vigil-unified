"""Salle d'un créneau de formation LEARN (phase 1.2) : qui entre, à quel titre, et quand."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.winny_gateway.test_vigil_studio_rooms import FakeDB
from winny_gateway import learn_link
from winny_gateway.auth import get_current_user
from winny_gateway.routes.vigil import rooms as rooms_mod

T1, T2 = "tenant-hbs", "tenant-autre"
NOW = datetime.now(UTC)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("LIVEKIT_URL", "wss://exemple.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "APIexemple")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "secret-exemple-assez-long-pour-hs256-0000")
    db = FakeDB()
    for mod in (rooms_mod, learn_link):
        monkeypatch.setattr(mod, "db_select", db.select)
    monkeypatch.setattr(rooms_mod, "db_insert", db.insert)
    monkeypatch.setattr(rooms_mod, "db_update", db.update)

    db.tables["learn_sessions"] = [
        {"id": "s-dist", "title": "TOPLEVEL IA", "code": "IA360-2026-10-26", "modality": "distanciel", "status": "planned", "tenant_id": T1},
        {"id": "s-pres", "title": "Marketing", "modality": "presentiel", "status": "planned", "tenant_id": T1},
    ]
    def slot(i, session, start):
        return {"id": i, "session_id": session, "tenant_id": T1, "formateur_id": "u-form", "on_date": "2026-10-26",
                "half": "am", "status": "planned", "starts_at": start.isoformat(),
                "ends_at": (start + timedelta(hours=3)).isoformat()}
    db.tables["learn_session_slots"] = [
        slot("sl-now", "s-dist", NOW - timedelta(minutes=10)),
        slot("sl-later", "s-dist", NOW + timedelta(hours=5)),
        slot("sl-pres", "s-pres", NOW),
    ]
    db.tables["learn_enrollments"] = [
        {"session_id": "s-dist", "apprenant_id": "u-app", "company_id": "c-1", "status": "inscrit"},
        {"session_id": "s-dist", "apprenant_id": "u-parti", "company_id": "c-2", "status": "abandon"},
    ]
    db.tables["learn_profiles"] = [
        {"id": "u-app", "full_name": "Camille Martin", "company_id": "c-1"},
        {"id": "u-ent", "full_name": "RH Acme", "company_id": "c-1"},
    ]

    app = FastAPI()
    app.include_router(rooms_mod.router)
    who = {"user": None}
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    c = TestClient(app)

    def as_(uid, role, tenant=T1):
        who["user"] = {"sub": uid, "email": f"{uid}@x.fr", "app_metadata": {"learn_role": role, "tenant_id": tenant}}
        return c
    c.as_ = as_  # type: ignore[attr-defined]
    c.db = db  # type: ignore[attr-defined]
    return c


def _join(c, slot="sl-now"):
    return c.post(f"/v1/rooms/learn/slots/{slot}/join")


def test_formateur_anime_et_la_salle_est_creee_a_son_nom(env):
    r = _join(env.as_("u-form", "formateur"))
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["role"] == "host" and d["token"]
    room = env.db.tables["rooms"][0]
    assert room["user_id"] == "u-form" and room["kind"] == "formation" and room["learn_slot_id"] == "sl-now"
    assert "TOPLEVEL IA" in room["title"]


def test_apprenant_inscrit_participe_dans_la_meme_salle(env):
    host = _join(env.as_("u-form", "formateur")).json()["data"]
    d = _join(env.as_("u-app", "apprenant")).json()["data"]
    assert d["role"] == "participant" and d["room_id"] == host["room_id"]
    assert len(env.db.tables["rooms"]) == 1


def test_apprenant_non_inscrit_ou_abandon_refuse(env):
    assert _join(env.as_("u-inconnu", "apprenant")).json()["detail"]["error"] == "not_enrolled"
    assert _join(env.as_("u-parti", "apprenant")).status_code == 403


def test_entreprise_dont_un_salarie_est_inscrit(env):
    assert _join(env.as_("u-ent", "entreprise")).json()["data"]["role"] == "participant"


def test_admin_du_meme_organisme_anime(env):
    assert _join(env.as_("u-adm", "admin")).json()["data"]["role"] == "host"


def test_autre_organisme_ne_voit_pas_le_creneau(env):
    r = _join(env.as_("u-adm2", "admin", tenant=T2))
    assert r.status_code == 404


def test_formateur_d_un_autre_creneau_refuse(env):
    assert _join(env.as_("u-autre-form", "formateur")).json()["detail"]["error"] == "not_in_session"


def test_session_presentielle_sans_salle(env):
    assert _join(env.as_("u-form", "formateur"), "sl-pres").json()["detail"]["error"] == "not_remote"


def test_trop_tot(env):
    r = _join(env.as_("u-app", "apprenant"), "sl-later")
    assert r.status_code == 425 and r.json()["detail"]["error"] == "too_early"


def test_creneau_annule(env):
    env.db.tables["learn_session_slots"][0]["status"] = "cancelled"
    assert _join(env.as_("u-form", "formateur")).json()["detail"]["error"] == "slot_cancelled"
