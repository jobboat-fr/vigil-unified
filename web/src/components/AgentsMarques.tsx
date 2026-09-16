import { Link } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Button } from "@nous-research/ui/ui/components/button";
import { AGENTS, agentsPourRole, useAbonnementAgents, type Agent, type RoleLearn } from "@/lib/agentique";

/**
 * Les trois agents d'AZZ&CO Labs, présentés par leur marque.
 *
 * Tant que l'abonnement n'est pas ouvert, les cartes sont verrouillées : on montre ce que
 * l'agent sait faire et ce qu'il ne fera pas, mais l'accès au tableau de bord attend.
 * Montrer la limite sur la carte est délibéré — un agent dont on connaît les bornes inspire
 * plus confiance qu'un agent qui promet tout.
 */

function CarteAgent({ agent, abonne }: { agent: Agent; abonne: boolean }) {
  return (
    <Card className="flex min-w-0 flex-col" style={{ borderColor: abonne ? agent.accent : undefined }}>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between gap-3">
          <img
            src={agent.logo}
            alt={agent.nom}
            style={{ height: 46, width: "auto", borderRadius: 6 }}
          />
          <span className="text-right">
            <span className="block text-base font-semibold" style={{ color: agent.accent }}>{agent.nom}</span>
            <span className="block text-xs text-text-secondary">{agent.accroche}</span>
          </span>
        </CardTitle>
      </CardHeader>

      <CardContent className="flex min-w-0 flex-1 flex-col gap-3 text-sm">
        <p className="text-text-secondary">{agent.mission}</p>

        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-text-secondary">Ce qu&apos;il fait</p>
          <ul className="mt-1 space-y-1">
            {agent.capacites.map((c) => (
              <li key={c} className="flex gap-2">
                <span style={{ color: agent.accent }}>·</span>
                <span>{c}</span>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-text-secondary">Ce qu&apos;il ne fait pas</p>
          <ul className="mt-1 space-y-1 opacity-75">
            {agent.limites.map((l) => (
              <li key={l} className="flex gap-2">
                <span>—</span>
                <span>{l}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="mt-auto space-y-2 pt-2">
          {abonne ? (
            <>
              <Button
                className="w-full"
                onClick={() => window.open(agent.tableauDeBord, "_blank", "noopener,noreferrer")}
              >
                Ouvrir le tableau de bord
              </Button>
              <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-text-secondary">
                {agent.pages.map((p) => (
                  <Link key={p.chemin} to={p.chemin} className="underline">
                    {p.libelle}
                  </Link>
                ))}
              </p>
            </>
          ) : (
            <>
              <div
                className="rounded-md px-3 py-2 text-xs"
                style={{ background: "var(--color-background-secondary, rgba(127,127,127,0.06))" }}
              >
                🔒 Accès verrouillé — {agent.prix} € par mois, par organisme.
              </div>
              <Link to="/abonnement" className="block">
                <Button ghost className="w-full">Voir l&apos;abonnement</Button>
              </Link>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export default function AgentsMarques({ role }: { role: RoleLearn | null }) {
  const { abonne } = useAbonnementAgents();
  // Sans rôle résolu, on montre les trois : la page est déjà réservée à l'exploitation.
  const agents = role ? agentsPourRole(role) : AGENTS;
  if (agents.length === 0) return null;

  return (
    <section className="space-y-3">
      <header>
        <h2 className="text-lg font-semibold">Nos agents</h2>
        <p className="text-sm text-text-secondary">
          Trois agents édités par AZZ&amp;CO Labs, chacun sur son propre runtime isolé. Chaque action
          conséquente passe par le protocole AZZING et reste journalisée.
        </p>
      </header>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {agents.map((a) => (
          <CarteAgent key={a.id} agent={a} abonne={abonne} />
        ))}
      </div>
    </section>
  );
}
