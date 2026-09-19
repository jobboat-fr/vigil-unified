// Une référence par requête — le fil qui relie ce que voit la personne à ce qu'on lit
// dans les journaux.
//
// Le navigateur pose `x-request-id` sur chaque appel ; la passerelle et LEARN le
// reprennent tel quel dans leur ligne de journal (`requete_id`) et le renvoient dans la
// réponse. Quand un écran affiche « référence 7f3c… », cette chaîne se cherche
// directement dans Loki : plus besoin de deviner l'heure ni la personne.
//
// Format : 32 caractères hexadécimaux, comme `uuid4().hex` côté Python — les deux
// mondes écrivent la même chose, les recherches n'ont pas de cas particulier.

const DERNIERES: string[] = [];
const MEMOIRE_MAX = 10;

/** Un identifiant de requête, aléatoire, sans tiret. */
export function nouvelleReference(): string {
  const brut =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`.padEnd(36, "0");
  return brut.replace(/-/g, "").slice(0, 32);
}

/** Retient une référence pour l'écran d'erreur : la dernière est la plus parlante. */
export function memoriserReference(reference: string | null | undefined): void {
  if (!reference) return;
  DERNIERES.unshift(reference);
  if (DERNIERES.length > MEMOIRE_MAX) DERNIERES.length = MEMOIRE_MAX;
}

/** La référence du dernier appel — ce qu'un écran d'erreur montre quand l'erreur
 *  vient du rendu et non d'une réponse précise. */
export function derniereReference(): string | undefined {
  return DERNIERES[0];
}

/** Les huit premiers caractères : assez pour retrouver la ligne, assez court pour être
 *  lu au téléphone. */
export function referenceCourte(reference: string | null | undefined): string {
  return (reference ?? "").slice(0, 8) || "—";
}
