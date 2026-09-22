/**
 * Ce qu'on dit à une personne quand une requête n'aboutit pas.
 *
 * Le défaut qu'on corrige ici est mécanique, pas cosmétique : `LearnError` est construite
 * avec `code ?? "HTTP 404"` comme message, et vingt-quatre écrans affichent `err.message`.
 * Résultat, la personne lit `organisme_hors_perimetre` ou `HTTP 404`. Ce n'est pas un
 * message, c'est une chaîne de journal égarée dans une interface.
 *
 * Trois qualités, dans cet ordre :
 *
 *  1. **Exact.** Un refus délibéré n'est pas une panne. L'assistant fermé hors créneau
 *     (402) est une limite voulue ; l'afficher en rouge à côté d'un « réessayer » ment sur
 *     ce qui se passe et fait chercher un problème qui n'existe pas.
 *  2. **Actionnable.** Dire le geste suivant. « Accès refusé » laisse sur place ;
 *     « réservé à l'administration de votre organisme » dit à qui s'adresser.
 *  3. **Court.** Deux phrases. Personne ne lit un paragraphe d'excuse.
 *
 * Et une règle de sécurité qui prime sur le confort : **ce qui appartient à un autre
 * organisme n'existe pas.** Un 403 « hors périmètre » se raconte comme un 404. Distinguer
 * les deux dirait à qui cherche que la ressource existe ailleurs — c'est précisément ce
 * qu'un contrôle d'accès est censé taire.
 */

import { referenceCourte } from "./reference";

/** Le registre commande le ton, l'icône et la présence d'un « réessayer ». */
export type Registre =
  | "session" // il faut se reconnecter
  | "refus" // le droit manque, et ce n'est pas une erreur
  | "absent" // ça n'existe pas, ou plus
  | "offre" // c'est fermé ici, mais ouvert ailleurs ou autrement
  | "saisie" // la demande est incomplète ou mal formée
  | "attente" // c'est temporaire, le temps règle le problème
  | "panne"; // c'est de notre côté

export interface Geste {
  texte: string;
  /** Une destination interne, ou rien si le geste est porté par `reessayer`. */
  vers?: string;
}

export interface Explication {
  registre: Registre;
  /** Court, sans point final : c'est un titre. */
  titre: string;
  /** Une phrase, deux au plus. */
  detail?: string;
  /** Le geste principal proposé à la personne. */
  geste?: Geste;
  /** Un nouvel essai a-t-il une chance d'aboutir ? Un refus de droit : non. */
  reessayable: boolean;
  /** La référence de requête, quand il y en a une. */
  reference?: string;
}

/** La forme commune de `LearnError` et `GatewayError` — on ne dépend d'aucune des deux. */
interface ErreurConnue {
  status?: number;
  code?: string;
  detail?: unknown;
  reference?: string;
  message?: string;
}

const objet = (v: unknown): Record<string, unknown> | null =>
  v && typeof v === "object" ? (v as Record<string, unknown>) : null;

/** Les ressources de la passerelle, nommées comme la personne les voit dans le menu. */
const RESSOURCES: Record<string, string> = {
  room: "la salle de réunion",
  mail: "la messagerie",
  crm: "le CRM",
  finance: "la finance",
  ops: "l'équipe agentique",
  legal: "le juridique",
  studio: "le studio",
  vault: "le coffre",
};

/**
 * Les fonctions qui dépendent d'un prestataire externe, et ce qu'elles s'appellent.
 *
 * Elles échouent en 501 ou 503 quand la clé du prestataire manque. Le 503 générique dit
 * « c'est temporaire, réessayez » : c'est faux ici, et cruel — attendre ne configurera
 * jamais rien. Ces pannes-là se règlent par quelqu'un, pas par le temps, et le message
 * doit envoyer vers ce quelqu'un.
 */
const NON_INSTALLE: Record<string, string> = {
  livekit_not_configured: "La visioconférence",
  livekit_api_missing: "La visioconférence",
  avatar_unavailable: "L'avatar en réunion",
  tavus_not_configured: "L'avatar en réunion",
};

const ACTIONS: Record<string, string> = {
  read: "consulter",
  create: "créer dans",
  update: "modifier",
  delete: "supprimer dans",
  host: "animer",
  join: "rejoindre",
  export: "exporter",
  sign: "signer",
};

/** « le 13 mars à 9 h 00 », ou rien si la date est illisible. */
function quand(iso: unknown): string | null {
  if (typeof iso !== "string" || !iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString("fr-FR", {
    weekday: "long",
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Le délai annoncé par un 429, en toutes lettres. */
function patienter(detail: unknown): string {
  const o = objet(detail);
  const s = Number(o?.retry_after ?? o?.["retry-after"]);
  if (!Number.isFinite(s) || s <= 0) return "Réessayez dans une minute.";
  if (s < 60) return `Réessayez dans ${Math.ceil(s)} secondes.`;
  return `Réessayez dans ${Math.ceil(s / 60)} minutes.`;
}

/**
 * Traduit n'importe quel échec en quelque chose qu'une personne peut lire et suivre.
 *
 * `quoi` nomme ce que l'écran tentait de faire, au groupe nominal : « la liste des
 * sessions », « votre émargement ». Il sert à écrire « la liste des sessions est
 * introuvable » plutôt que « introuvable ».
 */
export function expliquer(erreur: unknown, quoi?: string): Explication {
  const e = (erreur ?? {}) as ErreurConnue;
  const statut = typeof e.status === "number" ? e.status : undefined;
  const code = e.code ?? (objet(e.detail)?.error as string | undefined);
  const detail = objet(e.detail);
  const reference = e.reference;
  const sujet = quoi ? `${quoi}` : "cette page";

  // Pas de statut du tout : la requête n'est jamais partie. Réseau coupé, origine
  // injoignable, requête interrompue. Ce n'est ni un refus ni une panne serveur, et le
  // dire évite à quelqu'un dans un train de chercher un problème chez nous.
  if (statut === undefined || statut === 0) {
    if (e.code === "NO_SESSION") {
      return {
        registre: "session",
        titre: "Votre session a expiré",
        detail: "Reconnectez-vous : vous reviendrez exactement ici.",
        geste: { texte: "Se reconnecter" },
        reessayable: false,
        reference,
      };
    }
    return {
      registre: "attente",
      titre: "Connexion interrompue",
      detail: "La demande n'a pas pu partir. Vérifiez votre connexion réseau.",
      reessayable: true,
      reference,
    };
  }

  if (statut === 401) {
    // Une session expirée et une absence de session ne se règlent pas pareil : la
    // première se répare en un clic, la seconde demande de se connecter. Dire « votre
    // session a expiré » à quelqu'un qui n'a jamais été connecté est faux ; dire
    // « connectez-vous » à quelqu'un qui travaillait depuis une heure est insultant.
    const expiree = code === "invalid_session" || e.detail === "invalid_session";
    return {
      registre: "session",
      titre: expiree ? "Votre session a expiré" : "Connexion nécessaire",
      detail: expiree
        ? "Reconnectez-vous : vous reviendrez exactement ici."
        : `Connectez-vous pour accéder à ${sujet}.`,
      geste: { texte: "Se connecter" },
      reessayable: false,
      reference,
    };
  }

  if (statut === 402) {
    // Voulu, pas cassé : une limite d'offre n'est pas une panne. On propose, on ne
    // s'excuse pas, et on ne propose surtout pas de « réessayer » — rien ne changerait.
    //
    // Le texte dépendait de l'assistant, seul émetteur de 402 le jour où ce fichier a été
    // écrit. Une salle ou un studio qui refuserait pour la même raison aurait annoncé
    // « L'assistant est ouvert pendant vos formations » : faux, et déroutant. Le code
    // porte le cas particulier ; le cas général reste vrai partout.
    if (code === "assistant_hors_formation") {
      const prochain = quand(detail?.prochain_creneau);
      // Pas de bouton vers /abonnement ici, et c'est délibéré. Ce refus-là n'atteint
      // qu'un apprenant — la passerelle rend les autres rôles toujours ouverts — et
      // /abonnement est réservé à l'administration de l'organisme. Le bouton aurait donc
      // mené, à tous les coups, à un écran « accès réservé » : le défaut qu'on corrige,
      // déplacé d'un clic. On dit plutôt à qui s'adresser.
      return {
        registre: "offre",
        titre: "L'assistant est ouvert pendant vos formations",
        detail: prochain
          ? `Il vous accompagnera de nouveau ${prochain}. En dehors, l'accès permanent est ouvert par votre organisme de formation.`
          : "Il vous accompagne pendant vos créneaux. En dehors, l'accès permanent est ouvert par votre organisme de formation.",
        reessayable: false,
        reference,
      };
    }
    return {
      registre: "offre",
      titre: `${sujet.charAt(0).toUpperCase()}${sujet.slice(1)} demande un abonnement`,
      detail: phrasePrete(e) ?? "Cette fonction n'est pas comprise dans votre offre actuelle.",
      geste: { texte: "Voir l'abonnement", vers: "/abonnement" },
      reessayable: false,
      reference,
    };
  }

  if (statut === 403) {
    // Une limite d'offre annoncée en 403 reste une limite d'offre. Certaines routes
    // anciennes refusent en 403 avec une phrase qui parle d'abonnement (auto_trade) :
    // la rendre en « votre rôle ne donne pas ce droit » enverrait la personne demander
    // à son administration ce que seule une souscription débloque.
    const phrase403 = phrasePrete(e);
    if (code === "plan_requis" || (phrase403 && /abonnement|subscription|forfait|offre payante/i.test(phrase403))) {
      return {
        registre: "offre",
        titre: `${sujet.charAt(0).toUpperCase()}${sujet.slice(1)} demande un abonnement`,
        detail: "Cette fonction n'est pas comprise dans votre offre actuelle.",
        geste: { texte: "Voir l'abonnement", vers: "/abonnement" },
        reessayable: false,
        reference,
      };
    }

    // Hors périmètre : on ne confirme pas l'existence de la ressource. Même phrase
    // qu'un 404, volontairement.
    if (code === "organisme_hors_perimetre" || code === "tenant_mismatch") {
      return {
        registre: "absent",
        titre: "Introuvable",
        detail: `${sujet.charAt(0).toUpperCase()}${sujet.slice(1)} n'existe pas, ou n'est plus accessible.`,
        geste: { texte: "Retour à l'accueil", vers: "/accueil" },
        reessayable: false,
        reference,
      };
    }

    if (code === "famille_interdite_a_un_agent") {
      return {
        registre: "refus",
        titre: "Un assistant ne peut pas envoyer ce message",
        detail:
          "Les messages qui ouvrent un compte ou un document signé ne partent que d'une personne. Envoyez-le vous-même.",
        reessayable: false,
        reference,
      };
    }

    if (code === "forbidden" && detail) {
      const quelle = RESSOURCES[String(detail.resource)] ?? String(detail.resource ?? sujet);
      const faire = ACTIONS[String(detail.action)] ?? String(detail.action ?? "ouvrir");
      return {
        registre: "refus",
        titre: `Vous ne pouvez pas ${faire} ${quelle}`,
        detail: `Votre rôle${detail.role ? ` (${detail.role})` : ""} ne donne pas ce droit. L'administration de votre organisme peut vous l'accorder.`,
        reessayable: false,
        reference,
      };
    }

    return {
      registre: "refus",
      titre: "Accès réservé",
      detail: `Votre rôle ne donne pas accès à ${sujet}. L'administration de votre organisme peut vous l'accorder.`,
      // Un refus sans porte de sortie laisse sur place. Le tableau de bord Formation est
      // la seule page que les six rôles peuvent ouvrir.
      geste: { texte: "Retour au tableau de bord", vers: "/learn" },
      reessayable: false,
      reference,
    };
  }

  if (statut === 404) {
    return {
      registre: "absent",
      titre: "Introuvable",
      detail: `${sujet.charAt(0).toUpperCase()}${sujet.slice(1)} n'existe pas, ou a été supprimée.`,
      geste: { texte: "Retour à l'accueil", vers: "/accueil" },
      reessayable: false,
      reference,
    };
  }

  if (statut === 410) {
    // 410 tombait dans le fourre-tout final, et `meeting_closed` étant un code et non une
    // phrase, `phrasePrete` l'écartait à juste titre : il ne restait que « Cette action
    // n'a pas abouti ». La personne venait de cliquer sur un lien de réunion.
    // Trois 410 distincts, et il faut les distinguer : le studio périme aussi ses liens
    // de partage. Un « Cette réunion est terminée » sur un document partagé enverrait
    // chercher une visioconférence qui n'a jamais existé.
    if (code === "lien_expire") {
      return {
        registre: "absent",
        titre: "Ce lien de partage a expiré",
        detail: "Les liens ont une durée de vie limitée. Demandez-en un nouveau à la personne qui vous l'a envoyé.",
        reessayable: false,
        reference,
      };
    }
    const expire = code === "expired_share_token";
    return {
      registre: "absent",
      titre: expire ? "Ce lien d'invitation a expiré" : "Cette réunion est terminée",
      detail: expire
        ? "Demandez un nouveau lien à la personne qui vous a invité."
        : "L'hôte y a mis fin. Le compte rendu, s'il a été déposé, se trouve dans le coffre.",
      geste: { texte: "Retour au tableau de bord", vers: "/learn" },
      reessayable: false,
      reference,
    };
  }

  if (statut === 409) {
    return {
      registre: "saisie",
      titre: "Cette action entre en conflit",
      // La passerelle joint souvent la phrase utile — « Karim est déjà pris le 13 au
      // matin ». Quand elle est là, elle vaut mieux que tout ce qu'on écrirait ici.
      detail: phrasePrete(e) ?? "Quelque chose a changé entre-temps. Rechargez et reprenez.",
      reessayable: true,
      reference,
    };
  }

  if (statut === 413) {
    return {
      registre: "saisie",
      titre: "Fichier trop volumineux",
      detail: phrasePrete(e) ?? "Choisissez un fichier plus léger.",
      reessayable: false,
      reference,
    };
  }

  if (statut === 422 || statut === 400) {
    return {
      registre: "saisie",
      titre: "Il manque quelque chose",
      detail: phrasePrete(e) ?? "Un champ est absent ou mal renseigné. Vérifiez le formulaire.",
      reessayable: false,
      reference,
    };
  }

  if (statut === 429) {
    return {
      registre: "attente",
      titre: "Trop de demandes d'un coup",
      detail: patienter(e.detail),
      reessayable: true,
      reference,
    };
  }

  // Une fonction qui n'a jamais été installée sur cet espace. Elle doit se distinguer
  // des deux voisines dont elle empruntait les mots : ce n'est pas une panne (rien n'est
  // cassé) et ce n'est pas temporaire (attendre n'installe rien). C'est un réglage
  // manquant, et la seule suite utile est de le dire à qui peut le poser.
  //
  // On ne relaie jamais `detail.message` ici : la passerelle y met `str(exc)` du
  // prestataire, c'est-à-dire une trace technique — parfois une URL interne.
  if (code && NON_INSTALLE[code]) {
    return {
      registre: "panne",
      titre: `${NON_INSTALLE[code]} n'est pas activée sur votre espace`,
      detail:
        "Rien n'est cassé de votre côté, et réessayer n'y changera rien : la fonction n'a pas encore été configurée. Signalez-le à l'administration de votre organisme.",
      geste: { texte: "Aide et support", vers: "/aide" },
      reessayable: false,
      reference,
    };
  }

  if (statut === 501) {
    return {
      registre: "panne",
      titre: "Cette fonction n'est pas disponible ici",
      detail: "Elle n'est pas installée sur cet espace. Réessayer n'y changera rien.",
      geste: { texte: "Aide et support", vers: "/aide" },
      reessayable: false,
      reference,
    };
  }

  if (statut === 503) {
    const base = code === "learn_database_unavailable" || code === "database_unavailable";
    return {
      registre: "attente",
      titre: base ? "La base de données ne répond pas" : "Service momentanément indisponible",
      detail: "C'est temporaire. Rien de ce que vous avez saisi n'a été perdu.",
      reessayable: true,
      reference,
    };
  }

  if (statut >= 500) {
    // Notre faute. On le dit, on montre la référence, et on ne suggère surtout pas à la
    // personne de corriger ce qu'elle a fait — elle n'y est pour rien.
    return {
      registre: "panne",
      titre: "Le service a échoué de notre côté",
      detail: reference
        ? `Vous n'y êtes pour rien. Si cela se reproduit, donnez la référence ${referenceCourte(reference)} au support.`
        : "Vous n'y êtes pour rien. Réessayez dans un instant.",
      geste: { texte: "Aide et support", vers: "/aide" },
      reessayable: true,
      reference,
    };
  }

  return {
    registre: "panne",
    titre: "Cette action n'a pas abouti",
    detail: phrasePrete(e) ?? undefined,
    reessayable: true,
    reference,
  };
}

/**
 * La phrase toute faite du serveur, si c'en est une.
 *
 * Un code technique n'en est pas une. `LearnError` place le code dans `message` faute de
 * mieux, donc un message qui ressemble à `un_code_comme_ca` ou `HTTP 409` est écarté :
 * l'afficher serait exactement le défaut qu'on corrige.
 */
function phrasePrete(e: ErreurConnue): string | null {
  const candidats = [
    typeof e.detail === "string" ? e.detail : null,
    objet(e.detail)?.detail as string | undefined,
    objet(e.detail)?.message as string | undefined,
    e.message,
  ];
  for (const c of candidats) {
    if (typeof c !== "string") continue;
    const t = c.trim();
    if (!t) continue;
    if (/^HTTP \d{3}$/.test(t)) continue;
    if (/^[a-z0-9]+(_[a-z0-9]+)+$/.test(t)) continue; // un code, pas une phrase
    if (!/\s/.test(t)) continue; // un seul mot : jamais une phrase utile
    return t;
  }
  return null;
}

/** Une ligne, pour les endroits trop étroits pour un bloc — un toast, une cellule. */
export function expliquerCourt(erreur: unknown, quoi?: string): string {
  const x = expliquer(erreur, quoi);
  return x.detail ? `${x.titre} — ${x.detail}` : x.titre;
}
