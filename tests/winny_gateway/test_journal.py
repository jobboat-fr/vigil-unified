"""Journal JSON de la passerelle (schéma commun) et envoi Loki par lots, sans blocage."""
from __future__ import annotations

import json
import logging

from winny_gateway import journal_loki
from winny_gateway.logging import JsonFormatter


def test_schema_commun_et_ip_en_empreinte():
    rec = logging.makeLogRecord({"name": "gateway.http", "levelname": "WARNING", "msg": "GET /x → 403",
                                 "status_code": 403, "duration_ms": 12.5, "path": "/x", "ip": "1.2.3.4",
                                 "evenement": "http.requete"})
    d = json.loads(JsonFormatter().format(rec))
    assert d["service"] == "passerelle" and d["niveau"] == "warning" and d["statut"] == 403
    assert d["duree_ms"] == 12.5 and d["route"] == "/x" and d["evenement"] == "http.requete"
    assert "1.2.3.4" not in json.dumps(d) and len(d["ip"]) == 12


def test_loki_par_lots_etiquettes_limitees(monkeypatch):
    envoye = []

    def faux_urlopen(req, timeout=5):
        envoye.append((req.headers, json.loads(req.data)))

        class R:
            def read(self):
                return b""
        return R()

    monkeypatch.setattr(journal_loki.urllib.request, "urlopen", faux_urlopen)
    monkeypatch.setattr(journal_loki.threading, "Thread", lambda **kw: type("T", (), {"start": lambda self: None})())
    h = journal_loki.LokiHandler("https://logs.example/loki/api/v1/push", "vtlvs", "secret", "passerelle", JsonFormatter())
    log = logging.getLogger("test.loki")
    log.addHandler(h)
    log.setLevel(logging.INFO)
    log.warning("refus", extra={"evenement": "securite.delegation_refusee"})
    log.info("ok")
    h.vider()
    headers, corps = envoye[0]
    assert headers["Authorization"].startswith("Basic ")
    labels = sorted(tuple(sorted(s["stream"].items())) for s in corps["streams"])
    assert (("evenement", "securite.delegation_refusee"), ("niveau", "warning"), ("service", "passerelle")) in labels
    assert sum(len(s["values"]) for s in corps["streams"]) == 2
    log.removeHandler(h)


def test_loki_injoignable_ne_leve_pas(monkeypatch):
    def panne(*a, **k):
        raise OSError("réseau")

    monkeypatch.setattr(journal_loki.urllib.request, "urlopen", panne)
    monkeypatch.setattr(journal_loki.threading, "Thread", lambda **kw: type("T", (), {"start": lambda self: None})())
    h = journal_loki.LokiHandler("https://x", "u", "p", "passerelle", JsonFormatter())
    h.emit(logging.makeLogRecord({"msg": "x", "levelname": "INFO"}))
    h.vider()  # ne lève pas


def test_sans_configuration_rien_n_est_installe(monkeypatch):
    for v in ("LOKI_URL", "LOKI_USER", "LOKI_PASSWORD"):
        monkeypatch.delenv(v, raising=False)
    assert journal_loki.installer(logging.getLogger("x"), "passerelle", JsonFormatter()) is False


# ── La référence de requête (S6) ────────────────────────────────────────────
#
# Ce que l'écran d'erreur affiche doit être exactement ce qu'on cherche dans Loki. Deux
# règles : la référence posée par le navigateur est reprise telle quelle, et elle repart
# dans la réponse — sinon l'application affiche la sienne et le support cherche une
# chaîne qui n'existe nulle part.

import asyncio  # noqa: E402

from winny_gateway.logging import log_request  # noqa: E402


class _FausseRequete:
    def __init__(self, entetes: dict[str, str], chemin: str = "/v1/rooms"):
        self.headers = entetes
        self.method = "GET"
        self.url = type("U", (), {"path": chemin})()
        self.client = type("C", (), {"host": "1.2.3.4"})()


class _FausseReponse:
    def __init__(self, statut: int = 200):
        self.status_code = statut
        self.headers: dict[str, str] = {}


def _jouer(entetes: dict[str, str], statut: int = 200) -> _FausseReponse:
    reponse = _FausseReponse(statut)

    async def suite(_):
        return reponse

    return asyncio.run(log_request(_FausseRequete(entetes), suite))


def test_reference_du_navigateur_reprise_et_renvoyee(caplog):
    caplog.set_level(logging.INFO, logger="gateway.http")
    reference = "a3f19c0d4b5e6f7a8b9c0d1e2f3a4b5c"
    reponse = _jouer({"x-request-id": reference})
    assert reponse.headers["x-request-id"] == reference
    assert any(getattr(r, "request_id", None) == reference for r in caplog.records)


def test_reference_absente_ou_douteuse_remplacee():
    # Trop courte, et une tentative d'injection d'en-tête : on en fabrique une propre.
    for valeur in ("", "x", "abc\r\nSet-Cookie: a=b"):
        reponse = _jouer({"x-request-id": valeur} if valeur else {})
        pose = reponse.headers["x-request-id"]
        assert len(pose) == 32 and pose.isalnum()


def test_health_ne_journalise_pas_et_ne_pose_rien():
    reponse = _jouer({}, statut=200)
    assert "x-request-id" in reponse.headers
    sante = _FausseReponse()

    async def suite(_):
        return sante

    assert asyncio.run(log_request(_FausseRequete({}, "/health"), suite)) is sante
    assert "x-request-id" not in sante.headers
