import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";

/**
 * Le Noyau — ce que la plateforme tient, et pourquoi.
 *
 * Remplace la page Documentation, qui décrivait l'agent Hermes et pas ce produit. Réservée
 * à la direction et à l'éditeur : c'est une page de doctrine, pas un mode d'emploi.
 *
 * Elle existe pour une raison précise. Les règles ci-dessous sont tenues par la base de
 * données, pas par l'application — et quelqu'un qui ne le sait pas finit par les
 * réimplémenter dans le code, où elles divergent. Écrire une fois ce qui est déjà garanti
 * évite la deuxième copie.
 */

type Rule = { title: string; body: string; where: string };

const INVARIANTS: Rule[] = [
  {
    title: "Un organisme ne voit jamais les données d'un autre",
    body:
      "La lecture croisée renvoie zéro ligne ; l'écriture croisée lève cross_tenant_violation. "
      + "Ce n'est pas un filtre dans une requête : c'est un plancher restrictif que rien ne peut élargir.",
    where: "learn_tenant_table() — plancher RLS sur chacune des 46 tables",
  },
  {
    title: "Un émargement ne se modifie pas",
    body:
      "Ni correction, ni suppression, par personne — super administrateur compris. Une présence "
      + "modifiable après coup ne prouve rien, et c'est précisément ce qu'un audit vient vérifier.",
    where: "learn_append_only() — UPDATE et DELETE révoqués, pas seulement inutilisés",
  },
  {
    title: "Un assistant ne signe pas, n'émet pas, n'inscrit pas",
    body:
      "Il prépare et propose ; un humain nommé valide. La règle vaut pour l'émargement, pour "
      + "l'envoi d'un message au nom de l'organisme et pour la création d'un compte.",
    where: "learn_no_agent_writes() + AGENT_FORBIDDEN dans roles.py",
  },
  {
    title: "Une action d'amélioration nomme sa cause",
    body:
      "source_kind et source_id sont obligatoires. C'est l'indicateur 30 — la non-conformité la "
      + "plus fréquente au niveau national — et la seule preuve qu'un retour a produit quelque chose.",
    where: "learn_improvement_actions — colonnes NOT NULL",
  },
  {
    title: "Une pièce sous conservation ne se supprime pas",
    body:
      "L'obligation de conservation va de 3 à 10 ans selon le financement, et elle survit à "
      + "l'abonnement. Un client qui part emporte ses preuves, sinon c'est lui qui devient non conforme.",
    where: "learn_vault_guard() + learn_retention_until()",
  },
  {
    title: "Le niveau est établi avant l'inscription",
    body:
      "Le test de positionnement est passable sans compte, par un lien à usage unique. "
      + "L'indicateur 8 demande que le niveau soit connu avant d'inscrire, pas après.",
    where: "learn_grade_positioning() — correction en base, jamais côté client",
  },
];

const AXES = [
  {
    name: "Portée",
    body: "Quelles lignes le profil voit : la plateforme, l'organisme, ses sessions, son entreprise, ou lui-même.",
  },
  {
    name: "Hiérarchie",
    body: "Qui peut créer qui. Une liste blanche explicite, pas une comparaison de niveaux.",
  },
  {
    name: "Capacité",
    body: "Ce que le profil peut faire à une ressource. C'est le troisième axe, et c'est celui qu'on oublie.",
  },
];

export default function NoyauPage() {
  return (
    <div className="space-y-6 p-6">
      <header className="max-w-3xl">
        <h1 className="text-2xl font-semibold">Le Noyau</h1>
        <p className="mt-2 text-sm leading-relaxed opacity-80">
          Ce que la plateforme garantit, et où la garantie est tenue. Chaque règle ci-dessous
          est appliquée par la base de données. L&apos;interface les reflète ; elle ne les
          décide pas, et elle ne doit jamais en contenir une deuxième version.
        </p>
      </header>

      <section>
        <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-wider opacity-60">
          Les invariants
        </h2>
        <div className="grid gap-4 lg:grid-cols-2">
          {INVARIANTS.map((r) => (
            <Card key={r.title}>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">{r.title}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <p className="leading-relaxed opacity-80">{r.body}</p>
                <p className="text-xs opacity-60">
                  <span className="font-medium">Tenu par : </span>
                  {r.where}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-wider opacity-60">
          L&apos;autorisation a trois axes
        </h2>
        <Card>
          <CardContent className="space-y-4 p-5 text-sm">
            <p className="leading-relaxed opacity-80">
              Le niveau hiérarchique ne suffit pas, et s&apos;en contenter produit un vrai
              défaut : un auditeur (niveau 4) est au-dessus d&apos;un apprenant (niveau 5), donc
              une règle fondée sur le seul niveau laisserait un profil en lecture seule créer
              des comptes.
            </p>
            <ul className="divide-y divide-current/10">
              {AXES.map((a) => (
                <li key={a.name} className="py-2.5">
                  <span className="font-medium">{a.name}</span>
                  <span className="opacity-80"> — {a.body}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </section>

      <section>
        <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-wider opacity-60">
          Ce que la plateforme n&apos;est pas
        </h2>
        <Card>
          <CardContent className="space-y-2 p-5 text-sm leading-relaxed opacity-80">
            <p>
              Elle ne certifie pas à la place de l&apos;organisme : elle produit les preuves
              qu&apos;un audit demande, elle ne remplace pas l&apos;audit.
            </p>
            <p>
              Elle n&apos;envoie rien au nom de l&apos;organisme sans qu&apos;un humain nommé
              l&apos;ait validé — y compris lorsque c&apos;est l&apos;assistant qui a rédigé.
            </p>
            <p>
              Elle n&apos;invente aucun chiffre publiable : chaque taux est calculé et publié
              avec la population qui l&apos;a produit, parce que l&apos;indicateur 1 exige
              qu&apos;il soit vérifiable.
            </p>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
