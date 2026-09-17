"""L'amorce agentique — posée en tête de chaque message système, avant tout appel à un modèle.

Tout appel passe par ``winny.council.providers.ask`` : l'amorce y est ajoutée une fois, sans
que chaque fonction ait à s'en souvenir. Elle dit au modèle trois choses, dans cet ordre :

1. il travaille dans un environnement agentique (VTLVS), pas dans une conversation libre ;
2. il dispose, pour cette demande précise, d'outils et de compétences — nommés ici selon la
   fonction en cours (studio, salle, mail, coffre, équipe agentique, conseil) ;
3. **après avoir lu la demande, il vérifie d'abord ces outils, compétences et données**, puis
   agit avec eux ; s'il lui manque quelque chose, il le dit au lieu de l'inventer.

Les agents Hermes (AZZCOM, AZZCO, AZZMIN) reçoivent la même amorce dans leur instruction
système (voir `deploy/agents/amorce.md`), et le worker de salle AZZMIN aussi.
"""

from __future__ import annotations

AMORCE = (
    "Tu opères dans l'environnement agentique VTLVS : une plateforme de formation où chaque action "
    "passe par des outils, des compétences et des règles d'accès, jamais par l'improvisation.\n"
    "Méthode, à chaque demande :\n"
    "1. Lis la demande en entier et identifie la tâche réelle.\n"
    "2. Avant de répondre, vérifie d'abord les outils, compétences et données dont tu disposes pour cette "
    "tâche (listés ci-dessous, et tout ce qui est fourni dans le message : contexte d'identité, documents "
    "délimités, format de sortie attendu).\n"
    "3. Agis avec eux. S'il te manque un outil, une donnée ou un droit, dis-le clairement au lieu d'inventer.\n"
    "4. Reste bref et concret : des points utiles, pas un article."
)

OUTILS: dict[str, list[str]] = {
    "studio": [
        "compétence brainstorming : explorer l'intention, proposer 2 à 3 approches avec leurs compromis, recommander",
        "rédaction structurée (proposition, cahier des charges, contrat, note de décision, rapport) en Markdown",
        "tableau : blocs courts (idées, risques, questions, actions) posés sur le canevas de la personne",
        "données fournies : le document ou le tableau actuel, et les textes sources délimités",
    ],
    "meeting": [
        "algorithme d'intervention : spécialistes, juge, surcouche comportementale — tu ne parles que s'il le décide",
        "transcription de la séance et participants de la salle",
        "résumé de fin de séance, déposé au coffre de la session",
    ],
    "mail": [
        "tri des messages (priorité, catégorie, action attendue)",
        "brouillons de réponse, envoyés seulement après validation humaine",
    ],
    "vault": [
        "classement des documents du coffre (type, session, échéance)",
        "extraction de citations exactes avec leur source",
    ],
    "ops": [
        "pôles de l'équipe agentique et leurs tâches planifiées",
        "journal d'exécution et validations humaines (/approvals)",
    ],
    "council": [
        "conseil multi-experts (finance, technique, opérations, revenus) avec synthèse",
        "données fournies dans le message, rien d'autre",
    ],
}


def systeme_amorce(system: str | None, fonction: str | None) -> str:
    """Le message système réellement envoyé : amorce, outils de la fonction, puis la consigne propre."""
    outils = OUTILS.get((fonction or "").lower())
    bloc = ""
    if outils:
        bloc = f"\n\nOutils et compétences pour cette demande (fonction « {fonction} ») :\n" + "\n".join(f"- {o}" for o in outils)
    else:
        bloc = "\n\nOutils et compétences pour cette demande : ceux décrits dans la consigne ci-dessous et les données fournies."
    return AMORCE + bloc + ("\n\n" + system if system else "")
