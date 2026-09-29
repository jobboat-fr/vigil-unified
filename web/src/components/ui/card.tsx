import { cn } from "@/lib/utils";

/**
 * La carte VTLVS — remplace celle du kit Hermes, même interface.
 *
 * Le titre du kit était en police « étendue », gras, capitales et espacé de 0,08 em
 * (« DOCUMENT VAULT · 0 »). Ici : la police d'affichage du thème, en casse normale, lisible.
 * Les variables `--component-card-*` restent honorées : un thème peut toujours habiller
 * toutes les cartes.
 */

const STYLE: React.CSSProperties = {
  background: "var(--component-card-background)",
  borderImage: "var(--component-card-border-image)",
  boxShadow: "var(--component-card-box-shadow)",
  clipPath: "var(--component-card-clip-path)",
};

export function Card({ className, style, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("w-full min-w-0 rounded-xl border border-midground/15 bg-background-base/80 text-midground", className)}
      style={{ ...STYLE, ...style }}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col gap-1 border-b border-midground/10 p-4", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3
      className={cn("text-base font-semibold leading-snug [font-family:var(--theme-font-display)] break-words", className)}
      {...props}
    />
  );
}

export function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm leading-relaxed text-text-secondary", className)} {...props} />;
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-4", className)} {...props} />;
}
