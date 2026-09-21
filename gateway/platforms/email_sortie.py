"""Le transport sortant du courrier de l'agent.

L'agent reçoit par IMAP et répondait par SMTP, avec le mot de passe de la boîte sur l'hôte.
Deux raisons de changer, et la seconde est la vraie.

La première est matérielle : les ports SMTP sortants (25, 465, 587) sont bloqués depuis
l'hôte OVH où tourne l'agent. Aucune réponse ne partait.

La seconde : un identifiant de boîte sur une machine où tourne un modèle avec un terminal,
c'est la capacité d'écrire à n'importe qui depuis l'adresse de l'organisme, sans plafond et
sans trace. Rétablir SMTP aurait résolu le symptôme en installant le problème.

L'agent appelle donc LEARN, qui envoie. Il ne détient aucune clé.

**Le verrou porté ici : répondre seulement.** Le destinataire doit être présent dans le fil
courant *et* dans `EMAIL_ALLOWED_USERS`. Ce seul verrou annule le publipostage et
l'essentiel de l'exfiltration par courriel : on ne peut écrire qu'à quelqu'un qui a déjà
écrit, et qui figure sur une liste posée par un humain. Les trois autres — plafond,
journal, masquage — vivent côté LEARN, là où sont la base et les secrets.

Il est ici et pas dans une consigne parce qu'une consigne se contourne par le texte qu'on
donne à lire au modèle. Un `if` sur le chemin d'envoi ne se contourne pas.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class EnvoiRefuse(RuntimeError):
    """L'envoi n'a pas été tenté : un verrou l'a arrêté avant le transport."""


def destinataires_permis() -> set[str]:
    brut = os.getenv("EMAIL_ALLOWED_USERS", "")
    return {a.strip().lower() for a in brut.split(",") if a.strip()}


def verifier_reponse_seule(to_addr: str, fils: dict[str, dict[str, str]]) -> None:
    """Le verrou n° 1. Lève `EnvoiRefuse` plutôt que de laisser passer.

    Deux conditions, et il faut les deux :

    * **le fil** — l'adresse doit avoir écrit à l'agent, sinon ce n'est pas une réponse ;
    * **la liste** — elle doit figurer dans `EMAIL_ALLOWED_USERS`, sinon n'importe qui
      pourrait s'ouvrir un fil en écrivant le premier.

    La liste seule ne suffirait pas non plus : un agent pourrait écrire spontanément à
    toutes les adresses autorisées. C'est la conjonction qui fait le verrou.
    """
    adresse = (to_addr or "").strip().lower()
    if not adresse:
        raise EnvoiRefuse("destinataire vide")

    permis = destinataires_permis()
    if not permis:
        # Liste vide = personne, jamais « tout le monde ». Un garde-fou qui s'ouvre quand
        # on oublie de le configurer n'est pas un garde-fou.
        raise EnvoiRefuse("EMAIL_ALLOWED_USERS non configurée : aucun envoi autorisé")
    if adresse not in permis:
        raise EnvoiRefuse(f"destinataire hors liste autorisée : {adresse}")

    connus = {k.strip().lower() for k in fils}
    if adresse not in connus:
        raise EnvoiRefuse(f"aucun fil ouvert avec {adresse} : l'agent ne répond qu'à ce qu'on lui écrit")


async def expedier(
    *,
    to_addr: str,
    sujet: str,
    corps: str,
    fils: dict[str, dict[str, str]],
    in_reply_to: str | None = None,
    references: str | None = None,
) -> dict[str, Any]:
    """Fait partir une réponse par LEARN. Lève si un verrou refuse ou si LEARN refuse."""
    verifier_reponse_seule(to_addr, fils)

    base = (os.getenv("LEARN_API_URL") or "https://api.vtlvs.com").rstrip("/")
    jeton = os.getenv("HBS_API_TOKEN")
    tenant = os.getenv("LEARN_TENANT_ID")
    au_nom_de = os.getenv("LEARN_ON_BEHALF_OF")
    if not (jeton and tenant and au_nom_de):
        raise EnvoiRefuse("HBS_API_TOKEN / LEARN_TENANT_ID / LEARN_ON_BEHALF_OF absents")

    charge = {
        "tenant_id": tenant,
        "destinataire": to_addr,
        "sujet": sujet,
        "corps": corps,
        "in_reply_to": in_reply_to,
        "references": references,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            f"{base}/api/v1/learn/interne/agent-mail",
            headers={
                "Authorization": f"Bearer {jeton}",
                "X-Learn-On-Behalf-Of": au_nom_de,
                # Dit la vérité sur l'origine : c'est un agent qui écrit. LEARN s'en sert
                # pour appliquer les verrous qui ne valent que pour lui.
                "X-Learn-Principal": "agent",
            },
            json=charge,
        )

    if r.status_code == 429:
        raise EnvoiRefuse(f"plafond atteint : {r.text[:160]}")
    if r.status_code >= 400:
        raise EnvoiRefuse(f"LEARN {r.status_code}: {r.text[:200]}")

    rep = r.json()
    if rep.get("masques"):
        logger.warning(
            "[Email] %s secret(s) masqué(s) dans une réponse de l'agent vers %s",
            rep["masques"], to_addr)
    return rep
