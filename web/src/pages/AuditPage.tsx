import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { ww, type AuditEvent } from "@/lib/ww";
import { useWwPoll } from "@/lib/useWw";
import { WwGate } from "./scaffold";

export default function AuditPage() {
  const state = useWwPoll(() => ww.audit.events(150), 8000);
  const events: AuditEvent[] = Array.isArray(state.data) ? state.data : [];

  return (
    <div className="flex flex-col gap-6">
      <WwGate state={state}>
        <Card>
          <CardHeader>
            <CardTitle>Agentic Audit Log · {events.length}</CardTitle>
          </CardHeader>
          <CardContent>
            {events.length === 0 ? (
              <p className="text-text-secondary text-sm py-6 text-center">No audit events yet.</p>
            ) : (
              <ul className="space-y-1 max-h-[72vh] overflow-y-auto pr-1 font-mono text-xs">
                {events.map((e, i) => (
                  <li
                    key={e.id ?? i}
                    className="flex items-start gap-3 border-t border-current/10 py-1.5"
                  >
                    <span className="text-text-secondary shrink-0 w-36">
                      {e.ts ? new Date(e.ts).toLocaleString() : "—"}
                    </span>
                    <span
                      className="shrink-0 w-24 truncate"
                      style={{ color: e.critical ? "#ff3366" : "#38bdf8" }}
                    >
                      {e.component || "—"}
                    </span>
                    <span className="text-foreground/90 shrink-0 w-40 truncate">
                      {e.event_type}
                      {e.action ? `.${e.action}` : ""}
                    </span>
                    <span className="text-text-secondary truncate">
                      {e.decision_id ? `decision ${e.decision_id}` : ""}
                      {e.actor_email ? ` · ${e.actor_email}` : ""}
                    </span>
                    {e.critical ? (
                      <span className="ml-auto shrink-0 text-[10px] px-1.5 rounded" style={{ color: "#ff3366", background: "#ff33661a" }}>
                        CRITICAL
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </WwGate>
    </div>
  );
}
