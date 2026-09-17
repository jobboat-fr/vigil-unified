"""Limitation de débit par personne : paliers, Retry-After, clés, exemptions."""
from __future__ import annotations

import base64
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from winny_gateway import limite_debit as ld


def _jwt(sub: str) -> str:
    charge = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
    return f"e30.{charge}.sig"


def _app(monkeypatch):
    monkeypatch.setattr(ld, "COMPTEUR", ld.Compteur())
    monkeypatch.setitem(ld.PALIERS, "ia", (2, 60.0))
    monkeypatch.setitem(ld.PALIERS, "ecriture", (3, 60.0))
    app = FastAPI()
    app.add_middleware(ld.LimiteDebitMiddleware)

    @app.post("/v1/artifacts/{i}/agent")
    def agent(i: str):
        return {"ok": True}

    @app.post("/v1/crm/contacts")
    def ecrire():
        return {"ok": True}

    @app.get("/health")
    def sante():
        return {"ok": True}

    @app.post("/v1/rooms/livekit/webhook")
    def webhook():
        return {"ok": True}

    return TestClient(app)


def test_palier_ia_par_personne_avec_retry_after(monkeypatch):
    c = _app(monkeypatch)
    alice = {"authorization": f"Bearer {_jwt('alice')}"}
    bruno = {"authorization": f"Bearer {_jwt('bruno')}"}
    assert [c.post("/v1/artifacts/a/agent", headers=alice).status_code for _ in range(3)] == [200, 200, 429]
    r = c.post("/v1/artifacts/a/agent", headers=alice)
    assert r.status_code == 429 and 1 <= int(r.headers["retry-after"]) <= 60
    assert r.json()["error"] == "trop_de_requetes" and "assistant" in r.json()["detail"]
    # Bruno n'est pas pénalisé par Alice
    assert c.post("/v1/artifacts/a/agent", headers=bruno).status_code == 200


def test_palier_ecriture_et_exemptions(monkeypatch):
    c = _app(monkeypatch)
    h = {"authorization": f"Bearer {_jwt('alice')}"}
    assert [c.post("/v1/crm/contacts", headers=h).status_code for _ in range(4)][-1] == 429
    assert all(c.get("/health").status_code == 200 for _ in range(10))
    assert all(c.post("/v1/rooms/livekit/webhook").status_code == 200 for _ in range(10))


def test_sans_jeton_la_cle_est_l_ip(monkeypatch):
    c = _app(monkeypatch)
    a = {"cf-connecting-ip": "1.1.1.1"}
    b = {"cf-connecting-ip": "2.2.2.2"}
    assert [c.post("/v1/crm/contacts", headers=a).status_code for _ in range(4)][-1] == 429
    assert c.post("/v1/crm/contacts", headers=b).status_code == 200


def test_fenetre_glissante():
    cpt = ld.Compteur()
    lim = ld.PALIERS["ia"][0]
    for i in range(lim):
        assert cpt.essayer("u", "ia", maintenant=100.0 + i * 0.01)[0]
    ok, attente = cpt.essayer("u", "ia", maintenant=101.0)
    assert not ok and attente == 59
    assert cpt.essayer("u", "ia", maintenant=160.5)[0]


def test_journal_une_fois_par_fenetre():
    cpt = ld.Compteur()
    assert cpt.premier_refus("u", "ia", maintenant=10.0)
    assert not cpt.premier_refus("u", "ia", maintenant=20.0)
    assert cpt.premier_refus("u", "ia", maintenant=80.0)
