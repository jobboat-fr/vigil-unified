// Proxy for the Hermes dashboard plugin assets (/dashboard-plugins/*).
//
// The operator console (ChatPage + usePlugins) loads plugin JS/CSS from
// /dashboard-plugins/<name>/dist/... . Those assets live ONLY on the OVH Hermes
// dashboard (behind its Caddy gate), not in the Vercel deploy, so they 404 here
// and the browser refuses the wrong-MIME 404 bodies. This function proxies them
// to OVH with the gate secret + the dashboard's ephemeral session token (scraped
// from its HTML, exactly like web/api/ops.js), and RELAYS the upstream
// Content-Type so the browser accepts the JS/CSS.
//
// Routed via a vercel.json rewrite:
//   /dashboard-plugins/(.*)  ->  /api/plugin-proxy?__p=$1
//
// These are inert client assets (UI bundles), so they're not Supabase-gated —
// only the OVH gate secret (server-side) is required to reach them. The path is
// constrained to the /dashboard-plugins/ prefix so the proxy can't be used to
// reach arbitrary upstream paths.
//
// Required server-side env (already set for the ops proxy):
//   OPS_DASHBOARD_URL   e.g. https://vigil-ops-57-130-58-222.nip.io
//   OPS_GATE_SECRET     shared secret Caddy enforces on that host

const DASH = process.env.OPS_DASHBOARD_URL;
const GATE = process.env.OPS_GATE_SECRET;

let _opsToken = null;

// Content-Type fallback by extension, in case the upstream omits it.
const MIME = {
  js: "application/javascript; charset=utf-8",
  mjs: "application/javascript; charset=utf-8",
  css: "text/css; charset=utf-8",
  json: "application/json; charset=utf-8",
  svg: "image/svg+xml",
  map: "application/json; charset=utf-8",
  woff: "font/woff",
  woff2: "font/woff2",
};

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

export default async function handler(req, res) {
  if (!DASH || !GATE) {
    res.status(503).json({ detail: "operator proxy not configured" });
    return;
  }

  const method = req.method || "GET";
  if (method !== "GET" && method !== "HEAD") {
    res.status(405).json({ detail: "method not allowed" });
    return;
  }

  // Resolve the plugin path from the rewrite (__p) or a direct hit.
  const u = new URL(req.url || "/", "http://internal");
  let p = u.searchParams.get("__p");
  if (p === null) {
    p = (u.pathname || "").replace(/^\/?dashboard-plugins\//, "");
  }
  // Defense-in-depth: keep the proxy pinned to plugin assets.
  if (!p || p.includes("..") || p.includes("://")) {
    res.status(400).json({ detail: "bad plugin path" });
    return;
  }
  const upstream = `${DASH}/dashboard-plugins/${p}`;
  const headersFor = (tok) => ({ "x-ops-gate": GATE, "x-hermes-session-token": tok || "" });

  // Forward, refreshing the (restart-rotating) dashboard token once on 401.
  if (!_opsToken) await scrapeOpsToken();
  let up = await fetch(upstream, { method, headers: headersFor(_opsToken) });
  if (up.status === 401) {
    await scrapeOpsToken();
    up = await fetch(upstream, { method, headers: headersFor(_opsToken) });
  }

  res.status(up.status);
  let ct = up.headers.get("content-type");
  if (!ct || ct.startsWith("text/plain")) {
    const ext = (p.split(".").pop() || "").toLowerCase();
    if (MIME[ext]) ct = MIME[ext];
  }
  if (ct) res.setHeader("content-type", ct);
  res.setHeader("cache-control", "public, max-age=300"); // versioned per deploy
  const buf = Buffer.from(await up.arrayBuffer());
  res.send(buf);
}
