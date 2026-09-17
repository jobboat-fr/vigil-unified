"""Identité des agents — la couche déterministe entre un agent et les données.

Un agent (AZZCOM, AZZCO, AZZMIN) ne décide jamais lui-même pour qui il agit. Trois règles,
vérifiées ici avant toute route, sans rien demander au modèle :

1. **Son identifiant d'accès** (`vtlvs_ag_…`) est reconnu par empreinte dans
   `learn_agent_credentials` ; révoqué ou inconnu → 401.
2. **Pour qui** : une délégation signée par la plateforme (`X-Vtlvs-Delegation`, 10 min,
   émise à la demande de la personne connectée, liée à cet agent) ; à défaut, l'en-tête
   `X-Learn-On-Behalf-Of` n'est accepté que pour les personnes inscrites dans `delegants`.
   Toute autre personne → 403, journalisé comme événement de sécurité.
3. **Jusqu'où** : le rôle réel de la personne (relu en base), plafonné par `role_max` ;
   `lecture_seule` interdit toute écriture.

Copie à l'identique de `hbs-backend/app/learn/agent_identite.py` :
les deux hôtes appliquent la même règle, sur la même table.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

PREFIXE = "vtlvs_ag_"
DUREE_DELEGATION_S = 600

NIVEAUX = {"super_admin": 0, "admin": 1, "formateur": 2, "entreprise": 3,
           "auditeur": 4, "apprenant": 5, "prospect": 6}


class RefusIdentite(Exception):
    """Refus d'identité : code HTTP, code d'erreur stable, phrase française."""

    def __init__(self, statut: int, code: str, message: str) -> None:
        super().__init__(message)
        self.statut, self.code, self.message = statut, code, message


def est_identifiant_agent(jeton: str) -> bool:
    return jeton.startswith(PREFIXE)


def empreinte(jeton: str) -> str:
    return hashlib.sha256(jeton.encode()).hexdigest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def signer_delegation(secret: str, *, sub: str, agent: str, role: str | None = None,
                      tenant_id: str | None = None, page: str | None = None,
                      duree_s: int = DUREE_DELEGATION_S, maintenant: float | None = None) -> str:
    """Une délégation courte : « cet agent peut agir pour cette personne pendant 10 minutes »."""
    if not secret:
        raise RefusIdentite(503, "delegation_non_configuree", "La signature des délégations n'est pas configurée.")
    t = int(maintenant if maintenant is not None else time.time())
    corps = {"v": 1, "sub": sub, "agent": agent, "role": role, "tenant_id": tenant_id,
             "page": page, "iat": t, "exp": t + max(30, min(duree_s, 3600))}
    charge = _b64(json.dumps(corps, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64(hmac.new(secret.encode(), charge.encode(), hashlib.sha256).digest())
    return f"{charge}.{sig}"


def lire_delegation(secret: str, jeton: str, *, maintenant: float | None = None) -> dict[str, Any]:
    """Vérifie signature et échéance ; lève RefusIdentite sinon."""
    if not secret:
        raise RefusIdentite(503, "delegation_non_configuree", "La signature des délégations n'est pas configurée.")
    try:
        charge, sig = jeton.split(".", 1)
        attendu = _b64(hmac.new(secret.encode(), charge.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, attendu):
            raise ValueError("signature")
        corps = json.loads(_unb64(charge))
    except (ValueError, json.JSONDecodeError) as exc:
        raise RefusIdentite(403, "delegation_invalide", "La délégation présentée n'est pas authentique.") from exc
    if corps.get("v") != 1 or not corps.get("sub") or not corps.get("agent"):
        raise RefusIdentite(403, "delegation_invalide", "La délégation présentée est incomplète.")
    if int(corps.get("exp") or 0) < int(maintenant if maintenant is not None else time.time()):
        raise RefusIdentite(403, "delegation_expiree", "La délégation a expiré ; la personne doit la renouveler.")
    return corps


def delegant_autorise(identifiant: dict[str, Any], *, entete_delegant: str, delegation: dict[str, Any] | None) -> str:
    """Pour qui cet agent agit — décidé ici, jamais par l'agent.

    `identifiant` : la ligne de learn_agent_credentials. `delegation` : délégation signée déjà
    vérifiée, ou None.
    """
    entete = (entete_delegant or "").strip()
    if delegation is not None:
        if delegation.get("agent") != identifiant.get("agent"):
            raise RefusIdentite(403, "delegation_autre_agent",
                                "Cette délégation a été donnée à un autre agent.")
        if entete and entete != delegation["sub"]:
            raise RefusIdentite(400, "delegation_ambigue",
                                "La requête désigne deux personnes différentes.")
        return str(delegation["sub"])
    if not entete:
        raise RefusIdentite(401, "delegant_requis",
                            "Un agent doit toujours dire pour qui il agit.")
    permis = {str(d) for d in (identifiant.get("delegants") or [])}
    if entete not in permis:
        raise RefusIdentite(403, "delegation_refusee",
                            "Cet agent n'est pas autorisé à agir pour cette personne sans sa délégation.")
    return entete


def role_plafonne(role: str, role_max: str | None) -> str:
    """Le rôle le moins puissant des deux : l'agent n'agit jamais au-dessus de son plafond."""
    if not role_max or role_max not in NIVEAUX:
        return role
    if role not in NIVEAUX:
        return role
    return role if NIVEAUX[role] >= NIVEAUX[role_max] else role_max


METHODES_LECTURE = {"GET", "HEAD", "OPTIONS"}
