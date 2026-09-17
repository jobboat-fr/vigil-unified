"""Limitation de débit applicative — par personne, en plus de la bordure Cloudflare.

La bordure limite par adresse IP ; elle ne voit pas qui est connecté. Ici, la clé est la
personne (identifiant du jeton) — ou, pour un appel sans jeton, l'adresse IP. Trois paliers :

  * ``ia``       — appels qui déclenchent un modèle (brainstorm, rédaction, affiner, agent,
                   tri, résumé, conseil) : 30 par minute ;
  * ``ecriture`` — POST, PUT, PATCH, DELETE : 120 par minute ;
  * ``lecture``  — GET : 600 par minute.

Fenêtre glissante en mémoire : le service tourne sur une instance. Refus : 429, `Retry-After`
exact, message en français, événement `securite.limite_debit_atteinte` (journalisé une fois par
fenêtre et par personne, pour ne pas noyer le journal pendant une rafale).

Libres : /health, les webhooks signés, OPTIONS.

Copie à l'identique dans hbs-backend (`app/limite_debit.py`), avec ses propres motifs IA.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import os
import re
import time
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

journal = logging.getLogger("winny_gw.securite")

PALIERS = {"ia": (30, 60.0), "ecriture": (120, 60.0), "lecture": (600, 60.0)}

MOTIFS_IA = re.compile(
    r"/(brainstorm|refine|agent|canvas-brainstorm|canvas-diagram|summarize|triage|council|deliberate|ask)(/|$)"
)
LIBRES = re.compile(r"^/health$|/webhooks?(/|$)|/livekit/webhook$")


def _cle_personne(request: Request) -> str:
    """La personne derrière la requête, sans vérifier la signature : ce n'est qu'une clé de compteur.
    L'authentification, elle, est faite plus loin par la route."""
    auth = request.headers.get("authorization") or ""
    jeton = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if jeton.count(".") == 2:
        try:
            charge = jeton.split(".")[1]
            sub = json.loads(base64.urlsafe_b64decode(charge + "=" * (-len(charge) % 4))).get("sub")
            if sub:
                return f"u:{sub}"
        except (ValueError, json.JSONDecodeError):
            pass
    if jeton:
        # identifiant d'agent ou jeton de service : une empreinte, jamais le jeton
        delegant = request.headers.get("X-Learn-On-Behalf-Of") or request.headers.get("X-WinnyWoo-User-Id") or ""
        return "j:" + hashlib.sha256((jeton + "|" + delegant).encode()).hexdigest()[:16]
    ip = (request.headers.get("cf-connecting-ip")
          or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
          or (request.client.host if request.client else "inconnue"))
    return f"ip:{ip}"


def palier(methode: str, chemin: str) -> str:
    if MOTIFS_IA.search(chemin) and methode != "GET":
        return "ia"
    return "lecture" if methode in ("GET", "HEAD") else "ecriture"


class Compteur:
    def __init__(self) -> None:
        self._fenetres: dict[tuple[str, str], deque[float]] = {}
        self._signale: dict[tuple[str, str], float] = {}
        self._dernier_menage = time.monotonic()

    def essayer(self, cle: str, nom: str, maintenant: float | None = None) -> tuple[bool, int]:
        """(accepté, secondes avant qu'une place se libère)."""
        limite, fenetre = PALIERS[nom]
        t = time.monotonic() if maintenant is None else maintenant
        q = self._fenetres.setdefault((cle, nom), deque())
        while q and q[0] <= t - fenetre:
            q.popleft()
        if len(q) >= limite:
            return False, max(1, math.ceil(q[0] + fenetre - t))
        q.append(t)
        if t - self._dernier_menage > 300:
            self._menage(t)
        return True, 0

    def premier_refus(self, cle: str, nom: str, maintenant: float | None = None) -> bool:
        t = time.monotonic() if maintenant is None else maintenant
        k = (cle, nom)
        if k in self._signale and self._signale[k] > t - PALIERS[nom][1]:
            return False
        self._signale[k] = t
        return True

    def _menage(self, t: float) -> None:
        self._dernier_menage = t
        for k in [k for k, q in self._fenetres.items() if not q or q[-1] <= t - 120]:
            self._fenetres.pop(k, None)
        for k in [k for k, v in self._signale.items() if v <= t - 120]:
            self._signale.pop(k, None)


COMPTEUR = Compteur()


class LimiteDebitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        chemin = request.url.path
        if (os.getenv("RATE_LIMIT_MODE", "enforce").lower() == "off" or request.method == "OPTIONS"
                or LIBRES.search(chemin)):
            return await call_next(request)
        cle = _cle_personne(request)
        nom = palier(request.method, chemin)
        ok, attente = COMPTEUR.essayer(cle, nom)
        if ok:
            return await call_next(request)
        requete_id = request.headers.get("x-request-id")
        if COMPTEUR.premier_refus(cle, nom):
            limite, fenetre = PALIERS[nom]
            journal.warning(
                "Limite de débit « %s » atteinte (%s requêtes / %ss) pour %s sur %s %s — refus pendant %ss.",
                nom, limite, int(fenetre), cle[:24], request.method, chemin, attente,
                extra={"evenement": "securite.limite_debit_atteinte", "palier": nom, "cle": cle[:24],
                       "route": chemin, "methode": request.method, "requete_id": requete_id,
                       "attente_s": attente})
        message = ("Vous avez sollicité l'assistant très souvent en peu de temps. Il sera de nouveau disponible "
                   f"dans {attente} s." if nom == "ia" else
                   f"Trop de requêtes en peu de temps. Réessayez dans {attente} s.")
        return JSONResponse({"ok": False, "error": "trop_de_requetes", "detail": message,
                             "palier": nom, "requete_id": requete_id},
                            status_code=429, headers={"Retry-After": str(attente)})
