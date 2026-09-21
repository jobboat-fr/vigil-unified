/**
 * Le vocabulaire de la base, dit en français.
 *
 * Vingt-quatre écrans affichaient `{x.status}`, `{x.kind}` ou `{x.role}` tels quels. Une
 * personne lisait donc `planned` sous une session, `a_faire` sous une action, `in` sous un
 * émargement. Ce sont des valeurs de colonne, écrites pour une contrainte `check`, pas pour
 * être lues — le même défaut que les codes d'erreur affichés à la place des messages, et
 * il se corrige de la même façon : à un seul endroit.
 *
 * **Deux principes.**
 *
 * 1. *Le sens dépend du domaine.* `en_cours` se dit « en cours » pour une action et
 *    « copie commencée » pour une tentative d'évaluation ; `ouverte` se dit autrement pour
 *    une réclamation que pour une action requise. Traduire mot à mot produirait des phrases
 *    justes et inutiles. Chaque famille a donc sa table.
 * 2. *Ne jamais rendre un jeton brut.* Une valeur inconnue — ajoutée en base après coup,
 *    oubliée ici — ne doit pas ressortir en `snake_case` à l'écran. `humaniser()` en fait
 *    au moins quelque chose de lisible. C'est un filet, pas une dispense : une valeur qui
 *    passe par là mérite sa ligne dans la table.
 *
 * Les valeurs viennent des contraintes `check` des migrations, relevées une à une. Aucune
 * n'est devinée : inventer un libellé pour une valeur qui n'existe pas fabriquerait une
 * interface qui ment sur ce que contient la base.
 */

/** Dernier recours : `acquis_entree` → « Acquis entree ». Jamais de jeton nu à l'écran. */
export function humaniser(valeur: string | null | undefined): string {
  const v = (valeur ?? "").trim();
  if (!v) return "—";
  const mots = v.replace(/[_-]+/g, " ").trim();
  return mots.charAt(0).toUpperCase() + mots.slice(1);
}

function traduire(table: Record<string, string>, valeur: string | null | undefined): string {
  const v = (valeur ?? "").trim();
  if (!v) return "—";
  return table[v] ?? humaniser(v);
}

/** `learn_sessions.status` — le cycle de vie d'une session de formation. */
const SESSION: Record<string, string> = {
  draft: "Brouillon",
  planned: "Planifiée",
  running: "En cours",
  finished: "Terminée",
  cancelled: "Annulée",
};
export const statutSession = (v?: string | null) => traduire(SESSION, v);

/** `learn_session_slots.status` — une demi-journée. */
const CRENEAU: Record<string, string> = {
  planned: "Planifié",
  confirmed: "Confirmé",
  done: "Fait",
  cancelled: "Annulé",
};
export const statutCreneau = (v?: string | null) => traduire(CRENEAU, v);

/** `learn_enrollments.status` — le parcours d'une inscription. */
const INSCRIPTION: Record<string, string> = {
  demande: "Demandée",
  inscrit: "Inscrit",
  confirme: "Confirmée",
  abandon: "Abandon",
  termine: "Terminée",
};
export const statutInscription = (v?: string | null) => traduire(INSCRIPTION, v);

/** `learn_attendance.kind` — le sens d'une signature d'émargement. */
const EMARGEMENT: Record<string, string> = {
  in: "Arrivée",
  out: "Départ",
  countersign: "Contresignature",
};
export const sensEmargement = (v?: string | null) => traduire(EMARGEMENT, v);

/** Le type d'une évaluation. */
const EVALUATION: Record<string, string> = {
  positionnement: "Positionnement",
  acquis_entree: "Acquis à l'entrée",
  acquis_sortie: "Acquis à la sortie",
  examen: "Examen",
};
export const typeEvaluation = (v?: string | null) => traduire(EVALUATION, v);

/** L'état d'une tentative d'évaluation. */
const TENTATIVE: Record<string, string> = {
  en_cours: "Commencée",
  soumis: "Rendue",
  corrige: "Corrigée",
  expire: "Expirée",
};
export const statutTentative = (v?: string | null) => traduire(TENTATIVE, v);

/** L'état d'une action requise — `a_faire` / `fait` / `annule`. */
const ACTION: Record<string, string> = {
  a_faire: "À faire",
  fait: "Fait",
  annule: "Annulé",
};
export const statutAction = (v?: string | null) => traduire(ACTION, v);

/** L'état d'une réclamation — indicateur 31. */
const RECLAMATION: Record<string, string> = {
  ouverte: "Ouverte",
  en_cours: "En traitement",
  resolue: "Résolue",
  classee: "Classée",
};
export const statutReclamation = (v?: string | null) => traduire(RECLAMATION, v);

/** L'état d'un document à signer. */
const DOCUMENT: Record<string, string> = {
  brouillon: "Brouillon",
  genere: "Généré",
  envoye: "Envoyé",
  signe: "Signé",
  annule: "Annulé",
};
export const statutDocument = (v?: string | null) => traduire(DOCUMENT, v);

/** Le support d'un contenu de cours. */
const CONTENU: Record<string, string> = {
  text: "Texte",
  video: "Vidéo",
  pdf: "PDF",
  scorm: "SCORM",
  xapi: "xAPI",
  quiz: "Quiz",
  link: "Lien",
};
export const typeContenu = (v?: string | null) => traduire(CONTENU, v);

/** `learn_programs.nature` — la catégorie légale de l'action. */
const NATURE: Record<string, string> = {
  action_formation: "Action de formation",
  bilan_competences: "Bilan de compétences",
  vae: "VAE",
  apprentissage: "Apprentissage",
};
export const natureProgramme = (v?: string | null) => traduire(NATURE, v);

/** `learn_programs.modality`. */
const MODALITE: Record<string, string> = {
  presentiel: "Présentiel",
  distanciel: "Distanciel",
  mixte: "Mixte",
};
export const modalite = (v?: string | null) => traduire(MODALITE, v);

/** Les rôles, tels qu'ils se disent à une personne. */
const ROLE: Record<string, string> = {
  super_admin: "Super administrateur",
  admin: "Administrateur",
  formateur: "Formateur",
  entreprise: "Entreprise cliente",
  auditeur: "Auditeur",
  apprenant: "Apprenant",
  prospect: "Visiteur",
};
export const nomRole = (v?: string | null) => traduire(ROLE, v);
