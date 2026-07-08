import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Button } from "@nous-research/ui/ui/components/button";
import { billing, type BillingInfo, type BillingTier } from "@/lib/vigil";
import { GatewayError } from "@/lib/ww";

// Billing — plan, usage, and self-serve upgrades. Checkout runs on Stripe
// (gateway /v1/billing/checkout → redirect); the webhook provisions the org's
// subscription row, which is what tenant_plan() gates quotas/features on.

const GOLD = "#ffbd38";
const EMER = "#34d399";

function eur(cents: number): string {
  return cents === 0 ? "€0" : `€${(cents / 100).toFixed(0)}`;
}

function TierCard({
  tier,
  current,
  busy,
  onBuy,
}: {
  tier: BillingTier;
  current: boolean;
  busy: boolean;
  onBuy: (id: string) => void;
}) {
  const highlight = tier.id === "pro";
  return (
    <Card
      className="flex min-w-0 flex-1 flex-col"
      style={current ? { borderColor: EMER } : highlight ? { borderColor: GOLD } : undefined}
    >
      <CardHeader className="pb-2">
        <CardTitle className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-base">
          <span className="truncate">{tier.name}</span>
          <span className="shrink-0 whitespace-nowrap" style={{ color: highlight ? GOLD : undefined }}>
            {tier.contact_sales ? "Custom" : `${eur(tier.price_eur_cents)}/mo`}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-1 text-sm">
        <ul className="flex-1 space-y-1 text-muted-foreground">
          <li>{tier.ops_runs_per_day == null ? "Unlimited" : tier.ops_runs_per_day} agent runs/day</li>
          <li>{tier.max_connectors == null ? "Unlimited" : tier.max_connectors} connector{tier.max_connectors === 1 ? "" : "s"}</li>
          <li>{tier.departments} AI departments</li>
          <li>{tier.write_actions ? "✓ Outbound write-actions" : "— Read-only connectors"}</li>
          <li>{tier.byok ? "✓ Bring your own keys" : "— Managed models only"}</li>
        </ul>
        {current ? (
          <div className="mt-3 text-center text-xs font-semibold" style={{ color: EMER }}>
            Current plan
          </div>
        ) : tier.contact_sales ? (
          <Button
            outlined
            className="mt-3"
            onClick={() => {
              window.location.href = "mailto:sales@vigil-ai.xyz?subject=VIGIL%20Enterprise";
            }}
          >
            Contact sales
          </Button>
        ) : tier.purchasable ? (
          <Button
            className="mt-3"
            disabled={busy}
            onClick={() => onBuy(tier.id)}
            style={highlight ? { background: GOLD, color: "#041c1c" } : undefined}
          >
            {busy ? "Redirecting…" : `Upgrade to ${tier.name}`}
          </Button>
        ) : tier.id === "free" ? null : (
          <div className="mt-3 text-center text-xs text-muted-foreground">Not yet available</div>
        )}
      </CardContent>
    </Card>
  );
}

export default function BillingPage() {
  const [params] = useSearchParams();
  const checkoutResult = params.get("checkout"); // success | cancelled
  const [info, setInfo] = useState<BillingInfo | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busyTier, setBusyTier] = useState("");
  const [portalBusy, setPortalBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setInfo(await billing.info());
      setErr(null);
    } catch (e) {
      if (e instanceof GatewayError && e.code === "NO_SESSION") setErr("Sign in to manage billing.");
      else setErr((e as Error).message);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot load on mount
    void refresh();
  }, [refresh]);

  const buy = async (tierId: string) => {
    setBusyTier(tierId);
    setErr(null);
    try {
      const { url } = await billing.checkout(tierId);
      window.location.assign(url);
    } catch (e) {
      setErr((e as Error).message);
      setBusyTier("");
    }
  };

  const openPortal = async () => {
    setPortalBusy(true);
    setErr(null);
    try {
      const { url } = await billing.portal();
      window.location.assign(url);
    } catch (e) {
      setErr((e as Error).message);
      setPortalBusy(false);
    }
  };

  const usage = info?.usage;
  const sub = info?.subscription;
  const cancelPending = Boolean(sub?.metadata?.cancel_at_period_end);

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <div>
        <h1 className="text-xl font-semibold">Billing</h1>
        <p className="text-sm text-muted-foreground">
          Plan, usage and upgrades{info?.org?.name ? ` — ${info.org.name}` : ""}
        </p>
      </div>

      {checkoutResult === "success" && (
        <div className="rounded-md border px-3 py-2 text-sm" style={{ borderColor: EMER, color: EMER }}>
          Payment received — your plan updates as soon as Stripe confirms (usually seconds). Refresh if it hasn't.
        </div>
      )}
      {checkoutResult === "cancelled" && (
        <div className="rounded-md border px-3 py-2 text-sm text-muted-foreground">
          Checkout cancelled — no charge was made.
        </div>
      )}
      {err && (
        <div className="rounded-md border border-destructive px-3 py-2 text-sm text-destructive">{err}</div>
      )}

      {info && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">
              Current plan: <span style={{ color: GOLD }}>{info.limits?.name as string}</span>
              {sub?.status && sub.status !== "active" && (
                <span className="ml-2 text-xs text-muted-foreground">({sub.status})</span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-x-8 gap-y-2 text-sm">
            {usage && (
              <>
                <span>
                  Runs today: <b>{usage.runs_today}</b>
                  {usage.daily_cap != null && <span className="text-muted-foreground"> / {usage.daily_cap}</span>}
                </span>
                <span>
                  This month: <b>{usage.runs_month}</b> runs · ${usage.cost_usd_month.toFixed(2)} model cost
                </span>
              </>
            )}
            {cancelPending && sub?.current_period_end && (
              <span className="text-muted-foreground">
                Cancels {new Date(sub.current_period_end).toLocaleDateString()}
              </span>
            )}
            {sub && (
              <Button outlined size="sm" disabled={portalBusy} onClick={() => void openPortal()}>
                {portalBusy ? "Opening…" : "Manage subscription"}
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      {info && !info.stripe_configured && (
        <div className="rounded-md border px-3 py-2 text-xs text-muted-foreground">
          Payments are not configured on this environment yet — upgrades are in dev-mock mode.
        </div>
      )}

      {/* auto-fit keeps every card in-frame at any width instead of forcing 5 columns */}
      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))" }}>
        {info?.tiers.map((t) => (
          <TierCard
            key={t.id}
            tier={t}
            current={t.id === info.plan}
            busy={busyTier === t.id}
            onBuy={(id) => void buy(id)}
          />
        ))}
      </div>

      <p className="text-xs text-muted-foreground">
        Prices in EUR, billed monthly via Stripe. VAT handled at checkout. Enterprise includes custom
        quotas, SSO and a dedicated instance — talk to us.
      </p>
    </div>
  );
}
