import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { vigilAiHealth, type AiHealth } from "@/lib/vigil";

/** Page métier → fonction IA qui la sert (winny_gateway/ai_guard.py). */
const FONCTION_DE_LA_PAGE: Record<string, string> = {
  "/meeting-room": "meeting",
  "/mail": "mail",
  "/ops-team": "ops",
  "/studio": "studio",
  "/vault": "vault",
};

/**
 * Bandeau « assistant indisponible ».
 *
 * Il ne s'affiche que sur une page qui utilise l'IA, et seulement quand la passerelle dit
 * que la fonction est coupée — interrupteur, fournisseur en panne ou sans clé. Le reste de
 * la page ne dépend d'aucun modèle : le bandeau le dit, pour que personne n'attende une
 * réponse qui ne viendra pas.
 */
export function AssistantIndisponible() {
  const { pathname } = useLocation();
  const fonction = FONCTION_DE_LA_PAGE[pathname.replace(/\/$/, "")];
  const [etat, setEtat] = useState<AiHealth | null>(null);

  useEffect(() => {
    if (!fonction) return;
    let alive = true;
    const lire = () =>
      vigilAiHealth()
        .then((h) => alive && setEtat(h))
        .catch(() => alive && setEtat(null));
    lire();
    const id = window.setInterval(lire, 60_000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [fonction]);

  if (!fonction || !etat || etat.features[fonction] !== false) return null;

  const fournisseur = etat.providers[etat.provider];
  const retour = fournisseur?.retry_in_s ? ` Nouvel essai dans ${fournisseur.retry_in_s} s.` : "";
  const motif = !etat.enabled
    ? "L'assistant est désactivé."
    : etat.disabled_features.includes(fonction)
      ? "L'assistant est désactivé pour cette page."
      : "L'assistant ne répond pas pour le moment." + retour;

  return (
    <div
      role="status"
      className="mt-14 lg:mt-0 flex items-center gap-2 border-b border-amber-500/40 bg-amber-500/10 px-4 py-1.5 text-xs text-amber-300"
    >
      <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />
      <span>
        Assistant indisponible — {motif} La page reste utilisable : consulter, créer et enregistrer fonctionnent
        normalement.
      </span>
    </div>
  );
}
