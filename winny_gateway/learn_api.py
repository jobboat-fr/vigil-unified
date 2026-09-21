"""Écrire dans LEARN au nom d'une personne — par l'API LEARN, jamais en base directement.

La passerelle lit les tables LEARN pour décider (voir learn_link.py), mais toute écriture
passe par l'API LEARN (api.vtlvs.com) avec le jeton de service et `X-Learn-On-Behalf-Of` :
mêmes règles de rôle, de portée et de journal d'accès que si la personne agissait elle-même.
`X-Learn-Principal: agent` dit la vérité sur l'origine — un contenu produit par l'IA.

Env : LEARN_API_URL (https://api.vtlvs.com), HBS_API_TOKEN (le jeton de service LEARN).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from winny_gateway.logging import get_logger

logger = get_logger(__name__)


class LearnWriteError(RuntimeError):
    pass


def configured() -> bool:
    return bool(os.getenv("LEARN_API_URL") and os.getenv("HBS_API_TOKEN"))


async def deposit_text(*, on_behalf_of: str, session_id: str, filename: str, text: str,
                       kind: str = "compte_rendu_seance") -> dict[str, Any]:
    """Dépose un texte au coffre de la session. Renvoie l'objet coffre créé."""
    if not configured():
        raise LearnWriteError("LEARN_API_URL / HBS_API_TOKEN absents")
    base = os.environ["LEARN_API_URL"].rstrip("/")
    headers = {
        "Authorization": f"Bearer {os.environ['HBS_API_TOKEN']}",
        "X-Learn-On-Behalf-Of": on_behalf_of,
        "X-Learn-Principal": "agent",
    }
    files = {"fichier": (filename, text.encode("utf-8"), "text/plain")}
    data = {"kind": kind, "session_id": session_id, "visibility": "tenant", "retention_basis": "direct"}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{base}/api/v1/learn/vault", headers=headers, files=files, data=data)
    if r.status_code >= 400:
        raise LearnWriteError(f"coffre LEARN {r.status_code}: {r.text[:200]}")
    return r.json()


async def envoyer_courriel(
    *,
    on_behalf_of: str,
    tenant_id: str,
    email: str,
    cle: str,
    ctx: dict[str, Any],
    related_kind: str | None = None,
    related_id: str | None = None,
) -> dict[str, Any] | None:
    """Fait partir un message par l'entonnoir de LEARN, au nom d'une personne réelle.

    **Au mieux, jamais au prix de la demande.** Cette fonction est appelée après qu'un
    ticket a été enregistré : si l'envoi échoue — fournisseur muet, clé absente, réseau —
    la demande de la personne reste en base et l'écran continue de dire « reçu ». Perdre
    un message parce que l'accusé n'a pas pu partir serait échanger l'essentiel contre
    l'accessoire. L'échec est journalisé, pas propagé.

    Ce n'est pas une précaution théorique : au 21/09, `vtlvs.com` ne peut rien expédier
    (la clé Resend du compte qui détient le domaine est révoquée). Tout ce qui passe par
    ici doit donc continuer de fonctionner sans courrier.

    L'entonnoir de LEARN reste seul maître de ce qui part réellement : liste de
    suppression, préférences, consentement, validation du gabarit, et une ligne dans
    `learn_notifications` — y compris quand il refuse.
    """
    if not configured():
        logger.warning(
            "Courriel « %s » non expédié : LEARN_API_URL / HBS_API_TOKEN absents.", cle,
            extra={"evenement": "mail.transport_absent", "modele": cle})
        return None

    base = os.environ["LEARN_API_URL"].rstrip("/")
    headers = {
        "Authorization": f"Bearer {os.environ['HBS_API_TOKEN']}",
        "X-Learn-On-Behalf-Of": on_behalf_of,
    }
    charge = {
        "tenant_id": tenant_id,
        "email": email,
        "cle": cle,
        "ctx": ctx,
        "related_kind": related_kind,
        "related_id": related_id,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{base}/api/v1/learn/interne/envoi", headers=headers, json=charge)
    except Exception as e:  # noqa: BLE001 — journalisé, jamais propagé
        logger.warning(
            "Courriel « %s » non expédié : %s", cle, e,
            extra={"evenement": "mail.transport_echec", "modele": cle})
        return None

    if r.status_code >= 400:
        logger.warning(
            "Courriel « %s » refusé par LEARN (%s) : %s", cle, r.status_code, r.text[:200],
            extra={"evenement": "mail.refus", "modele": cle, "statut": r.status_code})
        return None
    return r.json()
