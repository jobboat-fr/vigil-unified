"""Projets du Studio : étapes validées, cartes à soi, et l'aperçu d'agent coupé CÔTÉ SERVEUR.

Trois personnes : Alice (organisme abonné à AZZCO seulement), Bruno (même organisme), Oscar
(organisme sans aucun abonnement). La personne qui appelle est choisie par l'en-tête X-Test-User.
Le modèle est remplacé par une sortie fixe de plusieurs paragraphes : ce sont des essais de
routes, pas de modèle.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from tests.winny_gateway.test_vigil_studio_rooms import FakeDB
from winny_gateway import droits_agents
from winny_gateway.auth import get_current_user
from winny_gateway.routes.vigil import projets as projets_mod
from winny_gateway.routes.vigil import studio as studio_mod

T1, T2 = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"

PREMIER = "Le projet tient en trois chantiers et le calendrier est réaliste si la salle est réservée tôt."
SECRET_1 = "Budget détaillé : 4 200 euros répartis entre location et supports imprimés."
SECRET_2 = "Risque principal : le formateur référent part en congé la semaine du 12."
SORTIE = (
    f"{PREMIER}\n\n"
    "## Budget prévisionnel\n\n"
    f"{SECRET_1}\n\n"
    "## Risques\n\n"
    f"- **Disponibilité** : {SECRET_2}\n"
    "- une puce sans intitulé qui ne doit jamais apparaître dans les points\n\n"
    "## Prochaines étapes\n\n"
    "Valider le devis avec la direction avant vendredi."
)


@pytest.fixture
def c(monkeypatch):
    db = FakeDB()
    db.tables["learn_profiles"] = [
        {"id": "alice", "tenant_id": T1, "email": "alice@hbs.fr", "full_name": "Alice", "role": "formateur"},
        {"id": "bruno", "tenant_id": T1, "email": "bruno@hbs.fr", "full_name": "Bruno", "role": "formateur"},
        {"id": "oscar", "tenant_id": T2, "email": "oscar@autre.fr", "full_name": "Oscar", "role": "admin"},
    ]
    db.tables["learn_tenants"] = [
        {"id": T1, "name": "HBS", "abonnements": ["azzco"]},
        {"id": T2, "name": "Autre", "abonnements": []},
    ]
    for mod in (projets_mod, studio_mod):
        monkeypatch.setattr(mod, "db_insert", db.insert)
        monkeypatch.setattr(mod, "db_select", db.select)
        monkeypatch.setattr(mod, "db_update", db.update)
        monkeypatch.setattr(mod, "db_delete", db.delete)
    monkeypatch.setattr(droits_agents, "db_select", db.select)

    appels: list[dict] = []

    async def faux_modele(worker, prompt, *, system=None, **kw):
        appels.append({"prompt": prompt, "system": system})
        return {"output": SORTIE, "stub": False}

    monkeypatch.setattr(projets_mod, "ask", faux_modele)

    async def who(request: Request):
        return {"sub": request.headers.get("X-Test-User", "alice"), "role": "authenticated"}

    app = FastAPI()
    app.include_router(projets_mod.router)
    app.include_router(studio_mod.router)
    app.dependency_overrides[get_current_user] = who
    client = TestClient(app)
    client.db = db  # type: ignore[attr-defined]
    client.appels = appels  # type: ignore[attr-defined]
    return client


def as_(user: str) -> dict[str, str]:
    return {"X-Test-User": user}


def data(r, code=200):
    assert r.status_code == code, r.text
    return r.json().get("data") if code == 200 else r.json()["detail"]


def projet(c, user="alice", titre="Session de rentrée") -> dict:
    return data(c.post("/v1/projets", json={"titre": titre}, headers=as_(user)))


# ── Étapes ──────────────────────────────────────────────────────────────────
def test_creation_rend_les_six_etapes_dans_l_ordre(c):
    p = projet(c)
    assert [e["cle"] for e in p["etapes"]] == [
        "nom_objectif", "perimetre_livrables", "equipe", "jalons", "ressources", "validation"]
    assert [e["numero"] for e in p["etapes"]] == [1, 2, 3, 4, 5, 6]
    assert not any(e["complete"] for e in p["etapes"])


def test_etapes_enregistrees_dans_le_desordre_restent_dans_l_ordre(c):
    pid = projet(c)["id"]
    data(c.patch(f"/v1/projets/{pid}/etapes/jalons", json={"jalons": [{"titre": "Kick-off", "echeance": "2026-10-05"}]},
                 headers=as_("alice")))
    data(c.patch(f"/v1/projets/{pid}/etapes/equipe", json={"membres": [
        {"kind": "personne", "id": "bruno", "role": "Formateur référent"},
        {"kind": "agent", "id": "azzco", "role": "Coordination"}]}, headers=as_("alice")))
    p = data(c.patch(f"/v1/projets/{pid}/etapes/nom_objectif",
                     json={"nom": "Rentrée 2026", "objectif": "Ouvrir deux sessions"}, headers=as_("alice")))
    assert [e["cle"] for e in p["etapes"]][:4] == ["nom_objectif", "perimetre_livrables", "equipe", "jalons"]
    assert [e["complete"] for e in p["etapes"]] == [True, False, True, True, False, False]
    assert p["titre"] == "Rentrée 2026" and p["etapes_completes"] == 3
    relu = data(c.get(f"/v1/projets/{pid}", headers=as_("alice")))
    assert relu["etapes"][3]["donnees"] == {"jalons": [{"titre": "Kick-off", "echeance": "2026-10-05"}]}


def test_cle_d_etape_inconnue_422(c):
    pid = projet(c)["id"]
    r = c.patch(f"/v1/projets/{pid}/etapes/budget", json={"montant": 1}, headers=as_("alice"))
    assert r.status_code == 422


@pytest.mark.parametrize("cle,corps", [
    ("nom_objectif", {"nom": ""}),
    ("nom_objectif", {"nom": "ok", "champ_inconnu": 1}),
    ("equipe", {"membres": [{"kind": "robot", "id": "x"}]}),
    ("equipe", {"membres": [{"kind": "agent", "id": "gpt"}]}),
    ("jalons", {"jalons": [{"titre": "Fin", "echeance": "pas une date"}]}),
    ("ressources", {"ressources": [{"titre": "Piège", "url": "javascript:alert(1)"}]}),
    ("ressources", {"ressources": [{"titre": "Ailleurs", "url": "//evil.example"}]}),
    ("validation", {"valideur": "Direction", "statut": "approuve"}),
])
def test_contenu_d_etape_invalide_422_et_rien_n_est_ecrit(c, cle, corps):
    pid = projet(c)["id"]
    d = data(c.patch(f"/v1/projets/{pid}/etapes/{cle}", json=corps, headers=as_("alice")), 422)
    assert d["error"] == "etape_invalide" and d["etape"] == cle
    assert c.db.tables["studio_projects"][0]["etapes"] == {}


def test_ressource_et_validation_valides(c):
    pid = projet(c)["id"]
    data(c.patch(f"/v1/projets/{pid}/etapes/ressources", json={"ressources": [
        {"titre": "Programme", "url": "https://exemple.fr/programme"}, {"titre": "Coffre", "url": "/learn/coffre"}]},
        headers=as_("alice")))
    p = data(c.patch(f"/v1/projets/{pid}/etapes/validation", json={"valideur": "Direction", "statut": "en_validation"},
                     headers=as_("alice")))
    assert p["statut"] == "en_validation"


# ── Isolation ───────────────────────────────────────────────────────────────
def test_un_autre_ne_voit_ni_ne_modifie_le_projet(c):
    pid = projet(c, "alice")["id"]
    carte = data(c.post(f"/v1/projets/{pid}/cartes", json={"kind": "agent", "ref_id": "azzco"}, headers=as_("alice")))
    for qui in ("bruno", "oscar"):
        h = as_(qui)
        assert c.get(f"/v1/projets/{pid}", headers=h).status_code == 404
        assert c.patch(f"/v1/projets/{pid}/etapes/nom_objectif", json={"nom": "volé"}, headers=h).status_code == 404
        assert c.post(f"/v1/projets/{pid}/cartes", json={"kind": "agent", "ref_id": "azzmin"}, headers=h).status_code == 404
        assert c.patch(f"/v1/projets/{pid}/cartes/{carte['id']}", json={"x": 1, "y": 1}, headers=h).status_code == 404
        assert c.delete(f"/v1/projets/{pid}/cartes/{carte['id']}", headers=h).status_code == 404
        assert c.post(f"/v1/projets/{pid}/agents/azzco/travail", json={"consigne": "Fais tout"}, headers=h).status_code == 404
        assert c.get(f"/v1/projets/{pid}/runs", headers=h).status_code == 404
        assert c.delete(f"/v1/projets/{pid}", headers=h).status_code == 404
        assert data(c.get("/v1/projets", headers=h))["projets"] == []
    assert c.db.tables["studio_projects"][0]["title"] == "Session de rentrée"
    assert len(c.db.tables["studio_project_cards"]) == 1
    assert c.appels == []  # aucun modèle appelé pour un intrus


def test_identifiant_mal_forme_404(c):
    assert c.get("/v1/projets/pas-un-uuid", headers=as_("alice")).status_code == 404


# ── Cartes ──────────────────────────────────────────────────────────────────
def test_cartes_ajouter_deplacer_retirer(c):
    pid = projet(c)["id"]
    agent = data(c.post(f"/v1/projets/{pid}/cartes", json={"kind": "agent", "ref_id": "azzco", "x": 10, "y": 20},
                        headers=as_("alice")))
    assert agent["titre"] == "AZZCO" and agent["abonne"] is True
    coffre = data(c.post(f"/v1/projets/{pid}/cartes", json={
        "kind": "coffre", "ref_id": "doc-42", "sous_type": "document", "libelle": "Convention"}, headers=as_("alice")))
    assert coffre["lien"] == "/learn/coffre" and coffre["titre"] == "Convention"

    data(c.patch(f"/v1/projets/{pid}/cartes/{agent['id']}", json={"x": 300, "y": -40}, headers=as_("alice")))
    p = data(c.get(f"/v1/projets/{pid}", headers=as_("alice")))
    deplacee = next(k for k in p["cartes"] if k["id"] == agent["id"])
    assert (deplacee["x"], deplacee["y"]) == (300.0, -40.0)

    data(c.delete(f"/v1/projets/{pid}/cartes/{coffre['id']}", headers=as_("alice")))
    assert [k["kind"] for k in data(c.get(f"/v1/projets/{pid}", headers=as_("alice")))["cartes"]] == ["agent"]


def test_carte_refusee_si_la_cible_n_est_pas_a_soi(c):
    pid = projet(c)["id"]
    # une salle et un artefact d'Oscar
    salle = c.db.tables.setdefault("rooms", [])
    salle.append({"id": "33333333-3333-3333-3333-333333333333", "user_id": "oscar", "title": "Salle d'Oscar"})
    art = data(c.post("/v1/artifacts/blank-canvas", json={"title": "Tableau d'Oscar"}, headers=as_("oscar")))
    h = as_("alice")
    assert c.post(f"/v1/projets/{pid}/cartes", json={"kind": "salle", "ref_id": salle[0]["id"]}, headers=h).status_code == 404
    assert c.post(f"/v1/projets/{pid}/cartes", json={"kind": "artefact", "ref_id": art["id"]}, headers=h).status_code == 404
    assert c.post(f"/v1/projets/{pid}/cartes", json={"kind": "agent", "ref_id": "hal"}, headers=h).status_code == 422
    assert c.post(f"/v1/projets/{pid}/cartes", json={"kind": "coffre", "ref_id": "d1"}, headers=h).status_code == 422
    assert c.post(f"/v1/projets/{pid}/cartes", json={"kind": "tableau", "ref_id": "x"}, headers=h).status_code == 422
    assert c.db.tables.get("studio_project_cards", []) == []


def test_artefact_relie_a_sa_salle_et_a_son_agent(c):
    pid = projet(c)["id"]
    art = data(c.post("/v1/artifacts/blank-canvas", json={"title": "Compte rendu"}, headers=as_("alice")))
    rid = "44444444-4444-4444-4444-444444444444"
    c.db.tables.setdefault("rooms", []).append(
        {"id": rid, "user_id": "alice", "title": "Réunion de cadrage", "status": "closed", "artifact_id": art["id"]})
    h = as_("alice")
    ca = data(c.post(f"/v1/projets/{pid}/cartes", json={"kind": "artefact", "ref_id": art["id"]}, headers=h))
    assert ca["salle_source"]["id"] == rid and ca["agent_source"] == "azzmin"
    assert ca["lien"] == f"/studio?artifact={art['id']}" and ca["version"] == 1
    cs = data(c.post(f"/v1/projets/{pid}/cartes", json={"kind": "salle", "ref_id": rid}, headers=h))
    assert cs["lien"] == f"/meeting-room?salle={rid}"
    cg = data(c.post(f"/v1/projets/{pid}/cartes", json={"kind": "agent", "ref_id": "azzmin"}, headers=h))
    assert cg["abonne"] is False  # l'organisme d'Alice n'est abonné qu'à AZZCO
    liens = data(c.get(f"/v1/projets/{pid}", headers=h))["liens"]
    assert {(x["de"], x["vers"], x["nature"]) for x in liens} == {
        (ca["id"], cs["id"], "salle_source"), (ca["id"], cg["id"], "agent_source")}


def test_artefact_partage_ne_revele_pas_la_salle_d_autrui(c):
    art = data(c.post("/v1/artifacts/blank-canvas", json={"title": "Compte rendu de Bruno"}, headers=as_("bruno")))
    next(x for x in c.db.tables["artifacts"] if x["id"] == art["id"])["tenant_id"] = T1
    c.db.tables.setdefault("rooms", []).append({"id": "55555555-5555-5555-5555-555555555555", "user_id": "bruno",
                                                "title": "Réunion privée de Bruno", "artifact_id": art["id"]})
    c.db.tables.setdefault("artifact_shares", []).append(
        {"id": "s1", "artifact_id": art["id"], "grantee_id": "alice", "access": "view"})
    pid = projet(c)["id"]
    r = c.post(f"/v1/projets/{pid}/cartes", json={"kind": "artefact", "ref_id": art["id"]}, headers=as_("alice"))
    carte = data(r)
    assert carte["titre"] == "Compte rendu de Bruno" and carte["salle_source"] is None
    assert carte["agent_source"] == "azzmin" and "Réunion privée" not in r.text


def test_supprimer_le_projet_garde_le_journal_des_travaux(c):
    pid = projet(c)["id"]
    data(c.post(f"/v1/projets/{pid}/cartes", json={"kind": "agent", "ref_id": "azzco"}, headers=as_("alice")))
    data(c.post(f"/v1/projets/{pid}/agents/azzco/travail", json={"consigne": "Planifie"}, headers=as_("alice")))
    data(c.delete(f"/v1/projets/{pid}", headers=as_("alice")))
    assert c.db.tables["studio_projects"] == [] and c.db.tables["studio_project_cards"] == []
    assert len(c.db.tables["studio_agent_runs"]) == 1


# ── L'aperçu verrouillé, coupé côté serveur ─────────────────────────────────
def test_non_abonne_recoit_un_apercu_et_jamais_la_suite(c):
    pid = projet(c)["id"]
    r = c.post(f"/v1/projets/{pid}/agents/azzmin/travail", json={"consigne": "Prépare le budget"}, headers=as_("alice"))
    d = data(r)
    assert d["verrouille"] is True and d["agent"] == "azzmin"
    assert d["message"] == "Abonnez-vous pour lire la suite."
    assert d["apercu"] == PREMIER
    assert d["points"] == ["Budget prévisionnel", "Risques", "Prochaines étapes"]
    assert "sortie" not in d
    # Rien de la suite ne quitte le serveur : ni le texte entier, ni ses morceaux.
    corps = r.text
    for fuite in (SORTIE, SECRET_1, SECRET_2, "Valider le devis", "4 200", "congé", "puce sans intitulé"):
        assert fuite not in corps, fuite
    # …mais l'agent a bien travaillé, et tout est gardé.
    assert len(c.appels) == 1 and "Prépare le budget" in c.appels[0]["prompt"]
    run = c.db.tables["studio_agent_runs"][0]
    assert run["sortie_complete"] == SORTIE and run["agent"] == "azzmin" and run["abonne"] is False
    assert run["project_id"] == pid and run["user_id"] == "alice" and run["brief"] == "Prépare le budget"


def test_non_abonne_relit_ses_travaux_en_apercu_seulement(c):
    pid = projet(c)["id"]
    data(c.post(f"/v1/projets/{pid}/agents/azzmin/travail", json={"consigne": "Budget"}, headers=as_("alice")))
    r = c.get(f"/v1/projets/{pid}/runs", headers=as_("alice"))
    (t,) = data(r)["travaux"]
    assert t["verrouille"] is True and SECRET_1 not in r.text and SORTIE not in r.text


def test_abonne_recoit_tout_et_relit_tout(c):
    pid = projet(c)["id"]
    d = data(c.post(f"/v1/projets/{pid}/agents/azzco/travail", json={"consigne": "Budget"}, headers=as_("alice")))
    assert d["verrouille"] is False and d["sortie"] == SORTIE and "apercu" not in d
    (t,) = data(c.get(f"/v1/projets/{pid}/runs", headers=as_("alice")))["travaux"]
    assert t["sortie"] == SORTIE
    assert c.db.tables["studio_agent_runs"][0]["abonne"] is True


def test_s_abonner_ouvre_les_anciens_travaux(c):
    pid = projet(c, "oscar")["id"]
    data(c.post(f"/v1/projets/{pid}/agents/azzcom/travail", json={"consigne": "Relance"}, headers=as_("oscar")))
    assert data(c.get(f"/v1/projets/{pid}/runs", headers=as_("oscar")))["travaux"][0]["verrouille"] is True
    c.db.tables["learn_tenants"][1]["abonnements"] = ["azzcom"]
    (t,) = data(c.get(f"/v1/projets/{pid}/runs", headers=as_("oscar")))["travaux"]
    assert t["verrouille"] is False and t["sortie"] == SORTIE


def test_apercu_sans_route_d_abonnement_en_enforce(c, monkeypatch):
    """Même en `enforce`, la route ne répond pas 402 : l'aperçu est le comportement voulu."""
    monkeypatch.setenv("AGENTS_ABONNEMENT_MODE", "enforce")
    pid = projet(c, "oscar")["id"]
    d = data(c.post(f"/v1/projets/{pid}/agents/azzco/travail", json={"consigne": "Budget"}, headers=as_("oscar")))
    assert d["verrouille"] is True


def test_abonnement_illisible_ferme(c, monkeypatch):
    async def panne(_uid):
        raise RuntimeError("base injoignable")
    monkeypatch.setattr(droits_agents, "etat", panne)
    pid = projet(c)["id"]
    r = c.post(f"/v1/projets/{pid}/agents/azzco/travail", json={"consigne": "Budget"}, headers=as_("alice"))
    assert data(r)["verrouille"] is True and SECRET_1 not in r.text


def test_agent_inconnu_422(c):
    pid = projet(c)["id"]
    assert c.post(f"/v1/projets/{pid}/agents/gpt/travail", json={"consigne": "x" * 10}, headers=as_("alice")).status_code == 422
    assert c.appels == []


# ── Les aides pures ─────────────────────────────────────────────────────────
def test_premier_paragraphe_d_un_seul_bloc_ne_rend_pas_tout():
    bloc = " ".join(f"Phrase numéro {i} qui dit quelque chose de précis." for i in range(40))
    apercu = projets_mod.premier_paragraphe(bloc)
    assert len(apercu) <= min(projets_mod.APERCU_MAX, int(len(bloc) * 0.4)) + 1
    assert apercu != bloc and "numéro 39" not in apercu


def test_premier_paragraphe_saute_les_titres_de_tete():
    suite = "La suite, beaucoup plus longue, qui détaille chaque point un par un. " * 3
    assert projets_mod.premier_paragraphe(f"# Titre\n\nLe vrai début.\n\n{suite}") == "Le vrai début."


def test_points_couverts_ne_prend_que_les_intitules():
    sortie = "- **Coût** : 12 000 euros\n- Délais : trois semaines\n- une remarque sans intitulé"
    assert projets_mod.points_couverts(sortie) == ["Coût", "Délais"]


# ── Monté dans la vraie application, derrière les droits du Studio ──────────
def test_monte_derriere_le_garde_studio(monkeypatch):
    import time

    from fastapi import HTTPException

    from winny_gateway import auth
    from winny_gateway import permissions as P
    from winny_gateway.app import create_app

    async def faux(request, credentials=None):
        if not credentials:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {"sub": "u1", "app_metadata": {"learn_role": credentials.credentials}}

    monkeypatch.setattr(P, "get_current_user", faux)
    # Le formateur peut lire le Studio mais pas y créer : la création d'un projet est refusée.
    monkeypatch.setattr(P.GRANTS, "_grants", {("formateur", "studio", "read")})
    monkeypatch.setattr(P.GRANTS, "_loaded_at", time.monotonic())
    app = create_app()

    async def route_user(request: Request):
        return await faux(request, await auth._bearer(request))

    app.dependency_overrides[auth.get_current_user] = route_user
    client = TestClient(app, raise_server_exceptions=False)
    assert client.post("/v1/projets", json={}).status_code == 401
    r = client.post("/v1/projets", json={}, headers={"Authorization": "Bearer formateur"})
    assert r.status_code == 403 and r.json()["detail"]["resource"] == "studio"
    r = client.post("/v1/projets/x/agents/azzco/travail", json={"consigne": "abc"},
                    headers={"Authorization": "Bearer formateur"})
    assert r.status_code == 403
