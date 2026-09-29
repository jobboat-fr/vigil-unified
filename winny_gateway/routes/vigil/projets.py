"""Projets du Studio — le canevas façon Railway : un projet, six étapes, des cartes reliées.

Un projet se construit en six étapes classiques, enregistrées une par une :

  1. ``nom_objectif``         le nom et l'objectif ;
  2. ``perimetre_livrables``  le périmètre et les livrables ;
  3. ``equipe``               les personnes et les agents, chacun avec son rôle ;
  4. ``jalons``               les jalons datés ;
  5. ``ressources``           les liens et documents utiles ;
  6. ``validation``           qui valide, et où en est la validation.

Puis il vit sur un canevas où l'on pose des cartes : une **salle** de réunion, un **artefact**
du Studio (avec la salle et l'agent dont il vient, quand on les connaît), un **agent**
(AZZMIN, AZZCO, AZZCOM, avec l'état de l'abonnement de l'organisme), un élément du
**coffre** (document, session, personne — un lien, rien de plus).

Aucune route ici n'appelle de modèle, sauf une : ``POST /{id}/agents/{agent}/travail``.
Celle-là fait TOUJOURS travailler l'agent et garde sa sortie entière dans
``studio_agent_runs`` ; mais si l'organisme n'est pas abonné à cet agent, la réponse ne
contient que le premier paragraphe et la liste des points traités — le reste ne quitte
jamais le serveur. C'est le comportement voulu (le produit se montre avant de se vendre),
d'où l'absence délibérée de ``droits_agents.exiger`` sur cette route : il refuserait en 402
avant que l'aperçu n'existe.

Accès : le propriétaire seulement.
TODO : partager un projet (lecture / modification) comme on partage un artefact
(028_artifact_shares) ; il faudra une table de partages dédiée et la même règle
« même organisme, révocable, jamais effacé ».
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from winny.council.confiance import donnees
from winny.council.providers import ask
from winny_gateway import droits_agents
from winny_gateway.auth import scoped_user
from winny_gateway.db import db_delete, db_insert, db_select, db_update
from winny_gateway.logging import get_logger
from winny_gateway.routes.vigil import studio as studio_mod

logger = get_logger(__name__)
journal_securite = get_logger("winny_gw.securite")
router = APIRouter(prefix="/v1/projets", tags=["studio"])

_PROJETS = "studio_projects"
_CARTES = "studio_project_cards"
_TRAVAUX = "studio_agent_runs"

AgentId = Literal["azzmin", "azzco", "azzcom"]
MESSAGE_VERROU = "Abonnez-vous pour lire la suite."


# ── Les six étapes ──────────────────────────────────────────────────────────
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EtapeNomObjectif(_Strict):
    nom: str = Field(min_length=1, max_length=200)
    objectif: str = Field(default="", max_length=4000)


class EtapePerimetreLivrables(_Strict):
    perimetre: str = Field(default="", max_length=4000)
    livrables: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("livrables")
    @classmethod
    def _livrables(cls, v: list[str]) -> list[str]:
        propres = [s.strip() for s in v if s and s.strip()]
        if any(len(s) > 300 for s in propres):
            raise ValueError("Un livrable tient en 300 caractères au plus.")
        return propres


class MembreEquipe(_Strict):
    kind: Literal["personne", "agent"]
    id: str = Field(min_length=1, max_length=200)
    role: str = Field(default="", max_length=200)
    nom: str | None = Field(default=None, max_length=200)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str, info: Any) -> str:
        if info.data.get("kind") == "agent" and v not in droits_agents.AGENTS:
            raise ValueError(f"Agent inconnu : {v}. Agents possibles : {', '.join(droits_agents.AGENTS)}.")
        return v


class EtapeEquipe(_Strict):
    membres: list[MembreEquipe] = Field(default_factory=list, max_length=50)


class Jalon(_Strict):
    titre: str = Field(min_length=1, max_length=200)
    echeance: date


class EtapeJalons(_Strict):
    jalons: list[Jalon] = Field(default_factory=list, max_length=50)


_URL_SURE = re.compile(r"^(https?://|/)(?!/)", re.IGNORECASE)


class Ressource(_Strict):
    titre: str = Field(min_length=1, max_length=200)
    url: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        # Un lien est affiché tel quel dans l'application : ni `javascript:`, ni `data:`, ni
        # adresse « //ailleurs » qui sortirait du site sans le dire.
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not _URL_SURE.match(v):
            raise ValueError("Un lien commence par https://, http:// ou / (page de l'application).")
        return v


class EtapeRessources(_Strict):
    ressources: list[Ressource] = Field(default_factory=list, max_length=50)


class EtapeValidation(_Strict):
    valideur: str = Field(default="", max_length=200)
    statut: Literal["brouillon", "en_validation", "valide"] = "brouillon"


# L'ordre de ce dictionnaire EST l'ordre des étapes : il ne dépend jamais de l'ordre d'écriture.
ETAPES: dict[str, tuple[str, type[_Strict]]] = {
    "nom_objectif": ("Nom et objectif", EtapeNomObjectif),
    "perimetre_livrables": ("Périmètre et livrables", EtapePerimetreLivrables),
    "equipe": ("Équipe : personnes et agents", EtapeEquipe),
    "jalons": ("Jalons", EtapeJalons),
    "ressources": ("Ressources", EtapeRessources),
    "validation": ("Validation", EtapeValidation),
}
CleEtape = Literal["nom_objectif", "perimetre_livrables", "equipe", "jalons", "ressources", "validation"]


def _etapes_ordonnees(stockees: Any) -> list[dict[str, Any]]:
    stockees = stockees if isinstance(stockees, dict) else {}
    return [
        {"cle": cle, "numero": i, "titre": titre, "donnees": stockees.get(cle), "complete": cle in stockees}
        for i, (cle, (titre, _m)) in enumerate(ETAPES.items(), start=1)
    ]


# ── Aides ───────────────────────────────────────────────────────────────────
def _uid(user: dict[str, Any]) -> str:
    return studio_mod._uid(user)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _introuvable(quoi: str = "projet_introuvable") -> HTTPException:
    # 404 et jamais 403 : on ne confirme pas qu'un projet d'autrui existe.
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": quoi})


async def _projet(projet_id: str, uid: str) -> dict[str, Any]:
    if not studio_mod._valid_uuid(projet_id):
        raise _introuvable()
    rows = await db_select(_PROJETS, filters={"id": projet_id, "user_id": uid}, limit=1)
    if not rows:
        raise _introuvable()
    return rows[0]


async def _carte(projet_id: str, carte_id: str) -> dict[str, Any]:
    if not studio_mod._valid_uuid(carte_id):
        raise _introuvable("carte_introuvable")
    rows = await db_select(_CARTES, filters={"id": carte_id, "project_id": projet_id}, limit=1)
    if not rows:
        raise _introuvable("carte_introuvable")
    return rows[0]


def _resume(row: dict[str, Any]) -> dict[str, Any]:
    etapes = row.get("etapes") if isinstance(row.get("etapes"), dict) else {}
    return {
        "id": row.get("id"),
        "titre": row.get("title") or "Projet sans titre",
        "etapes_completes": sum(1 for k in ETAPES if k in etapes),
        "etapes_total": len(ETAPES),
        "statut": ((etapes.get("validation") or {}).get("statut") or "brouillon"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


async def _etat_agents(uid: str) -> dict[str, bool]:
    """L'abonnement, lu par la règle unique (droits_agents). Base injoignable : tout fermé."""
    try:
        return dict((await droits_agents.etat(uid))["agents"])
    except Exception as exc:  # noqa: BLE001 — on ferme, on ne devine pas un abonnement
        journal_securite.error(
            "Abonnement illisible pour un projet : aperçus seulement.",
            extra={"evenement": "agents.abonnement_inverifiable", "surface": "projets",
                   "utilisateur": uid, "erreur": type(exc).__name__})
        return {a: False for a in droits_agents.AGENTS}


# ── Aperçu verrouillé ───────────────────────────────────────────────────────
_TITRE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_GRAS_SEUL = re.compile(r"^\s*(\*\*|__)(.+?)\1\s*:?\s*$")
_PUCE = re.compile(r"^\s*(?:[-*•+]|\d{1,2}[.)])\s+(.+)$")
_TITRE_DE_PUCE = re.compile(r"^(?:\*\*|__)(.+?)(?:\*\*|__)|^([^:—–]{2,80}?)\s*(?::|—|–)\s")
APERCU_MAX = 500
POINTS_MAX = 12


def _nettoyer(t: str) -> str:
    return re.sub(r"[*_`]+", "", t).strip().rstrip(":").strip()


def points_couverts(sortie: str) -> list[str]:
    """Les points traités, par leurs TITRES seulement : titres Markdown, lignes en gras seules,
    et l'intitulé d'une puce quand elle en a un (« **Budget** : … », « Budget : … »). Jamais
    le contenu d'une puce : une puce sans intitulé n'apparaît pas."""
    titres: list[str] = []
    puces: list[str] = []
    for ligne in sortie.splitlines():
        if m := _TITRE.match(ligne):
            titres.append(_nettoyer(m.group(1)))
        elif m := _GRAS_SEUL.match(ligne):
            titres.append(_nettoyer(m.group(2)))
        elif m := _PUCE.match(ligne):
            if t := _TITRE_DE_PUCE.match(m.group(1).strip()):
                puces.append(_nettoyer(t.group(1) or t.group(2) or ""))
    vus: list[str] = []
    for p in titres or puces:
        p = p[:80]
        if p and p not in vus:
            vus.append(p)
    return vus[:POINTS_MAX]


def _couper(texte: str, plafond: int) -> str:
    if len(texte) <= plafond:
        return texte
    coupe = texte[:plafond]
    fin = max(coupe.rfind(". "), coupe.rfind("! "), coupe.rfind("? "))
    if fin >= plafond // 3:
        return coupe[: fin + 1]
    espace = coupe.rfind(" ")
    return (coupe[:espace] if espace > 0 else coupe).rstrip(" ,;:") + "…"


def premier_paragraphe(sortie: str) -> str:
    """Le premier paragraphe de prose (ni titre, ni puce), plafonné.

    Plafonné deux fois : à ``APERCU_MAX`` caractères, et à 40 % de la sortie. Sans le second
    plafond, une réponse écrite d'un seul bloc serait rendue entière sous le nom d'« aperçu »."""
    lignes: list[str] = []
    for ligne in sortie.splitlines():
        brut = ligne.strip()
        if not brut:
            if lignes:
                break
            continue
        if _TITRE.match(ligne) or _GRAS_SEUL.match(ligne) or _PUCE.match(ligne) or brut.startswith(("```", "|", ">")):
            if lignes:
                break
            continue
        lignes.append(brut)
    paragraphe = " ".join(lignes)
    total = len(sortie.strip())
    plafond = min(APERCU_MAX, max(int(total * 0.4), 1))
    return _couper(paragraphe, plafond)


def _vue_travail(run: dict[str, Any], abonne: bool) -> dict[str, Any]:
    """Ce qui part vers le navigateur. Non abonné : l'aperçu, jamais `sortie_complete`."""
    sortie = run.get("sortie_complete") or ""
    base = {
        "id": run.get("id"),
        "agent": run.get("agent"),
        "brief": run.get("brief") or "",
        "stub": bool(run.get("stub")),
        "created_at": run.get("created_at"),
        "points": points_couverts(sortie),
    }
    if abonne:
        return {**base, "verrouille": False, "sortie": sortie}
    return {**base, "verrouille": True, "apercu": premier_paragraphe(sortie), "message": MESSAGE_VERROU}


# ── Projets ─────────────────────────────────────────────────────────────────
class CreerProjet(_Strict):
    titre: str = Field(default="Projet sans titre", min_length=1, max_length=200)


@router.post("")
async def creer_projet(body: CreerProjet, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """Un projet vide : les étapes viennent ensuite, une à une."""
    row = await db_insert(_PROJETS, {"user_id": _uid(user), "title": body.titre, "etapes": {}})
    if row is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "projet_non_enregistre"})
    return {"ok": True, "data": {**_resume(row), "etapes": _etapes_ordonnees(row.get("etapes"))}}


@router.get("")
async def lister_projets(user: dict = Depends(scoped_user)) -> dict[str, Any]:
    rows = await db_select(_PROJETS, filters={"user_id": _uid(user)}, order_by="-updated_at", limit=100)
    return {"ok": True, "data": {"projets": [_resume(r) for r in rows]}}


@router.get("/{projet_id}")
async def lire_projet(projet_id: str, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """Le projet, ses étapes dans l'ordre, ses cartes enrichies et les liens entre elles."""
    uid = _uid(user)
    row = await _projet(projet_id, uid)
    abonnements = await _etat_agents(uid)
    cartes_brutes = await db_select(_CARTES, filters={"project_id": projet_id}, order_by="created_at", limit=200)
    cartes = [await _enrichir(c, uid, abonnements) for c in cartes_brutes]
    return {"ok": True, "data": {
        **_resume(row),
        "etapes": _etapes_ordonnees(row.get("etapes")),
        "cartes": cartes,
        "liens": _liens(cartes),
        "abonnements": abonnements,
    }}


@router.patch("/{projet_id}/etapes/{cle}")
async def enregistrer_etape(projet_id: str, cle: CleEtape, donnees_etape: dict[str, Any] = Body(...),
                            user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """Enregistrer UNE étape. Une clé inconnue ou un contenu mal formé : 422, rien n'est écrit."""
    uid = _uid(user)
    row = await _projet(projet_id, uid)
    _titre, modele = ETAPES[cle]
    try:
        valide = modele.model_validate(donnees_etape)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={
            "error": "etape_invalide", "etape": cle,
            "detail": "Cette étape est incomplète ou mal renseignée.",
            "champs": [{"champ": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()],
        }) from exc
    etapes = dict(row.get("etapes") or {})
    etapes[cle] = valide.model_dump(mode="json")
    patch: dict[str, Any] = {"etapes": etapes, "updated_at": _now()}
    if cle == "nom_objectif":
        patch["title"] = valide.nom  # type: ignore[attr-defined]
    maj = await db_update(_PROJETS, patch, filters={"id": projet_id, "user_id": uid})
    nouveau = maj[0] if maj else {**row, **patch}
    return {"ok": True, "data": {**_resume(nouveau), "etapes": _etapes_ordonnees(nouveau.get("etapes"))}}


@router.delete("/{projet_id}")
async def supprimer_projet(projet_id: str, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """Le projet et ses cartes. Les travaux d'agent restent au journal (project_id → null)."""
    uid = _uid(user)
    await _projet(projet_id, uid)
    await db_delete(_CARTES, filters={"project_id": projet_id})
    await db_delete(_PROJETS, filters={"id": projet_id, "user_id": uid})
    return {"ok": True, "data": {"supprime": projet_id}}


# ── Cartes ──────────────────────────────────────────────────────────────────
class NouvelleCarte(_Strict):
    kind: Literal["salle", "artefact", "agent", "coffre"]
    ref_id: str = Field(min_length=1, max_length=200)
    x: float = Field(default=0, ge=-100_000, le=100_000)
    y: float = Field(default=0, ge=-100_000, le=100_000)
    sous_type: Literal["document", "session", "personne"] | None = None
    libelle: str | None = Field(default=None, max_length=200)


class DeplacerCarte(_Strict):
    x: float = Field(ge=-100_000, le=100_000)
    y: float = Field(ge=-100_000, le=100_000)


async def _verifier_reference(carte: NouvelleCarte, uid: str) -> None:
    """Une carte ne pointe que vers ce que la personne peut déjà ouvrir."""
    if carte.kind == "salle":
        if not studio_mod._valid_uuid(carte.ref_id) or not await db_select(
                "rooms", filters={"id": carte.ref_id, "user_id": uid}, columns="id", limit=1):
            raise _introuvable("salle_introuvable")
    elif carte.kind == "artefact":
        await studio_mod._accessible_row(carte.ref_id, uid)  # 404 sinon
    elif carte.kind == "agent":
        if carte.ref_id not in droits_agents.AGENTS:
            raise HTTPException(status_code=422, detail={
                "error": "agent_inconnu", "detail": f"Agents possibles : {', '.join(droits_agents.AGENTS)}."})
    elif carte.sous_type is None:
        raise HTTPException(status_code=422, detail={
            "error": "sous_type_requis", "detail": "Précisez s'il s'agit d'un document, d'une session ou d'une personne."})


@router.post("/{projet_id}/cartes")
async def ajouter_carte(projet_id: str, body: NouvelleCarte, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    uid = _uid(user)
    await _projet(projet_id, uid)
    await _verifier_reference(body, uid)
    row = await db_insert(_CARTES, {
        "project_id": projet_id, "kind": body.kind, "ref_id": body.ref_id,
        "sous_type": body.sous_type if body.kind == "coffre" else None,
        "libelle": body.libelle, "x": body.x, "y": body.y,
    })
    if row is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "carte_non_enregistree"})
    await db_update(_PROJETS, {"updated_at": _now()}, filters={"id": projet_id, "user_id": uid})
    return {"ok": True, "data": await _enrichir(row, uid, await _etat_agents(uid))}


@router.patch("/{projet_id}/cartes/{carte_id}")
async def deplacer_carte(projet_id: str, carte_id: str, body: DeplacerCarte,
                         user: dict = Depends(scoped_user)) -> dict[str, Any]:
    uid = _uid(user)
    await _projet(projet_id, uid)
    await _carte(projet_id, carte_id)
    await db_update(_CARTES, {"x": body.x, "y": body.y}, filters={"id": carte_id, "project_id": projet_id})
    return {"ok": True, "data": {"id": carte_id, "x": body.x, "y": body.y}}


@router.delete("/{projet_id}/cartes/{carte_id}")
async def retirer_carte(projet_id: str, carte_id: str, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """Retirer une carte du canevas. Ce qu'elle désigne (salle, artefact…) n'est pas touché."""
    uid = _uid(user)
    await _projet(projet_id, uid)
    await _carte(projet_id, carte_id)
    await db_delete(_CARTES, filters={"id": carte_id, "project_id": projet_id})
    return {"ok": True, "data": {"retire": carte_id}}


_LIENS_COFFRE = {"document": "/learn/coffre", "session": "/learn/formations", "personne": "/learn/comptes"}


async def _enrichir(carte: dict[str, Any], uid: str, abonnements: dict[str, bool]) -> dict[str, Any]:
    """Ce que la carte montre. Une cible disparue ou plus accessible : `manquant`, sans détail."""
    base = {"id": carte.get("id"), "kind": carte.get("kind"), "ref_id": carte.get("ref_id"),
            "x": float(carte.get("x") or 0), "y": float(carte.get("y") or 0)}
    kind, ref = carte.get("kind"), str(carte.get("ref_id") or "")
    if kind == "salle":
        rows = await db_select("rooms", filters={"id": ref, "user_id": uid}, limit=1) if studio_mod._valid_uuid(ref) else []
        if not rows:
            return {**base, "manquant": True, "titre": "Salle introuvable"}
        salle = rows[0]
        return {**base, "titre": salle.get("title") or "Salle de réunion", "statut": salle.get("status") or "active",
                "lien": f"/meeting-room?salle={ref}"}
    if kind == "artefact":
        try:
            art = await studio_mod._accessible_row(ref, uid)
        except HTTPException:
            return {**base, "manquant": True, "titre": "Artefact introuvable"}
        # La salle d'origine : rooms.artifact_id, posé par le résumé de fin de séance.
        sources = await db_select("rooms", filters={"artifact_id": ref, "user_id": str(art.get("user_id"))},
                                  columns="id,title", limit=1)
        salle = sources[0] if sources else None
        # L'agent d'origine se déduit de la surface qui l'a produit (droits_agents.SURFACES) :
        # un résumé de salle → l'agent de salle ; un document rédigé au Studio → l'agent du Studio.
        if salle:
            agent_source = droits_agents.SURFACES["salle"]
        elif (art.get("approach") or "").strip():
            agent_source = droits_agents.SURFACES["studio"]
        else:
            agent_source = None
        # La salle n'est montrée qu'à son propriétaire : à qui l'artefact est seulement partagé,
        # on ne donne ni son titre ni un lien qu'il ne pourrait pas ouvrir.
        salle_visible = salle if salle and str(art.get("user_id")) == uid else None
        return {**base, "titre": art.get("title") or "Artefact",
                "lien": f"/studio?artifact={ref}",
                "version": int(art.get("version") or 1),
                "maj": art.get("updated_at"),
                "salle_source": {"id": salle_visible["id"], "titre": salle_visible.get("title"),
                                 "lien": f"/meeting-room?salle={salle_visible['id']}"} if salle_visible else None,
                "agent_source": agent_source}
    if kind == "agent":
        return {**base, "titre": droits_agents.NOMS.get(ref, ref.upper()), "agent": ref,
                "abonne": bool(abonnements.get(ref))}
    return {**base, "titre": carte.get("libelle") or "Élément du coffre", "sous_type": carte.get("sous_type"),
            "lien": _LIENS_COFFRE.get(str(carte.get("sous_type")), "/learn/coffre")}


def _liens(cartes: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Les arêtes du canevas : d'un artefact vers la salle et l'agent dont il vient, quand
    ces cartes sont posées sur le même projet."""
    salles = {c["ref_id"]: c["id"] for c in cartes if c["kind"] == "salle" and not c.get("manquant")}
    agents = {c["ref_id"]: c["id"] for c in cartes if c["kind"] == "agent"}
    out: list[dict[str, str]] = []
    for c in cartes:
        if c["kind"] != "artefact" or c.get("manquant"):
            continue
        if (s := c.get("salle_source")) and s["id"] in salles:
            out.append({"de": c["id"], "vers": salles[s["id"]], "nature": "salle_source"})
        if (a := c.get("agent_source")) and a in agents:
            out.append({"de": c["id"], "vers": agents[a], "nature": "agent_source"})
    return out


# ── Faire travailler un agent (aperçu coupé côté serveur) ───────────────────
_MISSIONS: dict[str, str] = {
    "azzmin": ("Tu es AZZMIN, l'agent d'administration de la plateforme VTLVS : comptes, sessions, "
               "créneaux, coffre, documents, supervision. Tu prépares ce qu'un humain doit valider."),
    "azzco": ("Tu es AZZCO, l'agent de coordination de l'organisme : planning, dossiers, échéances, "
              "factures, obligations légales. Tu cites le texte ou la pièce sur laquelle tu te fondes, "
              "et sur un point qui engage tu renvoies au professionnel."),
    "azzcom": ("Tu es AZZCOM, l'agent de la relation client : qualifier un besoin, recommander, conduire "
               "vers la réservation. Tu n'inventes aucun chiffre : prix et dates viennent du catalogue."),
}
_FORME = (
    "Réponds en français, en Markdown : un premier paragraphe court qui résume ta réponse, puis des "
    "sections titrées (##) pour chaque point traité. Concret, sans préambule."
)


class Travail(_Strict):
    consigne: str = Field(min_length=3, max_length=2000)


def _contexte_projet(row: dict[str, Any]) -> str:
    lignes = [f"Projet : {row.get('title') or 'Projet sans titre'}"]
    for e in _etapes_ordonnees(row.get("etapes")):
        if e["complete"]:
            lignes.append(f"- {e['titre']} : {e['donnees']}")
    return "\n".join(lignes)


@router.post("/{projet_id}/agents/{agent}/travail")
async def travail_agent(projet_id: str, agent: AgentId, body: Travail,
                        user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """L'agent travaille toujours ; la réponse dépend de l'abonnement de l'organisme à CET agent.

    Pas de ``droits_agents.exiger`` ici, délibérément : l'aperçu est le comportement voulu
    pour qui n'est pas abonné. La sortie complète est gardée dans ``studio_agent_runs`` ;
    elle n'est envoyée qu'à un abonné."""
    uid = _uid(user)
    row = await _projet(projet_id, uid)
    prompt = (
        "Contexte du projet :\n" + donnees("projet", _contexte_projet(row), surface="studio.projet", longueur_max=6000)
        + "\n\nDemande de la personne :\n" + donnees("consigne", body.consigne, surface="studio.projet", longueur_max=2000)
    )
    systeme = await studio_mod._systeme(user, _MISSIONS[agent] + "\n\n" + _FORME)
    resultat = await ask(studio_mod._primary_worker(), prompt, system=systeme, temperature=0.4, max_tokens=1600)
    sortie = (resultat.get("output") or "").strip()
    if not sortie:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={
            "error": "agent_sans_reponse", "detail": "L'agent n'a rien rendu. Réessayez dans un instant."})

    abonne = bool((await _etat_agents(uid)).get(agent))
    run = await db_insert(_TRAVAUX, {
        "project_id": projet_id, "user_id": uid, "agent": agent, "brief": body.consigne,
        "sortie_complete": sortie, "stub": bool(resultat.get("stub")), "abonne": abonne,
    })
    if run is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail={"error": "travail_non_enregistre"})
    await db_update(_PROJETS, {"updated_at": _now()}, filters={"id": projet_id, "user_id": uid})

    if not abonne:
        journal_securite.info(
            "Travail de %s rendu en aperçu : organisme non abonné.", droits_agents.NOMS[agent],
            extra={"evenement": "agents.apercu_verrouille", "agent": agent, "utilisateur": uid,
                   "projet": projet_id, "travail": run.get("id"), "longueur": len(sortie)})
    else:
        logger.info("Travail de %s rendu en entier (projet %s).", droits_agents.NOMS[agent], projet_id,
                    extra={"evenement": "studio.projet_travail_agent", "agent": agent, "utilisateur": uid,
                           "projet": projet_id, "travail": run.get("id")})
    return {"ok": True, "data": _vue_travail(run, abonne)}


@router.get("/{projet_id}/runs")
async def travaux(projet_id: str, user: dict = Depends(scoped_user)) -> dict[str, Any]:
    """Les travaux d'agent du projet, du plus récent au plus ancien. Chacun est montré selon
    l'abonnement ACTUEL : un organisme qui s'abonne relit ses anciens travaux en entier."""
    uid = _uid(user)
    await _projet(projet_id, uid)
    abonnements = await _etat_agents(uid)
    rows = await db_select(_TRAVAUX, filters={"project_id": projet_id, "user_id": uid},
                           order_by="-created_at", limit=50)
    return {"ok": True, "data": {"travaux": [_vue_travail(r, bool(abonnements.get(r.get("agent")))) for r in rows]}}

