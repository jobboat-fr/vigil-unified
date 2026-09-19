import { Component, type ErrorInfo, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@nous-research/ui/ui/components/button";
import { derniereReference, referenceCourte } from "@/lib/reference";

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
  reference,
  preserve = "Rien de ce que vous avez saisi n'a été envoyé — donc rien n'a été enregistré de travers.",
  onReessayer,
  compact = false,
}: {
  titre?: string;
  cause?: string;
  reference?: string;
  preserve?: string | null;
  onReessayer?: () => void;
  compact?: boolean;
}) {
  const ref = reference ?? derniereReference();
  const naviguer = useNavigate();
  return (
    <div className={compact ? "w-full" : "flex min-h-0 flex-1 items-center justify-center px-4 py-10"}>
      <div className="w-full max-w-lg rounded-2xl border border-current/15 p-6">
        <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-text-secondary">
          <span aria-hidden className="inline-block h-1.5 w-1.5 rounded-full bg-current opacity-60" />
          Incident
        </div>
        <h1 className="mt-3 text-lg font-semibold">{titre}</h1>
        {cause && <p className="mt-2 break-words text-sm text-text-secondary">{cause}</p>}
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
          <Button size="sm" ghost onClick={() => naviguer("/aide")}>
            Aide et support
          </Button>
        </div>

        {ref && (
          <div className="mt-5 border-t border-current/10 pt-4">
            <p className="text-xs text-text-secondary">
              Si vous écrivez au support, donnez cette référence — elle mène directement à la trace
              de votre requête, sans avoir à raconter l'heure et l'écran.
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
  { erreur: Error | null; reference?: string }
> {
  state: { erreur: Error | null; reference?: string } = { erreur: null };

  static getDerivedStateFromError(erreur: Error) {
    return { erreur, reference: derniereReference() };
  }

  componentDidCatch(erreur: Error, info: ErrorInfo) {
    // La console reste la source pour le développement ; en production, l'important est
    // que la personne ait une sortie, pas qu'on remonte une pile au serveur.
    console.error("[frontière] écran interrompu", erreur, info.componentStack);
  }

  componentDidUpdate(prev: { children: ReactNode; titre?: string; cle?: string }) {
    // Changer de page doit effacer l'erreur : sinon la frontière garde l'écran cassé
    // affiché sur toutes les pages suivantes.
    if (prev.cle !== this.props.cle && this.state.erreur) this.setState({ erreur: null });
  }

  render() {
    if (!this.state.erreur) return this.props.children;
    return (
      <EcranErreur
        titre={this.props.titre}
        cause={this.state.erreur.message}
        reference={this.state.reference}
        onReessayer={() => this.setState({ erreur: null })}
      />
    );
  }
}
