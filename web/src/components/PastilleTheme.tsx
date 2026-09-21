import { cn } from "@/lib/utils";
import { libelleTheme, type ThemeFormation } from "@/lib/mots";

/**
 * La pastille d'une formation — « Plus que 2 places », « Session confirmée », « Complet ».
 *
 * Elle est là pour informer une décision, pas pour la forcer. Ce qui est délibérément
 * absent : le rouge, le clignotement, la flamme, le compte à rebours, le point
 * d'exclamation. Ces signaux-là ne disent rien sur la formation ; ils disent qu'on veut
 * vous presser, et sur un organisme certifié cela abîme exactement la chose qu'on vend.
 *
 * Trois poids, et le poids suit le **sens**, jamais l'envie de mettre en avant :
 *
 *   `saillant` — une information rare et utile à qui hésite : il reste peu de places, ou
 *                la session est confirmée. C'est le seul cas où l'accent de marque sort.
 *   `sobre`    — un fait ordinaire : nouveau, le plus suivi, éligible OPCO.
 *   `eteint`   — une porte fermée : complet, annulée. Volontairement en retrait, parce que
 *                sa seule utilité est d'éviter un clic inutile.
 *
 * Les libellés viennent de `lib/mots.ts` et les règles du serveur : la pastille ne décide
 * de rien, elle rend ce qu'on lui donne.
 */

type Poids = "saillant" | "sobre" | "eteint";

const POIDS: Record<string, Poids> = {
  dernieres_places: "saillant",
  session_confirmee: "saillant",
  derniere_session: "saillant",
  complet: "eteint",
  annulee: "eteint",
};

const CLASSES: Record<Poids, string> = {
  saillant: "border-current/25 font-medium",
  sobre: "border-current/15 text-text-secondary",
  eteint: "border-current/10 text-text-secondary opacity-70",
};

export function PastilleTheme({
  theme,
  className,
}: {
  theme: ThemeFormation;
  className?: string;
}) {
  const poids = POIDS[theme.code] ?? "sobre";
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] leading-5",
        CLASSES[poids],
        className,
      )}
    >
      {poids === "saillant" && (
        // La même arête d'accent que les blocs de refus : dans toute l'application, ce
        // trait veut dire « à remarquer ». Un vocabulaire visuel s'apprend une fois.
        <span
          aria-hidden
          className="h-2.5 w-[2px] rounded-full"
          style={{ background: "var(--color-accent, currentColor)" }}
        />
      )}
      {libelleTheme(theme)}
    </span>
  );
}

/** La rangée de pastilles d'une formation ou d'une session. Se tait si elle est vide. */
export function Pastilles({
  themes,
  className,
}: {
  themes?: ThemeFormation[] | null;
  className?: string;
}) {
  if (!themes?.length) return null;
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-1.5", className)}>
      {themes.map((t) => (
        <PastilleTheme key={`${t.code}:${t.valeur ?? ""}`} theme={t} />
      ))}
    </span>
  );
}
