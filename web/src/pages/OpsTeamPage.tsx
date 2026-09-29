import { useCallback, useEffect, useState } from "react";
import { SkeletonRows } from "@/components/EmptyState";
import { Link, useNavigate } from "react-router-dom";
import { Lock } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { EnTetePage } from "@/components/EnTetePage";
import { vigil, type Department, type OpsEvent, type OpsTask, type OpsUsage } from "@/lib/vigil";
import AgentsMarques from "@/components/AgentsMarques";
import { useLearnRole } from "@/lib/supabase";
import { Refus } from "@/components/Refus";
import { Markdown } from "@/components/Markdown";
import { AGENTS, useAbonnementAgents } from "@/lib/agentique";
import { mandatPole, nomFormule, nomPole, nomTravail, regardPole, statutPole, statutTachePole } from "@/lib/mots";

// Ops Team — the agentic company. Departments are on-demand agent units; each
// only counts as "working" once its effectiveness selftest passes. P0 ships the
// org board + the Support reference department, wired live to /v1/ops.

const STATUS_COLOR: Record<string, string> = {
  live: "var(--color-success)",
  failing: "var(--color-destructive)",
  provisioning: "var(--color-muted-foreground)",
};

// Le coût par exécution est notre coût de modèle : il regarde l'exploitation VTLVS, pas le client.
function healthLine(d: Department, exploitation: boolean): string {
  const h = d.health as { success_rate?: number | null; avg_cost_usd?: number; runs?: number; p50_ms?: number };
  if (!h || !h.runs) return "aucune exécution — lancez l'autotest pour le vérifier";
  const sr = h.success_rate == null ? "—" : `${Math.round(h.success_rate * 100)}%`;
  const cout = exploitation ? ` · ${(h.avg_cost_usd ?? 0).toFixed(3)} $ par exécution` : "";
  return `réussite ${sr}${cout} · ${h.p50_ms ?? 0} ms · ${h.runs} exécution${h.runs > 1 ? "s" : ""}`;
}

export default function OpsTeamPage() {
  const navigate = useNavigate();
  const [departments, setDepartments] = useState<Department[]>([]);
  const [events, setEvents] = useState<OpsEvent[]>([]);
  const [usage, setUsage] = useState<OpsUsage | null>(null);
  const [authError, setAuthError] = useState<unknown>(null);
  // L'erreur d'un pôle s'affiche DANS sa carte : un refus d'abonnement du Support n'a rien à
  // faire en haut de page, loin du bouton qui l'a provoqué.
  const [erreurs, setErreurs] = useState<Record<string, unknown>>({});
  const { estAbonne } = useAbonnementAgents();
  const [busy, setBusy] = useState<Record<string, string>>({});
  const [result, setResult] = useState<Record<string, OpsTask>>({});
  const [pausing, setPausing] = useState(false);
  const { role } = useLearnRole();

  const refresh = useCallback(async () => {
    try {
      const [{ departments }, { events }, usage] = await Promise.all([
        vigil.ops.departments(), vigil.ops.feed(20), vigil.ops.usage().catch(() => null),
      ]);
      setDepartments(departments);
      setEvents(events);
      setUsage(usage);
      setAuthError(null);
    } catch (e) {
      setAuthError(e);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot load on mount
    void refresh();
  }, [refresh]);

  const act = async (d: Department, action: string) => {
    setBusy((b) => ({ ...b, [d.id]: action }));
    setErreurs((x) => ({ ...x, [d.id]: null }));
    try {
      const { task } = action === "selftest" ? await vigil.ops.selftest(d.id) : await vigil.ops.run(d.id, action);
      setResult((r) => ({ ...r, [d.id]: task }));
      await refresh();
    } catch (e) {
      setErreurs((x) => ({ ...x, [d.id]: e }));
    } finally {
      setBusy((b) => ({ ...b, [d.id]: "" }));
    }
  };

  const anyPaused = departments.some((d) => d.paused);
  const toggleKill = async () => {
    setPausing(true);
    try {
      if (anyPaused) await vigil.ops.resumeAll();
      else await vigil.ops.pauseAll();
      await refresh();
    } catch (e) {
      // Sans ce `catch`, un refus laissait le bouton sans réponse (audit du 29/09).
      setAuthError(e);
    } finally {
      setPausing(false);
    }
  };

  const live = departments.filter((d) => d.status === "live").length;

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <EnTetePage
        titre="Équipe agentique"
        description={
          <>
            Les pôles de l'assistant. Chacun ne travaille qu'à la demande, et n'est compté
            comme opérationnel qu'une fois son autotest passé.
          </>
        }
        actions={
          <Button
            onClick={() => void toggleKill()}
            disabled={pausing}
            style={anyPaused ? undefined : { color: "var(--color-destructive)", borderColor: "var(--color-destructive)" }}
          >
            {pausing ? "…" : anyPaused ? "Tout reprendre" : "Tout suspendre"}
          </Button>
        }
      />

      {/* Les agents d'AZZ&CO Labs passent avant les pôles : c'est ce que le client achète. */}
      <AgentsMarques role={role as never} />

      {authError != null && <Refus erreur={authError} quoi="l'équipe agentique" onReessayer={() => void refresh()} />}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-md p-3" style={{ background: "var(--color-background-secondary, rgba(127,127,127,0.06))" }}>
          <div className="text-xs text-text-secondary">Pôles actifs</div>
          <div className="text-2xl font-semibold">{live} / {departments.length}</div>
        </div>
        <div className="rounded-md p-3" style={{ background: "var(--color-background-secondary, rgba(127,127,127,0.06))" }}>
          <div className="text-xs text-text-secondary">Formule · exécutions du jour</div>
          <div className="text-2xl font-semibold">
            {usage?.plan ? nomFormule(usage.plan) : "—"}
            <span className="text-sm font-normal text-text-secondary">
              {" · "}{usage ? usage.runs_today : 0}{usage?.daily_cap != null ? ` / ${usage.daily_cap}` : ""}
            </span>
          </div>
        </div>
        <div className="rounded-md p-3" style={{ background: "var(--color-background-secondary, rgba(127,127,127,0.06))" }}>
          <div className="text-xs text-text-secondary">Activité récente</div>
          <div className="text-2xl font-semibold">{events.length}</div>
        </div>
        <div className="rounded-md p-3" style={{ background: "var(--color-background-secondary, rgba(127,127,127,0.06))" }}>
          <div className="text-xs text-text-secondary">Arrêt d'urgence</div>
          <div className="text-2xl font-semibold" style={{ color: anyPaused ? "var(--color-destructive)" : "var(--color-success)" }}>{anyPaused ? "Enclenché" : "Prêt"}</div>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {departments.map((d) => {
          const r = result[d.id];
          const b = busy[d.id];
          const porteur = AGENTS.find((a) => a.id === d.agent);
          const ouvert = !d.agent || estAbonne(d.agent);
          return (
            <Card key={d.id}>
              <CardHeader>
                <CardTitle className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2">
                    <span style={{ width: 9, height: 9, borderRadius: "50%", background: STATUS_COLOR[d.status] || "var(--color-muted-foreground)", display: "inline-block" }} />
                    <span className="truncate">{nomPole(d.slug, d.name)}</span>
                  </span>
                  <span className="text-[10px] uppercase tracking-wide text-text-secondary">
                    {d.paused ? "Suspendu" : statutPole(d.status)}{d.head_lens ? ` · ${regardPole(d.head_lens)}` : ""}
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                <p className="text-sm text-text-secondary leading-snug">{mandatPole(d.slug, d.mandate)}</p>
                {porteur && (
                  <p className="text-xs">
                    Porté par <span className="font-semibold">{porteur.nom}</span>
                    {!ouvert && (
                      <span className="mt-1 flex items-start gap-1.5 text-text-secondary">
                        <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                        <span>
                          Réservé aux organismes abonnés à {porteur.nom}.{" "}
                          <Link to="/abonnement" className="font-medium text-foreground underline">Voir l'abonnement</Link>
                        </span>
                      </span>
                    )}
                  </p>
                )}
                <p className="text-[11px] text-text-secondary font-mono">{healthLine(d, role === "super_admin")}</p>
                {r && (
                  <div
                    className="rounded-md px-2.5 py-2 text-xs"
                    style={{
                      background: r.accepted ? "rgba(52,211,153,0.10)" : "rgba(251,113,133,0.10)",
                      border: `1px solid ${r.accepted ? "rgba(52,211,153,0.28)" : "rgba(251,113,133,0.28)"}`,
                    }}
                  >
                    <div className="flex items-center justify-between gap-2 font-semibold" style={{ color: r.accepted ? "#16a34a" : "#dc2626" }}>
                      <span>{r.accepted ? "✓" : "✕"} {nomTravail(r.job)} — {statutTachePole(r.status)}</span>
                      <span className="font-mono text-[10px] font-normal text-text-secondary">{role === "super_admin" ? `${Number(r.cost_usd).toFixed(3)} $ · ` : ""}{r.wall_ms} ms</span>
                    </div>
                    {(r.summary || r.reason) && (
                      <div className="mt-2"><Markdown content={r.summary || r.reason || ""} /></div>
                    )}
                    {r.output_artifact_id && (
                      <button
                        onClick={() => navigate(`/studio?artifact=${r.output_artifact_id}`)}
                        className="mt-1.5 inline-flex items-center gap-1 font-medium underline hover:text-foreground"
                        style={{ color: "var(--color-primary)" }}
                      >
                        Ouvrir le résultat →
                      </button>
                    )}
                  </div>
                )}
                {erreurs[d.id] != null && <Refus erreur={erreurs[d.id]} quoi={`le pôle ${nomPole(d.slug, d.name)}`} compact />}
                <div className="flex flex-wrap gap-2">
                  {(d.jobs.length ? d.jobs : ["run"]).map((job) => (
                    <Button key={job} onClick={() => void act(d, job)} disabled={!!b || d.paused || !ouvert}>
                      {b === job ? "En cours…" : nomTravail(job)}
                    </Button>
                  ))}
                  <Button ghost onClick={() => void act(d, "selftest")} disabled={!!b || d.paused || !ouvert}>
                    {b === "selftest" ? "Test en cours…" : "Autotest"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          );
        })}
        {departments.length === 0 && authError == null && (
          <Card><CardContent className="py-6"><SkeletonRows rows={4} /></CardContent></Card>
        )}
      </div>

      <Card>
        <CardHeader><CardTitle>Activité</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-1.5">
          {events.length === 0 && <p className="text-sm text-text-secondary">Aucune activité pour l'instant. Lancez un pôle.</p>}
          {events.map((e) => (
            <div key={e.id} className="text-sm leading-snug">
              <span className="text-text-secondary font-mono text-xs">{new Date(e.ts).toLocaleTimeString("fr-FR")}</span>{" "}
              <span>{e.summary}</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
