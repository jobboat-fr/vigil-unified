import { useNavigate } from "react-router-dom";
import { Button } from "@nous-research/ui/ui/components/button";
import { cn } from "@/lib/utils";
import { referenceCourte } from "@/lib/reference";
import { expliquer, type Explication, type Registre } from "@/lib/refus";

/**
 * Le bloc qui rend un échec lisible — un seul, pour toute l'application.
 *
 * Avant, chaque écran écrivait le sien : vingt-quatre variantes, et dans la plupart
 * `err.message`, c'est-à-dire un code technique. Une seule forme vaut mieux, parce qu'une
 * personne apprend à la lire une fois.
 *
 * Le registre ne change ni la taille ni la disposition, seulement **une arête de couleur
 * de deux pixels et la présence d'un « réessayer »**. Un refus de droit n'a pas à hurler
 * en rouge : il n'est pas cassé, il est fermé. Et proposer de réessayer là où réessayer ne
 * peut rien donner apprend aux gens à cliquer sans y croire.
 */

/** Une arête, pas un fond : le registre se lit du coin de l'œil sans repeindre l'écran. */
const ARETE: Record<Registre, string> = {
  session: "color-mix(in srgb, currentColor 45%, transparent)",
  refus: "color-mix(in srgb, currentColor 35%, transparent)",
  absent: "color-mix(in srgb, currentColor 25%, transparent)",
  offre: "var(--color-accent, color-mix(in srgb, currentColor 55%, transparent))",
  saisie: "color-mix(in srgb, currentColor 45%, transparent)",
  attente: "color-mix(in srgb, currentColor 30%, transparent)",
  panne: "color-mix(in srgb, currentColor 60%, transparent)",
};

/** Le mot qui coiffe le bloc. « Erreur » serait faux quatre fois sur sept. */
const ENTETE: Record<Registre, string> = {
  session: "Session",
  refus: "Accès",
  absent: "Introuvable",
  offre: "Disponibilité",
  saisie: "À compléter",
  attente: "Momentané",
  panne: "Incident",
};

export function Refus({
  erreur,
  quoi,
  onReessayer,
  compact = false,
  className,
}: {
  /** L'erreur telle qu'elle a été attrapée : `LearnError`, `GatewayError`, ou autre. */
  erreur: unknown;
  /** Ce que l'écran tentait d'obtenir, au groupe nominal : « la liste des sessions ». */
  quoi?: string;
  onReessayer?: () => void;
  compact?: boolean;
  className?: string;
}) {
  const x: Explication = expliquer(erreur, quoi);
  const naviguer = useNavigate();

  return (
    <div
      role={x.registre === "panne" || x.registre === "session" ? "alert" : "status"}
      aria-live="polite"
      className={cn(
        "w-full overflow-hidden rounded-xl border border-current/12",
        compact ? "max-w-xl" : "mx-auto max-w-xl",
        className,
      )}
    >
      <div aria-hidden className="h-[2px] w-full" style={{ background: ARETE[x.registre] }} />
      <div className={compact ? "px-4 py-4" : "px-5 py-5"}>
        <div className="text-[11px] uppercase tracking-[0.18em] text-text-secondary">
          {ENTETE[x.registre]}
        </div>
        <p className="mt-2 text-sm font-semibold">{x.titre}</p>
        {x.detail && (
          <p className="mt-1.5 text-sm leading-relaxed text-text-secondary">{x.detail}</p>
        )}

        {(x.reessayable && onReessayer) || x.geste ? (
          <div className="mt-4 flex flex-wrap items-center gap-2">
            {x.reessayable && onReessayer && (
              <Button size="sm" onClick={onReessayer}>
                Réessayer
              </Button>
            )}
            {x.geste?.vers && (
              <Button size="sm" outlined onClick={() => naviguer(x.geste!.vers!)}>
                {x.geste.texte}
              </Button>
            )}
          </div>
        ) : null}

        {x.reference && (
          <p className="mt-4 border-t border-current/10 pt-3 text-[11px] text-text-secondary">
            Référence <code className="font-mono">{referenceCourte(x.reference)}</code> — à
            donner au support, elle mène directement à la trace de cette requête.
          </p>
        )}
      </div>
    </div>
  );
}
