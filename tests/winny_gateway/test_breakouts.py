"""Sous-salles (phase 1.8) : répartition, qui entre où, fermeture."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.winny_gateway.test_vigil_studio_rooms import FakeDB
from winny_gateway import breakouts as bk
from winny_gateway import learn_link
from winny_gateway.auth import get_current_user
from winny_gateway.routes.vigil import rooms as rooms_mod

T = "tenant-hbs"
RID = "11111111-2222-3333-4444-555555555555"


def test_repartition_tourniquet_sur_les_noms():
    people = [{"id": f"u{i}", "name": n} for i, n in enumerate(["Zoé", "Adam", "Léa", "Bruno", "Chloé"])]
    groups = bk.distribute(people, 2)
    assert [g["id"] for g in groups] == ["g1", "g2"]
    assert groups[0]["members"] == ["u1", "u4", "u0"]  # Adam, Chloé, Zoé
    assert groups[1]["members"] == ["u3", "u2"]         # Bruno, Léa


def test_nom_livekit_et_salle_principale():
    assert bk.livekit_room(RID, "g2") == f"vigil-{RID}--g2"
    assert bk.parent_room_id(f"vigil-{RID}--g2") == RID
    assert bk.parent_room_id(f"vigil-{RID}") == RID


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
    now = datetime.now(UTC)
    db.tables["rooms"] = [{"id": RID, "user_id": "u-form", "title": "TOPLEVEL IA", "status": "active",
                           "learn_slot_id": "sl-1", "learn_session_id": "s-1", "breakouts": []}]
    db.tables["learn_session_slots"] = [{"id": "sl-1", "session_id": "s-1", "tenant_id": T, "formateur_id": "u-form",
                                         "status": "planned", "starts_at": (now - timedelta(minutes=5)).isoformat(),
                                         "ends_at": (now + timedelta(hours=3)).isoformat()}]
    db.tables["learn_sessions"] = [{"id": "s-1", "modality": "distanciel", "status": "planned", "tenant_id": T}]
    db.tables["learn_enrollments"] = [{"session_id": "s-1", "apprenant_id": f"u-a{i}", "status": "inscrit"} for i in range(4)]
    db.tables["learn_profiles"] = [{"id": f"u-a{i}", "full_name": f"Apprenant {i}"} for i in range(4)]
    app = FastAPI()
    app.include_router(rooms_mod.router)
    who = {}
    app.dependency_overrides[get_current_user] = lambda: who["u"]
    c = TestClient(app)

    def as_(uid, role):
        who["u"] = {"sub": uid, "app_metadata": {"learn_role": role, "tenant_id": T}}
        return c
    c.as_ = as_  # type: ignore[attr-defined]
    c.db = db  # type: ignore[attr-defined]
    return c


def test_formateur_cree_les_groupes_depuis_les_inscrits(env):
    r = env.as_("u-form", "formateur").post(f"/v1/rooms/{RID}/breakouts", json={"count": 2})
    assert r.status_code == 200, r.text
    groups = r.json()["data"]["breakouts"]
    assert sorted(m for g in groups for m in g["members"]) == ["u-a0", "u-a1", "u-a2", "u-a3"]
    assert groups[0]["member_names"][0].startswith("Apprenant")


def test_apprenant_ne_cree_pas(env):
    assert env.as_("u-a0", "apprenant").post(f"/v1/rooms/{RID}/breakouts", json={"count": 2}).status_code == 403


def test_apprenant_voit_et_rejoint_son_groupe_seulement(env):
    env.as_("u-form", "formateur").post(f"/v1/rooms/{RID}/breakouts", json={"count": 2})
    c = env.as_("u-a0", "apprenant")
    mine = c.get(f"/v1/rooms/{RID}/breakouts").json()["data"]["breakouts"]
    assert len(mine) == 1 and "u-a0" in mine[0]["members"]
    other = "g2" if mine[0]["id"] == "g1" else "g1"
    ok = c.post(f"/v1/rooms/{RID}/breakouts/{mine[0]['id']}/join").json()["data"]
    assert ok["room"] == f"vigil-{RID}--{mine[0]['id']}" and ok["token"]
    assert c.post(f"/v1/rooms/{RID}/breakouts/{other}/join").status_code == 403


def test_formateur_entre_dans_tous_les_groupes(env):
    c = env.as_("u-form", "formateur")
    c.post(f"/v1/rooms/{RID}/breakouts", json={"count": 2})
    for gid in ("g1", "g2"):
        assert c.post(f"/v1/rooms/{RID}/breakouts/{gid}/join").json()["data"]["role"] == "host"


def test_fermeture_vide_les_groupes(env):
    c = env.as_("u-form", "formateur")
    c.post(f"/v1/rooms/{RID}/breakouts", json={"count": 2})
    assert c.delete(f"/v1/rooms/{RID}/breakouts").status_code == 200
    assert env.as_("u-a0", "apprenant").get(f"/v1/rooms/{RID}/breakouts").json()["data"]["breakouts"] == []


def test_non_inscrit_ne_voit_rien(env):
    assert env.as_("u-intrus", "apprenant").get(f"/v1/rooms/{RID}/breakouts").status_code == 403
