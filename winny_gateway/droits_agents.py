"""Qui peut faire travailler un agent, et à quelle condition : l'abonnement.

Décidé par Azer le 29/09 : chaque surface agentique s'ouvre **sous abonnement**, et seulement
dans VTLVS. Ce module est l'unique endroit qui en décide, côté serveur ; l'application lit son
verdict (`GET /v1/agents/abonnements`) au lieu de le deviner.

Qui paie quoi
-------------
* Compte VTLVS (il a une ligne `learn_profiles`) : l'**organisme** est abonné à l'agent —
  `learn_tenants.abonnements` contient `azzmin`, `azzco` ou `azzcom`. C'est la colonne que
  la publication lit déjà ; le webhook Stripe l'alimentera quand le paiement des agents ouvrira.
* `super_admin` : toujours ouvert — c'est l'opérateur de la plateforme.
* Compte sans ligne `learn_profiles` : rien. C'était la règle de vigil-ai.xyz (un abonnement
  Stripe de son organisation) ; le site est éteint depuis le 29/09, la règle est retirée.

Quelle surface relève de quel agent
-----------------------------------
* la salle de réunion (intervention, résumé, amener un agent, avatar) → AZZMIN : le travailleur
  de salle est « azzmin-salle » et la délégation qu'il reçoit est signée `agent="azzmin"` ;
* le Studio et le conseil qui l'alimente (propositions, cahiers des charges, contrats, notes,
  rapports) → AZZCO, dont c'est le métier ;
* l'assistant de l'application → n'importe lequel des trois : c'est la porte d'entrée des agents.

Deux modes (`AGENTS_ABONNEMENT_MODE`)
-------------------------------------
* `observe` (défaut) : rien n'est bloqué, chaque refus qui *aurait* eu lieu est journalisé
  (`agents.abonnement_manquant`). On recense ainsi qui serait coupé avant de couper.
* `enforce` : refus 402 `abonnement_requis`, avec le nom de l'agent à souscrire.
Un mode inconnu vaut `enforce` : une faute de frappe doit fermer, pas ouvrir.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import Depends, HTTPException

from winny_gateway.auth import scoped_user
from winny_gateway.db import db_select
from winny_gateway.logging import get_logger

logger = get_logger("winny_gw.securite")

AGENTS: tuple[str, ...] = ("azzmin", "azzco", "azzcom")
NOMS = {"azzmin": "AZZMIN", "azzco": "AZZCO", "azzcom": "AZZCOM"}

# Surface → agent requis. `None` : l'un quelconque des trois. Chaque agent est aussi sa propre
# surface (délégation, contexte).
SURFACES: dict[str, str | None] = {
    "salle": "azzmin",
    "studio": "azzco",
    "conseil": "azzco",
    "assistant": None,
    **{a: a for a in AGENTS},
}


# ── Les formules d'accès (Azer, 29/09) ─────────────────────────────────────────────────
#
# contrat_hbs : HBS FORMATION, par l'Accord de collaboration — la plateforme (Art. 2.1) et les
#               trois agents (Art. 2.5), inclus dans l'abonnement de maintenance tant qu'aucun
#               tarif n'est notifié (Art. 2.7). Codé en dur, parce que c'est le contrat qui le
#               donne, pas un paiement. Tout compte de l'organisme HBS en hérite — y compris
#               la personne qui a acheté une formation HBS ou un agent par HBS.
#               Le privilège agents est révocable (Art. 2.6) : CONTRAT_HBS_AGENTS=revoque le
#               ferme sans toucher au reste, et HBS retombe sur ses abonnements réels.
# payant      : un autre organisme qui détient une formule payante (plateforme `vtlvs` ou un
#               agent). Toute la plateforme ; les agents, eux, un par un, selon l'abonnement.
# gratuit     : un organisme sans rien de payé. Pas d'agent, et des plafonds (PLAFONDS_GRATUITS).
#
# L'offre d'entrée montrée après un refus se déduit des prix fixés par Azer (lib/agentique.ts
# côté application) : l'agent refusé, ou le moins cher (AZZCOM) pour un plafond gratuit.
SLUG_CONTRAT = "hbs"
FORMULES = ("super_admin", "contrat_hbs", "payant", "gratuit")

#: Seule l'offre gratuite est plafonnée : toute formule payante ouvre la plateforme entière.
PLAFONDS_GRATUITS: dict[str, int] = {"projets": 1, "artefacts": 5}
_NOMS_RESSOURCES = {"projets": ("projet", "projets"), "artefacts": ("document du Studio", "documents du Studio")}


def _contrat_hbs_agents_actif() -> bool:
    return (os.getenv("CONTRAT_HBS_AGENTS") or "actif").strip().lower() != "revoque"


def mode() -> str:
    m = (os.getenv("AGENTS_ABONNEMENT_MODE") or "observe").strip().lower()
    return m if m in ("observe", "enforce") else "enforce"


async def _profil(user_id: str) -> dict[str, Any] | None:
    rows = await db_select("learn_profiles", filters={"id": user_id},
                           columns="id,role,tenant_id", limit=1, allow_unscoped=True)
    return rows[0] if rows else None


async def _organisme(tenant_id: str | None) -> tuple[str | None, set[str]]:
    """Le slug de l'organisme et ses abonnements."""
    if not tenant_id:
        return None, set()
    rows = await db_select("learn_tenants", filters={"id": tenant_id},
                           columns="slug,abonnements", limit=1, allow_unscoped=True)
    if not rows:
        return None, set()
    return rows[0].get("slug"), set(rows[0].get("abonnements") or [])


async def etat(user_id: str) -> dict[str, Any]:
    """Les agents ouverts à cette personne, et pourquoi. Aucun modèle, aucune supposition."""
    p = await _profil(user_id)
    if p is None:
        return {"compte": None, "role": None, "motif": None, "formule": "gratuit",
                "plafonds": dict(PLAFONDS_GRATUITS), "agents": {a: False for a in AGENTS}}
    if p.get("role") == "super_admin":
        return {"compte": "vtlvs", "role": "super_admin", "motif": "super_admin", "formule": "super_admin",
                "plafonds": {}, "agents": {a: True for a in AGENTS}}
    slug, abos = await _organisme(p.get("tenant_id"))
    if slug == SLUG_CONTRAT:
        agents = {a: True for a in AGENTS} if _contrat_hbs_agents_actif() else {a: a in abos for a in AGENTS}
        return {"compte": "vtlvs", "role": p.get("role"), "motif": "contrat_hbs", "formule": "contrat_hbs",
                "plafonds": {}, "agents": agents}
    formule = "payant" if abos else "gratuit"
    return {"compte": "vtlvs", "role": p.get("role"), "motif": "abonnement_organisme" if abos else None,
            "formule": formule, "plafonds": {} if abos else dict(PLAFONDS_GRATUITS),
            "agents": {a: a in abos for a in AGENTS}}


async def verifier_plafond(user_id: str, ressource: str, deja: int) -> None:
    """Lève 402 si l'offre gratuite atteint son plafond pour `ressource` (`deja` = le compte actuel).

    Appliqué dès `observe` : ce plafond n'a jamais été ouvert, il n'y a donc pas de parcours
    existant à ne pas casser. Base injoignable → on laisse passer : un plafond de volume ne
    justifie pas de bloquer une personne qui travaille (au contraire du verrou des agents).
    """
    try:
        e = await etat(user_id)
    except Exception:  # noqa: BLE001
        return
    limite = e.get("plafonds", {}).get(ressource)
    if limite is None or deja < limite:
        return
    un, plusieurs = _NOMS_RESSOURCES.get(ressource, (ressource, ressource))
    logger.info("Plafond de l'offre gratuite atteint (%s).", ressource,
                extra={"evenement": "offre.plafond_gratuit", "ressource": ressource, "utilisateur": user_id,
                       "limite": limite, "role": e.get("role")})
    raise HTTPException(status_code=402, detail={
        "error": "plafond_offre_gratuite", "ressource": ressource, "limite": limite, "role": e.get("role"),
        "message": (f"L'offre gratuite comprend {limite} {un if limite == 1 else plusieurs}. "
                    "Une formule payante ouvre la plateforme sans plafond."),
    })


def _ouvert(e: dict[str, Any], surface: str) -> bool:
    agent = SURFACES[surface]
    return any(e["agents"].values()) if agent is None else bool(e["agents"].get(agent))


def refus(surface: str, role: str | None = None) -> HTTPException:
    agent = SURFACES[surface]
    nom = NOMS[agent] if agent else "l'un des agents AZZMIN, AZZCO ou AZZCOM"
    return HTTPException(status_code=402, detail={
        "error": "abonnement_requis", "surface": surface, "agent": agent, "role": role,
        "message": f"Cette fonction est réservée aux organismes abonnés à {nom}.",
    })


async def verifier(user_id: str, surface: str) -> dict[str, Any]:
    """Lève 402 en mode `enforce` si la surface n'est pas ouverte ; journalise en `observe`."""
    try:
        e = await etat(user_id)
    except Exception as exc:  # noqa: BLE001 — base injoignable : on ferme en enforce, on laisse en observe
        logger.error("Vérification d'abonnement impossible (%s).", surface,
                     extra={"evenement": "agents.abonnement_inverifiable", "surface": surface,
                            "utilisateur": user_id, "mode": mode(), "erreur": type(exc).__name__})
        if mode() == "enforce":
            raise HTTPException(status_code=503, detail={
                "error": "abonnement_inverifiable",
                "message": "L'abonnement n'a pas pu être vérifié. Réessayez dans un instant."}) from exc
        return {"compte": None, "role": None, "motif": None, "agents": {a: False for a in AGENTS}}
    if _ouvert(e, surface):
        return e
    contexte = {"evenement": "agents.abonnement_manquant", "surface": surface,
                "agent": SURFACES[surface], "utilisateur": user_id, "role": e.get("role"),
                "compte": e.get("compte"), "mode": mode()}
    if mode() == "enforce":
        logger.info("Surface agentique refusée faute d'abonnement (%s).", surface, extra=contexte)
        raise refus(surface, e.get("role"))
    logger.warning("Surface agentique ouverte SANS abonnement — mode observe (%s).", surface, extra=contexte)
    return e


def exiger(surface: str):
    """Dépendance FastAPI : `_: dict = Depends(droits_agents.exiger("salle"))`."""
    if surface not in SURFACES:
        raise ValueError(f"surface inconnue : {surface}")

    # scoped_user et non get_current_user : quand le travailleur de salle appelle avec le jeton de
    # service au nom d'une personne, c'est l'abonnement de CETTE personne qui compte.
    async def _dep(user: dict[str, Any] = Depends(scoped_user)) -> dict[str, Any]:
        uid = str(user.get("sub") or "")
        if not uid:
            raise HTTPException(status_code=401, detail="no user id in token")
        return await verifier(uid, surface)

    return _dep
