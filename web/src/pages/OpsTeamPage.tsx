import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Button } from "@nous-research/ui/ui/components/button";
import { vigil, type Department, type OpsEvent, type OpsTask, type OpsUsage } from "@/lib/vigil";
import { GatewayError } from "@/lib/ww";

// Ops Team — the agentic company. Departments are on-demand agent units; each
// only counts as "working" once its effectiveness selftest passes. P0 ships the
// org board + the Support reference department, wired live to /v1/ops.

const STATUS_COLOR: Record<string, string> = {
  live: "#22c55e",
  failing: "#ef4444",
  provisioning: "#9ca3af",
};

function healthLine(d: Department): string {
  const h = d.health as { success_rate?: number | null; avg_cost_usd?: number; runs?: number; p50_ms?: number };
  if (!h || !h.runs) return "no runs yet — run the self-test to prove it works";
  const sr = h.success_rate == null ? "—" : `${Math.round(h.success_rate * 100)}%`;
  return `success ${sr} · $${(h.avg_cost_usd ?? 0).toFixed(3)}/run · ${h.p50_ms ?? 0}ms · ${h.runs} runs`;
}

export default function OpsTeamPage() {
  const [departments, setDepartments] = useState<Department[]>([]);
  const [events, setEvents] = useState<OpsEvent[]>([]);
  const [usage, setUsage] = useState<OpsUsage | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<string, string>>({});
  const [result, setResult] = useState<Record<string, OpsTask>>({});
  const [pausing, setPausing] = useState(false);

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
      if (e instanceof GatewayError && e.code === "NO_SESSION") setAuthError("Sign in to VIGIL to use the Ops Team.");
      else setAuthError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot load on mount
    void refresh();
  }, [refresh]);

  const act = async (d: Department, action: string) => {
    setBusy((b) => ({ ...b, [d.id]: action }));
    try {
      const { task } = action === "selftest" ? await vigil.ops.selftest(d.id) : await vigil.ops.run(d.id, action);
      setResult((r) => ({ ...r, [d.id]: task }));
      await refresh();
    } catch (e) {
      setAuthError((e as Error).message);
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
    } finally {
      setPausing(false);
    }
  };

  const live = departments.filter((d) => d.status === "live").length;

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <header className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-bold tracking-tight">Ops Team</h1>
          <p className="text-sm text-text-secondary">
            An agentic company — each department runs <em>on demand</em> and only counts as working once its
            self-test passes its effectiveness contract.
          </p>
        </div>
        <Button
          onClick={() => void toggleKill()}
          disabled={pausing}
          style={anyPaused ? undefined : { color: "#ef4444", borderColor: "#ef4444" }}
        >
          {pausing ? "…" : anyPaused ? "Resume all" : "Pause all"}
        </Button>
      </header>

      {authError && (
        <Card><CardContent className="py-4 text-sm" style={{ color: "#f59e0b" }}>{authError}</CardContent></Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-md p-3" style={{ background: "var(--color-background-secondary, rgba(127,127,127,0.06))" }}>
          <div className="text-xs text-text-secondary">Departments live</div>
          <div className="text-2xl font-semibold">{live} / {departments.length}</div>
        </div>
        <div className="rounded-md p-3" style={{ background: "var(--color-background-secondary, rgba(127,127,127,0.06))" }}>
          <div className="text-xs text-text-secondary">Plan · runs today</div>
          <div className="text-2xl font-semibold capitalize">
            {usage?.plan ?? "—"}
            <span className="text-sm font-normal text-text-secondary">
              {" · "}{usage ? usage.runs_today : 0}{usage?.daily_cap != null ? ` / ${usage.daily_cap}` : ""}
            </span>
          </div>
        </div>
        <div className="rounded-md p-3" style={{ background: "var(--color-background-secondary, rgba(127,127,127,0.06))" }}>
          <div className="text-xs text-text-secondary">Recent activity</div>
          <div className="text-2xl font-semibold">{events.length}</div>
        </div>
        <div className="rounded-md p-3" style={{ background: "var(--color-background-secondary, rgba(127,127,127,0.06))" }}>
          <div className="text-xs text-text-secondary">Kill switch</div>
          <div className="text-2xl font-semibold" style={{ color: anyPaused ? "#ef4444" : "#22c55e" }}>{anyPaused ? "paused" : "armed"}</div>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {departments.map((d) => {
          const r = result[d.id];
          const b = busy[d.id];
          return (
            <Card key={d.id}>
              <CardHeader>
                <CardTitle className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2">
                    <span style={{ width: 9, height: 9, borderRadius: "50%", background: STATUS_COLOR[d.status] || "#9ca3af", display: "inline-block" }} />
                    <span className="truncate">{d.name}</span>
                  </span>
                  <span className="text-[10px] uppercase tracking-wide text-text-secondary">
                    {d.paused ? "paused" : d.status}{d.head_lens ? ` · ${d.head_lens}` : ""}
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                <p className="text-sm text-text-secondary leading-snug">{d.mandate}</p>
                <p className="text-[11px] text-text-secondary font-mono">{healthLine(d)}</p>
                {r && (
                  <p
                    className="text-xs rounded-md px-2 py-1.5"
                    style={{
                      background: r.accepted ? "rgba(34,197,94,0.1)" : "rgba(239,68,68,0.1)",
                      color: r.accepted ? "#16a34a" : "#dc2626",
                    }}
                  >
                    {r.accepted ? "✓ " : "✕ "}{r.title} — {r.status}
                    {r.reason ? ` (${r.reason})` : ""} · ${Number(r.cost_usd).toFixed(3)} · {r.wall_ms}ms
                  </p>
                )}
                <div className="flex flex-wrap gap-2">
                  {(d.jobs.length ? d.jobs : ["run"]).map((job) => (
                    <Button key={job} onClick={() => void act(d, job)} disabled={!!b || d.paused} className="capitalize">
                      {b === job ? "Running…" : job.replace(/_/g, " ")}
                    </Button>
                  ))}
                  <Button ghost onClick={() => void act(d, "selftest")} disabled={!!b || d.paused}>
                    {b === "selftest" ? "Testing…" : "Self-test"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          );
        })}
        {departments.length === 0 && !authError && (
          <Card><CardContent className="py-6 text-center text-sm text-text-secondary">Loading departments…</CardContent></Card>
        )}
      </div>

      <Card>
        <CardHeader><CardTitle>Company activity</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-1.5">
          {events.length === 0 && <p className="text-sm text-text-secondary">No activity yet. Run a department.</p>}
          {events.map((e) => (
            <div key={e.id} className="text-sm leading-snug">
              <span className="text-text-secondary font-mono text-xs">{new Date(e.ts).toLocaleTimeString()}</span>{" "}
              <span>{e.summary}</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
