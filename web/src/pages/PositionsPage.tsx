import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { ww } from "@/lib/ww";
import { useWwPoll } from "@/lib/useWw";
import { WwGate } from "./scaffold";

const n = (v?: string) => (v == null || v === "" ? "—" : v);
const pnlColor = (v?: string) => {
  const x = Number(v ?? 0);
  return x > 0 ? "#00ff88" : x < 0 ? "#ff3366" : "#94a3b8";
};

export default function PositionsPage() {
  const state = useWwPoll(() => ww.broker.snapshot(), 6000);
  const snap = state.data;
  const positions = snap?.positions ?? [];
  const balances = snap?.balances ?? [];

  return (
    <div className="flex flex-col gap-6">
      <WwGate state={state}>
        <Card>
          <CardHeader>
            <CardTitle>
              Desk{snap?.broker ? ` · ${snap.broker}` : ""} — NAV ${n(snap?.nav_estimate)}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {!snap?.connected ? (
              <p className="text-text-secondary text-sm py-6 text-center">
                No broker connected — add keys in Settings.
              </p>
            ) : positions.length === 0 ? (
              <p className="text-text-secondary text-sm py-6 text-center">No open positions.</p>
            ) : (
              <table className="w-full text-sm font-mono">
                <thead className="text-[10px] uppercase tracking-wide text-text-secondary">
                  <tr className="text-left">
                    <th className="py-1">Symbol</th>
                    <th>Side</th>
                    <th className="text-right">Qty</th>
                    <th className="text-right">Entry</th>
                    <th className="text-right">uP&L</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p, i) => (
                    <tr key={i} className="border-t border-current/10">
                      <td className="py-1.5 text-foreground/90">{n(p.symbol)}</td>
                      <td style={{ color: pnlColor(p.side === "short" ? "-1" : "1") }}>{n(p.side)}</td>
                      <td className="text-right">{n(p.contracts)}</td>
                      <td className="text-right">{n(p.entry_price)}</td>
                      <td className="text-right" style={{ color: pnlColor(p.unrealized_pnl) }}>
                        {n(p.unrealized_pnl)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Balances</CardTitle>
          </CardHeader>
          <CardContent>
            {balances.length === 0 ? (
              <p className="text-text-secondary text-sm py-6 text-center">No balances.</p>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 font-mono text-sm">
                {balances.map((b, i) => (
                  <div key={i} className="flex flex-col">
                    <span className="text-[10px] uppercase tracking-wide text-text-secondary">{b.currency}</span>
                    <span className="text-foreground/85">{n(b.total)}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </WwGate>
    </div>
  );
}
