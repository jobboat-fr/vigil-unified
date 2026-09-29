"""Les routes héritées de WinnyWoo ne servent pas les comptes VTLVS.

La passerelle sert deux applications : VTLVS (app.vtlvs.com) et l'ancienne VIGIL
(vigil-ai.xyz), encore en ligne. Les routes de trading de WinnyWoo — portefeuille, ordres,
prévisions, backtest, signaux, clés de courtier, trading automatique, marché, chat — sont
restées montées pour VIGIL. Aucun écran VTLVS ne les appelle (relevé le 29/09 : zéro appel
dans `web/src`), mais un compte VTLVS pouvait les atteindre : y enregistrer des clés de
courtier, y lancer des analyses payées par la plateforme.

Cette dépendance se pose au montage du routeur (`app.include_router(..., dependencies=...)`) :
* sans jeton : rien ne change, la route décide (les données de marché publiques de VIGIL
  restent publiques) ;
* jeton invalide : rien ne change, la route répond elle-même 401 ;
* jeton de service (outillage opérateur de VIGIL) : laissé passer ;
* identifiant d'agent VTLVS (`vtlvs_ag_…`) ou compte VTLVS (ligne `learn_profiles`) : 404,
  la même réponse qu'une route inexistante — on ne confirme pas ce qui existe derrière.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials

from winny_gateway import auth
from winny_gateway import db as _db
from winny_gateway.logging import get_logger

logger = get_logger("winny_gw.securite")


async def _est_compte_vtlvs(user_id: str) -> bool:
    rows = await _db.db_select("learn_profiles", filters={"id": user_id}, columns="id", limit=1, allow_unscoped=True)
    return bool(rows)


async def hors_vtlvs(request: Request,
                     credentials: HTTPAuthorizationCredentials | None = Depends(auth._bearer)) -> None:
    if credentials is None:
        return
    try:
        user: dict[str, Any] = await auth.get_current_user(request, credentials)
    except HTTPException:
        return  # la route répondra elle-même 401
    if user.get("service_token") and not user.get("agent_credential"):
        return
    uid = str(user.get("sub") or "")
    if user.get("agent_credential") or (uid and await _est_compte_vtlvs(uid)):
        logger.warning("Route WinnyWoo refusée à un compte VTLVS (%s %s).", request.method, request.url.path,
                       extra={"evenement": "securite.route_winnywoo_refusee", "acteur": uid,
                              "route": request.url.path, "agent": bool(user.get("agent_credential"))})
        raise HTTPException(status_code=404, detail="Not Found")
