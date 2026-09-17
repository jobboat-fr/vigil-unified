/** Libellés et formats du studio, partagés entre l'écran connecté et la page de partage. */

export const KINDS = ["proposal", "brief", "contract", "memo", "report"] as const;

export const KIND_LABELS: Record<string, string> = {
  proposal: "Proposition",
  brief: "Cahier des charges",
  contract: "Contrat",
  memo: "Note de décision",
  report: "Rapport",
};

export const ACCESS_LABELS: Record<string, string> = {
  owner: "Le vôtre",
  edit: "Peut modifier",
  view: "Lecture seule",
};

export function dateLongue(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
}

/** « il y a 3 min », « hier », « le 12 septembre » — une date qu'on lit sans calculer. */
export function dateRelative(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return "à l'instant";
  if (s < 3600) return `il y a ${Math.floor(s / 60)} min`;
  if (s < 86400) return `il y a ${Math.floor(s / 3600)} h`;
  if (s < 172800) return "hier";
  return `le ${d.toLocaleDateString("fr-FR", { day: "numeric", month: "long" })}`;
}
