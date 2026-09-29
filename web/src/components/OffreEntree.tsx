import { useNavigate } from "react-router-dom";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AGENTS } from "@/lib/agentique";
import type { Explication } from "@/lib/refus";

/**
 * L'offre d'entrée, montrée après qu'une personne a lu un refus et répondu « D'accord ».
 *
 * La règle (Azer, 29/09) : un refus d'offre s'explique d'abord, aimablement ; puis on montre
 * la plus petite formule qui aurait ouvert ce qui vient d'être refusé, et un lien vers tout
 * le reste. Aucun prix n'est inventé ici : ce sont ceux fixés par Azer (`lib/agentique.ts`).
 *
 *  - un agent refusé → l'abonnement à CET agent ;
 *  - un plafond de l'offre gratuite → la formule la moins chère (toute formule payante lève
 *    les plafonds), soit l'agent au plus petit prix.
 *
 * Seule l'administration de l'organisme souscrit. Aux autres, on montre l'offre et à qui
 * s'adresser — jamais un bouton qui mènerait à « accès réservé ».
 */
export function OffreEntree({ offre }: { offre: NonNullable<Explication["offre"]> }) {
  const naviguer = useNavigate();
  const moinsCher = [...AGENTS].sort((a, b) => a.prix - b.prix)[0];
  const agent = AGENTS.find((a) => a.id === offre.agent) ?? moinsCher;

  return (
    <div className="mt-4 rounded-lg border border-border p-4">
      <p className="text-[11px] uppercase tracking-[0.05em] text-text-secondary">Notre offre d'entrée</p>
      <p className="mt-1 text-base font-semibold">
        {agent.nom} — {agent.prix} € HT <span className="text-sm font-normal text-text-secondary">/ mois</span>
      </p>
      <ul className="mt-3 flex flex-col gap-1.5 text-sm">
        <li className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />Toute la plateforme VTLVS, sans plafond</li>
        <li className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />{agent.nom} : {agent.accroche.charAt(0).toLowerCase()}{agent.accroche.slice(1)}</li>
        <li className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />Ou une formation HBS FORMATION, qui ouvre aussi l'accès</li>
      </ul>
      {!offre.peutSouscrire && (
        <p className="mt-3 text-xs text-text-secondary">L'abonnement se souscrit par l'administration de votre organisme : transmettez-lui cette offre.</p>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        {offre.peutSouscrire && <Button size="sm" onClick={() => naviguer("/abonnement")}>Voir l'abonnement</Button>}
        <Button size="sm" outlined onClick={() => naviguer("/offres")}>Voir tout ce que nous proposons</Button>
      </div>
    </div>
  );
}
