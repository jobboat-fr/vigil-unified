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
    // Voulu, pas cassé : l'assistant accompagne pendant les créneaux de formation, et
    // reste ouvert aux abonnés. On propose, on ne s'excuse pas.
    const prochain = quand(detail?.prochain_creneau);
    return {
      registre: "offre",
      titre: "L'assistant est ouvert pendant vos formations",
      detail: prochain
        ? `Il vous accompagnera de nouveau ${prochain}. L'abonnement y donne accès à tout moment.`
        : "Il vous accompagne pendant vos créneaux. L'abonnement y donne accès à tout moment.",
      geste: { texte: "Voir l'abonnement", vers: "/abonnement" },
      reessayable: false,
      reference,
    };
  }

  if (statut === 403) {
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
