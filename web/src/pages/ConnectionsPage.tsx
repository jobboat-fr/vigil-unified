import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Button } from "@nous-research/ui/ui/components/button";
import { vigil, type ConnectStatus, type Connection } from "@/lib/vigil";
import { GatewayError } from "@/lib/ww";

// Connections — tenants link their systems of record (GitHub, HubSpot, Stripe, …)
// with a per-provider token. Tokens are stored encrypted and never returned; the
// departments then sync + work the tenant's live data.

const PROVIDER_LABEL: Record<string, { name: string; hint: string; account?: string }> = {
  github: { name: "GitHub", hint: "Personal access token (repo, read:org)" },
  hubspot: { name: "HubSpot", hint: "Private-app access token" },
  stripe: { name: "Stripe", hint: "Restricted/secret key (read)" },
  gmail: { name: "Gmail", hint: "App password (16 chars, 2FA required)", account: "you@gmail.com" },
};

export default function ConnectionsPage() {
  const [status, setStatus] = useState<ConnectStatus | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [tokens, setTokens] = useState<Record<string, string>>({});
  const [accounts, setAccounts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState<Record<string, string>>({});
  const [err, setErr] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    try {
      setStatus(await vigil.connect.status());
      setAuthError(null);
    } catch (e) {
      if (e instanceof GatewayError && e.code === "NO_SESSION") setAuthError("Sign in to connect your systems.");
      else setAuthError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot load on mount
    void refresh();
  }, [refresh]);

  const note = (k: string, m: string, e = "") => {
    setMsg((s) => ({ ...s, [k]: m }));
    setErr((s) => ({ ...s, [k]: e }));
  };

  const connect = async (provider: string) => {
    const token = (tokens[provider] || "").trim();
    if (!token) return;
    setBusy(provider + ":connect");
    try {
      const { connection } = await vigil.connect.token(provider, token, (accounts[provider] || "").trim() || undefined);
      setTokens((t) => ({ ...t, [provider]: "" }));
      setAccounts((a) => ({ ...a, [provider]: "" }));
      note(provider, `Connected ${connection.external_account || provider}.`);
      await refresh();
    } catch (e) {
      note(provider, "", (e as Error).message);
    } finally {
      setBusy("");
    }
  };

  const sync = async (c: Connection) => {
    setBusy(c.id + ":sync");
    try {
      const r = await vigil.connect.sync(c.provider, c.id);
      const counts = Object.entries(r).filter(([, v]) => typeof v === "number").map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`).join(", ");
      note(c.provider, `Synced: ${counts || "ok"}.`);
      await refresh();
    } catch (e) {
      note(c.provider, "", (e as Error).message);
    } finally {
      setBusy("");
    }
  };

  const disconnect = async (c: Connection) => {
    setBusy(c.id + ":dc");
    try {
      await vigil.connect.disconnect(c.id);
      note(c.provider, "Disconnected.");
      await refresh();
    } finally {
      setBusy("");
    }
  };

  const inputCls = "flex-1 rounded-md border border-current/20 bg-transparent px-3 py-2 text-sm outline-none focus:border-current/50";

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-bold tracking-tight">Connections</h1>
        <p className="text-sm text-text-secondary">
          Link your systems of record. Tokens are encrypted at rest and never shown again; your departments sync and work the live data.
        </p>
      </header>

      {authError && <Card><CardContent className="py-4 text-sm" style={{ color: "#f59e0b" }}>{authError}</CardContent></Card>}

      <div className="grid gap-4 md:grid-cols-2">
        {status?.providers.map((p) => {
          const label = PROVIDER_LABEL[p.id] || { name: p.id, hint: "API token" };
          const conns = status.connections.filter((c) => c.provider === p.id);
          return (
            <Card key={p.id}>
              <CardHeader>
                <CardTitle className="flex items-center justify-between gap-2">
                  <span className="capitalize">{label.name}</span>
                  <span className="text-[10px] uppercase tracking-wide text-text-secondary">{p.kind}</span>
                </CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                {conns.map((c) => (
                  <div key={c.id} className="flex items-center gap-2 rounded-md border border-current/10 px-3 py-2 text-sm">
                    <span className="flex-1 truncate">
                      {c.external_account || c.provider} · <span className="text-text-secondary">{c.token_masked}</span>
                      {c.last_synced_at && <span className="text-text-secondary"> · synced {new Date(c.last_synced_at).toLocaleDateString()}</span>}
                    </span>
                    <span className="text-[10px] uppercase" style={{ color: c.status === "active" ? "#059669" : "#ef4444" }}>{c.status}</span>
                    <button type="button" className="text-xs text-text-secondary hover:text-foreground" disabled={!!busy} onClick={() => void sync(c)}>{busy === c.id + ":sync" ? "…" : "Sync"}</button>
                    <button type="button" className="text-xs text-text-secondary hover:text-foreground" disabled={!!busy} onClick={() => void disconnect(c)}>✕</button>
                  </div>
                ))}
                <div className="flex flex-col gap-2">
                  {label.account && (
                    <input
                      type="email"
                      className={inputCls}
                      placeholder={label.account}
                      value={accounts[p.id] || ""}
                      onChange={(e) => setAccounts((a) => ({ ...a, [p.id]: e.target.value }))}
                    />
                  )}
                  <div className="flex gap-2">
                    <input
                      type="password"
                      className={inputCls}
                      placeholder={label.hint}
                      value={tokens[p.id] || ""}
                      onChange={(e) => setTokens((t) => ({ ...t, [p.id]: e.target.value }))}
                      onKeyDown={(e) => { if (e.key === "Enter") void connect(p.id); }}
                    />
                    <Button disabled={busy === p.id + ":connect" || !(tokens[p.id] || "").trim() || (!!label.account && !(accounts[p.id] || "").trim())} onClick={() => void connect(p.id)}>
                      {busy === p.id + ":connect" ? "Connecting…" : "Connect"}
                    </Button>
                  </div>
                </div>
                {msg[p.id] && <p className="text-xs" style={{ color: "#059669" }}>{msg[p.id]}</p>}
                {err[p.id] && <p className="text-xs" style={{ color: "#ff3366" }}>{err[p.id]}</p>}
              </CardContent>
            </Card>
          );
        })}
        {!status && !authError && <Card><CardContent className="py-6 text-center text-sm text-text-secondary">Loading providers…</CardContent></Card>}
      </div>
    </div>
  );
}
