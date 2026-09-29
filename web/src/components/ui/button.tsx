import { cloneElement, isValidElement } from "react";
import { cn } from "@/lib/utils";

/**
 * Le bouton VTLVS — remplace celui du kit Hermes (`@nous-research/ui`), même interface.
 *
 * Pourquoi (captures d'Azer, 29/09) : le bouton du kit portait `leading-0` et
 * `tracking-[0.2em]`. Hauteur de ligne nulle : dès qu'un libellé passe à la ligne sur un
 * téléphone, ses deux lignes s'impriment l'une sur l'autre — « Enregistrer et ouvrir le
 * canevas » devenait « Enregilset rceam eevta souvrir ». Et un espacement de 0,2 em sur
 * chaque bouton de l'application.
 *
 * Ici : hauteur de ligne lisible, pas de capitales ni d'espacement forcés, un libellé qui
 * passe proprement à la ligne, 44 px de cible tactile, et les jetons de couleur du thème
 * (`midground`, `background-base`, `destructive`) : les neuf chartes s'appliquent toujours.
 */

type Taille = "default" | "sm" | "icon" | "xs";

export interface ButtonProps extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "prefix"> {
  destructive?: boolean | null;
  ghost?: boolean | null;
  invert?: boolean | null;
  outlined?: boolean | null;
  size?: Taille | null;
  prefix?: React.ReactNode;
  suffix?: React.ReactNode;
}

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-md font-semibold leading-snug text-center " +
  "whitespace-normal break-words transition-colors select-none cursor-pointer " +
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-current " +
  "disabled:pointer-events-none disabled:opacity-50";

const TAILLES: Record<Taille, string> = {
  default: "min-h-11 px-4 py-2 text-sm",
  sm: "min-h-9 px-3 py-1.5 text-[0.8125rem]",
  icon: "size-10 p-0 shrink-0 [&>svg]:size-4",
  xs: "size-8 p-0 shrink-0 [&>svg]:size-3.5",
};

function apparence({ destructive, ghost, invert, outlined }: ButtonProps): string {
  if (destructive) {
    if (ghost) return "bg-transparent text-destructive hover:bg-destructive/10";
    if (outlined) return "border border-destructive/40 bg-transparent text-destructive hover:bg-destructive/10";
    return "bg-destructive text-destructive-foreground hover:bg-destructive/90";
  }
  if (ghost) return "bg-transparent text-current hover:bg-midground/10";
  if (outlined) return "border border-midground/35 bg-transparent text-midground hover:bg-midground/8";
  if (invert) return "bg-midground/12 text-midground hover:bg-midground/20";
  return "bg-midground text-background-base hover:opacity-90";
}

function Icone({ children }: { children: React.ReactNode }) {
  if (isValidElement<{ className?: string }>(children)) {
    return cloneElement(children, { className: cn("size-4 shrink-0", children.props.className) });
  }
  return <span className="inline-flex shrink-0">{children}</span>;
}

export const Button = ({
  children, className, destructive, ghost, invert, outlined, prefix, size, suffix, ...props
}: ButtonProps) => (
  <button
    className={cn(BASE, TAILLES[size ?? "default"], apparence({ destructive, ghost, invert, outlined }), className)}
    {...props}
  >
    {prefix != null && <Icone>{prefix}</Icone>}
    {children}
    {suffix != null && <Icone>{suffix}</Icone>}
  </button>
);
