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
