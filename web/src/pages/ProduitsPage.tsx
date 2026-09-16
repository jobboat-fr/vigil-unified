import { Link } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Button } from "@nous-research/ui/ui/components/button";
import { AGENTS, useAbonnementAgents } from "@/lib/agentique";

/**
 * Ce qu'AZZ&CO Labs propose aux organismes de formation.
 *
 * La plateforme d'un côté, les agents de l'autre. La page dit aussi ce qui n'est pas encore
 * ouvert : un catalogue qui promet ce qui n'existe pas se paie à la première démonstration.
 */

const MODULES = [
  {
    nom: "Parcours et sessions",
    texte: "Programmes, sessions, créneaux, inscriptions et places. La base de l'exploitation d'un organisme.",
    etat: "Disponible",
  },
  {
    nom: "Émargement et preuve",
    texte: "Feuilles signées, chaînage infalsifiable, absences justifiées : la preuve que la formation a bien eu lieu.",
    etat: "Disponible",
  },
  {
    nom: "Coffre documentaire",
    texte: "Conventions, contrats, factures, attestations, avec durée de conservation et traçabilité des accès.",
    etat: "Disponible",
  },
  {
    nom: "Qualité et conformité",
    texte: "Enquêtes, réclamations, actions correctives, dossier d'audit prêt à présenter — pensé pour Qualiopi.",
    etat: "Disponible",
  },
  {
    nom: "Tunnel d'inscription",
    texte: "Demandes venues du site, test de positionnement, conversion en inscription, sans ressaisie.",
    etat: "Disponible",
  },
  {
    nom: "Paiement en ligne",
    texte: "Règlement entreprise ou particulier, échéancier conforme au Code du travail, factures archivées.",
    etat: "Sur la vitrine",
  },
] as const;

export default function ProduitsPage() {
  const { abonne } = useAbonnementAgents();
  const total = AGENTS.reduce((n, a) => n + a.prix, 0);

  return (
    <div className="space-y-8 p-6">
      <header>
        <h1 className="text-2xl font-semibold">Nos produits</h1>
        <p className="mt-1 max-w-3xl text-sm text-text-secondary">
          VTLVS est la plateforme de formation éditée par AZZ&amp;CO Labs : elle tient l&apos;exploitation
          et la preuve. Les agents viennent par-dessus, chacun sur son métier, et travaillent sur vos
          données réelles sans jamais dépasser les droits de la personne qui les mandate.
        </p>
      </header>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">La plateforme</h2>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {MODULES.map((m) => (
            <Card key={m.nom}>
              <CardHeader className="pb-2">
                <CardTitle className="flex items-baseline justify-between gap-3 text-base">
                  <span>{m.nom}</span>
                  <span className="text-[10px] uppercase tracking-wide text-text-secondary">{m.etat}</span>
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-text-secondary">{m.texte}</CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="text-lg font-semibold">Les agents</h2>
          <p className="text-sm text-text-secondary">
            {abonne ? "Votre abonnement est actif." : `À partir de ${Math.min(...AGENTS.map((a) => a.prix))} € par mois — les trois pour ${Math.round(total * 0.8)} €.`}
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {AGENTS.map((a) => (
            <Card key={a.id} className="flex min-w-0 flex-col">
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center justify-between gap-3">
                  <img src={a.logo} alt={a.nom} style={{ height: 42, width: "auto", borderRadius: 6 }} />
                  <span className="text-right">
                    <span className="block text-base font-semibold" style={{ color: a.accent }}>{a.nom}</span>
                    <span className="block text-xs text-text-secondary">{a.accroche}</span>
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="flex flex-1 flex-col gap-3 text-sm">
                <p className="text-text-secondary">{a.mission}</p>
                <ul className="space-y-1">
                  {a.capacites.slice(0, 3).map((c) => (
                    <li key={c} className="flex gap-2">
                      <span style={{ color: a.accent }}>·</span>
                      <span>{c}</span>
                    </li>
                  ))}
                </ul>
                <p className="text-lg font-semibold">
                  {a.prix} €<span className="text-sm font-normal text-text-secondary"> / mois</span>
                </p>
                <div className="mt-auto">
                  {abonne ? (
                    <Button
                      className="w-full"
                      onClick={() => window.open(a.tableauDeBord, "_blank", "noopener,noreferrer")}
                    >
                      Ouvrir le tableau de bord
                    </Button>
                  ) : (
                    <Link to="/abonnement" className="block">
                      <Button ghost className="w-full">🔒 Voir l&apos;abonnement</Button>
                    </Link>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <p className="text-xs text-text-secondary">
        La plateforme est vendue à l&apos;organisme ; les agents s&apos;y ajoutent par abonnement mensuel.
        Les formations affichées aux apprenants appartiennent à l&apos;organisme, pas à AZZ&amp;CO Labs.
      </p>
    </div>
  );
}
