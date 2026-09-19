import { useEffect, useState } from "react";

/**
 * « Connexion perdue » — et surtout, le moment où elle revient.
 *
 * Dans une salle de formation, le Wi-Fi tombe. Sans ce bandeau, l'application se contente
 * d'échouer en silence : les boutons ne répondent plus et personne ne sait pourquoi. Ici
 * on le dit, on rappelle que la saisie en cours reste à l'écran, et on confirme le retour
 * du réseau pendant trois secondes avant de disparaître — cette confirmation est ce qui
 * permet de reprendre sans recharger la page « au cas où ».
 *
 * `navigator.onLine` ne détecte pas un réseau présent mais inutile (portail captif) ; les
 * appels échoueront alors normalement, avec leur propre message et leur référence.
 */
export function BandeauReseau() {
  const [horsLigne, setHorsLigne] = useState(() => typeof navigator !== "undefined" && !navigator.onLine);
  const [retour, setRetour] = useState(false);

  useEffect(() => {
    const perdu = () => {
      setHorsLigne(true);
      setRetour(false);
    };
    const revenu = () => {
      setHorsLigne(false);
      setRetour(true);
    };
    window.addEventListener("offline", perdu);
    window.addEventListener("online", revenu);
    return () => {
      window.removeEventListener("offline", perdu);
      window.removeEventListener("online", revenu);
    };
  }, []);

  useEffect(() => {
    if (!retour) return;
    const t = setTimeout(() => setRetour(false), 3000);
    return () => clearTimeout(t);
  }, [retour]);

  if (!horsLigne && !retour) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 top-0 z-[60] flex justify-center px-3 pt-[max(0.5rem,env(safe-area-inset-top))]"
    >
      <div
        className="pointer-events-auto max-w-[min(32rem,100%)] rounded-full border px-4 py-1.5 text-center text-xs backdrop-blur"
        style={
          horsLigne
            ? { borderColor: "color-mix(in srgb, #f59e0b 55%, transparent)", background: "color-mix(in srgb, #f59e0b 12%, transparent)" }
            : { borderColor: "color-mix(in srgb, #22c55e 55%, transparent)", background: "color-mix(in srgb, #22c55e 12%, transparent)" }
        }
      >
        {horsLigne
          ? "Connexion perdue. Votre saisie reste à l'écran ; elle repartira dès le retour du réseau."
          : "Connexion rétablie."}
      </div>
    </div>
  );
}
