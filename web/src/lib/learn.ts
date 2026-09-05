// LEARN client — the training platform's API.
//
// Follows vigil.ts's shape (same gateway, same Supabase JWT) with one difference that
// matters: LEARN returns plain JSON rather than the `{ok, data}` envelope, because its
// errors are HTTP statuses carrying a typed body. A 409 from a double-booking names the
// conflicting range; a 423 names the module that is still locked. Flattening those into
// `{ok: false}` would throw away the part a user needs to read.
//
// The other rule this file exists to enforce: **never infer what a user may do from their
// role.** Every row arrives with `_can`, and components read that. A `role === "admin"`
// check in TypeScript is a second copy of a rule the database already owns.
import { getAccessToken } from "./supabase";
import { WW_BASE, GatewayError } from "./ww";

const BASE = `${WW_BASE}/api/v1/learn`;

/** What the caller may do to a row. Rendered from, never guessed at. */
export interface Can {
  create: boolean;
  read: boolean;
  update: boolean;
  delete: boolean;
  cancel: boolean;
  sign: boolean;
  export: boolean;
}

export class LearnError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "LearnError";
  }
  /** True when LEARN is deployed but has no database configured. */
  get unavailable() {
    return this.status === 503;
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = await getAccessToken();
  if (!token) throw new GatewayError("not signed in", "NO_SESSION");

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers: {
        "content-type": "application/json",
        accept: "application/json",
        authorization: `Bearer ${token}`,
      },
      body: body != null ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new GatewayError(`gateway unreachable: ${(e as Error).message}`, "UNREACHABLE");
  }

  if (res.status === 204) return undefined as T;

  let payload: unknown;
  try {
    payload = await res.json();
  } catch {
    if (res.ok) return undefined as T;
    throw new LearnError(`HTTP ${res.status}`, res.status);
  }

  if (!res.ok) {
    // FastAPI wraps our dict in `detail`; keep the code and the body so the UI can say
    // "Karim est déjà pris le 13 au matin" instead of "something went wrong".
    const d = (payload as { detail?: unknown })?.detail;
    const code = typeof d === "object" && d !== null ? (d as { error?: string }).error : undefined;
    throw new LearnError(code ?? `HTTP ${res.status}`, res.status, code, d);
  }
  return payload as T;
}

const qs = (params: Record<string, string | number | boolean | null | undefined>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v != null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};

// ---------------------------------------------------------------- dashboard

export interface Dashboard {
  tenant_id: string;
  sessions_actives?: number;
  creneaux_semaine?: number;
  inscrits?: number;
  reclamations_ouvertes?: number;
  actions_ouvertes?: number;
  copies_a_corriger?: number;
  apprenants_a_risque?: number;
  programmes_a_reviser?: number;
  pieces_purgeables?: number;
}

export const getDashboard = () => call<Dashboard>("GET", "/dashboard");

// ---------------------------------------------------------------- calendar

export interface Slot {
  id: string;
  session_id: string;
  on_date: string;
  half: "am" | "pm";
  starts_at: string;
  ends_at: string;
  status: "planned" | "confirmed" | "done" | "cancelled";
  title: string | null;
  formateur_id: string | null;
  formateur_name: string | null;
  room_id: string | null;
  room_name: string | null;
  room_colour: string | null;
  capacity: number | null;
  enrolled: number;
  _can: Can;
}

export const getCalendar = (from: string, to: string, opts: { formateur_id?: string; room_id?: string } = {}) =>
  call<{ from: string; to: string; count: number; items: Slot[] }>(
    "GET",
    `/calendar${qs({ from, to, ...opts })}`,
  );

export const getResources = () =>
  call<{ formateurs: { id: string; name: string }[]; rooms: { id: string; name: string; colour: string | null }[] }>(
    "GET",
    "/calendar/resources",
  );

/** Issue (and rotate) the personal ICS subscription token. */
export const issueCalendarToken = () =>
  call<{ token: string; url: string }>("POST", "/calendar/token");

// ---------------------------------------------------------------- attendance

export interface SheetRow {
  slot_id: string;
  apprenant_id: string;
  apprenant_name: string;
  signed_in_at: string | null;
  signed_out_at: string | null;
  countersigned_at: string | null;
  countersigned_by: string | null;
  absence_justified: boolean | null;
  state: "complet" | "entree_seule" | "absent" | "non_signe";
  _can: Can;
}

export const getSlotSheet = (slotId: string) =>
  call<{ slot_id: string; count: number; items: SheetRow[] }>("GET", `/slots/${slotId}/sheet`);

export const getSessionSheet = (sessionId: string) =>
  call<{ session_id: string; tally: Record<string, number>; items: SheetRow[] }>(
    "GET",
    `/sessions/${sessionId}/sheet`,
  );

/** Sign one's own entry or exit. The evidence bundle is built server-side. */
export const sign = (slotId: string, kind: "in" | "out") =>
  call<{ id: string; seq_no: number; signed_at: string; this_hash: string }>(
    "POST",
    `/slots/${slotId}/sign`,
    { kind },
  );

export const countersign = (slotId: string) =>
  call<{ id: string; seq_no: number; signed_at: string }>("POST", `/slots/${slotId}/countersign`);

export const verifyChain = () =>
  call<{ checked: number; valid: boolean; first_broken_seq: number | null; reason: string }>(
    "GET",
    "/attendance/verify",
  );

// ---------------------------------------------------------------- audit

export interface ManifestItem {
  piece: string;
  indicator: string;
  present: boolean;
  detail: string | null;
}

export const getAudit = (sessionId: string) =>
  call<{
    session: { code: string; program_title: string } | null;
    ready: boolean;
    readiness: string;
    missing: ManifestItem[];
    items: ManifestItem[];
  }>("GET", `/sessions/${sessionId}/audit`);

export const getAuditOverview = () =>
  call<{ items: { session_id: string; code: string; readiness: string; missing: string[] }[] }>(
    "GET",
    "/audit/overview",
  );

// ---------------------------------------------------------------- quality

export const getQualityIndicators = (year?: number) =>
  call<{ items: Record<string, number>[]; note: string }>("GET", `/quality/indicators${qs({ year })}`);

export const getReclamations = (status?: string) =>
  call<{ items: Record<string, unknown>[] }>("GET", `/reclamations${qs({ status })}`);

export const getAtRisk = (sessionId?: string) =>
  call<{ count: number; items: Record<string, unknown>[]; note: string }>(
    "GET",
    `/at-risk${qs({ session_id: sessionId })}`,
  );

// ---------------------------------------------------------------- platform

export const getReadiness = () =>
  call<{ ready: boolean; blocking: { requirement: string; detail: string | null }[]; items: unknown[] }>(
    "GET",
    "/platform/readiness",
  );

export const getReversibility = () =>
  call<{ items: { dataset: string; rows: number; note: string | null }[]; formats: Record<string, string>; note: string }>(
    "GET",
    "/platform/reversibility",
  );
