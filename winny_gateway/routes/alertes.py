"""Les alertes Grafana, remises par l'entonnoir de courriel.

Quatre règles d'alerte existent et se déclenchent. Aucune ne prévenait personne : il n'y
avait ni point de contact ni politique de notification. Une alerte qui ne sort pas de
Grafana est un tableau de bord que quelqu'un doit penser à regarder — c'est-à-dire, en
pratique, une alerte qui n'existe pas.

**Pourquoi un webhook et pas un envoi SMTP depuis Grafana.** Grafana tourne sur l'hôte OVH,
d'où les ports SMTP sortants sont bloqués : un point de contact « email » y resterait muet,
et muet de la même façon silencieuse qu'aujourd'hui. Il faudrait aussi y poser un mot de
passe de boîte, sur la machine qui héberge déjà l'agent — exactement ce qu'on a retiré à la
phase 11.

Grafana appelle donc cette route, et c'est la passerelle qui fait partir le message par
LEARN. Aucune clé sur l'hôte, une ligne dans `learn_notifications` pour chaque alerte
envoyée, et le même chemin que tout le reste du courrier.

L'authentification est un secret partagé comparé en temps constant. C'est assez pour une
route qui n'accepte qu'un format connu et n'écrit rien en base ; ce n'est pas une session,
et elle ne doit jamais en devenir une.
"""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from winny_gateway import learn_api
from winny_gateway.logging import get_logger

logger = get_logger("winny_gw.alertes")
router = APIRouter(tags=["alertes"])

#: Au-delà, on tronque. Une alerte Grafana peut embarquer des dizaines d'instances ; le
#: message doit rester lisible sur un téléphone, à l'heure où on le lit.
MAX_LIGNES = 12


class Alerte(BaseModel):
    """Le sous-ensemble du format Grafana qu'on lit. Le reste est ignoré volontairement :
    accepter un format large, c'est accepter d'en dépendre."""

    status: str = Field(default="firing", max_length=20)
    alerts: list[dict[str, Any]] = Field(default_factory=list)
    title: str | None = Field(default=None, max_length=300)


def _secret_valide(request: Request) -> bool:
    attendu = (os.getenv("GRAFANA_WEBHOOK_SECRET") or "").strip()
    if not attendu:
        # Pas de secret configuré = route fermée. Jamais ouverte : un webhook sans
        # authentification permet à n'importe qui de faire partir des courriels d'alerte
        # depuis le domaine de l'organisme.
        return False
    presente = (request.headers.get("x-alerte-secret") or "").strip()
    return bool(presente) and hmac.compare_digest(presente, attendu)


def _resume(a: Alerte) -> tuple[str, list[str]]:
    """Le titre et les lignes du message, à partir de la charge Grafana."""
    etat = "déclenchée" if a.status == "firing" else "résolue"
    titre = a.title or f"Alerte {etat}"

    lignes: list[str] = []
    for item in a.alerts[:MAX_LIGNES]:
        etiquettes = item.get("labels") or {}
        annotations = item.get("annotations") or {}
        nom = etiquettes.get("alertname") or "alerte"
        gravite = etiquettes.get("gravite")
        detail = annotations.get("summary") or annotations.get("description") or ""
        morceaux = [str(nom)]
        if gravite:
            morceaux.append(f"gravité {gravite}")
        if detail:
            morceaux.append(str(detail)[:300])
        lignes.append(" — ".join(morceaux))

    if len(a.alerts) > MAX_LIGNES:
        lignes.append(f"… et {len(a.alerts) - MAX_LIGNES} autre(s).")
    if not lignes:
        lignes.append("Aucun détail transmis par Grafana.")
    return f"{titre} ({etat})", lignes


@router.post("/api/v1/alertes/grafana", status_code=202)
async def alerte_grafana(body: Alerte, request: Request) -> dict[str, Any]:
    """Reçoit une alerte et la fait partir aux exploitants."""
    if not _secret_valide(request):
        # On ne dit pas laquelle des deux raisons : ni « secret absent », ni « secret
        # faux ». Les distinguer renseignerait sur l'état de la configuration.
        logger.warning("Alerte refusée : secret invalide ou absent.",
                       extra={"evenement": "securite.alerte_refusee"})
        raise HTTPException(status_code=401, detail={"error": "secret_invalide"})

    titre, lignes = _resume(body)

    tenant = (os.getenv("VTLVS_TENANT_PLATEFORME") or "").strip()
    porteur = (os.getenv("VTLVS_SUPPORT_AU_NOM_DE") or "").strip()
    destinataires = [a.strip() for a in (os.getenv("VTLVS_MAIL_COPIE") or "").split(",") if a.strip()][:5]

    if not (tenant and porteur and destinataires):
        # L'alerte est perdue, et c'est précisément ce qu'il faut journaliser en `error` :
        # une alerte non remise doit elle-même être une alerte.
        logger.error(
            "Alerte « %s » non remise : configuration de courriel incomplète.", titre,
            extra={"evenement": "alerte.non_remise", "titre": titre})
        return {"remise": False, "raison": "configuration_incomplete"}

    remises = 0
    for adresse in destinataires:
        envoi = await learn_api.envoyer_courriel(
            on_behalf_of=porteur, tenant_id=tenant, email=adresse,
            cle="alerte_organisme", ctx={"titre": titre, "lignes": lignes},
            related_kind="alerte")
        if envoi is not None:
            remises += 1

    logger.info("Alerte « %s » remise à %d destinataire(s).", titre, remises,
                extra={"evenement": "alerte.remise", "titre": titre, "remises": remises})
    return {"remise": remises > 0, "destinataires": remises}
