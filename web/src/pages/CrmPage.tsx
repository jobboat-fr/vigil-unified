import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Button } from "@nous-research/ui/ui/components/button";
import { vigil, DEAL_STAGES, type CrmContact, type CrmDeal, type CrmPipeline } from "@/lib/vigil";
import { GatewayError } from "@/lib/ww";

const money = (n: number, ccy = "USD") =>
  new Intl.NumberFormat(undefined, { style: "currency", currency: ccy, maximumFractionDigits: 0 }).format(n);

export default function CrmPage() {
  const [pipeline, setPipeline] = useState<CrmPipeline | null>(null);
  const [deals, setDeals] = useState<CrmDeal[]>([]);
  const [contacts, setContacts] = useState<CrmContact[]>([]);
  const [authError, setAuthError] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // new deal
  const [dealTitle, setDealTitle] = useState("");
  const [dealValue, setDealValue] = useState("");
  // new contact
  const [cName, setCName] = useState("");
  const [cCompany, setCCompany] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [p, d, c] = await Promise.all([vigil.crm.pipeline(), vigil.crm.deals(), vigil.crm.contacts()]);
      setPipeline(p);
      setDeals(d.deals);
      setContacts(c.contacts);
      setAuthError(null);
    } catch (e) {
      if (e instanceof GatewayError && e.code === "NO_SESSION") setAuthError("Sign in to VIGIL to use the CRM.");
      else setErr((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const addDeal = async () => {
    if (!dealTitle.trim()) return;
    setErr(null);
    try {
      await vigil.crm.addDeal({ title: dealTitle.trim(), value: parseFloat(dealValue) || 0, stage: "lead", probability: 10 });
      setDealTitle(""); setDealValue("");
      await refresh();
    } catch (e) { setErr((e as Error).message); }
  };

  const moveStage = async (d: CrmDeal, stage: string) => {
    await vigil.crm.updateDeal(d.id, { stage });
    await refresh();
  };

  const removeDeal = async (id: string) => { await vigil.crm.removeDeal(id); await refresh(); };

  const addContact = async () => {
    if (!cName.trim()) return;
    setErr(null);
    try {
      await vigil.crm.addContact({ name: cName.trim(), company: cCompany.trim() || undefined });
      setCName(""); setCCompany("");
      await refresh();
    } catch (e) { setErr((e as Error).message); }
  };

  const removeContact = async (id: string) => { await vigil.crm.removeContact(id); await refresh(); };

  const inputCls = "w-full rounded-md border border-current/20 bg-transparent px-3 py-2 text-sm outline-none focus:border-current/50";

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-bold tracking-tight">CRM</h1>
        <p className="text-sm text-text-secondary">Contacts and a deal pipeline — value rolls up to Finance, deals route to the Council.</p>
      </header>

      {authError && <Card><CardContent className="py-4 text-sm" style={{ color: "#f59e0b" }}>{authError}</CardContent></Card>}

      {pipeline && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          <Stat label="Open pipeline" value={money(pipeline.open_value)} />
          <Stat label="Weighted" value={money(pipeline.weighted_open_value)} color="#059669" />
          <Stat label="Deals" value={String(pipeline.deal_count)} />
        </div>
      )}

      {/* Pipeline board */}
      <Card>
        <CardHeader><CardTitle>Pipeline</CardTitle></CardHeader>
        <CardContent>
          <div className="flex flex-col gap-2 mb-4 sm:flex-row">
            <input className={inputCls} placeholder="New deal title" value={dealTitle} onChange={(e) => setDealTitle(e.target.value)} />
            <input className={`${inputCls} sm:w-40`} type="number" placeholder="Value" value={dealValue} onChange={(e) => setDealValue(e.target.value)} />
            <Button onClick={() => void addDeal()} disabled={!dealTitle.trim()}>Add deal</Button>
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
            {DEAL_STAGES.map((stage) => {
              const col = deals.filter((d) => d.stage === stage);
              const total = col.reduce((s, d) => s + (d.value || 0), 0);
              return (
                <div key={stage} className="rounded-md border border-current/10 p-2">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-xs font-semibold capitalize">{stage}</span>
                    <span className="text-[10px] text-text-secondary">{col.length} · {money(total)}</span>
                  </div>
                  <div className="flex flex-col gap-2">
                    {col.map((d) => (
                      <div key={d.id} className="rounded border border-current/10 p-2 text-xs">
                        <div className="flex items-start justify-between gap-1">
                          <span className="font-medium">{d.title}</span>
                          <button type="button" onClick={() => void removeDeal(d.id)} className="text-text-secondary hover:text-foreground">✕</button>
                        </div>
                        <div className="text-text-secondary">{money(d.value, d.currency)} · {d.probability}%</div>
                        <select
                          className="mt-1 w-full rounded border border-current/20 bg-transparent px-1 py-0.5 text-[10px]"
                          value={d.stage}
                          onChange={(e) => void moveStage(d, e.target.value)}
                        >
                          {DEAL_STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
                        </select>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Contacts */}
      <Card>
        <CardHeader><CardTitle>Contacts</CardTitle></CardHeader>
        <CardContent>
          <div className="flex flex-col gap-2 mb-3 sm:flex-row">
            <input className={inputCls} placeholder="Name" value={cName} onChange={(e) => setCName(e.target.value)} />
            <input className={inputCls} placeholder="Company" value={cCompany} onChange={(e) => setCCompany(e.target.value)} />
            <Button onClick={() => void addContact()} disabled={!cName.trim()}>Add</Button>
          </div>
          {err && <p className="mb-2 text-xs" style={{ color: "#ff3366" }}>{err}</p>}
          <div className="flex flex-col gap-1">
            {contacts.length === 0 && <p className="text-sm text-text-secondary">No contacts yet.</p>}
            {contacts.map((c) => (
              <div key={c.id} className="flex items-center justify-between gap-2 rounded-md border border-current/10 px-3 py-2">
                <div className="min-w-0">
                  <span className="block truncate text-sm font-medium">{c.name}</span>
                  <span className="text-xs text-text-secondary">{[c.title, c.company].filter(Boolean).join(" · ") || c.email || "—"}</span>
                </div>
                <button type="button" onClick={() => void removeContact(c.id)} className="text-xs text-text-secondary hover:text-foreground">Delete</button>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <Card>
      <CardContent className="py-4">
        <div className="text-[11px] uppercase tracking-wide text-text-secondary">{label}</div>
        <div className="text-lg font-bold tabular-nums" style={color ? { color } : undefined}>{value}</div>
      </CardContent>
    </Card>
  );
}
