// Accueil des comptes, documents à signer, actions requises, e-mails de l'organisme.
// Backend : hbs-backend app/learn/routes/{accueil,actions,emails}.py (migrations 0040-0042).
import { BASE, call, LearnError } from "./learn";

/** Appel sans session : pages publiques à jeton (activation, désinscription, mot de passe). */
async function publicCall<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers: { "content-type": "application/json", accept: "application/json" },
      body: body != null ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new LearnError("service_injoignable", 0, "service_injoignable");
  }
  const payload = (await res.json().catch(() => ({}))) as { detail?: unknown };
  if (!res.ok) {
    const d = payload?.detail;
    const code = typeof d === "object" && d !== null ? (d as { error?: string }).error : undefined;
    throw new LearnError(code ?? `HTTP ${res.status}`, res.status, code, d);
  }
  return payload as T;
}

// ── public ─────────────────────────────────────────────────────────────────
export type Activation = {
  etat: "valide" | "expire" | "utilise" | "remplace";
  email: string;
  nom: string;
  role: string;
  organisme: string;
  logo_url: string | null;
  couleur: string | null;
  expire_le: string;
  regles_mot_de_passe: string;
};
export const lireActivation = (jeton: string) => publicCall<Activation>("GET", `/public/activation/${jeton}`);
export const activerCompte = (jeton: string, mot_de_passe: string) =>
  publicCall<{ active: boolean; email: string; documents_a_signer: number }>("POST", `/public/activation/${jeton}`, {
    mot_de_passe,
    accepte_cgu: true,
    accepte_confidentialite: true,
  });
export const demanderNouveauLien = (jeton: string) =>
  publicCall<{ envoye_si_possible: boolean }>("POST", `/public/activation/${jeton}/nouveau-lien`);
export const lireDesinscription = (j: string) =>
  publicCall<{ organisme: string; email: string; famille: string; libelle: string }>(
    "GET",
    `/public/desinscription?j=${encodeURIComponent(j)}`,
  );
export const confirmerDesinscription = (j: string) =>
  publicCall<{ desinscrit: boolean }>("POST", "/public/desinscription", { j });
export const motDePasseOublie = (email: string) =>
  publicCall<{ envoye_si_compte: boolean }>("POST", "/public/mot-de-passe", { email });

// ── la personne connectée ──────────────────────────────────────────────────
export type ActionRequise = {
  id: string;
  kind: string;
  title: string;
  detail: string | null;
  link_path: string | null;
  due_at: string;
  status: string;
  created_at: string;
  en_retard?: boolean;
};
export type DocumentAttendu = { template_id: string; code: string; kind: string; title: string; version: number };
export type EtatAccueil = {
  profil: { id: string; full_name: string; email: string; role: string; activated_at: string | null } | null;
  statut: "actif" | "a_signer";
  documents_a_signer: DocumentAttendu[];
  actions: ActionRequise[];
  organisme: { name: string; logo_url: string | null; primary_colour: string | null } | null;
};
export const getAccueil = () => call<EtatAccueil>("GET", "/accueil");
export type DocumentALire = {
  id: string;
  titre: string;
  version: number;
  type: string;
  contenu_html: string;
  empreinte: string;
  consentement: string;
  deja_signe: { signed_at: string; signed_name: string; this_hash: string } | null;
};
/**
 * L'état d'accueil, sans le redemander à chaque navigation.
 *
 * `App.tsx` lit cet état pour deux choses : savoir s'il reste un document à signer — auquel
 * cas toute l'application est ramenée sur `/accueil` — et poser le nom et le favicon de
 * l'organisme. Son effet dépendait de `pathname`, donc l'appel repartait à **chaque
 * changement d'écran** : parcourir huit pages produisait dix-sept requêtes, mesurées en
 * production. Chacune traverse la bordure, Railway et Supabase pour une réponse qui, elle,
 * ne change presque jamais.
 *
 * Une minute de fraîcheur suffit pour un document à signer. Ce qui ne suffirait pas, c'est
 * de laisser la porte fermée après une signature : `oublierAccueil()` doit être appelé dès
 * qu'une action a pu changer ce que la personne doit faire, sinon elle reste enfermée
 * jusqu'à l'expiration du cache.
 */
let _dernier: { pose: number; etat: EtatAccueil } | null = null;

export async function getAccueilRecent(ageMax = 60_000): Promise<EtatAccueil> {
  const maintenant = Date.now();
  if (_dernier && maintenant - _dernier.pose < ageMax) return _dernier.etat;
  const etat = await getAccueil();
  _dernier = { pose: maintenant, etat };
  return etat;
}

/** Jette l'état retenu : le prochain appel repartira au serveur. */
export function oublierAccueil(): void {
  _dernier = null;
}

export const getDocumentALire = (id: string) => call<DocumentALire>("GET", `/accueil/documents/${id}`);
export const signerDocument = (id: string, nom_saisi: string, empreinte: string) =>
  call<{ signature_id: string; this_hash: string; restants: number; inscriptions_confirmees: number }>(
    "POST",
    `/accueil/documents/${id}/signer`,
    { nom_saisi, empreinte, consentement: true },
  );
export const getMesSignatures = () =>
  call<{ items: { id: string; title: string; template_version: number; signed_at: string; this_hash: string }[] }>(
    "GET",
    "/accueil/signatures",
  );
export const declarerFait = (id: string) => call<{ id: string }>("POST", `/me/actions/${id}/fait`);

// ── admin : documents à signer ─────────────────────────────────────────────
export type ModeleDocument = {
  id: string;
  code: string;
  kind: string;
  title: string;
  version: number;
  required_for: string[];
  active: boolean;
  signatures: number;
};
export const getDocumentsASigner = () => call<{ items: ModeleDocument[] }>("GET", "/documents-a-signer");
export const creerDocumentASigner = (b: {
  code: string;
  kind: string;
  title: string;
  body_html: string;
  required_for: string[];
}) => call<ModeleDocument>("POST", "/documents-a-signer", b);
export const modifierDocumentASigner = (
  id: string,
  b: { title?: string; body_html?: string; required_for?: string[]; active?: boolean },
) => call<ModeleDocument & { nouvelle_version: boolean }>("PUT", `/documents-a-signer/${id}`, b);
export type LigneSuivi = {
  profile_id: string;
  full_name: string;
  email: string;
  role: string;
  activated_at: string | null;
  template_id: string;
  title: string;
  version: number;
  signed_at: string | null;
};
export const getSuiviSignatures = () => call<{ items: LigneSuivi[] }>("GET", "/documents-a-signer/suivi");
export const envoyerInvitation = (profileId: string) =>
  call<{ envoi: string; erreur: string | null; expire_le: string }>("POST", `/profiles/${profileId}/invitation`);

// ── admin : actions requises ───────────────────────────────────────────────
export type ActionAdmin = ActionRequise & {
  full_name: string;
  email: string;
  role: string;
  rappels: number;
  alerte_envoyee: boolean;
  cancel_reason: string | null;
};
export const getActionsRequises = (statut = "a_faire", enRetard = false) =>
  call<{ items: ActionAdmin[] }>("GET", `/actions-requises?statut=${statut}&en_retard=${enRetard}`);
export const creerActionRequise = (b: {
  kind: string;
  title: string;
  detail?: string | null;
  link_path?: string | null;
  due_on: string;
  assignee_id?: string;
  role?: string;
  session_id?: string;
}) => call<{ crees: number }>("POST", "/actions-requises", b);
export const majActionRequise = (id: string, status: "fait" | "annule", motif?: string) =>
  call<ActionAdmin>("PATCH", `/actions-requises/${id}`, { status, motif });
export type Politique = { reminder_days: number[]; admin_alert_day: number; active: boolean };
export const getPolitique = () => call<Politique>("GET", "/actions-requises/politique");
export const setPolitique = (p: Politique) => call<Politique>("PUT", "/actions-requises/politique", p);

// ── admin : identité et e-mails ────────────────────────────────────────────
export type Marque = {
  tenant_id?: string;
  legal_name?: string;
  logo_url?: string | null;
  primary_colour?: string | null;
  address?: string | null;
  nda?: string | null;
  siret?: string | null;
  footer_mentions?: string | null;
  contact_email?: string | null;
  website?: string | null;
  configured?: boolean;
};
export const getMarque = () => call<Marque>("GET", "/branding");
export const setMarque = (m: Marque) => call<Marque>("PUT", "/branding", m);
export const deposerLogo = (f: File) => {
  const fd = new FormData();
  fd.append("fichier", f);
  return call<Marque>("POST", "/branding/logo", fd);
};
export type Domaine = {
  id: string;
  domain: string;
  status: "en_attente" | "verifie" | "echec" | "retire";
  dns_records: { record: string; name: string; type: string; value: string; priority?: number; status?: string }[];
  verified_at: string | null;
};
export const getDomaines = () =>
  call<{ items: Domaine[]; repli: string; familles: { code: string; libelle: string; adresse: string }[] }>(
    "GET",
    "/mail/domaines",
  );
export const ajouterDomaine = (domain: string) => call<Domaine>("POST", "/mail/domaines", { domain });
export const verifierDomaine = (id: string) => call<Domaine>("POST", `/mail/domaines/${id}/verifier`);
export const retirerDomaine = (id: string) => call<Domaine>("DELETE", `/mail/domaines/${id}`);
export type ModeleEmail = {
  cle: string;
  libelle: string;
  version: number;
  famille: string;
  famille_libelle: string;
  adresse: string;
  envoi_auto: boolean;
  /** Faux pour la copie d'exploitation et le support : il n'y a personne à qui demander
   *  cette validation, donc ces modèles ne figurent pas dans le compte en attente. */
  approbation_requise: boolean;
  valide: boolean;
  valide_le: string | null;
  sujet_exemple: string;
};
/** `en_attente` : combien de modèles ne partiront pas faute de validation. */
export const getModelesEmail = () =>
  call<{ items: ModeleEmail[]; en_attente: number }>("GET", "/mail/modeles");
export const validerModele = (cle: string) => call<{ valide: boolean }>("POST", `/mail/modeles/${cle}/valider`);
export const retirerModele = (cle: string) => call<{ valide: boolean }>("POST", `/mail/modeles/${cle}/retirer`);
export async function apercuModele(cle: string): Promise<string> {
  const { getAccessToken } = await import("./supabase");
  const token = await getAccessToken();
  const r = await fetch(`${BASE}/mail/modeles/${cle}/apercu`, { headers: { authorization: `Bearer ${token}` } });
  if (!r.ok) throw new LearnError(`HTTP ${r.status}`, r.status);
  return r.text();
}
export type Envoi = {
  id: string;
  email: string;
  category: string;
  template_key: string;
  subject: string;
  status: string;
  error: string | null;
  created_at: string;
  sent_at: string | null;
  delivered_at: string | null;
  bounced_at: string | null;
};
export const getEnvois = () => call<{ items: Envoi[] }>("GET", "/mail/envois");

const MESSAGES: Record<string, string> = {
  invitation_inconnue: "Ce lien d'activation n'est pas valable.",
  invitation_expire: "Ce lien a expiré.",
  invitation_utilise: "Ce compte est déjà activé. Connectez-vous avec votre adresse e-mail.",
  invitation_remplace: "Un lien plus récent vous a été envoyé : utilisez le dernier e-mail reçu.",
  mot_de_passe_faible:
    "Mot de passe trop faible : 10 caractères au moins, dont une minuscule, une majuscule et un chiffre.",
  consentements_requis: "Vous devez accepter les conditions d'utilisation et la politique de confidentialité.",
  auth_indisponible: "Le service d'authentification ne répond pas. Réessayez dans un instant.",
  document_modifie: "Le document a été mis à jour pendant votre lecture. Relisez la nouvelle version avant de signer.",
  nom_requis: "Saisissez votre nom complet pour signer.",
  consentement_requis: "Cochez la case de consentement pour signer.",
  signatures_requises: "Des documents attendent votre signature.",
  lien_invalide: "Ce lien n'est pas valable.",
  service_injoignable: "Le service est injoignable. Vérifiez votre connexion.",
  domaine_invalide: "Nom de domaine invalide (exemple : hbs-formation.fr).",
  fournisseur_absent: "L'envoi d'e-mails n'est pas encore configuré sur la plateforme.",
  motif_requis: "Indiquez le motif de l'annulation.",
  admin_organisme_requis: "Réservé à l'administration de l'organisme.",
  aucune_personne: "Aucune personne ne correspond à cette cible.",
};

/** Message français pour les codes d'erreur de l'accueil. */
export function messageAccueil(e: unknown): string {
  const code = e instanceof LearnError ? (e.code ?? e.message) : "";
  return MESSAGES[code] ?? (e instanceof Error ? e.message : "Une erreur est survenue.");
}

// ----------------------------------------------------------------- composer un message

/** Les trois natures. Ce qui les distingue n'est pas la mise en page mais le régime :
 *  `direct` s'adresse à une relation établie et n'est pas désinscriptible ; `annonces`
 *  l'est ; `newsletter` exige en plus un consentement explicite. */
export type NatureMessage = "direct" | "annonces" | "newsletter";

export type MessageAdmin = {
  id: string;
  nature: NatureMessage;
  sujet: string;
  corps: string;
  auteur_nom: string | null;
  cibles: number;
  envoyes: number;
  refuses: number;
  attente: number;
  created_at: string;
};

export const composerMessage = (body: {
  nature: NatureMessage;
  sujet: string;
  corps: string;
  destinataires: string[];
  bouton_texte?: string | null;
  bouton_url?: string | null;
}) => call<{ id: string; cibles: number; differes: number }>("POST", "/messages", body);

export const getMessagesAdmin = () => call<{ items: MessageAdmin[] }>("GET", "/messages");
