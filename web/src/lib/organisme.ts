// L'organisme de la personne connectée, disponible partout sans second appel.
//
// `/accueil` renvoie déjà le nom, le logo et la couleur de l'organisme ; App les dépose
// ici et n'importe quel composant les relit. Ça sert à deux détails qui comptent plus
// qu'ils n'en ont l'air : l'onglet du navigateur porte le nom de l'organisme (une
// formatrice qui a huit onglets ouverts retrouve le sien), et la favicon devient son
// logo. L'application appartient visuellement à l'organisme, pas à son éditeur.

import { useSyncExternalStore } from "react";

export interface Organisme {
  name: string;
  logo_url: string | null;
  primary_colour: string | null;
}

let courant: Organisme | null = null;
const abonnes = new Set<() => void>();

export function poserOrganisme(o: Organisme | null): void {
  if (courant?.name === o?.name && courant?.logo_url === o?.logo_url) return;
  courant = o;
  for (const f of abonnes) f();
}

function abonner(f: () => void): () => void {
  abonnes.add(f);
  return () => abonnes.delete(f);
}

export function useOrganisme(): Organisme | null {
  return useSyncExternalStore(abonner, () => courant, () => null);
}

/** Remplace la favicon par le logo de l'organisme (et la remet si l'on repart). */
export function poserFavicon(url: string | null): void {
  const defaut = "/favicon.ico";
  let lien = document.head.querySelector<HTMLLinkElement>('link[rel~="icon"][data-organisme]');
  if (!lien) {
    lien = document.createElement("link");
    lien.rel = "icon";
    lien.dataset.organisme = "1";
    document.head.appendChild(lien);
  }
  lien.href = url || defaut;
}
