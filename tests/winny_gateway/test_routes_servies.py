"""Ce que la passerelle sert réellement — gardes permanentes (29/09).

Parcourt les routes servies (voir routes_app.py : FastAPI 0.137 ne met plus les routeurs à
plat, un balayage de `app.routes` seul n'en voyait qu'une).
"""
from __future__ import annotations

from winny_gateway import auth
from tests.winny_gateway.routes_app import dependances, routes


def _app(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "x")
    from winny_gateway.app import create_app
    return create_app()


# Les seules routes servies sans personne connectée, chacune avec sa raison.
# Une route qui s'ajoute ici doit porter sa propre garde : signature, secret ou jeton opaque.
PUBLIQUES = {
    "/health": "sonde Railway",
    "/api/v1/alertes/grafana": "secret partagé Grafana (401 sinon)",
    "/api/v1/billing/webhook": "signature Stripe ; sans secret, refus 503 en production",
    "/v1/rooms/livekit/webhook": "signature LiveKit (presence.verify_webhook)",
    "/api/v1/features": "drapeaux de fonctionnalités, rien de personnel",
    "/api/v1/support/public": "formulaire de support public, limité en débit",
    "/api/v1/support/incident": "incident d'affichage, sans donnée saisie, borné en taille et en débit",
    "/v1/artifacts/partage/{token}": "jeton opaque 192 bits",
    "/v1/rooms/meeting/{share_token}": "jeton opaque 122 bits, 72 h",
    "/v1/rooms/guest/{share_token}/join": "jeton opaque 122 bits, 72 h",
}

# vigil-ai.xyz est éteint (Azer, 29/09) : ses routes de trading ont été retirées et ne doivent
# pas revenir par un montage oublié.
RETIREES = ("/api/v1/portfolio", "/api/v1/orders", "/api/v1/approvals", "/api/v1/agents/", "/api/v1/chat",
            "/api/v1/backtest", "/api/v1/signals", "/api/v1/settings", "/api/v1/broker", "/api/v1/auto-trade",
            "/api/v1/market", "/api/v1/webhooks", "/ws/", "/api/v1/events", "/api/v1/onboarding")


def test_aucune_route_publique_imprevue(monkeypatch):
    """La faille bring-agent (29/09) serait tombée ici avant d'être en ligne."""
    gardes = {auth.get_current_user, auth.scoped_user}
    imprevues = [(p, f.__name__) for p, _m, f, dep in routes(_app(monkeypatch))
                 if not (dependances(dep) & gardes) and p not in PUBLIQUES]
    assert not imprevues, f"routes servies sans connexion et non justifiées : {imprevues}"


def test_aucune_aide_servie(monkeypatch):
    """Une fonction « _privée » servie comme route = un décorateur posé au mauvais endroit."""
    assert not [(p, f.__name__) for p, _m, f, _d in routes(_app(monkeypatch)) if f.__name__.startswith("_")]


def test_les_routes_winnywoo_ne_reviennent_pas(monkeypatch):
    revenues = [p for p, _m, _f, _d in routes(_app(monkeypatch)) if p.startswith(RETIREES)]
    assert not revenues, f"routes WinnyWoo servies à nouveau : {revenues}"


def test_les_publiques_declarees_existent(monkeypatch):
    """La liste ne garde pas de justification pour une route disparue."""
    servies = {p for p, _m, _f, _d in routes(_app(monkeypatch))}
    assert set(PUBLIQUES) <= servies, set(PUBLIQUES) - servies
