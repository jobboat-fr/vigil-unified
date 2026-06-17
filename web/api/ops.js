// Supabase-gated reverse proxy for the Hermes operator dashboard API.
//
// All `/api/*` requests are routed here by a rewrite in vercel.json
// (`/api/(.*)` → `/api/ops?__opspath=$1`). Vercel's Vite (non-Next) runtime
// does not support `[...catch-all]` filesystem routes, so the rewrite is what
// funnels every operator path — single- and multi-segment — into this one
// function. We:
//   1. verify the caller holds a valid Supabase product session, then
//   2. forward to the OVH Hermes dashboard (reachable only behind a Caddy gate
//      keyed by OPS_GATE_SECRET), injecting that gate secret plus the
//      dashboard's own ephemeral session token — scraped from its served HTML
//      exactly as the dashboard's own SPA reads `window.__HERMES_SESSION_TOKEN__`.
//
// One product login lights up every operator page; the admin backend is never
// publicly usable (403 without the gate secret), and its token never reaches
// the browser. WebSocket/SSE endpoints (live log tail, /api/pty) are not
// proxied here — serverless functions can't hold those streams.
//
// Required server-side env (Vercel project settings, NOT VITE_*):
//   OPS_DASHBOARD_URL   e.g. https://vigil-ops-57-130-58-222.nip.io
//   OPS_GATE_SECRET     shared secret Caddy enforces on that host
//   SUPABASE_URL        https://<ref>.supabase.co
//   SUPABASE_ANON_KEY   anon (public) key, used to validate the user token

const DASH = process.env.OPS_DASHBOARD_URL;
const GATE = process.env.OPS_GATE_SECRET;
const SB_URL = process.env.SUPABASE_URL;
const SB_ANON = process.env.SUPABASE_ANON_KEY;

let _opsToken = null;
const _userCache = new Map();

async function verifySupabase(token) {
  if (!token || !SB_URL || !SB_ANON) return false;
  const now = Date.now();
  const hit = _userCache.get(token);
  if (hit && hit > now) return true;
  try {
    const r = await fetch(`${SB_URL}/auth/v1/user`, {
      headers: { apikey: SB_ANON, authorization: `Bearer ${token}` },
    });
    if (r.ok) {
      _userCache.set(token, now + 60_000);
      return true;
    }
  } catch {
    /* network blip — treat as unauthenticated */
  }
  return false;
}

async function scrapeOpsToken() {
  try {
    const r = await fetch(`${DASH}/`, { headers: { "x-ops-gate": GATE } });
    const html = await r.text();
    const m = html.match(/__HERMES_SESSION_TOKEN__\s*=\s*["']([^"']+)["']/);
    _opsToken = m ? m[1] : null;
  } catch {
    _opsToken = null;
  }
  return _opsToken;
}

function rawBody(req) {
  return new Promise((resolve) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => resolve(chunks.length ? Buffer.concat(chunks) : undefined));
    req.on("error", () => resolve(undefined));
  });
}

export default async function handler(req, res) {
  if (!DASH || !GATE) {
    res.status(503).json({ detail: "operator proxy not configured" });
    return;
  }

  // 1) Gate on the product (Supabase) session. The operator SPA attaches
  //    `Authorization: Bearer <supabase access token>` (see web/src/lib/api.ts).
  const authz = req.headers.authorization || "";
  const userToken = authz.startsWith("Bearer ") ? authz.slice(7) : "";
  if (!(await verifySupabase(userToken))) {
    // Shape matches the dashboard's gated 401 envelope so the SPA's 401
    // handler full-page-navigates to the product login.
    res
      .status(401)
      .json({ error: "unauthenticated", detail: "Unauthorized", login_url: "/auth" });
    return;
  }

  // 2) Reconstruct the upstream URL. The rewrite hands us the real operator
  //    path in `__opspath` (with any original query merged in alongside);
  //    fall back to req.url if a request reached us directly.
  const u = new URL(req.url || "/", "http://internal");
  let opspath = u.searchParams.get("__opspath");
  let upstream;
  if (opspath !== null) {
    u.searchParams.delete("__opspath");
    const qs = u.searchParams.toString();
    upstream = `${DASH}/api/${opspath}${qs ? `?${qs}` : ""}`;
  } else {
    let p = u.pathname;
    if (!p.startsWith("/api/") && p !== "/api") {
      p = `/api${p.startsWith("/") ? p : `/${p}`}`;
    }
    upstream = `${DASH}${p}${u.search}`;
  }

  // 3) Body passthrough. @vercel/node parses JSON/text bodies into req.body;
  //    reconstruct it, else fall back to the raw stream.
  const method = req.method || "GET";
  let body;
  let bodyCT = req.headers["content-type"];
  if (method !== "GET" && method !== "HEAD") {
    if (req.body !== undefined && req.body !== null && req.body !== "") {
      if (typeof req.body === "string" || Buffer.isBuffer(req.body)) {
        body = req.body;
      } else {
        body = JSON.stringify(req.body);
        bodyCT = bodyCT || "application/json";
      }
    } else {
      body = await rawBody(req);
    }
  }

  const headersFor = (opsTok) => {
    const h = { "x-ops-gate": GATE, "x-hermes-session-token": opsTok || "" };
    if (bodyCT) h["content-type"] = bodyCT;
    return h;
  };

  // 4) Forward, refreshing the (restart-rotating) dashboard token once on 401.
  if (!_opsToken) await scrapeOpsToken();
  let up = await fetch(upstream, { method, headers: headersFor(_opsToken), body });
  if (up.status === 401) {
    await scrapeOpsToken();
    up = await fetch(upstream, { method, headers: headersFor(_opsToken), body });
  }

  // 5) Relay status + body.
  res.status(up.status);
  const ct = up.headers.get("content-type");
  if (ct) res.setHeader("content-type", ct);
  const buf = Buffer.from(await up.arrayBuffer());
  res.send(buf);
}
