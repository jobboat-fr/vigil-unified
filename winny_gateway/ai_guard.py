"""Coupe-circuit IA côté passerelle : quelle fonction appelle, et l'état exposé à l'app.

Le coupe-circuit lui-même vit dans ``winny.council.guard`` : c'est là que passent tous les
appels de modèle. Ici :

  * ``feature("<nom>")`` — dépendance posée sur un routeur. Elle nomme la fonction pour la
    durée de la requête, ce qui permet de couper une fonction seule
    (``AI_DISABLED_FEATURES=meeting``) sans toucher aux autres ;
  * ``GET /v1/ai/health`` — l'app lit cet état et affiche « assistant indisponible »
    quand il le faut. Les pages continuent de fonctionner : lire, créer, modifier,
    enregistrer ne dépendent d'aucun modèle.

Fonctions nommées : meeting (salle, conseil), mail (tri), ops (équipe agentique),
studio (artefacts), vault (classement des documents), council (conseil hors salle).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from winny.council import guard
from winny_gateway.auth import get_current_user

FEATURES = ("meeting", "mail", "ops", "studio", "vault", "council", "assistant")


def feature(name: str):
    async def _use_feature() -> None:
        # Une dépendance async s'exécute dans la tâche de la requête : la variable de
        # contexte posée ici est visible de l'endpoint et de tous les appels à `ask`.
        guard.set_feature(name)

    return _use_feature


def status() -> dict[str, Any]:
    from winny.council.registry import worker_registry

    h = guard.health()
    # Toutes les fonctions passent aujourd'hui par le fournisseur du conseil.
    fam = worker_registry()["primary"]["family"]
    p = h["providers"].get(fam)
    provider_down = bool(p and p["state"] in ("open", "not_configured"))
    features = {f: h["enabled"] and f not in h["disabled_features"] and not provider_down for f in FEATURES}
    return {**h, "provider": fam, "available": h["enabled"] and not provider_down, "features": features}


router = APIRouter(prefix="/v1/ai", tags=["ai"])


@router.get("/health")
async def ai_health(_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """État du coupe-circuit : interrupteurs, fournisseurs, fonctions disponibles."""
    return {"ok": True, "data": status()}
