import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, Minus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AGENTS, PRIX_PACK_AGENTS } from "@/lib/agentique";
import { useLearnRole } from "@/lib/supabase";
import { vigil } from "@/lib/vigil";

/**
 * « Voir tout ce que nous proposons » — ouverte à tous les rôles.
 *
 * C'est là que mène l'offre d'entrée montrée après un refus (Azer, 29/09). Deux formules
 * côte à côte, les agents et le pack aux prix fixés par Azer, et les formations HBS.
 *
 * Ce que la page ne montre PAS : les termes de l'accord entre AZZ&CO LABS et HBS FORMATION.
 * Ils sont confidentiels (Accord, Art. 16) ; un compte HBS lit seulement que l'accès complet
 * est compris pour son organisme. Les plafonds de l'offre gratuite viennent de la passerelle
 * (`droits_agents.PLAFONDS_GRATUITS`) : une seule source, pas de copie ici.
 */

type Formule = "super_admin" | "contrat_hbs" | "payant" | "gratuit" | null;

const FORMATIONS_HBS = "https://hbs-formation.fr/formations";

function Case({ oui, texte }: { oui: boolean; texte?: string }) {
  return (
    <span className="flex items-center gap-1.5">
      {oui ? <Check className="h-4 w-4 shrink-0 text-success" aria-label="Compris" /> : <Minus className="h-4 w-4 shrink-0 text-text-secondary" aria-label="Non compris" />}
      {texte && <span>{texte}</span>}
    </span>
  );
}

export default function OffresPage() {
  const naviguer = useNavigate();
  const { role } = useLearnRole();
  const administration = role === "admin" || role === "super_admin";
  const [formule, setFormule] = useState<Formule>(null);
  const [plafonds, setPlafonds] = useState<Record<string, number> | null>(null);
  const moinsCher = Math.min(...AGENTS.map((a) => a.prix));
  const total = AGENTS.reduce((n, a) => n + a.prix, 0);

  useEffect(() => {
    vigil.agents.abonnements()
      .then((d) => { setFormule(d.formule ?? null); setPlafonds(d.plafonds_gratuits ?? null); })
      .catch(() => undefined); // la page reste lisible sans : seule la mention « votre formule » manque
  }, []);

  const lignes: { quoi: string; gratuit: React.ReactNode; payant: React.ReactNode }[] = [
    { quoi: "Sessions de formation en cours ou à venir", gratuit: <Case oui texte={plafonds?.sessions != null ? `${plafonds.sessions} au plus` : "limitées"} />, payant: <Case oui texte="sans limite" /> },
    { quoi: "Comptes (formateurs, apprenants, entreprises)", gratuit: <Case oui texte={plafonds?.comptes != null ? `${plafonds.comptes} au plus` : "limités"} />, payant: <Case oui texte="sans limite" /> },
    { quoi: "Planning, émargement, documents", gratuit: <Case oui />, payant: <Case oui /> },
    { quoi: "Salle de réunion vidéo", gratuit: <Case oui />, payant: <Case oui /> },
    { quoi: "Projets du Studio", gratuit: <Case oui texte={plafonds?.projets != null ? `${plafonds.projets} au plus` : "limités"} />, payant: <Case oui texte="sans limite" /> },
    { quoi: "Documents du Studio", gratuit: <Case oui texte={plafonds?.artefacts != null ? `${plafonds.artefacts} au plus` : "limités"} />, payant: <Case oui texte="sans limite" /> },
    { quoi: "Agents AZZMIN, AZZCO, AZZCOM et l'assistant", gratuit: <Case oui={false} />, payant: <Case oui texte="ceux que vous souscrivez" /> },
  ];

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 p-4 pb-12 md:p-6">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold">Nos offres</h1>
        <p className="max-w-prose text-sm text-text-secondary">
          Ce que demain vous demande, bâtissons-le ensemble, aujourd'hui : la plateforme pour piloter vos formations,
          et des agents qui travaillent avec vous, chacun dans son métier.
        </p>
        {formule === "contrat_hbs" && (
          <p className="rounded-lg border border-border p-3 text-sm">L'accès complet — plateforme et agents — est compris pour votre organisme.</p>
        )}
        {formule === "payant" && <p className="text-sm">Votre organisme dispose d'une formule payante.</p>}
        {formule === "gratuit" && <p className="text-sm">Votre organisme utilise l'offre gratuite.</p>}
      </header>

      {/* Tablette et plus : un tableau, les deux formules côte à côte. Téléphone : deux cartes
          l'une sous l'autre — un tableau qui défile cachait justement la colonne « payante ». */}
      <section aria-labelledby="comparer" className="flex flex-col gap-3">
        <h2 id="comparer" className="text-lg font-semibold">Comparer</h2>
        <div className="grid gap-3 sm:hidden">
          {([
            ["Gratuite", "0 €", "gratuit"],
            ["Formule payante", `dès ${moinsCher} € HT / mois`, "payant"],
          ] as const).map(([nom, prix, cle]) => (
            <div key={cle} className="rounded-xl border border-border p-4">
              <p className="font-semibold">{nom}</p>
              <p className="text-xs text-text-secondary">{prix}</p>
              <ul className="mt-3 flex flex-col gap-2 text-sm">
                {lignes.map((l) => (
                  <li key={l.quoi} className="flex flex-col gap-0.5">
                    <span className="text-text-secondary">{l.quoi}</span>
                    {l[cle]}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="hidden overflow-x-auto rounded-xl border border-border sm:block">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th scope="col" className="p-3 font-medium text-text-secondary">Ce qui est compris</th>
                <th scope="col" className="p-3">
                  <span className="block font-semibold">Gratuite</span>
                  <span className="block text-xs font-normal text-text-secondary">0 €</span>
                </th>
                <th scope="col" className="p-3">
                  <span className="block font-semibold">Formule payante</span>
                  <span className="block text-xs font-normal text-text-secondary">dès {moinsCher} € HT / mois</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {lignes.map((l) => (
                <tr key={l.quoi} className="border-b border-border last:border-0">
                  <th scope="row" className="p-3 font-normal">{l.quoi}</th>
                  <td className="p-3">{l.gratuit}</td>
                  <td className="p-3">{l.payant}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-text-secondary">Toute formule payante ouvre la plateforme entière. Les agents se souscrivent un par un, ou ensemble.</p>
      </section>

      <section aria-labelledby="agents" className="flex flex-col gap-3">
        <h2 id="agents" className="text-lg font-semibold">Les agents</h2>
        <ul className="grid gap-3 md:grid-cols-3">
          {AGENTS.map((a) => (
            <li key={a.id} className="flex min-w-0 flex-col gap-2 rounded-xl border border-border p-4">
              <span className="text-base font-semibold" style={{ color: a.accent }}>{a.nom}</span>
              <span className="text-sm text-text-secondary">{a.accroche}</span>
              <span className="mt-auto pt-2 text-xl font-semibold">{a.prix} € <span className="text-sm font-normal text-text-secondary">HT / mois</span></span>
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border p-4">
          <span className="text-sm"><span className="font-semibold">Les trois ensemble</span> — vente, coordination et administration sur les mêmes dossiers.</span>
          <span className="text-xl font-semibold">{PRIX_PACK_AGENTS} € <span className="text-sm font-normal text-text-secondary">HT / mois, au lieu de {total} €</span></span>
        </div>
      </section>

      <section aria-labelledby="formations" className="flex flex-col gap-2 rounded-xl border border-border p-4">
        <h2 id="formations" className="text-lg font-semibold">Les formations HBS FORMATION</h2>
        <p className="text-sm text-text-secondary">En présentiel, à Rouen. Suivre une formation HBS FORMATION ouvre aussi l'accès à la plateforme.</p>
        <a href={FORMATIONS_HBS} target="_blank" rel="noreferrer" className="self-start text-sm font-medium underline">Voir les formations ↗</a>
      </section>

      <footer className="flex flex-wrap items-center gap-3">
        {administration ? (
          <Button onClick={() => naviguer("/abonnement")}>Voir l'abonnement de l'organisme</Button>
        ) : (
          <p className="text-sm text-text-secondary">L'abonnement se souscrit par l'administration de votre organisme.</p>
        )}
        <Button outlined onClick={() => naviguer("/aide#demande")}>Poser une question</Button>
      </footer>
    </div>
  );
}
