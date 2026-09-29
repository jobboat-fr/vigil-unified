import { useEffect, useState } from "react";

/**
 * « Une nouvelle version est en ligne » — pour l'onglet resté ouvert pendant un déploiement.
 *
 * Un onglet garde en mémoire les écrans qu'il a déjà chargés. Après un déploiement, il
 * continue donc d'afficher l'ancienne version sans que rien n'échoue : le 29/09, Azer voyait
 * encore la salle de réunion en anglais sur son téléphone, une heure après sa correction.
 *
 * Quand l'onglet revient au premier plan (et au plus toutes les dix minutes), on relit
 * l'adresse d'accueil sans cache et on compare l'empreinte du script principal à celle de la
 * page ouverte. Différente : un bandeau propose de mettre à jour. On ne recharge jamais de
 * force — la personne est peut-être en train d'écrire.
 */

const INTERVALLE_MS = 10 * 60_000;
const SCRIPT = /\/assets\/index-[\w-]+\.js/;

function empreinteCourante(): string | null {
  const s = document.querySelector<HTMLScriptElement>('script[type="module"][src*="/assets/index-"]');
  return s?.src.match(SCRIPT)?.[0] ?? null;
}

export function BandeauVersion() {
  const [nouvelle, setNouvelle] = useState(false);

  useEffect(() => {
    const courante = empreinteCourante();
    if (!courante) return; // développement : pas de build, rien à comparer
    let derniere = 0;
    const verifier = async () => {
      if (document.visibilityState !== "visible" || Date.now() - derniere < 30_000) return;
      derniere = Date.now();
      try {
        const html = await (await fetch("/", { cache: "no-store", credentials: "same-origin" })).text();
        const enLigne = html.match(SCRIPT)?.[0];
        if (enLigne && enLigne !== courante) setNouvelle(true);
      } catch {
        // Réseau coupé : le bandeau réseau le dit déjà.
      }
    };
    document.addEventListener("visibilitychange", verifier);
    const minuterie = setInterval(verifier, INTERVALLE_MS);
    return () => {
      document.removeEventListener("visibilitychange", verifier);
      clearInterval(minuterie);
    };
  }, []);

  if (!nouvelle) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed inset-x-0 bottom-0 z-[60] flex justify-center px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
    >
      <div className="flex max-w-[min(32rem,100%)] flex-wrap items-center justify-center gap-x-3 gap-y-2 rounded-2xl border border-border bg-background px-4 py-2.5 text-sm shadow-lg">
        <span>Une nouvelle version de VTLVS est en ligne.</span>
        <span className="flex gap-2">
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="rounded-md bg-foreground px-3 py-1.5 text-sm font-semibold text-background"
          >
            Mettre à jour
          </button>
          <button type="button" onClick={() => setNouvelle(false)} className="rounded-md px-2 py-1.5 text-sm text-text-secondary hover:text-foreground">
            Plus tard
          </button>
        </span>
      </div>
    </div>
  );
}
