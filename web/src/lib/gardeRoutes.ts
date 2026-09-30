import type { PagePermissions } from "@/lib/vigil";

/**
 * Le garde des routes, sorti d'App.tsx pour être testé (29/09).
 *
 * Une seule source : les `roles` et la `capability` de chaque entrée de menu. Une route que
 * le rôle ne peut pas ouvrir affiche l'écran de refus au lieu de la page — sinon la page se
 * chargeait, puis échouait à sa façon (vide, figée, message brut). Une sous-adresse sans
 * entrée de menu hérite du garde de sa page parente (/profiles/new ← /profiles).
 */
export interface EntreeGardee {
  path: string;
  label: string;
  /** Absent : tout le monde. Présent : seuls ces rôles LEARN. */
  roles?: string[];
  /** Page métier : ouverte si la passerelle accorde (ressource, action). Prime sur `roles`
   *  dès que les droits sont connus ; `roles` sert de repli tant qu'ils ne le sont pas. */
  capability?: [string, string];
}

export function navAllowed(n: EntreeGardee, role: string | null, perms: PagePermissions | null): boolean {
  if (n.capability && perms) {
    return perms.grants[n.capability[0]]?.includes(n.capability[1]) ?? false;
  }
  return !n.roles || (!!role && n.roles.includes(role));
}

/** Chaque chemin refusé à ce rôle, avec le libellé de la page qui le garde. */
export function cheminsRefuses(
  entrees: EntreeGardee[],
  chemins: string[],
  role: string | null,
  perms: PagePermissions | null,
): Map<string, string> {
  const refuses = entrees.filter((n) => (n.roles || n.capability) && !navAllowed(n, role, perms));
  const out = new Map<string, string>(refuses.map((n) => [n.path, n.label]));
  // Une adresse qui a SA propre entrée de menu suit sa règle, jamais celle de son parent :
  // /studio/projets peut être ouvert à un rôle à qui /studio serait fermé.
  const auMenu = new Set(entrees.map((n) => n.path));
  for (const chemin of chemins) {
    if (auMenu.has(chemin)) continue;
    // Le parent le plus proche parmi TOUTES les entrées — ouvert ou fermé — décide.
    const parent = entrees
      .filter((n) => chemin.startsWith(`${n.path}/`))
      .sort((x, y) => y.path.length - x.path.length)[0];
    if (parent && out.has(parent.path)) out.set(chemin, parent.label);
  }
  return out;
}
