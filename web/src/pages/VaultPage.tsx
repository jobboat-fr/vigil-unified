import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { ww } from "@/lib/ww";
import { useWwPoll } from "@/lib/useWw";
import { WwGate } from "./scaffold";

interface VaultDoc {
  id?: string;
  filename?: string;
  title?: string;
  category?: string;
  summary?: string;
  risk_flags?: { severity?: string; note?: string }[];
}

const sevColor = (s?: string) => {
  const v = (s || "").toLowerCase();
  if (v === "high" || v === "critical") return "#ff3366";
  if (v === "medium") return "#f59e0b";
  return "#38bdf8";
};

export default function VaultPage() {
  const state = useWwPoll(() => ww.vault.list() as Promise<VaultDoc[]>, 15000);
  const docs: VaultDoc[] = Array.isArray(state.data) ? state.data : [];

  return (
    <div className="flex flex-col gap-6">
      <WwGate state={state}>
        <Card>
          <CardHeader>
            <CardTitle>Document Vault · {docs.length}</CardTitle>
          </CardHeader>
          <CardContent>
            {docs.length === 0 ? (
              <p className="text-text-secondary text-sm py-6 text-center">
                No documents yet — upload contracts, invoices, or legal/finance papers to ground the agent.
              </p>
            ) : (
              <ul className="space-y-2 max-h-[72vh] overflow-y-auto pr-1">
                {docs.map((d, i) => (
                  <li key={d.id ?? i} className="rounded-lg border border-current/15 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-foreground/90 truncate">{d.title || d.filename || "Untitled"}</span>
                      {d.category ? (
                        <span className="text-[10px] font-mono uppercase tracking-wide text-text-secondary shrink-0">
                          {d.category}
                        </span>
                      ) : null}
                    </div>
                    {d.summary ? <p className="mt-1 text-xs text-text-secondary line-clamp-2">{d.summary}</p> : null}
                    {d.risk_flags?.length ? (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {d.risk_flags.slice(0, 4).map((f, j) => (
                          <span
                            key={j}
                            className="text-[10px] px-1.5 py-0.5 rounded"
                            style={{ color: sevColor(f.severity), background: `${sevColor(f.severity)}1a` }}
                          >
                            ⚠ {f.note || f.severity}
                          </span>
                        ))}
                      </div>
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
