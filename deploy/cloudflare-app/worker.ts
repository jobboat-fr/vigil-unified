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
  /** Secret partagé avec les origines : prouve qu'une requête est passée par ce Worker. */
  EDGE_SECRET?: string;
}

// ── En-têtes de sécurité ──────────────────────────────────────────────────────────────
//
// Posés ici, à la bordure, pour toutes les réponses : la page, les fichiers, et les réponses
// d'API relayées. La CSP est celle d'une application sans script tiers : scripts et styles
// de l'origine, connexions vers Supabase (authentification) et LiveKit (visio), images et
// médias de l'origine, de Supabase (logos) et en data:/blob: (aperçus, flux vidéo). Rien
// d'autre ne peut se charger — un script injecté n'a nulle part où envoyer ce qu'il vole.
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' data: https://fonts.gstatic.com",
  "img-src 'self' data: blob: https://*.supabase.co https://hbs-formation.fr",
  "media-src 'self' blob: mediastream:",
  "connect-src 'self' https://*.supabase.co wss://*.supabase.co https://*.livekit.cloud wss://*.livekit.cloud",
  "frame-src 'self' blob:",
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "upgrade-insecure-requests",
].join("; ");

const SECURITY_HEADERS: Record<string, string> = {
  "strict-transport-security": "max-age=63072000; includeSubDomains; preload",
  "x-content-type-options": "nosniff",
  "x-frame-options": "DENY",
  "referrer-policy": "strict-origin-when-cross-origin",
  "permissions-policy": "camera=(self), microphone=(self), display-capture=(self), geolocation=(), payment=(), usb=()",
  "cross-origin-opener-policy": "same-origin",
};

/** Le document « Noyau », servi par LEARN pour être chargé dans une iframe. */
const VUE_NOYAU = /^\/api\/v1\/learn\/noyau\/[^/]+\/vue$/;

function secure(res: Response, requestId: string, isHtml: boolean, propre = false): Response {
  const out = new Response(res.body, res);
  for (const [k, v] of Object.entries(SECURITY_HEADERS)) out.headers.set(k, v);
  if (propre) {
    // Ce document apporte sa propre politique (scripts en ligne, three.js depuis notre
    // domaine) : l'écraser avec celle de l'application le rendrait inerte — c'est
    // exactement ce qui se passait quand il était injecté par `srcDoc`.
    // Et `x-frame-options: DENY`, posé sur tout le reste, empêcherait l'application de
    // le cadrer : ici c'est `frame-ancestors`, dans la politique du document, qui décide.
    out.headers.set("x-frame-options", "SAMEORIGIN");
    return finir(out, requestId);
  }
  if (isHtml) out.headers.set("content-security-policy", CSP);
  return finir(out, requestId);
}

function finir(out: Response, requestId: string): Response {
  out.headers.set("x-request-id", requestId);
  out.headers.delete("server");
  out.headers.delete("x-powered-by");
  return out;
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

async function proxy(request: Request, origin: string, env: Env, requestId: string): Promise<Response> {
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
  // Identifiant de requête propagé : un même identifiant relie la ligne du Worker, celle de
  // l'origine et le message d'erreur montré à la personne.
  headers.set("x-request-id", requestId);
  // Preuve de passage par la bordure. Une origine verrouillée refuse toute requête sans elle ;
  // un client ne peut pas la forger, il ne la connaît pas. On écrase toujours la valeur reçue.
  headers.delete("x-vtlvs-edge");
  if (env.EDGE_SECRET) headers.set("x-vtlvs-edge", env.EDGE_SECRET);

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
      JSON.stringify({ error: "upstream_unreachable", detail: "L'API est injoignable.", request_id: requestId }),
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
    // Un identifiant reçu n'est gardé que s'il a la forme attendue : pas d'injection dans les journaux.
    const recu = request.headers.get("x-request-id") || "";
    const requestId = /^[A-Za-z0-9-]{8,64}$/.test(recu) ? recu : crypto.randomUUID();
    const res = await route(request, env, pathname, requestId);
    const isHtml = (res.headers.get("content-type") || "").includes("text/html");
    // Idem : seule une réponse qui porte sa propre politique échappe à celle de
    // l'application. Un refus sur cette route reste couvert.
    const apporteSaPolitique = VUE_NOYAU.test(pathname) && res.headers.has("content-security-policy");
    return secure(res, requestId, isHtml, apporteSaPolitique);
  },
};

async function route(request: Request, env: Env, pathname: string, requestId: string): Promise<Response> {
  {

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
      return origin ? proxy(request, origin, env, requestId) : unavailable("La plateforme de formation");
    }

    // The gateway exposes both prefixes — /api/v1/approvals alongside /v1/rooms — so both
    // have to be forwarded. Matching only /api/ sent half the product to the SPA fallback.
    if (pathname.startsWith("/api/") || pathname.startsWith("/v1/")) {
      const origin = env.GATEWAY_ORIGIN;
      return origin ? proxy(request, origin, env, requestId) : unavailable("La passerelle VIGIL");
    }

    // Un fichier de `/assets/` porte son empreinte dans son nom : il existe, ou il
    // n'existera jamais. Le repli SPA renvoyait pourtant `index.html` avec un 200 pour
    // tout chemin absent — si bien qu'un navigateur resté sur une ancienne page demandait
    // `index-<vieux hash>.js`, recevait du HTML, et tentait de le parser comme du
    // JavaScript. Une erreur par requête, à chaque chargement, et un diagnostic qui pointe
    // vers le mauvais endroit puisque le réseau répond 200.
    //
    // Un 404 franc dit la vérité, et le service worker sait alors qu'il doit se recharger.
    if (pathname.startsWith("/assets/")) {
      const res = await env.ASSETS.fetch(request);
      const ct = res.headers.get("content-type") || "";
      if (res.status === 200 && ct.includes("text/html")) {
        return new Response("asset introuvable — build périmé", {
          status: 404,
          headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" },
        });
      }
      return res;
    }

    return env.ASSETS.fetch(request);
  }
}
