/**
 * Les agents d'AZZ&CO Labs, tels que l'application les présente.
 *
 * Une seule source pour les trois marques : l'écran agentique, la page d'abonnement et les
 * encarts posés sur les pages métier lisent tous cette liste. Les adresses des tableaux de
 * bord sont celles des sous-domaines réels ; chaque agent tourne sur son propre runtime,
 * isolé des autres.
 */

export type RoleLearn = "super_admin" | "admin" | "formateur" | "auditeur" | "apprenant" | "entreprise";

export type Agent = {
  id: "azzmin" | "azzco" | "azzcom";
  nom: string;
  accroche: string;
  /** Ce que l'agent fait, en clair, pour quelqu'un qui découvre. */
  mission: string;
  /** Ses capacités concrètes, telles qu'elles existent aujourd'hui. */
  capacites: string[];
  /** Ce qu'il ne fera jamais — dit sur la carte, parce que ça rassure plus que ça n'inquiète. */
  limites: string[];
  /** Rôles à qui la carte est proposée. */
  roles: RoleLearn[];
  /** Pages de l'application où cet agent intervient. */
  pages: { libelle: string; chemin: string }[];
  tableauDeBord: string;
  logo: string;
  accent: string;
  /** Prix mensuel affiché, en euros, hors taxes. */
  prix: number;
};

export const AGENTS: Agent[] = [
  {
    id: "azzmin",
    nom: "AZZMIN",
    accroche: "L'administration de la plateforme",
    mission:
      "Il tient la plateforme : comptes, sessions, créneaux, coffre, documents, supervision. " +
      "Il prépare ce qui doit être validé par un humain et exécute le reste, chaque action " +
      "conséquente étant passée au protocole AZZING et journalisée.",
    capacites: [
      "Lire l'état réel de la plateforme et des journaux avant de conclure",
      "Préparer et générer les documents : conventions, contrats, attestations, rapports",
      "Préparer les créations de compte et les modifications de fiche",
      "Vérifier les entrées et sorties de session, et signaler ce qui manque",
      "Rédiger les courriels et les messages, envoyés après accord",
    ],
    limites: [
      "Il ne signe aucun émargement, ne crée aucun compte et n'émet aucun document seul : la plateforme le lui refuse",
      "Il ne divulgue rien sur une personne à quelqu'un d'autre, même s'il y a accès",
    ],
    roles: ["super_admin", "admin", "auditeur", "formateur"],
    pages: [
      { libelle: "Demandes d'inscription", chemin: "/learn/demandes" },
      { libelle: "Personnes", chemin: "/learn/people" },
      { libelle: "Coffre", chemin: "/learn/coffre" },
      { libelle: "Émargement", chemin: "/learn/emargement" },
    ],
    tableauDeBord: "https://azzmin.vtlvs.com",
    logo: "/marques/azzmin.svg",
    accent: "#5B5BD6",
    prix: 149,
  },
  {
    id: "azzco",
    nom: "AZZCO",
    accroche: "La coordination, le droit et les comptes",
    mission:
      "Il suit l'intérieur de l'organisme : planning, dossiers, échéances, factures, " +
      "obligations légales. Sur toute question de droit ou de comptabilité, il cite le texte " +
      "ou la pièce sur laquelle il se fonde et explique son raisonnement.",
    capacites: [
      "Suivre les demandes, les sessions, les formateurs et les places",
      "Préparer devis, conventions, contrats et relances",
      "Vérifier la complétude des pièces comptables et les échéances",
      "Citer l'article, la pièce ou l'indicateur qui fonde sa réponse",
      "Signaler ce qui dérape avant que ça ne coûte",
    ],
    limites: [
      "Il n'est ni avocat ni expert-comptable : sur un point qui engage, il prépare le dossier et renvoie au professionnel",
      "Rien ne part vers l'extérieur sans accord explicite",
    ],
    roles: ["super_admin", "admin", "formateur"],
    pages: [
      { libelle: "Calendrier", chemin: "/learn/calendar" },
      { libelle: "Parcours", chemin: "/learn/parcours" },
      { libelle: "Finance", chemin: "/finance" },
      { libelle: "Documents", chemin: "/learn/coffre" },
    ],
    tableauDeBord: "https://azzco.vtlvs.com",
    logo: "/marques/azzco.svg",
    accent: "#1F8A70",
    prix: 129,
  },
  {
    id: "azzcom",
    nom: "AZZCOM",
    accroche: "La vente et la relation client",
    mission:
      "Il répond aux visiteurs du site et aux candidats : il qualifie le besoin, recommande " +
      "une formation, donne le prix et les dates sans détour, et conduit vers la réservation. " +
      "Tous ses chiffres viennent du catalogue, jamais de sa mémoire.",
    capacites: [
      "Répondre en quelques phrases, prix et dates vérifiés à la source",
      "Qualifier un besoin et recommander une formation précise",
      "Conduire vers la réservation ou vers un conseiller",
      "Tenir la relation sur le site et dans l'application",
    ],
    limites: [
      "Aucun accès aux dossiers personnels",
      "Aucune promesse d'emploi, de résultat ou d'accord de financement",
    ],
    roles: ["super_admin", "admin"],
    pages: [
      { libelle: "Demandes d'inscription", chemin: "/learn/demandes" },
      { libelle: "CRM", chemin: "/crm" },
    ],
    tableauDeBord: "https://azzcom.vtlvs.com",
    logo: "/marques/azzcom.svg",
    accent: "#E4572E",
    prix: 99,
  },
];

export const agentsPourRole = (role: RoleLearn | null): Agent[] =>
  role ? AGENTS.filter((a) => a.roles.includes(role)) : [];

export const agentsPourPage = (chemin: string): Agent[] =>
  AGENTS.filter((a) => a.pages.some((p) => p.chemin === chemin));

/**
 * L'abonnement aux agents.
 *
 * Le paiement n'est pas encore ouvert : la fonction renvoie donc « non abonné » pour tout le
 * monde, et les cartes restent verrouillées. Quand la facturation sera branchée, c'est ici
 * qu'on lira l'état réel de l'abonnement de l'organisme — nulle part ailleurs, pour qu'un
 * seul endroit décide de ce qui est ouvert.
 */
export type EtatAbonnement = { abonne: boolean; enPreparation: boolean };

export function useAbonnementAgents(): EtatAbonnement {
  return { abonne: false, enPreparation: true };
}
