import { useCallback, useEffect, useState } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { useLearnRole } from "@/lib/supabase";
import LearnDashboardApprenant from "@/pages/LearnDashboardApprenant";
import LearnDashboardFormateur from "@/pages/LearnDashboardFormateur";
import {
  getDashboard,
  getAuditOverview,
  getReadiness,
  LearnError,
  type Dashboard,
} from "@/lib/learn";

/**
 * The organisme at a glance.
 *
 * Deliberately a worklist rather than vanity totals: every tile is something someone has
 * to act on. "412 apprenants formés" tells you nothing on a Monday morning; "3 copies à
 * corriger, 1 programme à réviser" tells you where to start.
 *
 * Nothing here filters by role. The same request from a formateur returns their own
 * numbers because row-level security narrowed them — a `role === "admin"` branch in this
 * file would be a second copy of a rule the database already owns.
 *
 * L'apprenant fait exception, et c'est la seule. Il ne lui manquait pas des lignes : ces
 * tuiles ne posent pas ses questions. Réclamations au titre de l'indicateur 31, dossiers
 * d'audit incomplets, « à régler avant d'accueillir un second organisme » — il lisait le
 * tableau de bord de l'organisme, exact et entièrement hors sujet pour lui. La règle
 * ci-dessus porte sur le périmètre des données, que RLS continue de tenir ; celle-ci porte
 * sur les questions posées, que RLS ne peut pas deviner. Voir `LearnDashboardApprenant`.
 */

type Tile = { label: string; value: number; hint: string; urgent?: boolean };

function tilesFrom(d: Dashboard): Tile[] {
  const n = (v: number | undefined) => v ?? 0;
  return [
    { label: "Sessions actives", value: n(d.sessions_actives), hint: "planifiées ou en cours" },
    { label: "Créneaux cette semaine", value: n(d.creneaux_semaine), hint: "demi-journées à venir" },
    { label: "Apprenants inscrits", value: n(d.inscrits), hint: "toutes sessions" },
    {
      label: "Réclamations ouvertes",
      value: n(d.reclamations_ouvertes),
      hint: "indicateur 31",
      urgent: n(d.reclamations_ouvertes) > 0,
    },
    {
      label: "Actions d'amélioration",
      value: n(d.actions_ouvertes),
      hint: "en cours — indicateur 32",
    },
    {
      label: "Copies à corriger",
      value: n(d.copies_a_corriger),
      hint: "réponses libres en attente",
      urgent: n(d.copies_a_corriger) > 0,
    },
    {
      label: "Apprenants à risque",
      value: n(d.apprenants_a_risque),
      hint: "suivi distanciel — indicateur 19",
      urgent: n(d.apprenants_a_risque) > 0,
    },
    {
      label: "Programmes à réviser",
      value: n(d.programmes_a_reviser),
      hint: "1ʳᵉ cause de suspension en audit",
      urgent: n(d.programmes_a_reviser) > 0,
    },
  ];
}

export default function LearnDashboardPage() {
  const { role, resolu } = useLearnRole();
  const [data, setData] = useState<Dashboard | null>(null);
  const [audit, setAudit] = useState<{ code: string; readiness: string; missing: string[] }[]>([]);
  const [blocking, setBlocking] = useState<{ requirement: string; detail: string | null }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  // `/platform/readiness` est réservé à qui pilote ou contrôle l'organisme : LEARN
  // refuse un formateur ou une entreprise en 403 (routes/platform.py). L'appel partait
  // pourtant pour tous les rôles, et le `.catch()` rendait le refus invisible à l'écran.
  // Invisible, mais pas gratuit : ce tableau se recharge toutes les 30 secondes, donc
  // chaque formateur connecté produisait un 403 toutes les 30 secondes — journalisé en
  // avertissement, expédié vers Loki, et compté par l'alerte Grafana sur les refus.
  // On ne demande plus ce qu'on sait ne pas avoir le droit de lire.
  const piloteOuControle = role === "super_admin" || role === "admin" || role === "auditeur";

  const load = useCallback(async () => {
    try {
      const [d, a, r] = await Promise.all([
        getDashboard(),
        getAuditOverview().catch(() => ({ items: [] })),
        piloteOuControle
          ? getReadiness().catch(() => ({ ready: true, blocking: [], items: [] }))
          : Promise.resolve({ ready: true, blocking: [], items: [] }),
      ]);
      setData(d);
      setAudit(a.items.filter((s) => s.missing.length > 0).slice(0, 6));
      setBlocking(r.blocking);
      setError(null);
    } catch (e) {
      if (e instanceof LearnError && e.unavailable) setUnavailable(true);
      else setError((e as Error).message);
    }
  }, [piloteOuControle]);

  // Tant que le rôle n'est pas résolu, on ne demande rien : un apprenant verrait sinon
  // l'écran de l'organisme le temps d'un aller-retour, et les requêtes partiraient pour
  // un écran qu'on s'apprête à remplacer.
  useEffect(() => {
    if (!resolu || role === "apprenant") return;
    void load();
    const t = setInterval(() => void load(), 30_000);
    return () => clearInterval(t);
  }, [load, resolu, role]);

  if (!resolu) return null;
  if (role === "apprenant") return <LearnDashboardApprenant />;
  if (role === "formateur") return <LearnDashboardFormateur />;

  if (unavailable) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-text-secondary">
          LEARN n'a pas de base de données configurée sur cet environnement.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {blocking.length > 0 && (
        <Card className="border-amber-500/40">
          <CardHeader>
            <CardTitle className="text-amber-500">
              À régler avant d'accueillir un second organisme
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm">
            <ul className="space-y-1.5">
              {blocking.map((b) => (
                <li key={b.requirement}>
                  <span className="font-medium">{b.requirement}</span>
                  {b.detail && <span className="text-text-secondary"> — {b.detail}</span>}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {(data ? tilesFrom(data) : []).map((t) => (
          <Card key={t.label} className={t.urgent ? "border-amber-500/40" : undefined}>
            <CardContent className="py-4">
              <div className="text-2xl font-semibold tabular-nums">{t.value}</div>
              <div className="mt-0.5 text-sm">{t.label}</div>
              <div className="text-text-secondary mt-1 text-xs">{t.hint}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Dossiers d'audit incomplets</CardTitle>
        </CardHeader>
        <CardContent>
          {audit.length === 0 ? (
            <p className="text-text-secondary py-6 text-center text-sm">
              Aucune pièce manquante sur les sessions récentes.
            </p>
          ) : (
            <ul className="space-y-2 text-sm">
              {audit.map((s) => (
                <li key={s.code} className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="font-mono text-xs">{s.code}</span>
                  <span className="tabular-nums">{s.readiness}</span>
                  <span className="text-text-secondary">{s.missing.join(" · ")}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="text-text-secondary mt-4 text-xs">
            Le dossier existe en permanence. Il ne se prépare pas la veille de l'audit.
          </p>
        </CardContent>
      </Card>

      {error && <p className="text-sm text-red-400">{error}</p>}
    </div>
  );
}
