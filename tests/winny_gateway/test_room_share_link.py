"""Lien d'invitation d'une salle (phase 1.1) : il expire, et meurt avec la réunion."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.winny_gateway.test_vigil_studio_rooms import _data, client  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def _livekit(monkeypatch):
    monkeypatch.setenv("LIVEKIT_URL", "wss://exemple.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "APIexemple")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "secret-exemple-assez-long-pour-hs256-0000")


def _room(client):
    return _data(client.post("/v1/rooms", json={"title": "Atelier IA 360"}))["id"]


def test_lien_porte_une_echeance_et_reste_stable(client):
    rid = _room(client)
    a = _data(client.post(f"/v1/rooms/{rid}/share"))
    b = _data(client.post(f"/v1/rooms/{rid}/share"))
    assert a["share_token"] == b["share_token"]
    exp = datetime.fromisoformat(a["expires_at"])
    assert timedelta(hours=71) < exp - datetime.now(UTC) <= timedelta(hours=72)


def test_invite_entre_avec_un_lien_valable(client):
    rid = _room(client)
    tok = _data(client.post(f"/v1/rooms/{rid}/share"))["share_token"]
    assert _data(client.get(f"/v1/rooms/meeting/{tok}"))["room_title"] == "Atelier IA 360"
    join = _data(client.post(f"/v1/rooms/guest/{tok}/join", json={"name": "Camille"}))
    assert join["token"] and join["room"] == f"vigil-{rid}"


def test_lien_expire_refuse_puis_remplace(client):
    rid = _room(client)
    old = _data(client.post(f"/v1/rooms/{rid}/share"))["share_token"]
    row = next(r for r in client.db.tables["rooms"] if r["id"] == rid)
    row["share_expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    r = client.post(f"/v1/rooms/guest/{old}/join", json={"name": "Camille"})
    assert r.status_code == 410 and r.json()["detail"]["error"] == "expired_share_token"
    new = _data(client.post(f"/v1/rooms/{rid}/share"))["share_token"]
    assert new != old
    assert client.get(f"/v1/rooms/meeting/{old}").status_code == 404


def test_lien_sans_echeance_refuse(client):
    rid = _room(client)
    row = next(r for r in client.db.tables["rooms"] if r["id"] == rid)
    row["share_token"] = "ancien-jeton"
    assert client.get("/v1/rooms/meeting/ancien-jeton").status_code == 410


def test_reunion_close_refuse_l_entree(client):
    rid = _room(client)
    tok = _data(client.post(f"/v1/rooms/{rid}/share"))["share_token"]
    row = next(r for r in client.db.tables["rooms"] if r["id"] == rid)
    row["status"] = "closed"
    r = client.post(f"/v1/rooms/guest/{tok}/join", json={"name": "Camille"})
    assert r.status_code == 410 and r.json()["detail"]["error"] == "meeting_closed"
    assert client.post(f"/v1/rooms/{rid}/share").status_code == 409


def test_lien_inconnu_404(client):
    assert client.get("/v1/rooms/meeting/nimporte-quoi").status_code == 404
