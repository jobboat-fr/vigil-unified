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

// ----------------------------------------------------------------- thèmes de formation

/** Un thème tel que le serveur le rend : un code, et sa valeur quand il y en a une. */
export interface ThemeFormation {
  code: string;
  valeur?: string | number | null;
}

/**
 * Le libellé d'un thème.
 *
 * Les règles vivent côté serveur (`app/learn/themes.py`) — le serveur dit ce qui est vrai,
 * l'écran dit comment ça se dit. Le nombre de places n'est donc jamais recalculé ici : il
 * arrive déjà compté, et une pastille de rareté qui se recalculerait à l'écran pourrait
 * diverger de ce que la base sait.
 */
export function libelleTheme(t: ThemeFormation): string {
  switch (t.code) {
    case "complet":
      return "Complet";
    case "annulee":
      return "Annulée";
    case "dernieres_places": {
      const n = Number(t.valeur ?? 0);
      return n === 1 ? "Dernière place" : `Plus que ${n} places`;
    }
    case "session_confirmee":
      return "Session confirmée";
    case "nouvelle_session":
      return "Nouvelle session";
    case "derniere_session":
      return "Dernière session programmée";
    case "nouveau":
      return "Nouveau";
    case "plus_suivi":
      return "Le plus suivi";
    case "certifiante":
      return t.valeur ? `Certifiante · ${t.valeur}` : "Certifiante";
    case "opco":
      return "Éligible OPCO";
    case "entree_permanente":
      return "Entrée permanente";
    case "nouveau_format":
      return "Nouveau format";
    case "prix_ferme":
      return "Prix ferme";
    default:
      return humaniser(t.code);
  }
}

// ----------------------------------------------------------------- la passerelle (pages opérateur)
//
// Les pages héritées de VIGIL affichaient les valeurs de la passerelle telles quelles :
// `pending`, `reconciled`, `live`… Mêmes principes qu'au-dessus. Les valeurs sont relevées
// dans `winny_gateway/migrations` (les colonnes n'ont pas de `check`, elles portent la liste
// en commentaire) et dans `winny_gateway/ops/engine.py` pour les pôles.

/** `outbound_actions.status` (021) — une action sortante soumise à validation. */
const ACTION_SORTANTE: Record<string, string> = {
  pending: "En attente",
  executed: "Exécutée",
  rejected: "Refusée",
  failed: "Échouée",
};
export const statutActionSortante = (v?: string | null) => traduire(ACTION_SORTANTE, v);

/** `finance_transactions.status` (011) — capturer, classer, rapprocher. */
const OPERATION: Record<string, string> = {
  uncategorized: "À classer",
  categorized: "Classée",
  reconciled: "Rapprochée",
};
export const statutOperation = (v?: string | null) => traduire(OPERATION, v);

/** `finance_connections.status` (018) et `connections.status` (020). */
const LIAISON: Record<string, string> = {
  active: "Active",
  error: "En erreur",
  revoked: "Révoquée",
};
export const statutLiaison = (v?: string | null) => traduire(LIAISON, v);

/** `connections.kind` (020) — la famille d'un connecteur, déclarée par chaque intégration. */
const FAMILLE_CONNECTEUR: Record<string, string> = {
  engineering: "Développement",
  email: "Messagerie",
  crm: "CRM",
  tasks: "Tâches",
  payments: "Paiements",
  bank: "Banque",
  accounting: "Comptabilité",
  generic: "Autre",
};
export const familleConnecteur = (v?: string | null) => traduire(FAMILLE_CONNECTEUR, v);

/** `departments.status` (017) — un pôle n'est actif qu'après son autotest. */
const POLE: Record<string, string> = {
  provisioning: "En préparation",
  live: "Actif",
  failing: "En échec",
};
export const statutPole = (v?: string | null) => traduire(POLE, v);

/** `ops_tasks.status` (017) — une exécution de pôle. */
const TACHE_POLE: Record<string, string> = {
  queued: "En file",
  working: "En cours",
  done: "Terminée",
  blocked: "Bloquée",
  halted: "Arrêtée",
};
export const statutTachePole = (v?: string | null) => traduire(TACHE_POLE, v);

/**
 * Les pôles et leurs travaux (`ops/engine.py`), dits en français.
 *
 * Seul l'affichage change : le serveur garde ses identifiants et son `mandate` anglais, qui
 * nourrit aussi les consignes des agents — le traduire là-bas changerait leur comportement.
 * Un pôle ajouté côté serveur et absent d'ici garde son texte d'origine. La clé est le
 * `slug` du pôle : son `id` est un identifiant propre à chaque organisme.
 */
const POLES: Record<string, { nom: string; mandat: string }> = {
  support: { nom: "Support", mandat: "Trier la boîte de réception : classer chaque message et préparer une réponse à ceux qui en attendent une." },
  finance: { nom: "Finance", mandat: "Rapprocher les comptes : relever les opérations bancaires, classer chacune et signaler les anomalies à revoir." },
  revenue: { nom: "Ventes", mandat: "Garder les affaires en mouvement : préparer une relance pour chaque affaire arrêtée en proposition ou en négociation." },
  marketing: { nom: "Marketing", mandat: "Préparer des campagnes pour la base de contacts : public, canaux et variantes de message." },
  growth: { nom: "Prospection", mandat: "Trouver et qualifier les prospects entrants dans le CRM, puis confier les affaires au pôle Ventes." },
  legal: { nom: "Juridique", mandat: "Relire les documents de l'organisme (le coffre) : risques, obligations et échéances, sources citées." },
  operations: { nom: "Opérations", mandat: "Suivre les actions ouvertes et le travail bloqué : un point d'étape déterministe." },
  cos: { nom: "Coordination", mandat: "Répartir le travail entre les pôles et rédiger la note de synthèse de la direction." },
};
export const nomPole = (slug: string, nomServeur: string) => POLES[slug]?.nom ?? nomServeur;
export const mandatPole = (slug: string, mandatServeur: string) => POLES[slug]?.mandat ?? mandatServeur;

/** Le regard qui relit un pôle (`head_lens`). */
const REGARD: Record<string, string> = {
  comms: "communication",
  cfo_review: "direction financière",
  cro: "direction commerciale",
  cmo: "direction marketing",
  legal_review: "juridique",
  coo: "direction des opérations",
  cos: "coordination",
};
export const regardPole = (v?: string | null) => (v ? REGARD[v] ?? humaniser(v).toLowerCase() : "");

/** Les travaux d'un pôle (`jobs`), en verbe : ce sont des boutons. */
const TRAVAIL: Record<string, string> = {
  run: "Lancer",
  triage: "Trier",
  reconcile: "Rapprocher",
  report: "Rapport",
  analyze: "Analyser",
  follow_up: "Relancer",
  campaign: "Campagne",
  scout: "Prospecter",
  review: "Relire",
  digest: "Point d'étape",
  route: "Répartir",
  brief: "Note de synthèse",
  selftest: "Autotest",
};
export const nomTravail = (v?: string | null) => traduire(TRAVAIL, v);

/**
 * `subscriptions.status` — les états d'abonnement de Stripe, recopiés tels quels par le
 * webhook (`routes/billing.py`), plus `inactive` que le webhook pose quand Stripe n'en dit rien.
 */
const ABONNEMENT: Record<string, string> = {
  active: "Actif",
  trialing: "Période d'essai",
  past_due: "Paiement en retard",
  unpaid: "Impayé",
  canceled: "Résilié",
  incomplete: "Paiement à finaliser",
  incomplete_expired: "Paiement expiré",
  paused: "Suspendu",
  inactive: "Inactif",
};
export const statutAbonnement = (v?: string | null) => traduire(ABONNEMENT, v);

/** Le nom d'une formule, tel que `ops/billing.py` (`OPS_PLANS`) le donne à la page Facturation. */
const FORMULE: Record<string, string> = {
  free: "Gratuit",
  starter: "Starter",
  pro: "Pro",
  team: "Team",
  enterprise: "Enterprise",
};
export const nomFormule = (v?: string | null) => traduire(FORMULE, v);
