import { useState } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { ww, type SignalRow, type DebatePoint } from "@/lib/ww";
import { useWwPoll } from "@/lib/useWw";
import { WwGate } from "./scaffold";

const sideColor = (s?: string) => {
  const v = (s || "").toLowerCase();
  if (v === "long" || v === "buy") return "#00ff88";
  if (v === "short" || v === "sell") return "#ff3366";
  return "#94a3b8";
};
const pct = (n?: number) =>
  n == null ? "—" : `${Math.round((Math.abs(n) <= 1 ? n * 100 : n))}%`;
const num = (n?: number) => (n == null ? "—" : Number(n).toPrecision(6).replace(/\.?0+$/, ""));
const usd = (n?: number) => {
  if (n == null) return "—";
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(1)}K`;
  return `$${n.toFixed(2)}`;
};

function latestBySymbol(rows: SignalRow[], src: string): SignalRow[] {
  const seen = new Map<string, SignalRow>();
  for (const r of rows) {
    if (r.source !== src || !r.symbol) continue;
    if (!seen.has(r.symbol)) seen.set(r.symbol, r);
  }
  return [...seen.values()];
}

function DebateCol({ title, color, points }: { title: string; color: string; points?: DebatePoint[] }) {
  if (!points?.length) return null;
  return (
    <div>
      <div className="text-[10px] font-mono uppercase tracking-wide mb-1" style={{ color }}>
        {title} · {points.length}
      </div>
      <ul className="space-y-1">
        {points.map((p, i) => (
          <li key={i} className="text-xs leading-snug">
            <span className="text-foreground/85">{p.point}</span>
            {p.evidence ? <span className="text-text-secondary"> — {p.evidence}</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function SignalCard({ row }: { row: SignalRow }) {
  const [open, setOpen] = useState(false);
  const d = row.data || {};
  const debate = d.debate;
  const enr = (d.enrichment || {}) as Record<string, number | undefined> & {
    consensus?: { price?: number; n_sources?: number; spread_pct?: number };
    fear_greed?: { value?: number; label?: string };
  };
  const ind = row.indicators || {};
  const cons = enr.consensus;

  return (
    <li className="rounded-lg border border-current/15 p-3">
      <button onClick={() => setOpen((o) => !o)} className="w-full flex items-center justify-between gap-2 text-left">
        <span className="font-mono font-bold text-foreground/90">{row.symbol || "—"}</span>
        <span className="flex items-center gap-2">
          <span
            className="font-mono text-[10px] px-2 py-0.5 rounded"
            style={{
              color: sideColor(row.side || debate?.verdict),
              background: `${sideColor(row.side || debate?.verdict)}1a`,
            }}
          >
            {(row.side || debate?.verdict || "—").toUpperCase()} · {pct(row.confidence ?? debate?.conviction)}
          </span>
          <span className="text-text-secondary text-[10px]">{open ? "▾" : "▸"}</span>
        </span>
      </button>

      <div className="grid grid-cols-4 gap-2 mt-2">
        <Metric label="Entry" value={num(row.entry ?? ind.x_consensus_price)} />
        <Metric label="24h" value={ind.x_change_24h_pct != null ? `${Number(ind.x_change_24h_pct).toFixed(1)}%` : "—"} />
        <Metric label="RSI" value={ind.rsi14 != null ? Number(ind.rsi14).toFixed(0) : "—"} />
        <Metric label="Spread" value={cons?.spread_pct != null ? `${cons.spread_pct.toFixed(2)}%` : "—"} />
      </div>

      {debate?.summary ? <p className="mt-2 text-xs text-text-secondary italic">{debate.summary}</p> : null}

      {open && (
        <div className="mt-3 pt-3 border-t border-current/10 space-y-3">
          {debate && (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <DebateCol title="Bull" color="#00ff88" points={debate.bull} />
              <DebateCol title="Bear" color="#ff3366" points={debate.bear} />
              <DebateCol title="Risk" color="#f59e0b" points={debate.risk} />
            </div>
          )}
          <div>
            <div className="text-[10px] font-mono uppercase tracking-wide text-text-secondary mb-1">Data used</div>
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
              <Metric label="Consensus" value={num(cons?.price)} />
              <Metric label="Sources" value={cons?.n_sources != null ? String(cons.n_sources) : "—"} />
              <Metric label="Vol 24h" value={usd(enr.volume_24h_usd)} />
              <Metric label="Mkt cap" value={usd(enr.market_cap_usd)} />
              <Metric label="BTC dom" value={enr.btc_dominance_pct != null ? `${Number(enr.btc_dominance_pct).toFixed(1)}%` : "—"} />
              <Metric label="F&G" value={enr.fear_greed ? `${enr.fear_greed.value} ${enr.fear_greed.label}` : "—"} />
            </div>
          </div>
        </div>
      )}
    </li>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[9px] uppercase tracking-wide text-text-secondary">{label}</span>
      <span className="text-xs font-mono text-foreground/85">{value}</span>
    </div>
  );
}

export default function SignalsPage() {
  const state = useWwPoll(() => ww.signals.live(100), 6000);
  const rows = state.data ?? [];
  const forecasts = latestBySymbol(rows, "forecaster");
  const analyses = latestBySymbol(rows, "analyst");

  return (
    <div className="flex flex-col gap-6">
      <WwGate state={state}>
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Forecasts · {forecasts.length}</CardTitle>
            </CardHeader>
            <CardContent>
              {forecasts.length === 0 ? (
                <p className="text-text-secondary text-sm py-6 text-center">No forecasts yet.</p>
              ) : (
                <ul className="space-y-2 max-h-[68vh] overflow-y-auto pr-1">
                  {forecasts.map((f) => (
                    <SignalCard key={`f:${f.symbol}`} row={f} />
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Analyst Debate · {analyses.length}</CardTitle>
            </CardHeader>
            <CardContent>
              {analyses.length === 0 ? (
                <p className="text-text-secondary text-sm py-6 text-center">No analyst decisions yet.</p>
              ) : (
                <ul className="space-y-2 max-h-[68vh] overflow-y-auto pr-1">
                  {analyses.map((d) => (
                    <SignalCard key={`a:${d.symbol}`} row={d} />
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>
      </WwGate>
    </div>
  );
}
