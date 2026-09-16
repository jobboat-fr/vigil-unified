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
