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
import { getAccessToken, signalerSessionExpiree } from "./supabase";
import { WW_BASE, GatewayError } from "./ww";
import { memoriserReference, nouvelleReference } from "./reference";

/**
 * LEARN has its own origin, separate from the VIGIL gateway.
 *
 * The two halves of this application are two deployments: the training platform runs on
 * Railway at api.vtlvs.com (jobboat-fr/hbs-backend-, `app/learn/`), and the VIGIL gateway
 * is a different service. Pointing both at one base means whichever is not deployed takes
 * the other down with it — and for a while that is exactly what happened: every LEARN page
 * called a host that answers only VIGIL routes and got a 404 that reads like a bug.
 *
 * `WW_BASE` is kept as the fallback so a single-origin deployment still works unchanged.
 */
const LEARN_ORIGIN = (
  (import.meta.env.VITE_LEARN_API_URL as string | undefined)?.trim() || WW_BASE
).replace(/\/$/, "");

export const BASE = `${LEARN_ORIGIN}/api/v1/learn`;

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
  // Declared and assigned explicitly rather than as constructor parameter properties:
  // this package builds with `erasableSyntaxOnly`, which rejects that shorthand because it
  // emits runtime code from a type-position annotation.
  readonly status: number;
  readonly code?: string;
  readonly detail?: unknown;
  /** L'identifiant que LEARN a écrit dans son journal pour cette requête. */
  readonly reference?: string;

  constructor(message: string, status: number, code?: string, detail?: unknown, reference?: string) {
    super(message);
    this.name = "LearnError";
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.reference = reference;
  }
  /** True when LEARN is deployed but has no database configured. */
  get unavailable() {
    return this.status === 503;
  }
}

export async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = await getAccessToken();
  if (!token) throw new GatewayError("Session expirée — reconnectez-vous.", "NO_SESSION");

  // `FormData` doit partir tel quel : c'est le navigateur qui écrit l'en-tête
  // `multipart/form-data` **et sa frontière**. Poser `content-type` soi-même produirait
  // une frontière absente, et le serveur lirait un corps qu'il ne sait pas découper.
  const estFormulaire = typeof FormData !== "undefined" && body instanceof FormData;

  const reference = nouvelleReference();
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers: {
        ...(estFormulaire ? {} : { "content-type": "application/json" }),
        accept: "application/json",
        authorization: `Bearer ${token}`,
        "x-request-id": reference,
      },
      body: estFormulaire
        ? (body as FormData)
        : body != null
          ? JSON.stringify(body)
          : undefined,
    });
  } catch (e) {
    throw new GatewayError(`gateway unreachable: ${(e as Error).message}`, "UNREACHABLE", undefined, undefined, reference);
  }

  // LEARN renvoie la référence qu'il a journalisée (middleware `JournalHttpMiddleware`).
  const tracee = res.headers.get("x-request-id") || reference;
  memoriserReference(tracee);

  if (res.status === 204) return undefined as T;

  let payload: unknown;
  try {
    payload = await res.json();
  } catch {
    if (res.ok) return undefined as T;
    throw new LearnError(`HTTP ${res.status}`, res.status, undefined, undefined, tracee);
  }

  if (!res.ok) {
    // FastAPI wraps our dict in `detail`; keep the code and the body so the UI can say
    // "Karim est déjà pris le 13 au matin" instead of "something went wrong".
    const d = (payload as { detail?: unknown })?.detail;
    const code = typeof d === "object" && d !== null ? (d as { error?: string }).error : undefined;
    if (res.status === 401 && (d === "invalid_session" || d === "unidentified_session")) signalerSessionExpiree();
    throw new LearnError(code ?? `HTTP ${res.status}`, res.status, code, d, tracee);
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
  /** Modalité (vue learn_calendar) : présentiel, distanciel ou mixte. */
  modality?: "presentiel" | "distanciel" | "mixte" | null;
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

// ---------------------------------------------------------------- formations & contenu
//
// Added so the LEARN pages stop being two screens against a 81-endpoint API. Every list
// returns `_can`; components render controls from that and never from a role check.

export interface Program {
  id: string;
  code: string | null;
  title: string;
  nature: string;
  objectives: string | null;
  prerequisites: string | null;
  duration_hours: number;
  modality: string;
  certifiante: boolean;
  rncp_code: string | null;
  version: number;
  published: boolean;
  _can?: Can;
}

export const getPrograms = () =>
  call<{ items: Program[]; _can?: Can }>("GET", "/programs");

export interface Session {
  id: string;
  program_id: string;
  code: string | null;
  title: string | null;
  starts_on: string;
  ends_on: string;
  modality: string;
  place: string | null;
  capacity: number;
  status: string;
  program_title?: string | null;
  enrolled?: number | null;
  _can?: Can;
}

export const getSessions = (status?: string) =>
  call<{ items: Session[]; _can?: Can }>(
    "GET",
    `/sessions${status ? `?status=${encodeURIComponent(status)}` : ""}`,
  );

export interface SessionDetail extends Session {
  program_version?: number | null;
  next_review_due?: string | null;
  certifiante?: boolean | null;
  rncp_code?: string | null;
  formateurs: { id: string; full_name: string | null; email: string | null }[];
  learners: {
    id: string;
    enrollment_id: string;
    full_name: string | null;
    email: string | null;
    status: string;
    level: string | null;
    company: string | null;
    _can?: Can;
  }[];
  slots: Slot[];
}

/**
 * Le détail d'une session : son programme, ses formateurs, ses inscrits, ses créneaux.
 *
 * `GET /sessions/{id}/enrollments` n'existe pas — cette route est un POST, et l'appeler en
 * GET renvoyait 405. Les inscrits arrivent avec le détail de la session, ce qui est aussi
 * la bonne granularité : une inscription n'a pas de sens hors de sa session.
 */
export const getSession = (sessionId: string) =>
  call<SessionDetail>("GET", `/sessions/${sessionId}`);

export interface Enrollment {
  id: string;
  apprenant_id: string;
  apprenant_name?: string | null;
  email?: string | null;
  status: string;
  level: string | null;
  company_name?: string | null;
}

export interface Course {
  id: string;
  program_id: string | null;
  title: string;
  summary: string | null;
  version: number;
  published: boolean;
  modules?: number | null;
  _can?: Can;
}

export const getCourses = () => call<{ items: Course[]; _can?: Can }>("GET", "/courses");

/** The course's modules and their lessons. `/outline`, not `/modules` — checked against
 *  the deployed OpenAPI rather than assumed, after inventing a route earlier today. */
export interface CourseModule {
  id: string;
  title: string;
  summary: string | null;
  position: number;
  required: boolean;
  unlocked?: boolean;
  lessons?: {
    id: string;
    title: string;
    kind?: string;
    position: number;
    duration_minutes?: number | null;
    status?: string | null;
    progress_pct?: number | null;
  }[];
}

/** La clé est `modules`, pas `items` — vérifié contre la réponse déployée. Le type
 *  précédent annonçait `items`, si bien que le plan d'un cours s'affichait vide alors que
 *  l'appel réussissait : la panne la plus difficile à voir, celle qui renvoie 200. */
export const getCourseOutline = (courseId: string) =>
  call<{ modules: CourseModule[] }>("GET", `/courses/${courseId}/outline`);

// ---------------------------------------------------------------- évaluation

export interface Assessment {
  id: string;
  program_id: string | null;
  code: string | null;
  title: string;
  kind: "positionnement" | "acquis_entree" | "acquis_sortie" | "examen";
  duration_minutes: number;
  pass_mark: number | null;
  retakes_allowed: number;
  active: boolean;
  questions?: number | null;
  _can?: Can;
}

export const getAssessments = (kind?: string) =>
  call<{ items: Assessment[]; _can?: Can }>(
    "GET",
    `/assessments${kind ? `?kind=${encodeURIComponent(kind)}` : ""}`,
  );

/** Une ligne du carnet de notes : une tentative d'un apprenant sur une évaluation.
 *  Les colonnes viennent de la vue `learn_gradebook`, relevées sur la base plutôt que
 *  supposées. */
export interface GradeRow {
  session_id: string;
  session_code: string | null;
  profile_id: string;
  apprenant_name: string | null;
  assessment_kind: string;
  assessment_title: string | null;
  attempt_no: number;
  score: number | null;
  max_score: number | null;
  percent: number | null;
  level: string | null;
  passed: boolean | null;
  status: string | null;
  review_status: string | null;
  submitted_at: string | null;
  _can?: Can;
}

/** Sans `session_id`, la vue renvoie tout ce que le profil a le droit de voir — ce qui est
 *  exactement ce qu'il faut à un apprenant qui consulte ses propres résultats. */
export const getGradebook = (sessionId?: string) =>
  call<{ items: GradeRow[] }>(
    "GET",
    `/gradebook${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ""}`,
  );

/** Résultats par bloc de compétences — l'indicateur 3 pour un organisme certificateur. */
export interface BlocRow {
  profile_id: string;
  apprenant_name: string | null;
  session_id: string;
  bloc: string;
  questions: number;
  score: number | null;
  max_score: number | null;
  percent: number | null;
}

export const getBlocs = (sessionId?: string) =>
  call<{ items: BlocRow[] }>(
    "GET",
    `/blocs${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ""}`,
  );

export const getReviewQueue = () =>
  call<{ items: GradeRow[] }>("GET", "/review-queue");

// ---------------------------------------------------------------- documents & coffre

export interface VaultObject {
  id: string;
  kind: string;
  filename: string | null;
  size_bytes: number | null;
  /** Deletion is refused before this date — by a trigger, not by convention. */
  retention_until: string | null;
  legal_hold: boolean;
  imported: boolean;
  created_at: string;
  _can?: Can;
}

export const getVault = (kind?: string) =>
  call<{ items: VaultObject[]; _can?: Can }>(
    "GET",
    `/vault${kind ? `?kind=${encodeURIComponent(kind)}` : ""}`,
  );

/** Déposer une pièce au coffre. `FormData`, donc pas de `content-type` posé à la main :
 *  le navigateur doit écrire lui-même la frontière multipart. */
export async function uploadVault(
  fichier: File,
  opts: { kind?: string; session_id?: string; subject_id?: string; visibility?: string } = {},
): Promise<VaultObject> {
  const fd = new FormData();
  fd.append("fichier", fichier);
  fd.append("kind", opts.kind ?? "piece_jointe");
  // `tenant` par défaut : une pièce déposée est destinée au dossier, donc à l'organisme
  // qui la traite. `self` la rendait illisible pour lui (migration 0033).
  fd.append("visibility", opts.visibility ?? "tenant");
  if (opts.session_id) fd.append("session_id", opts.session_id);
  if (opts.subject_id) fd.append("subject_id", opts.subject_id);
  return call<VaultObject>("POST", "/vault", fd);
}

/** L'URL signée d'une pièce — valable deux minutes, redemandée à chaque clic. */
export const getVaultUrl = (objectId: string) =>
  call<{ url: string; expires_in: number; filename: string }>(
    "GET",
    `/vault/${encodeURIComponent(objectId)}/url`,
  );

export const getDocuments = () =>
  call<{ items: Record<string, unknown>[]; _can?: Can }>("GET", "/documents");

// ---------------------------------------------------------------- personnes & rôles

export interface Person {
  id: string;
  full_name: string | null;
  email: string;
  username: string | null;
  phone: string | null;
  role: string;
  company_id: string | null;
  created_at: string;
}

export const getProfiles = (role?: string) =>
  call<{ items: Person[]; _can: Can }>(
    "GET",
    `/profiles${role ? `?role=${encodeURIComponent(role)}` : ""}`,
  );

// ---------------------------------------------------------------- Gestion (admin)

/** Les sociétés clientes de l'organisme, pour rattacher un compte « entreprise ». */
export const listCompanies = () =>
  call<{ items: { id: string; name: string; siret: string | null }[] }>("GET", "/companies");

export const createProfile = (body: {
  full_name: string;
  email: string;
  role: string;
  username?: string | null;
  phone?: string | null;
  company_id?: string | null;
  /** Le nom de la société : retrouvée si elle existe, créée sinon. */
  company_name?: string | null;
  password?: string | null;
}) =>
  call<Person & { password_set: boolean; invitation: { envoi: string; erreur: string | null } | null }>("POST", "/profiles", body);

export const createProgram = (body: {
  title: string;
  code?: string | null;
  nature?: string;
  objectives?: string | null;
  prerequisites?: string | null;
  duration_hours?: number;
  modality?: string;
  published?: boolean;
}) => call<Program>("POST", "/programs", body);

export const createSession = (body: {
  program_id: string;
  code?: string | null;
  title?: string | null;
  starts_on: string;
  ends_on: string;
  modality?: string;
  place?: string | null;
  capacity?: number;
}) => call<Session>("POST", "/sessions", body);

export const generateSlots = (
  sessionId: string,
  body: { dates: string[]; halves: ("am" | "pm")[]; formateur_id?: string | null; room_id?: string | null },
) => call<{ created: number }>("POST", `/sessions/${encodeURIComponent(sessionId)}/slots:generate`, body);

export const enrollLearner = (sessionId: string, apprenantId: string) =>
  call<unknown>("POST", `/sessions/${encodeURIComponent(sessionId)}/enrollments`, { apprenant_id: apprenantId });

export const getAssignableRoles = () =>
  call<{ items: { role: string; level: number; scope: string }[] }>("GET", "/roles");

export const getLeads = (status?: string) =>
  call<{ items: Record<string, unknown>[]; _can: Can }>(
    "GET",
    `/leads${status ? `?status=${encodeURIComponent(status)}` : ""}`,
  );

export interface LeadDetail {
  id: string;
  full_name: string;
  email: string;
  company_name: string | null;
  status: string;
  level: string | null;
  score: number | null;
  campaign: string | null;
  created_at: string;
  program_title: string | null;
  session_code: string | null;
  starts_on: string | null;
  phone: string | null;
  message: string | null;
  program_id: string | null;
  session_id: string | null;
  positioning_answers: { bloc: string | null; question: string; kind: string; reponse: string | string[] }[];
  events: { event: string; detail: Record<string, unknown>; actor_role: string; at: string }[];
  _can?: Can;
}

export const getLead = (id: string) => call<LeadDetail>("GET", `/leads/${encodeURIComponent(id)}`);

export const convertLead = (id: string, sessionId: string) =>
  call<{ lead_id: string; profile_id: string; enrollment_id: string; invited: boolean }>(
    "POST",
    `/leads/${encodeURIComponent(id)}/convert`,
    { session_id: sessionId, invite_redirect: `${window.location.origin}/learn` },
  );

export const refuseLead = (id: string, reason: string) =>
  call<unknown>("POST", `/leads/${encodeURIComponent(id)}/refuse`, { reason });

export const getActions = (status?: string) =>
  call<{ items: Record<string, unknown>[] }>(
    "GET",
    `/actions${status ? `?status=${encodeURIComponent(status)}` : ""}`,
  );

// ---------------------------------------------------------------- Le Noyau

export interface NoyauMeta {
  slug: string;
  title: string;
  version: number;
  bytes: number;
  updated_at: string;
  tenant_id: string | null;
  /** Le modèle éditable, ou `null` quand c'est celui du fichier qui fait foi. */
  model: Record<string, unknown> | null;
}

/** Les métadonnées du document, sans son contenu — la page a besoin de savoir qu'il
 *  existe avant de télécharger cent kilo-octets. */
export const getNoyauMeta = (slug = "noyau") =>
  call<NoyauMeta>("GET", `/noyau/${encodeURIComponent(slug)}`);

/**
 * L'URL du document lui-même, avec le jeton en paramètre.
 *
 * Une iframe ne porte pas d'en-tête `Authorization` : le navigateur charge son `src`
 * lui-même, sans passer par le code qui poserait le jeton. Le jeton voyage donc dans
 * l'URL — ce qui n'est pas anodin, et pourquoi la réponse est `private, no-store` et
 * `noindex`. L'alternative — charger le HTML en `fetch` puis le poser en `srcdoc` — évite
 * le jeton dans l'URL et c'est ce que fait la page : cette fonction reste pour le cas où
 * l'on voudrait ouvrir le document dans un onglet.
 */
export const noyauHtmlUrl = (slug: string, token: string) =>
  `${BASE}/noyau/${encodeURIComponent(slug)}/html?access_token=${encodeURIComponent(token)}`;

/** Le document, récupéré avec le jeton en en-tête puis posé en `srcdoc`. */
/** Un lien de lecture court pour l'iframe du Noyau (voir routes/noyau.py). */
export const lienNoyau = (slug = "noyau") =>
  call<{ url: string; expire_dans_s: number }>("POST", `/noyau/${encodeURIComponent(slug)}/lien`);

export async function getNoyauHtml(slug = "noyau"): Promise<string> {
  const token = await getAccessToken();
  if (!token) throw new GatewayError("Session expirée — reconnectez-vous.", "NO_SESSION");
  const res = await fetch(`${BASE}/noyau/${encodeURIComponent(slug)}/html`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new LearnError(
      res.status === 404
        ? "Ce document n'est pas accessible avec votre profil."
        : "Chargement impossible.",
      res.status, undefined, body);
  }
  return res.text();
}

/** Enregistrer le modèle éditable. Le super_admin seul — la base tranche. */
export const putNoyauModel = (model: Record<string, unknown>, slug = "noyau") =>
  call<{ slug: string; version: number; updated_at: string }>(
    "PUT", `/noyau/${encodeURIComponent(slug)}/model`, { model },
  );
