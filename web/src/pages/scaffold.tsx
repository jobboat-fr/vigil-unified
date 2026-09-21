import type { ReactNode } from "react";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Refus } from "@/components/Refus";
import type { WwState } from "@/lib/useWw";

/**
 * L'attente, le besoin de session et l'échec, rendus pareil partout.
 *
 * Le contenu déjà chargé reste à l'écran quand un rafraîchissement échoue : perdre une
 * liste qu'on était en train de lire parce qu'un appel de fond a raté est une punition
 * sans raison.
 *
 * L'échec passe désormais par `Refus`, qui traduit le statut en phrase. Ce bloc affichait
 * `state.error.message` — or ce message *est* le code technique, `LearnError` étant
 * construite avec `code ?? "HTTP 404"`. La personne lisait donc `organisme_hors_perimetre`.
 */
export function WwGate({
  state,
  quoi,
  onReessayer,
  children,
}: {
  state: WwState<unknown>;
  /** Ce que l'écran tentait d'obtenir, au groupe nominal : « la liste des sessions ». */
  quoi?: string;
  onReessayer?: () => void;
  children: ReactNode;
}) {
  if (state.data == null && state.loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner />
      </div>
    );
  }

  if (state.data == null && state.needsAuth) {
    return <Refus erreur={{ status: 401 }} quoi={quoi} />;
  }

  if (state.data == null && state.error) {
    return <Refus erreur={state.error} quoi={quoi} onReessayer={onReessayer} />;
  }

  return <>{children}</>;
}

/** Une carte sobre pour un contenu vide qui n'est pas une erreur. */
export function CarteVide({ children }: { children: ReactNode }) {
  return (
    <Card>
      <CardContent className="py-10 text-center text-sm text-text-secondary">
        {children}
      </CardContent>
    </Card>
  );
}
