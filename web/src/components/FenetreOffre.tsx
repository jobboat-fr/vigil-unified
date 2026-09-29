import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { OffreEntree } from "@/components/OffreEntree";
import { EVENEMENT_OFFRE, type Explication } from "@/lib/refus";

/**
 * La fenêtre d'offre : le même parcours qu'un bloc <Refus>, pour les écrans qui n'affichent
 * qu'une ligne d'erreur (voir `annoncerOffre` dans lib/refus).
 *
 * D'abord l'explication, aimable ; « D'accord » ; puis l'offre d'entrée et « Voir tout ce que
 * nous proposons » (Azer, 29/09). Échap ou « Fermer » la referment ; la ligne d'erreur de
 * l'écran reste, elle, à sa place.
 */
export function FenetreOffre() {
  const [x, setX] = useState<Explication | null>(null);
  const [offreVue, setOffreVue] = useState(false);
  const titre = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const ouvrir = (ev: Event) => {
      setX((ev as CustomEvent<Explication>).detail);
      setOffreVue(false);
    };
    window.addEventListener(EVENEMENT_OFFRE, ouvrir);
    return () => window.removeEventListener(EVENEMENT_OFFRE, ouvrir);
  }, []);

  useEffect(() => {
    if (!x) return;
    titre.current?.focus();
    const echap = (e: KeyboardEvent) => { if (e.key === "Escape") setX(null); };
    window.addEventListener("keydown", echap);
    return () => window.removeEventListener("keydown", echap);
  }, [x]);

  if (!x?.offre) return null;

  return (
    <div className="fixed inset-0 z-[70] flex items-end justify-center bg-black/40 p-3 sm:items-center" onClick={() => setX(null)}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="fenetre-offre-titre"
        className="max-h-[90dvh] w-full max-w-md overflow-y-auto rounded-2xl border border-border bg-background p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[11px] uppercase tracking-[0.05em] text-text-secondary">Disponibilité</p>
            <h2 id="fenetre-offre-titre" ref={titre} tabIndex={-1} className="mt-1 text-base font-semibold outline-none">{x.titre}</h2>
          </div>
          <Button ghost size="icon" aria-label="Fermer" onClick={() => setX(null)}><X className="h-5 w-5" /></Button>
        </div>
        {x.detail && <p className="mt-2 text-sm leading-relaxed text-text-secondary">{x.detail}</p>}
        {offreVue ? (
          <OffreEntree offre={x.offre} />
        ) : (
          <div className="mt-4 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => setOffreVue(true)}>D'accord</Button>
          </div>
        )}
      </div>
    </div>
  );
}
