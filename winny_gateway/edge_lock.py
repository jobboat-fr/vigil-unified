"""Verrou d'origine : une requête doit être passée par la bordure Cloudflare (le Worker).

Le Worker d'app.vtlvs.com ajoute `x-vtlvs-edge: <secret>` à chaque requête qu'il relaie. Une
requête qui arrive sans ce secret a contourné Cloudflare — donc son WAF, sa limitation de débit
et sa protection DDoS — en appelant directement l'URL Railway.

ORIGIN_LOCK_MODE :
  * `enforce` — refus 403, journalisé ;
  * `observe` — laissée passer, journalisée (pour recenser les appelants directs avant de
    verrouiller) ;
  * `off`     — rien.
ORIGIN_EDGE_SECRET : le secret partagé avec le Worker. Sans lui, le mode `enforce` retombe sur
`observe` et le dit dans le journal : un verrou sans clé fermerait tout le service.

Toujours libres : /health (sonde de Railway).
"""

from __future__ import annotations

import hmac
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from winny_gateway.logging import get_logger

logger = get_logger("winny_gw.securite")

LIBRES = ("/health",)


def _ip(request: Request) -> str:
    return (request.headers.get("cf-connecting-ip")
            or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
            or (request.client.host if request.client else "inconnue"))


class EdgeLockMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        mode = os.getenv("ORIGIN_LOCK_MODE", "observe").strip().lower()
        secret = os.getenv("ORIGIN_EDGE_SECRET", "")
        if mode == "off" or request.url.path in LIBRES or request.method == "OPTIONS":
            return await call_next(request)
        recu = request.headers.get("x-vtlvs-edge", "")
        if secret and recu and hmac.compare_digest(recu, secret):
            return await call_next(request)

        contexte = {
            "evenement": "securite.origine_hors_bordure",
            "route": request.url.path,
            "methode": request.method,
            "ip": _ip(request),
            "user_agent": (request.headers.get("user-agent") or "")[:160],
            "requete_id": request.headers.get("x-request-id"),
            "mode": mode,
            "raison": "secret_absent" if not recu else ("secret_non_configure" if not secret else "secret_invalide"),
        }
        if mode == "enforce" and secret:
            logger.warning(
                "Requête refusée : elle n'est pas passée par la bordure Cloudflare (%s %s depuis %s, %s).",
                request.method, request.url.path, contexte["ip"], contexte["raison"], extra=contexte)
            return JSONResponse(
                {"ok": False, "error": "acces_direct_refuse",
                 "detail": "Cette adresse n'est pas publique. Passez par https://app.vtlvs.com.",
                 "requete_id": contexte["requete_id"]},
                status_code=403)
        logger.info(
            "Requête reçue sans passer par la bordure Cloudflare (%s %s depuis %s) — laissée passer, mode %s.",
            request.method, request.url.path, contexte["ip"], mode if secret else "observe (secret absent)",
            extra=contexte)
        return await call_next(request)
