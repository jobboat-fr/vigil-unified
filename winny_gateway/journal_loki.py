"""Envoi des journaux vers Loki (logs.vtlvs.com) — sans jamais ralentir une requête.

Le gestionnaire met chaque ligne dans une file en mémoire ; un fil d'arrière-plan l'envoie par
lots toutes les 2 secondes (ou à 500 lignes). Si Loki est injoignable, les lignes les plus
anciennes sont abandonnées au-delà de 10 000 en attente : un puits de journaux en panne ne doit
jamais faire tomber le service qui l'alimente. La sortie standard (Railway) reste la référence.

Activation : LOKI_URL, LOKI_USER, LOKI_PASSWORD. Étiquettes Loki volontairement peu nombreuses :
service, niveau, evenement — le reste est dans la ligne JSON.

Copie identique dans hbs-backend (`app/journal_loki.py`).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
import threading
import time
import urllib.request
from collections import deque

LOT_MAX = 500
PERIODE_S = 2.0
FILE_MAX = 10_000


class LokiHandler(logging.Handler):
    def __init__(self, url: str, utilisateur: str, mot_de_passe: str, service: str, formatter: logging.Formatter) -> None:
        super().__init__()
        self.url = url
        self.service = service
        self.setFormatter(formatter)
        self._auth = "Basic " + base64.b64encode(f"{utilisateur}:{mot_de_passe}".encode()).decode()
        self._file: deque[tuple[dict[str, str], str, str]] = deque(maxlen=FILE_MAX)
        self._verrou = threading.Lock()
        self._dernier_echec = 0.0
        threading.Thread(target=self._boucle, name="journal-loki", daemon=True).start()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            ligne = self.format(record)
            etiquettes = {
                "service": self.service,
                "niveau": record.levelname.lower(),
                "evenement": str(getattr(record, "evenement", None) or getattr(record, "action", None) or "journal")[:80],
            }
            self._file.append((etiquettes, str(int(record.created * 1e9)), ligne))
        except Exception:  # noqa: BLE001 — un journal ne doit jamais lever
            pass

    def _boucle(self) -> None:
        while True:
            time.sleep(PERIODE_S)
            self.vider()

    def vider(self) -> None:
        with self._verrou:
            lot = []
            while self._file and len(lot) < LOT_MAX:
                lot.append(self._file.popleft())
        if not lot:
            return
        flux: dict[str, dict] = {}
        for etiquettes, ts, ligne in lot:
            cle = json.dumps(etiquettes, sort_keys=True)
            flux.setdefault(cle, {"stream": etiquettes, "values": []})["values"].append([ts, ligne])
        corps = json.dumps({"streams": list(flux.values())}).encode()
        req = urllib.request.Request(self.url, data=corps, method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": self._auth,
                                              "User-Agent": f"vtlvs-journal/{self.service}"})
        try:
            urllib.request.urlopen(req, timeout=5).read()
        except Exception as exc:  # noqa: BLE001
            maintenant = time.monotonic()
            if maintenant - self._dernier_echec > 300:
                # Sur la sortie standard, pas dans le journal : on ne boucle pas sur soi-même.
                print(f"[journal-loki] envoi impossible ({type(exc).__name__}) — {len(lot)} lignes abandonnées",
                      file=sys.stderr)
                self._dernier_echec = maintenant


def installer(journal: logging.Logger, service: str, formatter: logging.Formatter) -> bool:
    url, utilisateur, mdp = os.getenv("LOKI_URL", ""), os.getenv("LOKI_USER", ""), os.getenv("LOKI_PASSWORD", "")
    if not (url and utilisateur and mdp):
        return False
    if any(isinstance(h, LokiHandler) for h in journal.handlers):
        return True
    h = LokiHandler(url, utilisateur, mdp, service, formatter)
    h.setLevel(logging.INFO)
    journal.addHandler(h)
    return True
