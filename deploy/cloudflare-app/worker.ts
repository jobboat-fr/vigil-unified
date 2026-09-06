/**
 * app.vtlvs.com — static assets, plus a same-origin front door for the two APIs.
 *
 * Why this exists rather than assets-only hosting: the SPA calls `/api/...` on its own
 * origin. With `not_found_handling: single-page-application`, every one of those returned
 * **200 text/html** — the index page — and the client parsed HTML as JSON and threw. A 404
 * would at least be honest; HTML is the worst of both, because it looks like success.
 *
 * Proxying also removes CORS from the picture entirely. The browser only ever talks to
 * app.vtlvs.com, so no preflight, no allow-list to keep in sync with each new hostname.
 *
 * Two upstreams, because the product is two deployments:
 *   /api/v1/learn/*  → the training platform (hbs-backend on Railway)
 *   /api/*           → the VIGIL gateway (winny_gateway)
 *
 * An unset upstream answers 503 with a JSON body naming what is missing, never HTML. A page
 * whose data is unavailable should say so; it should not receive a document.
 */

interface Env {
  ASSETS: { fetch: (req: Request) => Promise<Response> };
  LEARN_API_ORIGIN?: string;
  GATEWAY_ORIGIN?: string;
}

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "transfer-encoding",
  "upgrade",
  "proxy-authorization",
  "te",
  "trailer",
]);

function unavailable(which: string): Response {
  return new Response(
    JSON.stringify({
      error: "upstream_not_configured",
      detail: `${which} n'est pas déployé ou n'est pas configuré pour cet environnement.`,
    }),
    { status: 503, headers: { "content-type": "application/json; charset=utf-8" } },
  );
}

async function proxy(request: Request, origin: string): Promise<Response> {
  const incoming = new URL(request.url);
  const target = new URL(incoming.pathname + incoming.search, origin);

  // Rebuild the headers rather than forwarding them wholesale: `host` must belong to the
  // upstream, and hop-by-hop headers are meaningless across a new connection.
  const headers = new Headers();
  for (const [k, v] of request.headers) {
    if (!HOP_BY_HOP.has(k.toLowerCase()) && k.toLowerCase() !== "host") headers.set(k, v);
  }
  // Preserve who asked, for the origin's own rate limiting and access log.
  const ip = request.headers.get("cf-connecting-ip");
  if (ip) headers.set("x-forwarded-for", ip);
  headers.set("x-forwarded-host", incoming.host);

  try {
    const res = await fetch(
      new Request(target.toString(), {
        method: request.method,
        headers,
        body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
        redirect: "manual",
      }),
    );
    return new Response(res.body, {
      status: res.status,
      statusText: res.statusText,
      headers: res.headers,
    });
  } catch {
    return new Response(
      JSON.stringify({ error: "upstream_unreachable", detail: "L'API est injoignable." }),
      { status: 502, headers: { "content-type": "application/json; charset=utf-8" } },
    );
  }
}

/**
 * Endpoints that belong to the Hermes *dashboard* server, not to the product gateway.
 *
 * This deployment has no dashboard: it is a static SPA in front of two APIs. The client
 * polls these anyway — they drive optional features (plugin tabs, theme catalogue, agent
 * profiles) — and every poll logged a 404, 114 of them on one page load.
 *
 * Answering with an honest empty result is better than a 404 for a reason beyond tidiness:
 * these are catalogues, and "this deployment has none" is exactly what an empty catalogue
 * means. Nothing here invents data. `/api/auth/me` and the LEARN and gateway routes are
 * deliberately NOT in this list — an empty answer there would be a lie about who is signed
 * in, and a 404 is the correct, loud response.
 */
const DASHBOARD_STUBS: Record<string, unknown> = {
  "/api/dashboard/plugins": [],
  "/api/dashboard/themes": { themes: [], active: null },
  "/api/dashboard/font": {},
  "/api/profiles": { profiles: [] },
  "/api/profiles/active": null,
  "/api/config": {},
  "/api/status": { ok: true, dashboard: false },
};

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const { pathname } = new URL(request.url);

    // Not stubbed, deliberately: `AuthMeResponse` requires a real user, and the client
    // already passes `allowUnauthorized` for it. 401 is the true answer — there is no
    // dashboard session here, the app authenticates through Supabase. It costs one console
    // line, which is cheaper than a fabricated session.
    if (pathname === "/api/auth/me") {
      return new Response(JSON.stringify({ error: "no_dashboard_session" }), {
        status: 401,
        headers: { "content-type": "application/json; charset=utf-8" },
      });
    }

    if (pathname in DASHBOARD_STUBS) {
      return new Response(JSON.stringify(DASHBOARD_STUBS[pathname]), {
        status: 200,
        headers: {
          "content-type": "application/json; charset=utf-8",
          // Says plainly that this is the edge answering, not a backend — so nobody spends
          // an afternoon looking for the service that returned an empty plugin list.
          "x-vtlvs-stub": "dashboard-absent-in-this-deployment",
          "cache-control": "no-store",
        },
      });
    }

    if (pathname.startsWith("/api/v1/learn/")) {
      const origin = env.LEARN_API_ORIGIN;
      return origin ? proxy(request, origin) : unavailable("La plateforme de formation");
    }

    // The gateway exposes both prefixes — /api/v1/approvals alongside /v1/rooms — so both
    // have to be forwarded. Matching only /api/ sent half the product to the SPA fallback.
    if (pathname.startsWith("/api/") || pathname.startsWith("/v1/")) {
      const origin = env.GATEWAY_ORIGIN;
      return origin ? proxy(request, origin) : unavailable("La passerelle VIGIL");
    }

    return env.ASSETS.fetch(request);
  },
};
