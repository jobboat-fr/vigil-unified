import { Component, type ErrorInfo, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { estEchecDeModule, rechargerPourNouvelleVersion } from "@/lib/nouvelleVersion";
import { derniereReference, nouvelleReference, referenceCourte } from "@/lib/reference";
import { signalerIncident } from "@/lib/compte";

/**
 * Ce qu'on montre quand ça casse.
 *
 * Trois choses, dans cet ordre, parce que c'est l'ordre des questions qu'une personne se
 * pose : qu'est-ce qui s'est passé, est-ce que j'ai perdu mon travail, qu'est-ce que je
 * fais maintenant. La référence vient en dernier — elle ne sert qu'au support, mais elle
 * lui sert vraiment : c'est la chaîne exacte à chercher dans les journaux.
 *
 * Pas d'excuse ampoulée, pas de « Oups ! », pas de visage triste. Une panne n'est pas une
 * blague, et une personne en plein émargement n'a pas envie qu'on lui fasse un clin d'œil.
 */
export function EcranErreur({
  titre = "Cet écran n'a pas pu s'afficher",
  cause,
  detail,
  reference,
  preserve = "Rien de ce que vous avez saisi n'a été envoyé — donc rien n'a été enregistré de travers.",
  onReessayer,
  compact = false,
}: {
  titre?: string;
  cause?: string;
  /** Le message technique brut (souvent en anglais) : replié, pour le support. */
  detail?: string;
  reference?: string;
  preserve?: string | null;
  onReessayer?: () => void;
  compact?: boolean;
}) {
  const ref = reference ?? derniereReference();
  const naviguer = useNavigate();
  // « Aide et support » emporte la référence et la page : la personne n'a rien à recopier.
  const versAide = () => {
    const q = new URLSearchParams({ page: window.location.pathname });
    if (ref) q.set("reference", ref);
    naviguer(`/aide?${q.toString()}#demande`);
  };
  return (
    <div className={compact ? "w-full" : "flex min-h-0 flex-1 items-center justify-center px-4 py-10"}>
      <div className="w-full max-w-lg rounded-2xl border border-current/15 p-6">
        <div className="flex items-center gap-2 text-xs uppercase tracking-[0.05em] text-text-secondary">
          <span aria-hidden className="inline-block h-1.5 w-1.5 rounded-full bg-current opacity-60" />
          Incident
        </div>
        <h1 className="mt-3 text-lg font-semibold">{titre}</h1>
        {cause && <p className="mt-2 break-words text-sm text-text-secondary">{cause}</p>}
        {detail && (
          <details className="mt-2 text-xs text-text-secondary">
            <summary className="cursor-pointer">Détail technique</summary>
            <p className="mt-1 break-words font-mono">{detail}</p>
          </details>
        )}
        {preserve && <p className="mt-3 text-sm">{preserve}</p>}

        <div className="mt-5 flex flex-wrap gap-2">
          {onReessayer && (
            <Button size="sm" onClick={onReessayer}>
              Réessayer
            </Button>
          )}
          <Button size="sm" outlined onClick={() => naviguer("/accueil")}>
            Retour à l'accueil
          </Button>
          <Button size="sm" ghost onClick={versAide}>
            Aide et support
          </Button>
        </div>

        {ref && (
          <div className="mt-5 border-t border-current/10 pt-4">
            <p className="text-xs text-text-secondary">
              Cette référence est jointe automatiquement si vous passez par « Aide et support ». Elle
              permet au support de retrouver l'incident dans nos journaux, sans vous demander l'heure ni l'écran.
            </p>
            <button
              type="button"
              className="mt-2 rounded-lg border border-current/15 px-3 py-1.5 font-mono text-xs tracking-wider transition hover:border-current/40"
              onClick={() => void navigator.clipboard?.writeText(ref).catch(() => undefined)}
              title="Copier la référence complète"
            >
              {referenceCourte(ref)}
              <span className="ml-2 opacity-50">copier</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * La frontière : une erreur de rendu s'arrête ici au lieu de vider la page.
 *
 * Avant, une seule exception dans un composant laissait un écran blanc — pas de menu, pas
 * de message, rien à cliquer. React démonte tout l'arbre quand personne n'attrape. On en
 * pose deux : une autour de l'application (le dernier filet) et une autour de la zone de
 * page, pour qu'un écran cassé laisse la navigation debout.
 */
export class FrontiereErreur extends Component<
  { children: ReactNode; titre?: string; cle?: string },
  { erreur: Error | null; reference?: string; recharge?: boolean }
> {
  state: { erreur: Error | null; reference?: string; recharge?: boolean } = { erreur: null };

  static getDerivedStateFromError(erreur: Error) {
    // Une référence PROPRE à l'incident : celle du dernier appel réussi ne menait à rien
    // (capture d'Azer, 29/09 — « 3c824844 » ne correspondait à aucune erreur au journal).
    return { erreur, reference: nouvelleReference() };
  }

  componentDidCatch(erreur: Error, info: ErrorInfo) {
    // Un onglet plus vieux que le déploiement : on prend la version en ligne, sans écran
    // d'incident — ce n'en est pas un (voir lib/nouvelleVersion).
    if (estEchecDeModule(erreur)) {
      if (rechargerPourNouvelleVersion()) {
        this.setState({ recharge: true });
        return;
      }
      if (this.state.reference) {
        signalerIncident({ reference: this.state.reference, nature: "module", page: window.location.pathname, message: erreur.message });
      }
      return;
    }
    // La console reste la source pour le développement ; en production, l'important est
    // que la personne ait une sortie, pas qu'on remonte une pile au serveur.
    console.error("[frontière] écran interrompu", erreur, info.componentStack);
    if (this.state.reference) {
      signalerIncident({ reference: this.state.reference, nature: "rendu", page: window.location.pathname, message: erreur.message });
    }
  }

  componentDidUpdate(prev: { children: ReactNode; titre?: string; cle?: string }) {
    // Changer de page doit effacer l'erreur : sinon la frontière garde l'écran cassé
    // affiché sur toutes les pages suivantes.
    if (prev.cle !== this.props.cle && this.state.erreur) this.setState({ erreur: null });
  }

  render() {
    if (!this.state.erreur) return this.props.children;
    if (this.state.recharge) {
      return (
        <div role="status" className="flex min-h-0 flex-1 items-center justify-center px-4 py-10 text-sm text-text-secondary">
          Une nouvelle version est en ligne — chargement…
        </div>
      );
    }
    if (estEchecDeModule(this.state.erreur)) {
      // Le rechargement a déjà été tenté : le fichier manque vraiment, ou le réseau est coupé.
      return (
        <EcranErreur
          titre="Cet écran n'a pas pu se charger"
          cause="La page n'a pas pu être téléchargée : la connexion est peut-être coupée, ou une mise à jour est en cours."
          detail={this.state.erreur.message}
          reference={this.state.reference}
          onReessayer={() => window.location.reload()}
        />
      );
    }
    return (
      <EcranErreur
        titre={this.props.titre}
        cause="Une erreur inattendue a interrompu cet écran. Elle nous a été signalée."
        detail={this.state.erreur.message}
        reference={this.state.reference}
        onReessayer={() => this.setState({ erreur: null })}
      />
    );
  }
}
