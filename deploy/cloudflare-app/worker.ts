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

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const { pathname } = new URL(request.url);

    if (pathname.startsWith("/api/v1/learn/")) {
      const origin = env.LEARN_API_ORIGIN;
      return origin ? proxy(request, origin) : unavailable("La plateforme de formation");
    }

    if (pathname.startsWith("/api/")) {
      const origin = env.GATEWAY_ORIGIN;
      return origin ? proxy(request, origin) : unavailable("La passerelle VIGIL");
    }

    return env.ASSETS.fetch(request);
  },
};
