// Un onglet ouvert avant un déploiement ne doit pas casser.
//
// Chaque page est un fichier à part, chargé à la première visite, dont le nom porte une
// empreinte du build (`MeetingRoomPage-NbQvHwnL.js`). Un déploiement remplace ces fichiers :
// un onglet resté ouvert demande alors l'ancien nom, le serveur ne l'a plus, et le
// navigateur répond « Importing a module script failed ». C'est ce qu'Azer a vu le 29/09 au
// soir sur son téléphone — un écran « Incident », puis la salle de réunion d'avant, en
// anglais, alors que la version en ligne était déjà corrigée.
//
// La réponse juste n'est pas un message d'erreur : c'est recharger, une fois, pour prendre
// la version en ligne. Une fois seulement — si le rechargement ne règle rien (réseau coupé,
// fichier réellement absent), on laisse l'écran d'incident parler plutôt que de boucler.

const CLE = "vtlvs:rechargement-version";
const DELAI_ANTI_BOUCLE_MS = 60_000;

const MOTIFS = [
  /Importing a module script failed/i, // Safari
  /Failed to fetch dynamically imported module/i, // Chrome
  /error loading dynamically imported module/i, // Firefox
  /Unable to preload CSS/i, // Vite, feuille de style d'une page
  /ChunkLoadError|Loading chunk \S+ failed/i,
];

/** L'erreur vient-elle d'un fichier de page introuvable (onglet plus vieux que le déploiement) ? */
export function estEchecDeModule(e: unknown): boolean {
  const message = e instanceof Error ? e.message : typeof e === "string" ? e : "";
  return MOTIFS.some((m) => m.test(message));
}

/** Recharge la page pour prendre la version en ligne. Rend `false` si un rechargement vient
 *  d'être tenté (moins d'une minute) ou si le stockage de session est bloqué : dans les deux
 *  cas, recharger encore risquerait une boucle. */
export function rechargerPourNouvelleVersion(): boolean {
  try {
    const derniere = Number(sessionStorage.getItem(CLE) || 0);
    if (Date.now() - derniere < DELAI_ANTI_BOUCLE_MS) return false;
    sessionStorage.setItem(CLE, String(Date.now()));
  } catch {
    return false;
  }
  window.location.reload();
  return true;
}

/** Vite émet `vite:preloadError` quand le préchargement d'une page échoue : on recharge
 *  avant même que l'écran d'incident ait lieu d'apparaître. */
export function installerRepriseDeVersion(): void {
  window.addEventListener("vite:preloadError", (ev) => {
    if (rechargerPourNouvelleVersion()) ev.preventDefault();
  });
}
