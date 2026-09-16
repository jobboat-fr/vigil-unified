"""Fin de séance (phase 1.7) : présence LiveKit, écarts avec l'émargement, compte rendu au coffre."""
from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.winny_gateway.test_vigil_studio_rooms import FakeDB
from winny_gateway import presence
from winny_gateway.auth import get_current_user
from winny_gateway.routes.vigil import rooms as rooms_mod

KEY, SECRET = "APIexemple", "secret-exemple-assez-long-pour-hs256-0000"
T0 = datetime(2026, 10, 26, 8, 0, tzinfo=UTC)
SLOT = {"id": "sl-1", "session_id": "s-1", "tenant_id": "t", "starts_at": T0.isoformat(),
        "ends_at": (T0 + timedelta(hours=4)).isoformat()}


def _signed(body: bytes, secret=SECRET, iss=KEY, digest=None):
    claims = {"iss": iss, "exp": int(time.time()) + 60,
              "sha256": digest or base64.b64encode(hashlib.sha256(body).digest()).decode()}
    return "Bearer " + jwt.encode(claims, secret, algorithm="HS256")


@pytest.fixture(autouse=True)
def _lk(monkeypatch):
    monkeypatch.setenv("LIVEKIT_URL", "wss://exemple.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", KEY)
    monkeypatch.setenv("LIVEKIT_API_SECRET", SECRET)


# ── Signature du webhook ────────────────────────────────────────────────────
def test_signature_valide():
    body = b'{"event":"participant_joined"}'
    presence.verify_webhook(body, _signed(body))


@pytest.mark.parametrize("auth,err", [
    (None, "missing_signature"),
    ("Bearer x.y.z", "bad_signature"),
])
def test_signature_absente_ou_fausse(auth, err):
    with pytest.raises(presence.WebhookRefused, match=err):
        presence.verify_webhook(b"{}", auth)


def test_corps_modifie_refuse():
    with pytest.raises(presence.WebhookRefused, match="body_mismatch"):
        presence.verify_webhook(b'{"a":2}', _signed(b'{"a":1}'))


def test_autre_cle_refusee():
    with pytest.raises(presence.WebhookRefused):
        presence.verify_webhook(b"{}", _signed(b"{}", secret="autre-secret-assez-long-0000000000000"))


# ── Rapprochement ───────────────────────────────────────────────────────────
def _ev(uid, event, minutes):
    return {"identity": uid, "event": event, "at": (T0 + timedelta(minutes=minutes)).isoformat()}


def test_presence_bornee_au_creneau():
    ev = [_ev("a", "joined", -30), _ev("a", "left", 60), _ev("a", "joined", 120), _ev("a", "left", 300)]
    assert presence.presence_seconds(ev, T0, T0 + timedelta(hours=4)) == 60 * 60 + 120 * 60


def test_ecarts():
    learners = [{"apprenant_id": x, "full_name": x.upper()} for x in ("present", "absent", "court", "ok", "fantome")]
    sheet = [{"apprenant_id": x, "signed_in_at": T0.isoformat()} for x in ("absent", "court", "ok")]
    events = [_ev("present", "joined", 0), _ev("present", "left", 200),
              _ev("court", "joined", 0), _ev("court", "left", 60),
              _ev("ok", "joined", 0), _ev("ok", "left", 240)]
    rows = {r["apprenant_id"]: r for r in presence.reconcile(SLOT, learners, sheet, events)}
    assert rows["present"]["ecart"] == "present_non_signe"
    assert rows["absent"]["ecart"] == "signe_non_present"
    assert rows["court"]["ecart"] == "presence_courte"
    assert rows["ok"]["ecart"] is None
    assert rows["fantome"]["ecart"] is None  # ni signé ni présent : l'absence se gère dans LEARN


# ── Routes ──────────────────────────────────────────────────────────────────
@pytest.fixture
def client(monkeypatch):
    db = FakeDB()
    for name in ("db_insert", "db_select", "db_update", "db_delete"):
        monkeypatch.setattr(rooms_mod, name, getattr(db, name.removeprefix("db_")))
    app = FastAPI()
    app.include_router(rooms_mod.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "u-form", "app_metadata": {"learn_role": "formateur"}}
    c = TestClient(app)
    c.db = db  # type: ignore[attr-defined]
    return c


def _room(client, **extra):
    row = {"id": "11111111-2222-3333-4444-555555555555", "user_id": "u-form", "title": "IA 360 — matin",
           "transcript": [{"speaker": "Claire", "text": "Bonjour à tous"}], "status": "active", **extra}
    client.db.tables.setdefault("rooms", []).append(row)
    return row["id"]


def test_webhook_enregistre_entree_et_ignore_agent(client):
    rid = _room(client)
    for part, expect in (({"identity": "u-app", "name": "Camille"}, "joined"),
                         ({"identity": "agent-1", "kind": "AGENT"}, None)):
        body = json.dumps({"event": "participant_joined", "id": f"EV_{part['identity']}", "createdAt": 1793000000,
                           "room": {"name": f"vigil-{rid}"}, "participant": part}).encode()
        r = client.post("/v1/rooms/livekit/webhook", content=body, headers={"authorization": _signed(body)})
        assert r.status_code == 200
        assert r.json()["data"].get("recorded") == expect
    rows = client.db.tables["room_presence"]
    assert [(x["identity"], x["event"]) for x in rows] == [("u-app", "joined")]


def test_webhook_non_signe_401(client):
    assert client.post("/v1/rooms/livekit/webhook", content=b"{}").status_code == 401


def test_attendance_check_salle_de_formation(client):
    rid = _room(client, learn_slot_id="sl-1", learn_session_id="s-1")
    client.db.tables["learn_session_slots"] = [SLOT]
    client.db.tables["learn_enrollments"] = [{"session_id": "s-1", "apprenant_id": "u-app", "status": "inscrit"}]
    client.db.tables["learn_profiles"] = [{"id": "u-app", "full_name": "Camille"}]
    client.db.tables["learn_attendance_sheet"] = []
    client.db.tables["room_presence"] = [dict(_ev("u-app", "joined", 0), room_id=rid), dict(_ev("u-app", "left", 180), room_id=rid)]
    d = client.get(f"/v1/rooms/{rid}/attendance-check").json()["data"]
    assert d["ecarts"] == [{"apprenant_id": "u-app", "nom": "Camille", "presence_ratio": 0.75,
                            "signe": False, "ecart": "present_non_signe"}]


def test_attendance_check_refuse_hors_formation(client):
    rid = _room(client)
    assert client.get(f"/v1/rooms/{rid}/attendance-check").status_code == 409


def test_cloture_formation_depose_au_coffre_sans_crm(client, monkeypatch):
    rid = _room(client, learn_slot_id="sl-1", learn_session_id="s-1")
    deposits = []

    async def fake_summary(**_k):
        return {"summary_markdown": "Résumé de la séance.", "decisions": [], "next_steps": [],
                "commitments": [], "follow_ups": [{"name": "Camille"}], "stub": False}

    async def fake_structure(**_k):
        return {}

    async def fake_deposit(**kw):
        deposits.append(kw)
        return {"id": "vault-1"}

    async def no_agent(_rid):
        return False

    monkeypatch.setattr(rooms_mod, "summarize_meeting", fake_summary)
    monkeypatch.setattr(rooms_mod, "structure_meeting", fake_structure)
    monkeypatch.setattr(rooms_mod.learn_api, "deposit_text", fake_deposit)
    monkeypatch.setattr(rooms_mod, "_end_room_agent", no_agent)
    d = client.post(f"/v1/rooms/{rid}/summarize", json={}).json()["data"]
    assert d["vault_object_id"] == "vault-1"
    assert deposits[0]["session_id"] == "s-1" and deposits[0]["on_behalf_of"] == "u-form"
    assert "Résumé de la séance." in deposits[0]["text"]
    assert d["contacts_saved"] == 0 and "crm_contacts" not in client.db.tables


def test_cloture_ia_indisponible_ne_depose_rien(client, monkeypatch):
    rid = _room(client, learn_slot_id="sl-1", learn_session_id="s-1")

    async def stub_summary(**_k):
        return {"summary_markdown": "[conseil hors ligne]", "decisions": [], "next_steps": [],
                "commitments": [], "follow_ups": [], "stub": True}

    async def fake_structure(**_k):
        return {}

    async def boom(**_k):
        raise AssertionError("ne doit pas déposer")

    async def no_agent(_rid):
        return False

    monkeypatch.setattr(rooms_mod, "summarize_meeting", stub_summary)
    monkeypatch.setattr(rooms_mod, "structure_meeting", fake_structure)
    monkeypatch.setattr(rooms_mod.learn_api, "deposit_text", boom)
    monkeypatch.setattr(rooms_mod, "_end_room_agent", no_agent)
    d = client.post(f"/v1/rooms/{rid}/summarize", json={}).json()["data"]
    assert d["vault_object_id"] is None
