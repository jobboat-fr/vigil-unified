/**
 * api.vtlvs.com — la bordure de LEARN.
 *
 * Tout appel à l'API de formation passe ici avant Railway : le site hbs-formation.fr, les
 * outils des agents, la passerelle, et app.vtlvs.com. Ce Worker fait quatre choses, dans cet
 * ordre, et chacune se lit dans le journal avec un nom d'événement stable :
 *
 *   1. refuser ce qui n'a rien à faire sur une API (méthodes TRACE/CONNECT, corps trop gros) ;
 *   2. limiter le débit par adresse IP — serré sur les routes publiques sensibles (activation,
 *      mot de passe oublié, désinscription, formulaires, webhooks), large sur le reste ;
 *   3. relayer vers l'origine Railway avec la preuve de passage `x-vtlvs-edge` : l'origine,
 *      verrouillée, refuse toute requête qui arrive sans elle ;
 *   4. poser les en-têtes de sécurité d'une API sur la réponse.
 *
 * Pourquoi un Worker plutôt que des règles WAF de zone : les règles se configurent hors dépôt,
 * sans revue ni historique. Ici, la politique est du code, relue, testée, déployée par la CI.
 */

interface RateLimit {
  limit: (opts: { key: string }) => Promise<{ success: boolean }>;
}

interface Env {
  /** Origine Railway du service `web`, jamais l'adresse publique (elle pointe sur ce Worker). */
  LEARN_ORIGIN: string;
  /** Secret partagé avec l'origine (ORIGIN_EDGE_SECRET côté Railway). */
  EDGE_SECRET?: string;
  /** Routes publiques sensibles : 20 requêtes par minute par IP. */
  LIMITE_SENSIBLE: RateLimit;
  /** Tout le reste : 600 requêtes par minute par IP. */
  LIMITE_GENERALE: RateLimit;
}

/** Au-delà, un corps est refusé avant d'atteindre l'origine (les pièces du coffre y compris). */
export const TAILLE_MAX_OCTETS = 30 * 1024 * 1024;

const METHODES = new Set(["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]);

/**
 * Les routes que l'on peut appeler sans compte, et qu'un robot a intérêt à marteler :
 * essais de jetons d'activation, envois d'e-mails de réinitialisation, faux formulaires.
 */
const SENSIBLES = [
  /^\/api\/v1\/learn\/public\/activation\//,
  /^\/api\/v1\/learn\/public\/mot-de-passe$/,
  /^\/api\/v1\/learn\/public\/desinscription$/,
  /^\/api\/v1\/learn\/public\/leads\//,
  /^\/api\/v1\/learn\/public\/positionnement\//,
  /^\/api\/v1\/learn\/public\/identifier$/,
  /^\/api\/v1\/learn\/public\/webhooks\//,
];

export const estSensible = (chemin: string) => SENSIBLES.some((r) => r.test(chemin));

const ENTETES_API: Record<string, string> = {
  "strict-transport-security": "max-age=63072000; includeSubDomains; preload",
  "x-content-type-options": "nosniff",
  "x-frame-options": "DENY",
  "referrer-policy": "no-referrer",
  "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
  "cross-origin-resource-policy": "same-site",
};

const HOP_BY_HOP = new Set(["connection", "keep-alive", "transfer-encoding", "upgrade", "proxy-authorization", "te", "trailer"]);

/** Une ligne de journal au schéma commun de l'écosystème (voir le plan S4). */
function journal(niveau: "info" | "warn" | "error", evenement: string, message: string, details: Record<string, unknown>) {
  console[niveau === "info" ? "log" : niveau](JSON.stringify({
    ts: new Date().toISOString(),
    niveau,
    service: "bordure-api",
    evenement,
    message,
    ...details,
  }));
}

function refus(statut: number, erreur: string, detail: string, requeteId: string, extra: Record<string, string> = {}) {
  return new Response(JSON.stringify({ ok: false, error: erreur, detail, requete_id: requeteId }), {
    status: statut,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...extra },
  });
}

function securiser(res: Response, requeteId: string): Response {
  const out = new Response(res.body, res);
  for (const [k, v] of Object.entries(ENTETES_API)) out.headers.set(k, v);
  out.headers.set("x-request-id", requeteId);
  out.headers.delete("server");
  out.headers.delete("x-powered-by");
  return out;
}

export async function traiter(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const recu = request.headers.get("x-request-id") || "";
  const requeteId = /^[A-Za-z0-9-]{8,64}$/.test(recu) ? recu : crypto.randomUUID();
  const ip = request.headers.get("cf-connecting-ip") || "inconnue";
  const contexte = { requete_id: requeteId, route: url.pathname, methode: request.method, ip };

  if (!METHODES.has(request.method)) {
    journal("warn", "securite.methode_refusee", `Méthode ${request.method} refusée sur ${url.pathname} : une API n'en a pas l'usage.`, contexte);
    return refus(405, "methode_refusee", "Cette méthode n'est pas acceptée.", requeteId);
  }

  const taille = Number(request.headers.get("content-length") || "0");
  if (taille > TAILLE_MAX_OCTETS) {
    journal("warn", "securite.corps_trop_gros", `Corps de ${taille} octets refusé sur ${url.pathname} (maximum ${TAILLE_MAX_OCTETS}).`, contexte);
    return refus(413, "corps_trop_gros", "Le fichier ou le contenu envoyé dépasse 30 Mo.", requeteId);
  }

  // Un appel serveur (site hbs-formation, agents) porte un jeton de service et relaie, depuis
  // une seule IP, les formulaires de tous les visiteurs : le palier serré les bloquerait tous.
  // Il passe au palier général ; un faux en-tête n'y gagne que la limite générale, et l'origine
  // garde ses propres limites par adresse e-mail et par jeton.
  const sensible = estSensible(url.pathname) && !(request.headers.get("authorization") || "").startsWith("Bearer ");
  const limite = sensible ? env.LIMITE_SENSIBLE : env.LIMITE_GENERALE;
  if (request.method !== "OPTIONS" && limite) {
    const { success } = await limite.limit({ key: `${sensible ? "s" : "g"}:${ip}` });
    if (!success) {
      journal("warn", "securite.limite_debit_atteinte",
        `Limite de débit ${sensible ? "des routes sensibles (20/min)" : "générale (600/min)"} atteinte par ${ip} sur ${url.pathname} — requête refusée.`,
        { ...contexte, palier: sensible ? "sensible" : "generale" });
      return refus(429, "trop_de_requetes", "Trop de requêtes en peu de temps. Réessayez dans une minute.", requeteId, { "retry-after": "60" });
    }
  }

  if (!env.LEARN_ORIGIN) {
    journal("error", "bordure.origine_non_configuree", "LEARN_ORIGIN absent : aucune requête ne peut être relayée.", contexte);
    return refus(503, "origine_non_configuree", "La plateforme de formation est momentanément indisponible.", requeteId);
  }

  const headers = new Headers();
  for (const [k, v] of request.headers) {
    const nom = k.toLowerCase();
    if (!HOP_BY_HOP.has(nom) && nom !== "host") headers.set(k, v);
  }
  headers.set("x-forwarded-for", ip);
  headers.set("x-forwarded-host", url.host);
  headers.set("x-request-id", requeteId);
  // Jamais la valeur du client : il ne connaît pas le secret, et ne doit pas pouvoir essayer.
  headers.delete("x-vtlvs-edge");
  if (env.EDGE_SECRET) headers.set("x-vtlvs-edge", env.EDGE_SECRET);

  const cible = new URL(url.pathname + url.search, env.LEARN_ORIGIN);
  const debut = Date.now();
  try {
    const res = await fetch(new Request(cible.toString(), {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
      redirect: "manual",
    }));
    if (res.status >= 500) {
      journal("error", "bordure.origine_erreur", `L'origine a répondu ${res.status} pour ${request.method} ${url.pathname}.`,
        { ...contexte, statut: res.status, duree_ms: Date.now() - debut });
    }
    return securiser(res, requeteId);
  } catch (e) {
    journal("error", "bordure.origine_injoignable", `Origine Railway injoignable pour ${request.method} ${url.pathname}.`,
      { ...contexte, raison: String(e).slice(0, 200), duree_ms: Date.now() - debut });
    return securiser(refus(502, "origine_injoignable", "La plateforme de formation ne répond pas. Réessayez dans un instant.", requeteId), requeteId);
  }
}

export default { fetch: traiter };
