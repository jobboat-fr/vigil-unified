import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Le titre d'un écran, sa phrase d'explication, et ses actions.
 *
 * Le patron qu'on remplace était partout le même : un `flex justify-between` entre un bloc
 * de texte et un bouton. Tant que la fenêtre est large, il tient. En dessous, le texte
 * garde sa place et c'est le bouton qui cède — « Tout suspendre » se casse en deux lignes,
 * ou déborde de sa bordure. Le défaut n'est pas dans le libellé : c'est le rapport de
 * force entre deux éléments d'une même rangée qui est mal posé.
 *
 * Ici, les actions ne rétrécissent pas (`shrink-0`) et ne coupent pas leur libellé
 * (`whitespace-nowrap`) ; c'est la rangée qui passe à la ligne quand il n'y a plus la
 * place. Un bouton d'action garde donc toujours sa taille lisible, à n'importe quelle
 * largeur — et sur téléphone il s'étale sur toute la largeur plutôt que de se recroqueviller
 * dans un coin, ce qui en fait aussi une cible tactile correcte.
 *
 * La hiérarchie ne change jamais : le titre reste en premier dans l'ordre du document,
 * donc dans l'ordre de lecture d'un lecteur d'écran, même quand les actions passent
 * visuellement dessous.
 */
export function EnTetePage({
  titre,
  description,
  actions,
  className,
}: {
  titre: ReactNode;
  description?: ReactNode;
  /** Les boutons de l'écran. Au-delà de deux, envisager un menu plutôt qu'une rangée. */
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "flex flex-wrap items-start justify-between gap-x-4 gap-y-3",
        className,
      )}
    >
      <div className="flex min-w-0 flex-col gap-1">
        <h1 className="text-xl font-bold tracking-tight">{titre}</h1>
        {description && (
          <p className="max-w-prose text-sm leading-relaxed text-text-secondary">
            {description}
          </p>
        )}
      </div>

      {actions && (
        <div
          className={cn(
            // `w-full` sous le seuil : quand la rangée a déjà passé la ligne, autant que
            // les actions occupent la largeur plutôt que de flotter à droite du vide.
            "flex w-full shrink-0 flex-wrap items-center gap-2 sm:w-auto",
            "[&_button]:whitespace-nowrap [&_a]:whitespace-nowrap",
            "[&>button]:max-sm:flex-1",
          )}
        >
          {actions}
        </div>
      )}
    </header>
  );
}
