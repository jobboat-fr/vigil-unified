import { useEffect, useRef, useState } from "react";
import * as Plot from "@observablehq/plot";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { ww, type Candle } from "@/lib/ww";
import { useWwPoll } from "@/lib/useWw";

const SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT"];
const UP = "#00ff88";
const DOWN = "#ff3366";

const usd = (n?: number) => {
  if (n == null) return "—";
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(1)}K`;
  return `$${n.toFixed(2)}`;
};
const num = (n?: number) => (n == null ? "—" : Number(n).toPrecision(6).replace(/\.?0+$/, ""));

function Candles({ candles }: { candles: Candle[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || candles.length === 0) return;
    const data = candles.map((c) => ({ ...c, date: new Date(c.t * 1000) }));
    const width = ref.current.clientWidth || 800;
    const chart = Plot.plot({
      width,
      height: 380,
      marginLeft: 56,
      x: { type: "utc", label: null, ticks: 6 },
      y: { grid: true, label: null },
      marks: [
        Plot.ruleX(data, {
          x: "date",
          y1: "l",
          y2: "h",
          stroke: (d: Candle) => (d.c >= d.o ? UP : DOWN),
          strokeWidth: 1,
        }),
        Plot.ruleX(data, {
          x: "date",
          y1: "o",
          y2: "c",
          stroke: (d: Candle) => (d.c >= d.o ? UP : DOWN),
          strokeWidth: 4,
        }),
      ],
      style: { background: "transparent", color: "rgba(255,255,255,0.65)" },
    });
    ref.current.append(chart);
    return () => chart.remove();
  }, [candles]);
  return <div ref={ref} className="w-full" />;
}

function Metric({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[9px] uppercase tracking-wide text-text-secondary">{label}</span>
      <span className="text-sm font-mono" style={{ color: color ?? undefined }}>{value}</span>
    </div>
  );
}

export default function TradeDeskPage() {
  const [symbol, setSymbol] = useState(SYMBOLS[0]);
  const ohlcv = useWwPoll(() => ww.market.ohlcv(symbol, "hour", 168), 30000);
  const enrich = useWwPoll(() => ww.market.enrich(symbol), 15000);

  const candles = ohlcv.data?.candles ?? [];
  const e = enrich.data;
  const cons = e?.consensus;
  const last = candles.length ? candles[candles.length - 1].c : cons?.price;
  const chg = e?.change_24h_pct;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {SYMBOLS.map((s) => (
          <button
            key={s}
            onClick={() => setSymbol(s)}
            className="px-3 py-1 rounded text-xs font-mono border border-current/20"
            style={
              s === symbol
                ? { background: "rgba(56,189,248,0.15)", color: "#38bdf8" }
                : { color: "rgba(255,255,255,0.6)" }
            }
          >
            {s}
          </button>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            {symbol} — {num(last)}{" "}
            {chg != null ? (
              <span style={{ color: chg >= 0 ? UP : DOWN }}>
                {chg >= 0 ? "+" : ""}
                {chg.toFixed(2)}%
              </span>
            ) : null}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {ohlcv.loading && candles.length === 0 ? (
            <p className="text-text-secondary text-sm py-16 text-center">Loading chart…</p>
          ) : candles.length === 0 ? (
            <p className="text-text-secondary text-sm py-16 text-center">No price data for {symbol}.</p>
          ) : (
            <Candles candles={candles} />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Live market — cross-source</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
            <Metric label="Consensus" value={num(cons?.price)} />
            <Metric label="Spread" value={cons?.spread_pct != null ? `${cons.spread_pct.toFixed(2)}%` : "—"} />
            <Metric label="Sources" value={cons?.n_sources != null ? String(cons.n_sources) : "—"} />
            <Metric label="Vol 24h" value={usd(e?.volume_24h_usd)} />
            <Metric label="Mkt cap" value={usd(e?.market_cap_usd)} />
            <Metric
              label="F&G"
              value={e?.fear_greed ? `${e.fear_greed.value} ${e.fear_greed.label}` : "—"}
            />
          </div>
          {e?.sources ? (
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
              {Object.entries(e.sources).map(([name, v]) => (
                <span key={name} className="text-[11px] font-mono text-text-secondary">
                  {name}: <span className="text-foreground/80">{num(v?.price)}</span>
                </span>
              ))}
            </div>
          ) : null}
          <p className="mt-3 text-xs text-text-secondary">
            Ask the agent in chat for a forecast or to propose a trade — orders route through the
            approval gate under the §1.3 5%-NAV cap.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
