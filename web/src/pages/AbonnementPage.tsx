import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Button } from "@nous-research/ui/ui/components/button";
import { AGENTS, useAbonnementAgents } from "@/lib/agentique";

/**
 * L'abonnement aux agents.
 *
 * Le paiement n'est pas encore ouvert : on annonce les formules et on le dit franchement,
 * plutôt que d'afficher un bouton qui échouerait. L'état vient de `useAbonnementAgents`,
 * seul endroit qui décide de ce qui est ouvert.
 */
export default function AbonnementPage() {
  const { abonne, enPreparation } = useAbonnementAgents();
  const total = AGENTS.reduce((n, a) => n + a.prix, 0);
  const pack = Math.round(total * 0.8);

  return (
    <div className="space-y-6 p-6">
      <header>
        <h1 className="text-2xl font-semibold">Abonnement aux agents</h1>
        <p className="mt-1 text-sm text-text-secondary">
          Chaque agent travaille sur son propre runtime, avec ses compétences, sa mémoire et ses
          droits. L&apos;abonnement est mensuel, par organisme, sans engagement de durée.
        </p>
      </header>

      {enPreparation && (
        <Card>
          <CardContent className="py-4 text-sm">
            <b>Bientôt disponible.</b> Le paiement en ligne n&apos;est pas encore ouvert : les
            agents restent verrouillés pour tout le monde. Écrivez-nous pour être prévenu de
            l&apos;ouverture, ou pour un essai encadré.
          </CardContent>
        </Card>
      )}

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
              <p className="text-2xl font-semibold">
                {a.prix} €<span className="text-sm font-normal text-text-secondary"> / mois</span>
              </p>
              <Button className="mt-auto w-full" disabled>
                {abonne ? "Abonnement actif" : "Bientôt"}
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Les trois ensemble</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center justify-between gap-4 text-sm">
          <p className="text-text-secondary">
            Vente, coordination et administration, sur les mêmes dossiers. Les trois agents partagent
            le même cadre de travail, et chacun reste dans son périmètre.
          </p>
          <p className="whitespace-nowrap text-2xl font-semibold">
            {pack} €<span className="text-sm font-normal text-text-secondary"> / mois — au lieu de {total} €</span>
          </p>
          <Button disabled>Bientôt</Button>
        </CardContent>
      </Card>

      <p className="text-xs text-text-secondary">
        Prix hors taxes, par organisme. L&apos;abonnement ouvre l&apos;accès aux tableaux de bord des
        agents et à leurs actions dans l&apos;application ; il ne modifie ni vos droits, ni vos données.
      </p>
    </div>
  );
}
