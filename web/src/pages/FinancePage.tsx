import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Button } from "@nous-research/ui/ui/components/button";
import { vigil, type FinanceTxn, type FinanceSummary, type FinanceConnectStatus } from "@/lib/vigil";
import { GatewayError } from "@/lib/ww";

const money = (n: number, ccy = "USD") =>
  new Intl.NumberFormat(undefined, { style: "currency", currency: ccy, maximumFractionDigits: 2 }).format(n);

export default function FinancePage() {
  const [summary, setSummary] = useState<FinanceSummary | null>(null);
  const [txns, setTxns] = useState<FinanceTxn[]>([]);
  const [authError, setAuthError] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // capture form
  const [amount, setAmount] = useState("");
  const [desc, setDesc] = useState("");
  const [category, setCategory] = useState("");
  const [sign, setSign] = useState<-1 | 1>(-1); // expense default
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [s, t] = await Promise.all([vigil.finance.summary(), vigil.finance.transactions({ limit: 100 })]);
      setSummary(s);
      setTxns(t.transactions);
      setAuthError(null);
    } catch (e) {
      if (e instanceof GatewayError && e.code === "NO_SESSION") setAuthError("Sign in to VIGIL to use Finance.");
      else setErr((e as Error).message);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot load on mount
    void refresh();
  }, [refresh]);

  const capture = async () => {
    const val = parseFloat(amount);
    if (!Number.isFinite(val) || val <= 0) return;
    setBusy(true);
    setErr(null);
    try {
      await vigil.finance.addTransaction({
        amount: sign * Math.abs(val),
        description: desc.trim(),
        category: category.trim() || undefined,
      });
      setAmount(""); setDesc(""); setCategory("");
      await refresh();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const cycleStatus = async (t: FinanceTxn) => {
    const next = t.status === "reconciled" ? "categorized" : "reconciled";
    await vigil.finance.updateTransaction(t.id, { status: next });
    await refresh();
  };

  const remove = async (id: string) => {
    await vigil.finance.removeTransaction(id);
    await refresh();
  };

  const inputCls = "w-full rounded-md border border-current/20 bg-transparent px-3 py-2 text-sm outline-none focus:border-current/50";
  const statusColor: Record<string, string> = { uncategorized: "#f59e0b", categorized: "#3b82f6", reconciled: "#059669" };

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-bold tracking-tight">Finance</h1>
        <p className="text-sm text-text-secondary">Capture → classify → reconcile. The books the CFO suite reasons over.</p>
      </header>

      {authError && <Card><CardContent className="py-4 text-sm" style={{ color: "#f59e0b" }}>{authError}</CardContent></Card>}

      {summary && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Income" value={money(summary.income)} color="#059669" />
          <Stat label="Expense" value={money(summary.expense)} color="#ef4444" />
          <Stat label="Net" value={money(summary.net)} color={summary.net >= 0 ? "#059669" : "#ef4444"} />
          <Stat label="Reconciled" value={`${Math.round(summary.reconcile_progress * 100)}%`} sub={`${summary.reconciled_count}/${summary.transaction_count}`} />
        </div>
      )}

      <ConnectPanel onSynced={() => void refresh()} />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader><CardTitle>Capture a transaction</CardTitle></CardHeader>
            <CardContent className="flex flex-col gap-3">
              <div className="flex gap-2">
                <button type="button" onClick={() => setSign(-1)} className="flex-1 rounded-md px-3 py-2 text-sm" style={{ border: "1px solid currentColor", opacity: sign === -1 ? 1 : 0.4 }}>− Expense</button>
                <button type="button" onClick={() => setSign(1)} className="flex-1 rounded-md px-3 py-2 text-sm" style={{ border: "1px solid currentColor", opacity: sign === 1 ? 1 : 0.4 }}>+ Income</button>
              </div>
              <input className={inputCls} type="number" inputMode="decimal" placeholder="Amount" value={amount} onChange={(e) => setAmount(e.target.value)} />
              <input className={inputCls} placeholder="Description" value={desc} onChange={(e) => setDesc(e.target.value)} />
              <input className={inputCls} placeholder="Category (optional)" value={category} onChange={(e) => setCategory(e.target.value)} />
              <Button onClick={() => void capture()} disabled={busy || !amount} className="w-full">{busy ? "…" : "Add to ledger"}</Button>
              {err && <p className="text-xs" style={{ color: "#ff3366" }}>{err}</p>}
            </CardContent>
          </Card>

          {summary && Object.keys(summary.by_category).length > 0 && (
            <Card>
              <CardHeader><CardTitle>By category</CardTitle></CardHeader>
              <CardContent className="flex flex-col gap-1">
                {Object.entries(summary.by_category).sort((a, b) => a[1] - b[1]).map(([cat, val]) => (
                  <div key={cat} className="flex justify-between text-sm">
                    <span className="capitalize text-text-secondary">{cat}</span>
                    <span style={{ color: val >= 0 ? "#059669" : "#ef4444" }}>{money(val)}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </div>

        <Card>
          <CardHeader><CardTitle>Ledger</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-1">
            {txns.length === 0 && <p className="text-sm text-text-secondary">No transactions yet.</p>}
            {txns.map((t) => (
              <div key={t.id} className="flex items-center gap-3 rounded-md border border-current/10 px-3 py-2">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium">{t.description || "(no description)"}</span>
                    {t.category && <span className="rounded px-1.5 py-0.5 text-[10px] capitalize text-text-secondary" style={{ border: "1px solid currentColor" }}>{t.category}</span>}
                  </div>
                  <span className="text-xs text-text-secondary">{t.txn_date}</span>
                </div>
                <button type="button" onClick={() => void cycleStatus(t)} className="rounded px-2 py-0.5 text-[10px] uppercase" style={{ color: statusColor[t.status] || "#888", border: `1px solid ${statusColor[t.status] || "#888"}` }} title="Toggle reconciled">{t.status}</button>
                <span className="w-24 text-right text-sm tabular-nums" style={{ color: t.amount >= 0 ? "#059669" : "#ef4444" }}>{money(t.amount, t.currency)}</span>
                <button type="button" onClick={() => void remove(t.id)} className="text-xs text-text-secondary hover:text-foreground">✕</button>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function ConnectPanel({ onSynced }: { onSynced: () => void }) {
  const [status, setStatus] = useState<FinanceConnectStatus | null>(null);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [keyVals, setKeyVals] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      setStatus(await vigil.finance.connect.status());
    } catch (e) {
      if (!(e instanceof GatewayError && e.code === "NO_SESSION")) setErr((e as Error).message);
    }
  }, []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot load on mount
    void load();
  }, [load]);

  const plaid = status?.providers.find((p) => p.id === "plaid");
  const canSandbox = !!plaid?.configured && status?.plaid_env === "sandbox";

  const wrap = async (key: string, fn: () => Promise<string>) => {
    setBusy(key); setErr(null); setMsg(null);
    try { setMsg(await fn()); await load(); onSynced(); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(""); }
  };

  return (
    <Card>
      <CardHeader><CardTitle>Bank &amp; accounting</CardTitle></CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-sm text-text-secondary">
          Connect a bank (Plaid) or accounting platform to sync transactions into the ledger. The Finance
          department reconciles whatever lands here.
        </p>

        {/* Providers + their platform keys (keys management) */}
        <div className="flex flex-col gap-2">
          {status?.providers.map((p) => (
            <div key={p.id} className="rounded-md border border-current/10 px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium">{p.name}</span>
                <span className="rounded px-2 py-0.5 text-[10px] uppercase" style={{ color: p.configured ? "#059669" : "#f59e0b", border: "1px solid currentColor" }}>
                  {p.configured ? "configured" : p.implemented ? "keys needed" : "coming soon"}
                </span>
              </div>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {p.required_keys.map((k) => (
                  <span key={k.name} className="rounded px-1.5 py-0.5 text-[10px] font-mono" style={{ color: k.set ? "#059669" : "#9ca3af", border: "1px solid currentColor" }} title={k.set ? "set" : "not set"}>
                    {k.set ? "✓ " : "○ "}{k.name}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Keys editor — enter platform keys from the UI (stored encrypted) */}
        {plaid && (
          <details open={!plaid.configured}>
            <summary className="cursor-pointer text-xs text-text-secondary">{plaid.configured ? "Update Plaid keys" : "Set Plaid keys"}</summary>
            <div className="mt-2 flex flex-col gap-2">
              {plaid.required_keys.map((k) =>
                k.name.endsWith("_ENV") ? (
                  <select
                    key={k.name}
                    className="rounded-md border border-current/20 bg-transparent px-3 py-2 text-sm outline-none focus:border-current/50"
                    defaultValue=""
                    onChange={(e) => setKeyVals((v) => ({ ...v, [k.name]: e.target.value }))}
                  >
                    <option value="" disabled>{k.name} (environment)</option>
                    <option value="sandbox">sandbox</option>
                    <option value="production">production</option>
                  </select>
                ) : (
                  <input
                    key={k.name}
                    type={k.name.includes("SECRET") ? "password" : "text"}
                    placeholder={k.name + (k.set ? " (set — leave blank to keep)" : "")}
                    className="rounded-md border border-current/20 bg-transparent px-3 py-2 text-sm outline-none focus:border-current/50"
                    onChange={(e) => setKeyVals((v) => ({ ...v, [k.name]: e.target.value }))}
                  />
                ),
              )}
              <Button
                disabled={!!busy}
                onClick={() => void wrap("keys", async () => {
                  const r = await vigil.finance.connect.keys("plaid", keyVals);
                  setKeyVals({});
                  return `Saved ${r.saved} key${r.saved === 1 ? "" : "s"}.`;
                })}
              >
                {busy === "keys" ? "Saving…" : "Save keys"}
              </Button>
            </div>
          </details>
        )}

        {/* Connections */}
        {status && status.connections.length > 0 && (
          <div className="flex flex-col gap-1.5">
            {status.connections.map((c) => (
              <div key={c.id} className="flex items-center gap-2 rounded-md border border-current/10 px-3 py-2 text-sm">
                <span className="flex-1 truncate">{c.institution || c.provider} · <span className="text-text-secondary">{c.accounts_count} accts · {c.token_masked}</span></span>
                <span className="text-[10px] uppercase" style={{ color: c.status === "active" ? "#059669" : "#ef4444" }}>{c.status}</span>
                <button type="button" className="text-xs text-text-secondary hover:text-foreground" onClick={() => void wrap("dc" + c.id, async () => { await vigil.finance.connect.disconnect(c.id); return "Disconnected."; })}>✕</button>
              </div>
            ))}
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {canSandbox && (
            <Button disabled={!!busy} onClick={() => void wrap("sandbox", async () => { const r = await vigil.finance.connect.sandbox(); return `Connected ${r.connection.institution || "bank"}.`; })}>
              {busy === "sandbox" ? "Connecting…" : "Connect sandbox bank"}
            </Button>
          )}
          <Button ghost disabled={!!busy || !status?.connections.length} onClick={() => void wrap("sync", async () => { const r = await vigil.finance.connect.sync(); return `Synced ${r.transactions_added} transactions from ${r.connections} connection(s).`; })}>
            {busy === "sync" ? "Syncing…" : "Sync now"}
          </Button>
        </div>

        {plaid && !plaid.configured && (
          <p className="text-xs text-text-secondary">
            Set <code>PLAID_CLIENT_ID</code>, <code>PLAID_SECRET</code> and <code>PLAID_ENV</code> on the gateway to enable bank connections.
          </p>
        )}
        {msg && <p className="text-xs" style={{ color: "#059669" }}>{msg}</p>}
        {err && <p className="text-xs" style={{ color: "#ff3366" }}>{err}</p>}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <Card>
      <CardContent className="py-4">
        <div className="text-[11px] uppercase tracking-wide text-text-secondary">{label}</div>
        <div className="text-lg font-bold tabular-nums" style={color ? { color } : undefined}>{value}</div>
        {sub && <div className="text-xs text-text-secondary">{sub}</div>}
      </CardContent>
    </Card>
  );
}
