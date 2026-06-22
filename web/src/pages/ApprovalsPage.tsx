import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Button } from "@nous-research/ui/ui/components/button";
import { vigil, type OutboundAction } from "@/lib/vigil";
import { GatewayError } from "@/lib/ww";

// Approvals — the human-in-the-loop gate for outbound write-actions. Departments
// (and the UI) only ever PROPOSE; nothing leaves the system until it's approved here.

const STATUS_COLOR: Record<string, string> = {
  pending: "#f59e0b", executed: "#059669", rejected: "#6b7280", failed: "#ef4444",
};

function summarize(a: OutboundAction): string {
  const p = a.params as Record<string, string>;
  if (a.action === "send") return `Send email to ${p.to || "?"} — “${p.subject || ""}”`;
  if (a.action === "create_issue") return `Open issue in ${p.repo || "?"}: “${p.title || ""}”`;
  return `${a.action} (${Object.keys(a.params).join(", ")})`;
}

export default function ApprovalsPage() {
  const [actions, setActions] = useState<OutboundAction[]>([]);
  const [authError, setAuthError] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setActions((await vigil.connect.actions()).actions);
      setAuthError(null);
    } catch (e) {
      if (e instanceof GatewayError && e.code === "NO_SESSION") setAuthError("Sign in to review approvals.");
      else setAuthError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot load on mount
    void refresh();
  }, [refresh]);

  const decide = async (a: OutboundAction, kind: "approve" | "reject") => {
    setBusy(a.id + kind);
    setErr(null);
    try {
      if (kind === "approve") await vigil.connect.approve(a.id);
      else await vigil.connect.reject(a.id);
      await refresh();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  const pending = actions.filter((a) => a.status === "pending");
  const recent = actions.filter((a) => a.status !== "pending").slice(0, 20);

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-bold tracking-tight">Approvals</h1>
        <p className="text-sm text-text-secondary">
          Nothing leaves the system until you approve it. Departments propose outbound actions; you decide.
        </p>
      </header>

      {authError && <Card><CardContent className="py-4 text-sm" style={{ color: "#f59e0b" }}>{authError}</CardContent></Card>}
      {err && <Card><CardContent className="py-3 text-sm" style={{ color: "#ff3366" }}>{err}</CardContent></Card>}

      <Card>
        <CardHeader><CardTitle>Pending · {pending.length}</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-2">
          {pending.length === 0 && <p className="text-sm text-text-secondary">Nothing waiting. Clear.</p>}
          {pending.map((a) => (
            <div key={a.id} className="flex items-center gap-3 rounded-md border border-current/10 px-3 py-2">
              <span className="rounded px-1.5 py-0.5 text-[10px] uppercase" style={{ color: "#888", border: "1px solid currentColor" }}>{a.provider}</span>
              <span className="min-w-0 flex-1 truncate text-sm">{summarize(a)}</span>
              <span className="text-[10px] text-text-secondary">{a.requested_by}</span>
              <Button disabled={!!busy} onClick={() => void decide(a, "approve")} style={{ color: "#059669", borderColor: "#059669" }}>
                {busy === a.id + "approve" ? "…" : "Approve"}
              </Button>
              <button type="button" disabled={!!busy} className="text-xs text-text-secondary hover:text-foreground" onClick={() => void decide(a, "reject")}>Reject</button>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Recent</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-1.5">
          {recent.length === 0 && <p className="text-sm text-text-secondary">No history yet.</p>}
          {recent.map((a) => (
            <div key={a.id} className="flex items-center gap-2 text-sm">
              <span className="text-[10px] uppercase w-16" style={{ color: STATUS_COLOR[a.status] }}>{a.status}</span>
              <span className="min-w-0 flex-1 truncate">{summarize(a)}</span>
              {a.error && <span className="truncate text-xs" style={{ color: "#ef4444" }}>{a.error}</span>}
              {a.result && typeof (a.result as { issue_url?: string }).issue_url === "string" && (
                <a href={(a.result as { issue_url: string }).issue_url} className="text-xs underline" style={{ color: "var(--color-text-info)" }}>view</a>
              )}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
