"""Les routes héritées de WinnyWoo ne servent pas les comptes VTLVS (29/09)."""
from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tests.winny_gateway.test_vigil_studio_rooms import FakeDB
from winny_gateway import auth, perimetre
from winny_gateway import db as db_mod

JETONS = {
    "jeton-vtlvs": {"sub": "u-vtlvs", "role": "authenticated"},
    "jeton-vigil": {"sub": "u-vigil", "role": "authenticated"},
    "jeton-service": {"sub": "00000000-0000-0000-0000-00000000ffff", "role": "service", "service_token": True},
    "vtlvs_ag_x": {"sub": "u-vtlvs", "role": "authenticated", "agent_credential": {"agent": "azzmin"}},
}


@pytest.fixture
def client(monkeypatch):
    db = FakeDB()
    db.tables["learn_profiles"] = [{"id": "u-vtlvs", "role": "admin"}]
    monkeypatch.setattr(db_mod, "db_select", db.select)

    async def faux_user(_request, credentials):
        if credentials.credentials not in JETONS:
            raise HTTPException(status_code=401, detail="invalid_session")
        return JETONS[credentials.credentials]
    monkeypatch.setattr(auth, "get_current_user", faux_user)

    r = APIRouter(prefix="/api/v1/market")

    @r.get("/overview")  # publique pour VIGIL
    async def overview():
        return {"ok": True}

    app = FastAPI()
    app.include_router(r, dependencies=[Depends(perimetre.hors_vtlvs)])
    return TestClient(app)


def _get(c, jeton=None):
    return c.get("/api/v1/market/overview", headers={"Authorization": f"Bearer {jeton}"} if jeton else {})


def test_sans_jeton_la_route_publique_reste_publique(client):
    assert _get(client).status_code == 200


def test_compte_vigil_passe(client):
    assert _get(client, "jeton-vigil").status_code == 200


def test_jeton_de_service_passe(client):
    assert _get(client, "jeton-service").status_code == 200


def test_compte_vtlvs_404(client):
    r = _get(client, "jeton-vtlvs")
    assert r.status_code == 404 and r.json()["detail"] == "Not Found"


def test_agent_vtlvs_404(client):
    assert _get(client, "vtlvs_ag_x").status_code == 404


def test_jeton_invalide_la_route_decide(client):
    # route publique ici : elle répond ; une route protégée répondrait son propre 401
    assert _get(client, "n-importe-quoi").status_code == 200


def _app(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    from winny_gateway.app import create_app
    return create_app()


def test_montage_reel(monkeypatch):
    """Sur la vraie application : les routes WinnyWoo portent le verrou, pas celles de VTLVS."""
    from tests.winny_gateway.routes_app import dependances, routes
    servies = {p: dep for p, _m, _f, dep in routes(_app(monkeypatch))}
    for chemin in ("/api/v1/orders/submit-direct", "/api/v1/settings/api-keys", "/api/v1/market/overview",
                   "/api/v1/portfolio/trades"):
        assert chemin in servies and perimetre.hors_vtlvs in dependances(servies[chemin]), chemin
    for chemin in ("/v1/rooms/{room_id}/summarize", "/v1/agents/abonnements", "/v1/connect/status",
                   "/api/v1/approvals/pending"):
        if chemin in servies:
            assert perimetre.hors_vtlvs not in dependances(servies[chemin]), chemin


# Les seules routes servies sans personne connectée, chacune avec sa raison (relevé du 29/09).
# Une route qui s'ajoute ici doit porter sa propre garde : signature, secret ou jeton opaque.
PUBLIQUES = {
    "/health": "sonde Railway",
    "/api/v1/alertes/grafana": "secret partagé Grafana (401 sinon)",
    "/api/v1/billing/webhook": "signature Stripe ; sans secret, refus 503 en production",
    "/api/v1/webhooks/coinbase": "signature HMAC ; sans secret, refus (sauf drapeau de dev)",
    "/v1/rooms/livekit/webhook": "signature LiveKit (presence.verify_webhook)",
    "/api/v1/features": "drapeaux de fonctionnalités, rien de personnel",
    "/api/v1/support/public": "formulaire de support public, limité en débit",
    "/api/v1/market/overview": "données de marché publiques de VIGIL",
    "/api/v1/market/news": "données de marché publiques de VIGIL",
    "/api/v1/market/enrich/{symbol:path}": "données de marché publiques de VIGIL",
    "/api/v1/market/ohlcv/{symbol:path}": "données de marché publiques de VIGIL",
    "/v1/artifacts/partage/{token}": "jeton opaque 192 bits",
    "/v1/rooms/meeting/{share_token}": "jeton opaque 122 bits, 72 h",
    "/v1/rooms/guest/{share_token}/join": "jeton opaque 122 bits, 72 h",
}


def test_aucune_route_publique_imprevue(monkeypatch):
    """Garde permanente : la faille bring-agent (29/09) serait tombée ici avant d'être en ligne."""
    from winny_gateway import auth
    from tests.winny_gateway.routes_app import dependances, routes
    gardes = {auth.get_current_user, auth.scoped_user}
    imprevues = [(p, f.__name__) for p, _m, f, dep in routes(_app(monkeypatch))
                 if not (dependances(dep) & gardes) and p not in PUBLIQUES]
    assert not imprevues, f"routes servies sans connexion et non justifiées : {imprevues}"


def test_aucune_aide_servie(monkeypatch):
    """Une fonction « _privée » servie comme route = un décorateur posé au mauvais endroit."""
    from tests.winny_gateway.routes_app import routes
    assert not [(p, f.__name__) for p, _m, f, _d in routes(_app(monkeypatch)) if f.__name__.startswith("_")]
