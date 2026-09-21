"""Mon compte (RGPD) et support, pour l'application VTLVS.

  POST  /api/v1/compte/export                 art. 15/20 — tout ce que la plateforme sait de moi
  POST  /api/v1/compte/suppression            art. 17 — effacement, avec les conservations légales
  POST  /api/v1/support/public                formulaire de contact sans compte (site, aide publique)
  POST  /api/v1/support/demande               une demande d'aide, connecté
  GET   /api/v1/support/boite                 administration : demandes de son organisme (super_admin : toutes)
  POST  /api/v1/support/boite/{id}/reponse    administration : répondre
  PATCH /api/v1/support/boite/{id}            administration : changer le statut

L'effacement suit la règle de LEARN (migration 0046) : ce que la loi impose de garder
(émargements, signatures, évaluations, coffre) reste, pseudonymisé ; le reste est supprimé. Le
compte d'authentification n'est pas supprimé mais neutralisé (e-mail pseudonyme, connexion
bloquée) : le supprimer casserait les chaînes de preuves qui y font référence.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from winny_gateway.auth import get_current_user
from winny_gateway import learn_api
from winny_gateway.db import audit_log, db_delete, db_insert, db_select, db_update, get_admin_client
from winny_gateway.logging import get_logger

logger = get_logger("winny_gw.compte")
router = APIRouter(tags=["compte"])

TABLES_PERSONNELLES = ["user_preferences", "onboarding_state", "approval_requests", "artifacts", "rooms"]


def _uid(user: dict[str, Any]) -> str:
    if user.get("service_token") or user.get("agent_credential"):
        raise HTTPException(status_code=403, detail={
            "error": "reserve_a_la_personne", "detail": "Seule la personne elle-même peut faire cette demande."})
    uid = str(user.get("sub") or "")
    if not uid:
        raise HTTPException(status_code=401, detail="session_invalide")
    return uid


def _rpc(nom: str, uid: str) -> Any:
    return get_admin_client().rpc(nom, {"p_user": uid}).execute().data


async def _profil(uid: str) -> dict[str, Any]:
    rows = await db_select("learn_profiles", filters={"id": uid}, columns="id,role,tenant_id,full_name,email",
                           limit=1, allow_unscoped=True)
    return rows[0] if rows else {}


# ── Export ──────────────────────────────────────────────────────────────────
@router.post("/api/v1/compte/export")
async def exporter(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    learn = await asyncio.to_thread(_rpc, "learn_export_profil", uid)
    passerelle: dict[str, Any] = {}
    for table in TABLES_PERSONNELLES + ["support_tickets"]:
        try:
            passerelle[table] = await db_select(table, filters={"user_id": uid}, limit=5000)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Export : table %s illisible (%s).", table, exc)
            passerelle[table] = []
    logger.info("Export RGPD fourni à %s.", uid, extra={"evenement": "rgpd.export", "acteur": uid})
    await audit_log(user_id=uid, event_type="rgpd", action="export", component="compte", details={})
    return {"ok": True, "data": {"genere_le": datetime.now(UTC).isoformat(), "plateforme": learn,
                                 "espace_de_travail": passerelle}}


# ── Suppression ─────────────────────────────────────────────────────────────
class SuppressionBody(BaseModel):
    confirmation: str = Field(description="Le mot SUPPRIMER, en toutes lettres.")
    motif: str | None = Field(default=None, max_length=500)


@router.post("/api/v1/compte/suppression")
async def supprimer(body: SuppressionBody, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    if body.confirmation.strip().upper() != "SUPPRIMER":
        raise HTTPException(status_code=422, detail={
            "error": "confirmation_requise", "detail": "Écrivez SUPPRIMER pour confirmer."})
    prof = await _profil(uid)
    if prof.get("role") == "super_admin":
        raise HTTPException(status_code=409, detail={
            "error": "editeur_non_effacable",
            "detail": "Le compte éditeur ne peut pas être supprimé tant qu'aucun autre éditeur n'existe."})
    try:
        resultat = await asyncio.to_thread(_rpc, "learn_effacer_profil", uid)
    except Exception as exc:  # noqa: BLE001
        logger.error("Effacement LEARN impossible pour %s : %s", uid, exc,
                     extra={"evenement": "rgpd.effacement_echec", "acteur": uid})
        raise HTTPException(status_code=503, detail={
            "error": "effacement_indisponible", "detail": "La suppression n'a pas pu aboutir. Rien n'a été effacé ; réessayez."}) from exc

    for table in TABLES_PERSONNELLES:
        try:
            await db_delete(table, filters={"user_id": uid})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Effacement : table %s (%s).", table, exc)
    for col in ("owner_id", "grantee_id"):
        try:
            await db_delete("artifact_shares", filters={col: uid}, allow_unscoped=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Effacement : partages (%s).", exc)

    pseudo = f"supprime+{uid.replace('-', '')}@supprime.invalid"
    compte_neutralise = False
    try:
        await asyncio.to_thread(lambda: get_admin_client().auth.admin.update_user_by_id(
            uid, {"email": pseudo, "ban_duration": "876000h", "user_metadata": {}}))
        compte_neutralise = True
    except Exception as exc:  # noqa: BLE001
        logger.error("Neutralisation du compte d'authentification impossible pour %s : %s", uid, exc,
                     extra={"evenement": "rgpd.neutralisation_echec", "acteur": uid})

    logger.warning("Compte %s supprimé à la demande de la personne (%s).", uid, prof.get("role"),
                   extra={"evenement": "rgpd.effacement", "acteur": uid, "role": prof.get("role"),
                          "compte_neutralise": compte_neutralise})
    await audit_log(user_id=None, event_type="rgpd", action="effacement", component="compte",
                    details={"profil": uid, "role": prof.get("role"), "resultat": resultat,
                             "motif_fourni": bool(body.motif)})
    return {"ok": True, "data": {
        "supprime": True,
        "message": "Votre compte est supprimé. Les preuves de formation que la loi oblige à garder sont conservées sans votre nom.",
        "conserve": (resultat or {}).get("conserve", []) if isinstance(resultat, dict) else [],
    }}


# ── Support ─────────────────────────────────────────────────────────────────
class DemandePublique(BaseModel):
    nom: str = Field(min_length=2, max_length=120)
    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    sujet: str = Field(min_length=3, max_length=160)
    message: str = Field(min_length=10, max_length=5000)
    organisme: str | None = Field(default=None, max_length=160)
    site_web: str | None = Field(default=None, description="Piège à robots : doit rester vide.")


class DemandeConnectee(BaseModel):
    sujet: str = Field(min_length=3, max_length=160)
    message: str = Field(min_length=10, max_length=5000)
    page: str | None = Field(default=None, max_length=200)


#: Le repli en mémoire, et rien d'autre qu'un repli.
#:
#: Il vit dans le processus : il repart à zéro à chaque déploiement, et deux instances ne
#: partagent rien. Contre quelqu'un qui insiste, cela ne tient pas — il suffit d'attendre
#: la prochaine mise en ligne, ou de tomber sur l'autre instance. Le compteur qui fait foi
#: est en base (`learn_public_throttle`, migration 0016) ; celui-ci ne sert que lorsque la
#: base ne répond pas, et mieux vaut alors un plafond imparfait que pas de plafond.
_fenetres: dict[str, deque[float]] = defaultdict(deque)


def _trop_de_demandes_memoire(cle: str, limite: int, fenetre: float) -> bool:
    t = time.monotonic()
    q = _fenetres[cle]
    while q and q[0] <= t - fenetre:
        q.popleft()
    if len(q) >= limite:
        return True
    q.append(t)
    return False


async def _trop_de_demandes(cle: str, limite: int = 5, fenetre: int = 3600) -> bool:
    """Le plafond, compté en base pour survivre aux déploiements et aux instances.

    `learn_public_throttle` rend `true` quand la requête est **autorisée** — on inverse
    donc. La fenêtre glisse côté base, sur une seule ligne par seau, sans table à purger.

    Si la base ne répond pas, on retombe sur le compteur en mémoire plutôt que de laisser
    passer : un formulaire public sans aucun plafond est une invitation, et refuser à tort
    quelques messages pendant une panne coûte moins cher que d'en accepter dix mille.
    """
    try:
        client = get_admin_client()
        reponse = await asyncio.to_thread(
            lambda: client.rpc(
                "learn_public_throttle",
                {"p_bucket": f"support:{cle}", "p_window": int(fenetre), "p_limit": int(limite)},
            ).execute()
        )
        autorise = reponse.data
        if isinstance(autorise, list):
            autorise = autorise[0] if autorise else None
        if isinstance(autorise, bool):
            return not autorise
        logger.warning("Plafond de support : réponse inattendue de la base (%r).", autorise,
                       extra={"evenement": "support.plafond_inattendu"})
    except Exception as e:  # noqa: BLE001 — on se rabat, on ne casse pas le formulaire
        logger.warning("Plafond de support : base injoignable (%s), repli en mémoire.", e,
                       extra={"evenement": "support.plafond_repli"})
    return _trop_de_demandes_memoire(cle, limite, fenetre)


async def _creer_ticket(*, user_id: str | None, email: str, sujet: str, message: str, source: str,
                        tenant_id: str | None = None) -> dict[str, Any]:
    row = {"user_id": user_id, "email": email, "subject": sujet, "status": "open", "source": source}
    if tenant_id:
        row["tenant_id"] = tenant_id
    ticket = await db_insert("support_tickets", row, allow_unscoped=True)
    if not ticket:
        raise HTTPException(status_code=503, detail={"error": "demande_non_enregistree",
                                                     "detail": "Votre demande n'a pas pu être enregistrée. Réessayez."})
    await db_insert("support_messages", {"ticket_id": ticket["id"], "author_type": "user", "author_id": user_id,
                                         "author_email": email, "body": message}, allow_unscoped=True)
    return ticket


#: Le délai annoncé dans l'accusé. Annoncer un délai qu'on ne tient pas coûte plus cher
#: que de ne rien annoncer : une promesse tenue à moitié se retient mieux qu'un silence.
DELAI_REPONSE = "un jour ouvré"


def _plateforme() -> tuple[str, str] | None:
    """L'organisme et la personne au nom de qui le support écrit.

    Le formulaire public n'appartient à aucun organisme : il faut donc dire explicitement
    lequel porte le courrier du support, plutôt que d'en deviner un. Non configuré, le
    support continue d'enregistrer les demandes — il n'envoie simplement pas d'accusé, et
    le journal le dit.
    """
    tenant = (os.getenv("VTLVS_TENANT_PLATEFORME") or "").strip()
    porteur = (os.getenv("VTLVS_SUPPORT_AU_NOM_DE") or "").strip()
    return (tenant, porteur) if tenant and porteur else None


async def _accuser_reception(ticket: dict[str, Any], email: str, sujet: str, source: str) -> None:
    """Accusé au demandeur, puis avis aux porteurs. Ni l'un ni l'autre ne peut faire échouer
    la demande : elle est déjà enregistrée quand on arrive ici."""
    couple = _plateforme()
    if not couple:
        logger.warning(
            "Accusé de réception non envoyé : VTLVS_TENANT_PLATEFORME / VTLVS_SUPPORT_AU_NOM_DE absents.",
            extra={"evenement": "support.accuse_impossible", "ticket": ticket["id"]})
        return
    tenant, porteur = couple
    reference = str(ticket["id"])[:8].upper()

    # L'accusé ne porte **pas** le message soumis : sinon le formulaire public devient un
    # remailer anonyme, capable d'expédier un texte arbitraire vers une adresse arbitraire
    # depuis un domaine vérifié, avec notre SPF et notre réputation.
    await learn_api.envoyer_courriel(
        on_behalf_of=porteur, tenant_id=tenant, email=email, cle="support_accuse",
        ctx={"reference": reference, "delai": DELAI_REPONSE, "objet": sujet},
        related_kind="support_ticket", related_id=str(ticket["id"]))

    for exploitant in _exploitants():
        await learn_api.envoyer_courriel(
            on_behalf_of=porteur, tenant_id=tenant, email=exploitant, cle="support_avis",
            ctx={"reference": reference, "source": source, "objet": sujet},
            related_kind="support_ticket", related_id=str(ticket["id"]))


def _exploitants() -> list[str]:
    """Qui est prévenu qu'une demande est arrivée. Même variable que la copie de l'entonnoir."""
    brut = os.getenv("VTLVS_MAIL_COPIE") or ""
    return [a.strip() for a in brut.split(",") if a.strip()][:5]


@router.post("/api/v1/support/public")
async def demande_publique(body: DemandePublique, request: Request) -> dict[str, Any]:
    ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "")
    empreinte = hashlib.sha256(ip.encode()).hexdigest()[:12]
    if body.site_web:
        logger.info("Formulaire de contact : robot écarté (piège rempli).",
                    extra={"evenement": "securite.robot_formulaire", "ip": empreinte})
        return {"ok": True, "data": {"recu": True}}
    if await _trop_de_demandes(f"ip:{empreinte}") or await _trop_de_demandes(f"mail:{str(body.email).lower()}"):
        raise HTTPException(status_code=429, detail={"error": "trop_de_demandes",
                                                     "detail": "Vous avez déjà envoyé plusieurs messages. Nous revenons vers vous."},
                            headers={"Retry-After": "3600"})
    message = body.message + (f"\n\n— {body.nom}" + (f", {body.organisme}" if body.organisme else ""))
    ticket = await _creer_ticket(user_id=None, email=str(body.email), sujet=body.sujet, message=message, source="site")
    logger.info("Demande de contact publique reçue (ticket %s).", ticket["id"],
                extra={"evenement": "support.demande_publique", "ticket": ticket["id"], "ip": empreinte})
    await _accuser_reception(ticket, str(body.email), body.sujet, "site public")
    return {"ok": True, "data": {"recu": True, "reference": str(ticket["id"])[:8].upper()}}


@router.post("/api/v1/support/demande")
async def demande_connectee(body: DemandeConnectee, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    prof = await _profil(uid)
    if await _trop_de_demandes(f"u:{uid}", limite=10):
        raise HTTPException(status_code=429, detail={"error": "trop_de_demandes",
                                                     "detail": "Plusieurs demandes sont déjà ouvertes. Nous y répondons."})
    message = body.message + (f"\n\n(page : {body.page})" if body.page else "")
    ticket = await _creer_ticket(user_id=uid, email=prof.get("email") or user.get("email") or "", sujet=body.sujet,
                                 message=message, source="application", tenant_id=prof.get("tenant_id"))
    logger.info("Demande d'aide de %s (%s), ticket %s.", uid, prof.get("role"), ticket["id"],
                extra={"evenement": "support.demande", "acteur": uid, "ticket": ticket["id"]})
    courriel = prof.get("email") or user.get("email") or ""
    if courriel:
        await _accuser_reception(ticket, courriel, body.sujet, "application")
    return {"ok": True, "data": {"id": ticket["id"], "reference": str(ticket["id"])[:8].upper()}}


async def _admin(uid: str) -> dict[str, Any]:
    prof = await _profil(uid)
    if prof.get("role") not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail={"error": "reserve_a_l_administration",
                                                     "detail": "La boîte de support est réservée à l'administration."})
    return prof


async def _ticket_visible(ticket_id: str, prof: dict[str, Any]) -> dict[str, Any]:
    rows = await db_select("support_tickets", filters={"id": ticket_id}, limit=1, allow_unscoped=True)
    if not rows:
        raise HTTPException(status_code=404, detail={"error": "demande_introuvable"})
    t = rows[0]
    if prof.get("role") != "super_admin" and str(t.get("tenant_id") or "") != str(prof.get("tenant_id") or ""):
        raise HTTPException(status_code=404, detail={"error": "demande_introuvable"})
    return t


@router.get("/api/v1/support/boite")
async def boite(statut: str | None = None, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    prof = await _admin(uid)
    filtres: dict[str, Any] = {} if prof.get("role") == "super_admin" else {"tenant_id": prof.get("tenant_id")}
    if statut:
        filtres["status"] = statut
    tickets = await db_select("support_tickets", filters=filtres, order_by="-created_at", limit=200, allow_unscoped=True)
    out = []
    for t in tickets:
        msgs = await db_select("support_messages", filters={"ticket_id": t["id"]}, order_by="created_at",
                               limit=100, allow_unscoped=True)
        out.append({**t, "messages": [{"auteur": m.get("author_type"), "email": m.get("author_email"),
                                       "texte": m.get("body"), "le": m.get("created_at")} for m in msgs]})
    return {"ok": True, "data": {"demandes": out}}


class Reponse(BaseModel):
    message: str = Field(min_length=1, max_length=5000)


@router.post("/api/v1/support/boite/{ticket_id}/reponse")
async def repondre(ticket_id: str, body: Reponse, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    prof = await _admin(uid)
    t = await _ticket_visible(ticket_id, prof)
    await db_insert("support_messages", {"ticket_id": t["id"], "author_type": "staff", "author_id": uid,
                                         "author_email": prof.get("email"), "body": body.message}, allow_unscoped=True)
    await db_update("support_tickets", {"status": "answered", "updated_at": datetime.now(UTC).isoformat()},
                    filters={"id": t["id"]}, allow_unscoped=True)
    logger.info("Réponse à la demande %s par %s.", t["id"], uid,
                extra={"evenement": "support.reponse", "acteur": uid, "ticket": t["id"]})

    # L'adresse est **relue sur le ticket**, jamais prise dans la requête ni dans le corps
    # du message : sinon répondre deviendrait un moyen d'écrire à n'importe qui depuis un
    # domaine vérifié, ce qui est exactement la faille que l'accusé évite en se taisant.
    couple = _plateforme()
    destinataire = (t.get("email") or "").strip()
    if couple and destinataire:
        tenant, porteur = couple
        envoi = await learn_api.envoyer_courriel(
            on_behalf_of=str(uid), tenant_id=tenant, email=destinataire, cle="support_reponse",
            ctx={"reference": str(t["id"])[:8].upper(), "corps": body.message},
            related_kind="support_ticket", related_id=str(t["id"]))
        if envoi is None:
            # L'administration doit savoir que sa réponse est enregistrée mais pas partie,
            # sinon elle croit avoir répondu et attend un retour qui ne viendra pas.
            return {"ok": True, "data": {"repondu": True, "expedie": False}}
        return {"ok": True, "data": {"repondu": True, "expedie": True}}

    return {"ok": True, "data": {"repondu": True, "expedie": False}}


class Statut(BaseModel):
    statut: Literal["open", "answered", "closed"]


@router.patch("/api/v1/support/boite/{ticket_id}")
async def changer_statut(ticket_id: str, body: Statut, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = _uid(user)
    prof = await _admin(uid)
    t = await _ticket_visible(ticket_id, prof)
    await db_update("support_tickets", {"status": body.statut, "updated_at": datetime.now(UTC).isoformat()},
                    filters={"id": t["id"]}, allow_unscoped=True)
    return {"ok": True, "data": {"statut": body.statut}}
