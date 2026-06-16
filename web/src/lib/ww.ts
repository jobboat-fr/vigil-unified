// WinnyWoo gateway client for the VIGIL × WinnyWoo product pages.
//
// Talks to the FastAPI gateway (signals, broker, audit, vault, market). All
// /api/v1/* responses are { ok, data }; `call` unwraps to `data`. Auth is the
// Supabase JWT both products share. A missing session or a network failure
// throws a GatewayError with `code` so pages render an offline / sign-in state
// instead of crashing.
import { getAccessToken } from "./supabase";

// Full native port (UNIFIED_PORT_PLAN): the WinnyWoo gateway is vendored into
// vigil-unified (winny_gateway) and runs locally on :8400 — no Railway. An
// explicit VITE_WW_GATEWAY_URL always wins (for a hosted deploy); otherwise we
// default to the local gateway in every environment.
const LOCAL_DEFAULT = "http://127.0.0.1:8400";

function resolveBase(): string {
  const configured = (import.meta.env.VITE_WW_GATEWAY_URL as string | undefined)?.trim();
  if (configured) return configured.replace(/\/$/, "");
  return LOCAL_DEFAULT;
}

export const WW_BASE = resolveBase();

export class GatewayError extends Error {
  code: string;
  status?: number;
  constructor(message: string, code: string, status?: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

async function call<T = unknown>(
  method: string,
  path: string,
  body?: unknown,
  opts?: { public?: boolean },
): Promise<T> {
  const token = await getAccessToken();
  if (!token && !opts?.public) {
    throw new GatewayError("not signed in to VIGIL", "NO_SESSION");
  }
  const headers: Record<string, string> = {
    "content-type": "application/json",
    accept: "application/json",
  };
  if (token) headers.authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${WW_BASE}${path}`, {
      method,
      headers,
      body: body != null ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new GatewayError(`gateway unreachable: ${(e as Error).message}`, "UNREACHABLE");
  }
  let payload: { ok?: boolean; data?: unknown; error?: string };
  try {
    payload = await res.json();
  } catch {
    payload = { ok: false, error: "BAD_JSON" };
  }
  if (!res.ok || payload.ok === false) {
    throw new GatewayError(payload.error || `HTTP ${res.status}`, "HTTP_ERROR", res.status);
  }
  return payload.data as T;
}

// ── Signal shapes (mirror gateway/routes/signals.py) ────────────────────────
export interface DebatePoint { point: string; evidence?: string }
export interface SignalRow {
  id?: string; ts?: string; symbol?: string; source?: string;
  side?: string; confidence?: number;
  entry?: number; stop?: number; target?: number;
  indicators?: Record<string, number>;
  thesis?: string;
  data?: {
    debate?: { bull?: DebatePoint[]; bear?: DebatePoint[]; risk?: DebatePoint[]; summary?: string; verdict?: string; conviction?: number; method?: string };
    enrichment?: Record<string, unknown>;
  };
}

export interface BrokerSnapshot {
  connected?: boolean; broker?: string;
  balances?: { currency: string; total: string; free?: string; used?: string }[];
  positions?: { symbol?: string; side?: string; contracts?: string; entry_price?: string; unrealized_pnl?: string }[];
  open_orders?: { id?: string; symbol?: string; side?: string; type?: string; amount?: string; price?: string | null; filled?: string; status?: string; datetime?: string }[];
  nav_estimate?: string;
}

export interface AuditEvent {
  id?: string; ts?: string; event_type?: string; action?: string;
  component?: string; decision_id?: string; critical?: boolean;
  actor_email?: string; payload?: Record<string, unknown>;
}

export const ww = {
  health: () => call("GET", "/health"),
  signals: {
    live: (limit = 50) => call<SignalRow[]>("GET", `/api/v1/signals/live?limit=${limit}`),
    risk: () => call("GET", "/api/v1/signals/risk"),
  },
  broker: {
    snapshot: () => call<BrokerSnapshot>("GET", "/api/v1/broker/snapshot"),
    openOrders: () => call("GET", "/api/v1/broker/open-orders"),
    trades: (limit = 50) => call("GET", `/api/v1/broker/trades?limit=${limit}`),
    ticker: (symbol: string) => call("GET", `/api/v1/broker/ticker/${encodeURIComponent(symbol)}`),
  },
  audit: {
    events: (limit = 100) => call<AuditEvent[]>("GET", `/api/v1/audit/events?limit=${limit}`),
    verify: () => call("GET", "/api/v1/audit/verify"),
  },
  vault: {
    list: () => call("GET", "/v1/vault/documents"),
    search: (q: string) => call("GET", `/v1/vault/search?q=${encodeURIComponent(q)}`),
  },
  market: {
    overview: () => call<MarketOverview>("GET", "/api/v1/market/overview", undefined, { public: true }),
    // Normalise the pair separator to "-" so the path never carries an encoded
    // slash (%2F) — proxies decode it to "/", adding a path segment that 404s
    // the single-segment route. The gateway's _split_symbol maps "-" back.
    enrich: (symbol: string) =>
      call<EnrichData>("GET", `/api/v1/market/enrich/${encodeURIComponent(symbol.replace(/\//g, "-"))}`, undefined, { public: true }),
    ohlcv: (symbol: string, timeframe: "hour" | "minute" | "day" = "hour", limit = 168) =>
      call<OhlcvData>(
        "GET",
        `/api/v1/market/ohlcv/${encodeURIComponent(symbol.replace(/\//g, "-"))}?timeframe=${timeframe}&limit=${limit}`,
        undefined,
        { public: true },
      ),
  },
};

export interface MarketOverview {
  btc_price?: string;
  btc_24h_change?: string;
  eth_price?: string;
  eth_24h_change?: string;
  btc_dominance_pct?: number;
  btc_market_cap_usd?: number;
  fear_greed_index?: number;
  fear_greed_label?: string;
  asof?: string;
}

export interface Candle { t: number; o: number; h: number; l: number; c: number; v: number }
export interface OhlcvData { symbol: string; timeframe: string; candles: Candle[] }
export interface EnrichData {
  consensus?: { price?: number; n_sources?: number; spread_pct?: number };
  fear_greed?: { value?: number; label?: string };
  change_24h_pct?: number;
  market_cap_usd?: number;
  volume_24h_usd?: number;
  btc_dominance_pct?: number;
  sources?: Record<string, { price?: number }>;
}
