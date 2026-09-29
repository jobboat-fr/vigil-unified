// WinnyWoo gateway client for the VIGIL × WinnyWoo product pages.
//
// Talks to the FastAPI gateway (audit, vault). All
// /api/v1/* responses are { ok, data }; `call` unwraps to `data`. Auth is the
// Supabase JWT both products share. A missing session or a network failure
// throws a GatewayError with `code` so pages render an offline / sign-in state
// instead of crashing.
import { getAccessToken } from "./supabase";
import { memoriserReference, nouvelleReference } from "./reference";

// Où vit la passerelle.
//
// `VITE_WW_GATEWAY_URL` gagne toujours. Sans lui, la valeur par défaut dépend de
// l'environnement, et c'est le correctif :
//
//   dev   → http://127.0.0.1:8400, la passerelle vendorisée que l'on lance à côté ;
//   prod  → la même origine que la page. Le Worker Cloudflare relaie /api et /v1 vers
//           les deux backends, donc une URL relative arrive exactement où il faut — et
//           le navigateur ne parle qu'à une origine, ce qui retire le CORS du tableau.
//
// Le défaut « localhost partout » était livré tel quel : une fois en ligne, chaque page
// appelait http://127.0.0.1:8400 depuis le navigateur du visiteur. Les requêtes
// échouaient en ERR_BLOCKED_BY_CLIENT ou ERR_CONNECTION_REFUSED, la console se
// remplissait, et les pages restaient vides — un symptôme qui ressemble à « pas de
// données » alors que l'appel n'a jamais quitté la machine du visiteur.
const LOCAL_DEFAULT = "http://127.0.0.1:8400";

function resolveBase(): string {
  const configured = (import.meta.env.VITE_WW_GATEWAY_URL as string | undefined)?.trim();
  if (configured) return configured.replace(/\/$/, "");
  // Chaîne vide = même origine : les chemins restent « /api/… », relatifs à la page.
  return import.meta.env.DEV ? LOCAL_DEFAULT : "";
}

export const WW_BASE = resolveBase();

export class GatewayError extends Error {
  code: string;
  status?: number;
  detail?: unknown;
  /** L'identifiant de la requête fautive, à donner au support : la même chaîne se
   *  cherche telle quelle dans les journaux. */
  reference?: string;
  constructor(message: string, code: string, status?: number, detail?: unknown, reference?: string) {
    super(message);
    this.code = code;
    this.status = status;
    this.detail = detail;
    this.reference = reference;
  }
}

/** Ce que la passerelle renvoie : `{ok, data, error}` pour ses propres réponses, et
 *  `{detail}` quand FastAPI lève une HTTPException — `detail` étant un texte ou un objet. */
export type GatewayPayload = { ok?: boolean; data?: unknown; error?: string; detail?: unknown };

const RESSOURCES: Record<string, string> = {
  room: "la salle de réunion", mail: "le mail", crm: "le CRM", finance: "la finance",
  ops: "l'équipe agentique", legal: "le juridique", studio: "le studio",
};
const ACTIONS: Record<string, string> = {
  read: "consulter", create: "créer dans", update: "modifier", delete: "supprimer dans",
  host: "animer", join: "rejoindre",
};

/** Un message en français, précis, à partir de n'importe quelle réponse d'erreur. */
export function gatewayErrorMessage(status: number, payload: GatewayPayload): string {
  const d = payload.detail;
  const obj = d && typeof d === "object" ? (d as Record<string, unknown>) : null;
  const code = (obj?.error as string | undefined) ?? payload.error;
  if (status === 401) return "Session expirée — reconnectez-vous.";
  if (code === "forbidden" && obj) {
    const quoi = RESSOURCES[obj.resource as string] ?? String(obj.resource);
    const faire = ACTIONS[obj.action as string] ?? String(obj.action);
    const role = obj.role ? ` (${obj.role})` : "";
    return `Accès refusé : votre rôle${role} ne permet pas de ${faire} ${quoi}.`;
  }
  if (code === "database_unavailable") {
    const table = obj?.table ? ` (${obj.table})` : "";
    return `La base de données ne répond pas${table}. Réessayez dans un instant.`;
  }
  if (code === "permissions_unavailable") return "Les droits d'accès sont momentanément illisibles. Réessayez dans un instant.";
  if (code === "internal_scope_error") return "Requête refusée par sécurité : elle ne précisait pas à qui appartiennent les données.";
  if (typeof d === "string" && d) return d;
  // La passerelle joint souvent une phrase prête à lire à son code d'erreur.
  if (obj && typeof obj.detail === "string" && obj.detail) return obj.detail;
  if (status === 429) return "Trop de requêtes en peu de temps. Réessayez dans une minute.";
  if (code) return code;
  return `Erreur ${status}`;
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
  const reference = nouvelleReference();
  const headers: Record<string, string> = {
    "content-type": "application/json",
    accept: "application/json",
    "x-request-id": reference,
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
    throw new GatewayError(`gateway unreachable: ${(e as Error).message}`, "UNREACHABLE", undefined, undefined, reference);
  }
  // Le serveur renvoie la référence qu'il a journalisée — la sienne fait foi.
  const tracee = res.headers.get("x-request-id") || reference;
  memoriserReference(tracee);
  let payload: GatewayPayload;
  try {
    payload = await res.json();
  } catch {
    payload = { ok: false, error: "BAD_JSON" };
  }
  if (!res.ok || payload.ok === false) {
    throw new GatewayError(gatewayErrorMessage(res.status, payload), "HTTP_ERROR", res.status, payload.detail, tracee);
  }
  return payload.data as T;
}

export interface AuditEvent {
  id?: string; ts?: string; event_type?: string; action?: string;
  component?: string; decision_id?: string; critical?: boolean;
  actor_email?: string; payload?: Record<string, unknown>;
}

export const ww = {
  health: () => call("GET", "/health"),
  audit: {
    events: (limit = 100) => call<AuditEvent[]>("GET", `/api/v1/audit/events?limit=${limit}`),
    verify: () => call("GET", "/api/v1/audit/verify"),
  },
  vault: {
    list: () => call("GET", "/v1/vault/documents"),
    search: (q: string) => call("GET", `/v1/vault/search?q=${encodeURIComponent(q)}`),
  },
};

