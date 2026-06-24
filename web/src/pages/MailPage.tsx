import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Button } from "@nous-research/ui/ui/components/button";
import { vigil, MAIL_CATEGORIES, type MailMessage, type MailTriageSummary } from "@/lib/vigil";
import { GatewayError } from "@/lib/ww";
import { EmptyState } from "@/components/EmptyState";

const CAT_COLOR: Record<string, string> = {
  urgent: "#ef4444", respond: "#f59e0b", fyi: "#3b82f6",
  newsletter: "#8b5cf6", spam: "#6b7280", archive: "#10b981",
};

export default function MailPage() {
  const [summary, setSummary] = useState<MailTriageSummary | null>(null);
  const [messages, setMessages] = useState<MailMessage[]>([]);
  const [authError, setAuthError] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncNote, setSyncNote] = useState<string | null>(null);
  const [triaging, setTriaging] = useState<string | null>(null);

  // manual ingest
  const [from, setFrom] = useState("");
  const [subject, setSubject] = useState("");
  const [snippet, setSnippet] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [s, m] = await Promise.all([vigil.mail.summary(), vigil.mail.messages({ limit: 100 })]);
      setSummary(s);
      setMessages(m.messages);
      setAuthError(null);
    } catch (e) {
      if (e instanceof GatewayError && e.code === "NO_SESSION") setAuthError("Sign in to VIGIL to use Mail.");
      else setErr((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const sync = async () => {
    setSyncing(true);
    setSyncNote(null);
    try {
      const r = await vigil.mail.sync();
      setSyncNote(r.available ? `Synced ${r.synced}/${r.fetched} from himalaya.` : `Mailbox transport unavailable (${r.reason}). Use manual ingest below.`);
      await refresh();
    } catch (e) {
      setSyncNote((e as Error).message);
    } finally {
      setSyncing(false);
    }
  };

  const triage = async (id: string) => {
    setTriaging(id);
    try {
      await vigil.mail.triage(id);
      await refresh();
    } catch (e) { setErr((e as Error).message); }
    finally { setTriaging(null); }
  };

  const setCategory = async (id: string, category: string) => {
    await vigil.mail.update(id, { category });
    await refresh();
  };

  const remove = async (id: string) => { await vigil.mail.remove(id); await refresh(); };

  const ingest = async () => {
    if (!subject.trim() && !from.trim()) return;
    setErr(null);
    try {
      await vigil.mail.ingest({
        from_addr: from.trim() || undefined,
        subject: subject.trim() || undefined,
        snippet: snippet.trim() || undefined,
        received_at: new Date().toISOString(),
      });
      setFrom(""); setSubject(""); setSnippet("");
      await refresh();
    } catch (e) { setErr((e as Error).message); }
  };

  const inputCls = "w-full rounded-md border border-current/20 bg-transparent px-3 py-2 text-sm outline-none focus:border-current/50";

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <header className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-bold tracking-tight">Mail</h1>
          <p className="text-sm text-text-secondary">Inbox triage over the himalaya transport. Outbound is review-then-send — never auto-sent.</p>
        </div>
        <Button onClick={() => void sync()} disabled={syncing}>{syncing ? "Syncing…" : "Sync mailbox"}</Button>
      </header>

      {authError && <Card><CardContent className="py-4 text-sm" style={{ color: "#f59e0b" }}>{authError}</CardContent></Card>}
      {syncNote && <Card><CardContent className="py-3 text-xs text-text-secondary">{syncNote}</CardContent></Card>}

      {summary && (
        <div className="grid grid-cols-3 gap-3 md:grid-cols-6">
          <Stat label="Total" value={String(summary.total)} />
          <Stat label="Unread" value={String(summary.unread)} color="#f59e0b" />
          <Stat label="Triaged" value={`${summary.triaged}/${summary.total}`} />
          {(["urgent", "respond", "fyi"] as const).map((c) => (
            <Stat key={c} label={c} value={String(summary.by_category[c] ?? 0)} color={CAT_COLOR[c]} />
          ))}
        </div>
      )}

      <Card>
        <CardHeader><CardTitle>Manual ingest</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-2 sm:flex-row">
          <input className={inputCls} placeholder="From" value={from} onChange={(e) => setFrom(e.target.value)} />
          <input className={inputCls} placeholder="Subject" value={subject} onChange={(e) => setSubject(e.target.value)} />
          <input className={inputCls} placeholder="Snippet" value={snippet} onChange={(e) => setSnippet(e.target.value)} />
          <Button onClick={() => void ingest()}>Add</Button>
        </CardContent>
      </Card>
      {err && <p className="text-xs" style={{ color: "#ff3366" }}>{err}</p>}

      <Card>
        <CardHeader><CardTitle>Inbox</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-1">
          {messages.length === 0 && <EmptyState title="No messages yet" hint="Connect Gmail on the Connections page, or ingest a mailbox above, then triage your inbox." />}
          {messages.map((m) => (
            <div key={m.id} className="flex items-center gap-3 rounded-md border border-current/10 px-3 py-2">
              <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: m.status === "unread" ? "#f59e0b" : "transparent", border: "1px solid currentColor" }} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium">{m.subject || "(no subject)"}</span>
                  {m.category && <span className="rounded px-1.5 py-0.5 text-[10px] uppercase" style={{ color: CAT_COLOR[m.category], border: `1px solid ${CAT_COLOR[m.category]}` }}>{m.category}</span>}
                  {m.priority === "high" && <span className="text-[10px] font-bold" style={{ color: "#ef4444" }}>HIGH</span>}
                </div>
                <span className="text-xs text-text-secondary">{m.from_name || m.from_addr || "unknown"}</span>
              </div>
              <select
                className="rounded border border-current/20 bg-transparent px-1 py-0.5 text-[10px]"
                value={m.category ?? ""}
                onChange={(e) => void setCategory(m.id, e.target.value)}
              >
                <option value="" disabled>category…</option>
                {MAIL_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <Button ghost className="text-xs" disabled={triaging === m.id} onClick={() => void triage(m.id)}>{triaging === m.id ? "…" : "AI triage"}</Button>
              <button type="button" onClick={() => void remove(m.id)} className="text-xs text-text-secondary hover:text-foreground">✕</button>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <Card>
      <CardContent className="py-3">
        <div className="text-[11px] uppercase tracking-wide capitalize text-text-secondary">{label}</div>
        <div className="text-lg font-bold tabular-nums" style={color ? { color } : undefined}>{value}</div>
      </CardContent>
    </Card>
  );
}
