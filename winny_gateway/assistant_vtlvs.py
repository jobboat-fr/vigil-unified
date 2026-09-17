"""L'assistant de l'application (page /chat) — pour chaque rôle, avec ses propres données.

Pourquoi ce module : l'assistant relayait vers l'ancien serveur d'agent (HERMES_URL), éteint ;
la page avait été coupée. Il répond désormais ici, sans serveur intermédiaire, et suit trois
règles déterministes, décidées avant tout appel au modèle :

1. **Qui peut l'utiliser**
   * super_admin, admin, formateur, entreprise, auditeur : toujours ;
   * apprenant : **pendant ses créneaux de formation** (du quart d'heure avant le début au quart
     d'heure après la fin d'un créneau d'une session où il est inscrit) ; **hors formation,
     sous abonnement** (abonnement actif de son organisation) ;
   * prospect ou rôle inconnu : non.
2. **Ce qu'il sait** : les données sont lues avec le jeton de la personne elle-même (API LEARN,
   RLS) — son agenda des 14 prochains jours et ses actions requises. Il ne peut rien voir de plus
   que ce que la personne voit dans l'application.
3. **Comment il répond** : amorce agentique + contexte d'identité (winny.council), données
   délimitées, réponses courtes en points.
"""

from __future__ import annotations

import os
import time
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from winny.council import guard
from winny.council.confiance import PourQui, contexte_identite, donnees
from winny_gateway.db import db_select
from winny_gateway.logging import get_logger

logger = get_logger("winny_gw.assistant")

ROLES_TOUJOURS = {"super_admin", "admin", "formateur", "entreprise", "auditeur"}
MARGE = timedelta(minutes=15)
STATUTS_INSCRIT = ("inscrit", "confirme")

GUIDE_ROLE: dict[str, str] = {
    "super_admin": "Tout l'espace : organismes, personnes, sessions, coffre, qualité, pages métier (salle, mail, CRM, finance, juridique, équipe agentique), identité & e-mails, actions requises.",
    "admin": "Son organisme : demandes d'inscription, personnes, sessions et créneaux, émargement, coffre, documents à signer, actions requises, identité & e-mails, salle de réunion, studio.",
    "formateur": "Ses sessions : calendrier, émargement de ses créneaux, salle de réunion (animer, sous-salles), contenus, évaluations, studio.",
    "entreprise": "Ses salariés inscrits : sessions, présences, documents, salle de réunion en participant, studio.",
    "auditeur": "Lecture seule de l'organisme audité : preuves Qualiopi, coffre, émargements, documents.",
    "apprenant": "Son parcours : accueil, documents à signer, calendrier de ses créneaux, salle de réunion pendant la formation, ses actions, studio.",
}

CONSIGNE = (
    "Tu es Vigil, l'assistant de l'application VTLVS (plateforme de formation). Tu aides la personne à "
    "s'orienter dans l'application et à avancer sur ce qu'elle doit faire.\n"
    "Style : réponse directe en 1 à 5 puces courtes, pas d'article, pas de préambule. Termine si utile par "
    "UNE prochaine étape concrète (le nom de la page à ouvrir dans le menu).\n"
    "Tu ne réalises aucune action toi-même dans cette conversation : tu expliques où et comment la faire. "
    "Si une information n'est pas dans les données fournies, dis-le simplement."
)


class AccesRefuse(Exception):
    def __init__(self, statut: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.statut, self.code, self.message, self.details = statut, code, message, details or {}


def _ts(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


async def profil(user_id: str) -> dict[str, Any]:
    rows = await db_select("learn_profiles", filters={"id": user_id},
                           columns="id,role,tenant_id,full_name,email", limit=1, allow_unscoped=True)
    return rows[0] if rows else {}


async def creneaux_apprenant(user_id: str) -> list[dict[str, Any]]:
    """Les créneaux des sessions où la personne est inscrite (lecture déterministe, par son identifiant)."""
    sessions: set[str] = set()
    for statut in STATUTS_INSCRIT:
        for e in await db_select("learn_enrollments", filters={"apprenant_id": user_id, "status": statut},
                                 columns="session_id", limit=200, allow_unscoped=True):
            sessions.add(str(e["session_id"]))
    creneaux: list[dict[str, Any]] = []
    for sid in sessions:
        creneaux += await db_select("learn_session_slots", filters={"session_id": sid},
                                    columns="id,session_id,starts_at,ends_at,status", limit=500, allow_unscoped=True)
    return [c for c in creneaux if (c.get("status") or "") not in ("cancelled", "annule", "annulé")]


async def abonnement_actif(user_id: str) -> bool:
    for m in await db_select("org_members", filters={"user_id": user_id}, columns="org_id", limit=20, allow_unscoped=True):
        for s in await db_select("subscriptions", filters={"org_id": m["org_id"]}, columns="status,current_period_end",
                                 limit=20, allow_unscoped=True):
            fin = _ts(s.get("current_period_end"))
            if s.get("status") in ("active", "trialing") and (fin is None or fin > datetime.now(UTC)):
                return True
    return False


async def verifier_acces(user_id: str, maintenant: datetime | None = None) -> dict[str, Any]:
    """Décide, sans modèle, si la personne peut parler à l'assistant maintenant. Lève AccesRefuse sinon."""
    now = maintenant or datetime.now(UTC)
    p = await profil(user_id)
    role = p.get("role")
    if role in ROLES_TOUJOURS:
        return {"profil": p, "motif": "role"}
    if role != "apprenant":
        raise AccesRefuse(403, "assistant_non_disponible", "L'assistant n'est pas disponible pour votre compte.")
    creneaux = await creneaux_apprenant(user_id)
    for c in creneaux:
        debut, fin = _ts(c.get("starts_at")), _ts(c.get("ends_at"))
        if debut and fin and debut - MARGE <= now <= fin + MARGE:
            return {"profil": p, "motif": "creneau", "fin_creneau": fin.isoformat()}
    if await abonnement_actif(user_id):
        return {"profil": p, "motif": "abonnement"}
    prochains = sorted((_ts(c["starts_at"]) for c in creneaux if _ts(c.get("starts_at")) and _ts(c["starts_at"]) > now))
    raise AccesRefuse(
        402, "assistant_hors_formation",
        "L'assistant vous accompagne pendant vos créneaux de formation. En dehors, il est accessible avec l'abonnement.",
        {"prochain_creneau": prochains[0].isoformat() if prochains else None},
    )


async def _learn_get(jeton: str, chemin: str) -> Any:
    base = (os.getenv("LEARN_API_URL") or "https://api.vtlvs.com").rstrip("/")
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(base + "/api/v1/learn" + chemin, headers={"Authorization": f"Bearer {jeton}"})
        return r.json() if r.status_code == 200 else None


CHAMPS_AGENDA = ("starts_at", "ends_at", "session_code", "session_title", "program_title", "title",
                 "modality", "room_name", "formateur_name", "half")


async def instantane(jeton: str) -> str:
    """Ce que la personne voit elle-même : agenda des 14 prochains jours, actions à faire. Avec SON jeton."""
    auj = datetime.now(UTC).date()
    lignes: list[str] = []
    try:
        cal = await _learn_get(jeton, f"/calendar?from={auj}&to={auj + timedelta(days=14)}")
        items = (cal or {}).get("items") or []
        if items:
            lignes.append("Agenda (14 jours) :")
            for it in items[:12]:
                lignes.append("- " + " · ".join(str(it[k]) for k in CHAMPS_AGENDA if it.get(k)))
        else:
            lignes.append("Agenda (14 jours) : rien de prévu.")
    except (httpx.HTTPError, ValueError):
        lignes.append("Agenda : indisponible pour le moment.")
    try:
        act = await _learn_get(jeton, "/me/actions")
        items = (act or {}).get("items") if isinstance(act, dict) else act
        if items:
            lignes.append("Actions à faire :")
            for a in items[:8]:
                lignes.append(f"- {a.get('title') or a.get('titre') or a.get('kind')} (échéance {a.get('due_at') or a.get('echeance') or '—'})")
        elif items is not None:
            lignes.append("Actions à faire : aucune.")
    except (httpx.HTTPError, ValueError):
        pass
    return "\n".join(lignes)


class Memoire:
    """Les derniers échanges d'une conversation (en mémoire, 8 tours, 2 h, 2 000 conversations)."""

    def __init__(self) -> None:
        self._d: OrderedDict[str, tuple[float, list[tuple[str, str]]]] = OrderedDict()

    def lire(self, cle: str) -> list[tuple[str, str]]:
        v = self._d.get(cle)
        if not v or time.monotonic() - v[0] > 7200:
            return []
        return v[1]

    def ajouter(self, cle: str, question: str, reponse: str) -> None:
        tours = (self.lire(cle) + [(question, reponse)])[-8:]
        self._d[cle] = (time.monotonic(), tours)
        self._d.move_to_end(cle)
        while len(self._d) > 2000:
            self._d.popitem(last=False)


MEMOIRE = Memoire()


async def repondre(*, user_id: str, jeton: str, message: str, session_id: str, page: str | None,
                   acces: dict[str, Any]) -> dict[str, Any]:
    from winny.council.providers import ask
    from winny.council.registry import worker_registry

    p = acces["profil"]
    organisme = None
    if p.get("tenant_id"):
        rows = await db_select("learn_tenants", filters={"id": p["tenant_id"]}, columns="name", limit=1, allow_unscoped=True)
        organisme = rows[0]["name"] if rows else None
    qui = PourQui(user_id=user_id, role=p.get("role"), nom=p.get("full_name"), organisme=organisme)
    systeme = (contexte_identite(qui) + "\n\n" + CONSIGNE + "\n\nCe que ce rôle trouve dans l'application : "
               + GUIDE_ROLE.get(p.get("role") or "", "") )
    cle = f"{user_id}:{session_id}"
    historique = "\n".join(f"Personne : {q}\nVigil : {r}" for q, r in MEMOIRE.lire(cle))
    prompt = (
        "Données de la personne (lues avec ses propres droits) :\n"
        + donnees("données de la personne", await instantane(jeton), surface="assistant", longueur_max=4000)
        + (f"\n\nPage ouverte : {page}" if page else "")
        + ("\n\nÉchanges précédents :\n" + donnees("échanges précédents", historique, surface="assistant", longueur_max=4000)
           if historique else "")
        + "\n\nMessage de la personne :\n" + donnees("message", message, surface="assistant", longueur_max=2000)
    )
    debut = time.monotonic()
    with guard.use_feature("assistant"):
        res = await ask(worker_registry()["primary"], prompt, system=systeme, temperature=0.3, max_tokens=500)
    texte = (res.get("output") or "").strip()
    if res.get("stub") or not texte:
        texte = ("L'assistant ne peut pas répondre pour le moment. Vos pages restent utilisables : "
                 "ouvrez le menu pour continuer, et réessayez dans un instant.")
    MEMOIRE.ajouter(cle, message, texte)
    logger.info("Assistant : réponse à %s (%s, accès %s) en %s ms.", user_id, p.get("role"), acces.get("motif"),
                int((time.monotonic() - debut) * 1000),
                extra={"evenement": "assistant.reponse", "acteur": user_id, "role": p.get("role"),
                       "motif_acces": acces.get("motif"), "stub": bool(res.get("stub"))})
    return {"texte": texte, "stub": bool(res.get("stub"))}
