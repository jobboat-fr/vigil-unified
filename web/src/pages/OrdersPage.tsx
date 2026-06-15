import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { ww } from "@/lib/ww";
import { useWwPoll } from "@/lib/useWw";
import { WwGate } from "./scaffold";

const n = (v?: string | number | null) => (v == null || v === "" ? "—" : String(v));

interface Trade {
  symbol?: string; side?: string; amount?: string | number; price?: string | number;
  datetime?: string; status?: string;
}

export default function OrdersPage() {
  const state = useWwPoll(() => ww.broker.snapshot(), 6000);
  const trades = useWwPoll(() => ww.broker.trades(50) as Promise<Trade[]>, 15000);
  const openOrders = state.data?.open_orders ?? [];
  const history = Array.isArray(trades.data) ? trades.data : [];

  return (
    <div className="flex flex-col gap-6">
      <WwGate state={state}>
        <Card>
          <CardHeader>
            <CardTitle>Open Orders · {openOrders.length}</CardTitle>
          </CardHeader>
          <CardContent>
            {openOrders.length === 0 ? (
              <p className="text-text-secondary text-sm py-6 text-center">No open orders.</p>
            ) : (
              <table className="w-full text-sm font-mono">
                <thead className="text-[10px] uppercase tracking-wide text-text-secondary text-left">
                  <tr>
                    <th className="py-1">Symbol</th><th>Side</th><th>Type</th>
                    <th className="text-right">Qty</th><th className="text-right">Price</th><th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {openOrders.map((o, i) => (
                    <tr key={i} className="border-t border-current/10">
                      <td className="py-1.5 text-foreground/90">{n(o.symbol)}</td>
                      <td>{n(o.side)}</td><td>{n(o.type)}</td>
                      <td className="text-right">{n(o.amount)}</td>
                      <td className="text-right">{n(o.price)}</td>
                      <td>{n(o.status)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Fill History · {history.length}</CardTitle>
          </CardHeader>
          <CardContent>
            {history.length === 0 ? (
              <p className="text-text-secondary text-sm py-6 text-center">No recent fills.</p>
            ) : (
              <table className="w-full text-sm font-mono">
                <thead className="text-[10px] uppercase tracking-wide text-text-secondary text-left">
                  <tr>
                    <th className="py-1">Time</th><th>Symbol</th><th>Side</th>
                    <th className="text-right">Qty</th><th className="text-right">Price</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((t, i) => (
                    <tr key={i} className="border-t border-current/10">
                      <td className="py-1.5">{t.datetime ? new Date(t.datetime).toLocaleString() : "—"}</td>
                      <td className="text-foreground/90">{n(t.symbol)}</td>
                      <td>{n(t.side)}</td>
                      <td className="text-right">{n(t.amount)}</td>
                      <td className="text-right">{n(t.price)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      </WwGate>
    </div>
  );
}
