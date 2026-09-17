/** Mon compte (RGPD) et support — appels à la passerelle. */
import { getAccessToken, signalerSessionExpiree } from "./supabase";
import { WW_BASE, GatewayError, gatewayErrorMessage, type GatewayPayload } from "./ww";

async function appel<T>(method: string, path: string, body?: unknown, publique = false): Promise<T> {
  const token = publique ? null : await getAccessToken();
  if (!publique && !token) throw new GatewayError("Session expirée — reconnectez-vous.", "NO_SESSION");
  let res: Response;
  try {
    res = await fetch(`${WW_BASE}${path}`, {
      method,
      headers: { "content-type": "application/json", accept: "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}) },
      body: body != null ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new GatewayError("Connexion impossible. Vérifiez votre réseau : rien n'a été envoyé.", "UNREACHABLE");
  }
  const payload = (await res.json().catch(() => ({}))) as GatewayPayload & { data?: T };
  if (!res.ok || payload.ok === false) {
    if (res.status === 401 && !publique) signalerSessionExpiree();
    throw new GatewayError(gatewayErrorMessage(res.status, payload), "HTTP_ERROR", res.status, payload.detail);
  }
  return payload.data as T;
}

export type Demande = {
  id: string;
  subject: string;
  status: "open" | "answered" | "closed";
  email: string | null;
  source: string | null;
  created_at: string;
  messages: { auteur: string; email: string | null; texte: string; le: string }[];
};

export const compte = {
  exporter: () => appel<Record<string, unknown>>("POST", "/api/v1/compte/export"),
  supprimer: (confirmation: string, motif?: string) =>
    appel<{ supprime: boolean; message: string; conserve: string[] }>("POST", "/api/v1/compte/suppression", { confirmation, motif }),
};

export const support = {
  demander: (sujet: string, message: string, page?: string) =>
    appel<{ id: string; reference: string }>("POST", "/api/v1/support/demande", { sujet, message, page }),
  boite: (statut?: string) => appel<{ demandes: Demande[] }>("GET", `/api/v1/support/boite${statut ? `?statut=${statut}` : ""}`),
  repondre: (id: string, message: string) => appel<{ repondu: boolean }>("POST", `/api/v1/support/boite/${id}/reponse`, { message }),
  statut: (id: string, statut: Demande["status"]) => appel<{ statut: string }>("PATCH", `/api/v1/support/boite/${id}`, { statut }),
};

/** Les pages légales vivent sur le site public, là où les liens d'activation pointent déjà. */
export const LIENS_LEGAUX = [
  { label: "Conditions générales d'utilisation", href: "https://vtlvs.com/cgu" },
  { label: "Confidentialité et RGPD", href: "https://vtlvs.com/confidentialite" },
  { label: "Mentions légales", href: "https://vtlvs.com/mentions-legales" },
];
