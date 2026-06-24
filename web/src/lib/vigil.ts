// VIGIL feature client (Meeting Room + AI Council) for the unified web app.
//
// Talks to the same gateway as ww.ts (winny_gateway on :8400) but to the VIGIL
// /v1/* namespace (council, rooms) ported from VIGIL backendv2. Auth is the
// shared Supabase JWT. SSE endpoints are consumed with fetch + a stream reader
// because EventSource cannot attach an Authorization header.
import { getAccessToken } from "./supabase";
import { WW_BASE, GatewayError } from "./ww";

async function vigilCall<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  const token = await getAccessToken();
  if (!token) throw new GatewayError("not signed in to VIGIL", "NO_SESSION");
  let res: Response;
  try {
    res = await fetch(`${WW_BASE}${path}`, {
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
  let payload: { ok?: boolean; data?: unknown; error?: string };
  try {
    payload = await res.json();
  } catch {
    payload = { ok: false, error: "BAD_JSON" };
  }
  if (!res.ok || payload.ok === false) {
    throw new GatewayError(payload.error || `HTTP ${res.status}`, "HTTP_ERROR", res.status);
  }
  return payload.data as T;
}

// ── Types (mirror winny_gateway/routes/vigil/*) ─────────────────────────────
export interface CouncilTaskInfo {
  description: string;
  categories: string[];
  requirements: string[];
  pattern_focus: string[];
  consensus_threshold: number;
  readiness_threshold: number;
  sla_ms: number;
}

export interface Intervention {
  parsed: boolean;
  should_intervene?: boolean | null;
  intervention_text?: string | null;
  category?: string | null;
  confidence?: number | null;
  reasoning?: string | null;
}

export interface CouncilRecord {
  run_id: string;
  task: string;
  verdict: {
    consensus_reached: boolean;
    readiness_pass: boolean;
    readiness_score: number;
    chairman_invoked: boolean;
    final_intervention: Intervention;
  };
  totals: { cost_usd: number; latency_ms_total: number; n_llm_calls: number; tokens_in: number; tokens_out: number };
  stages: Record<string, unknown>;
}

export interface RoomMember {
  id: string;
  name: string;
  title: string;
  lens: string;
  model?: string | null;
  voiceColor?: string;
  status?: string;
}

export interface AvatarSession {
  provider: string;
  provider_session_id?: string;
  conversation_id?: string;
  conversation_url?: string | null;
  livekit_url?: string | null;
  persona?: string;
  status?: string;
  share_token?: string;
  fallback_chain?: unknown[];
}

export interface PublicMeeting {
  room_title: string | null;
  live_url: string | null;
  provider: string | null;
  persona: string | null;
  has_live: boolean;
}

export interface GuestRoomJoin {
  room_title: string | null;
  token: string;
  url: string | null;
  room: string;
  identity: string;
}

/** External (non-account) guest joins the shared LiveKit room via a share token. */
export async function joinGuestRoom(shareToken: string, name: string): Promise<GuestRoomJoin> {
  const res = await fetch(`${WW_BASE}/v1/rooms/guest/${encodeURIComponent(shareToken)}/join`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify({ name }),
  });
  const payload = (await res.json().catch(() => ({}))) as { ok?: boolean; data?: GuestRoomJoin; error?: string };
  if (!res.ok || payload.ok === false) throw new GatewayError(payload.error || `HTTP ${res.status}`, "HTTP_ERROR", res.status);
  return payload.data as GuestRoomJoin;
}

/** Resolve a share token → the live meeting (no auth — for external guests). */
export async function resolvePublicMeeting(shareToken: string): Promise<PublicMeeting> {
  const res = await fetch(`${WW_BASE}/v1/rooms/meeting/${encodeURIComponent(shareToken)}`, {
    headers: { accept: "application/json" },
  });
  const payload = (await res.json().catch(() => ({}))) as { ok?: boolean; data?: PublicMeeting; error?: string };
  if (!res.ok || payload.ok === false) throw new GatewayError(payload.error || `HTTP ${res.status}`, "HTTP_ERROR", res.status);
  return payload.data as PublicMeeting;
}

export interface LiveKitJoin {
  token: string;
  url: string | null;
  room: string;
  identity: string;
}

export interface MeetingCanvasNode {
  id: string;
  label: string;
  kind: "problem" | "decision" | "outcome" | string;
  x: number;
  y: number;
}
export interface MeetingCanvas {
  nodes: MeetingCanvasNode[];
  edges: { from: string; to: string }[];
  table: { columns: string[]; rows: string[][] };
}

export interface CanvasBlock {
  text: string;
  kind: string;
  color: string;
  lens?: string | null;
}
export interface CanvasBrainstormResult {
  blocks: CanvasBlock[];
  lens: string;
  stub: boolean;
}

export interface MeetingSummary {
  summary_markdown: string;
  decisions: string[];
  next_steps: string[];
  commitments: { text: string; owner?: string; due?: string }[];
  follow_ups: { name: string; company?: string; next_step?: string }[];
  artifact_id: string | null;
  canvas: MeetingCanvas | null;
  commitments_saved: number;
  contacts_saved: number;
  stub: boolean;
}

export interface LiveIntervention {
  speak: boolean;
  message?: string;
  urgency?: "low" | "normal" | "high";
  reason?: string;
  touched_specialties?: string[];
  cost_usd?: number;
  stub?: boolean;
}

export interface Room {
  id: string;
  title: string;
  lens: string;
  members: RoomMember[];
  transcript: { speaker: string; text: string; ts: string }[];
  created_at: string;
}

export interface SseEvent {
  event: string;
  data: Record<string, unknown>;
}

export interface BrainstormApproach {
  name: string;
  summary: string;
  tradeoffs: string;
  recommended: boolean;
}

export interface BrainstormPlan {
  understanding: string;
  clarifying_questions: string[];
  approaches: BrainstormApproach[];
  recommended_design: string;
}

export interface Artifact {
  id: string;
  title: string;
  kind: string;
  brief: string;
  approach: string;
  content: string;
  canvas: MeetingCanvas | null;
  tldraw: unknown | null;
  stub: boolean;
  revisions: number;
  created_at: string;
  updated_at: string;
}

export interface FinanceAccount {
  id: string;
  name: string;
  type: string;
  created_at: string;
}

export interface FinanceTxn {
  id: string;
  txn_date: string;
  description: string;
  amount: number;
  currency: string;
  category: string | null;
  account_id: string | null;
  status: string;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface FinanceSummary {
  income: number;
  expense: number;
  net: number;
  by_category: Record<string, number>;
  transaction_count: number;
  reconciled_count: number;
  reconcile_progress: number;
}

export interface CrmContact {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  company: string | null;
  title: string | null;
  tags: string[];
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface CrmDeal {
  id: string;
  title: string;
  contact_id: string | null;
  stage: string;
  value: number;
  currency: string;
  probability: number;
  expected_close: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface CrmPipeline {
  stages: Record<string, { count: number; value: number; weighted: number }>;
  open_value: number;
  weighted_open_value: number;
  deal_count: number;
}

export const DEAL_STAGES = ["lead", "qualified", "proposal", "negotiation", "won", "lost"] as const;

export interface MailMessage {
  id: string;
  external_id: string | null;
  thread_id: string | null;
  folder: string;
  from_addr: string | null;
  from_name: string | null;
  to_addrs: string[];
  subject: string | null;
  snippet: string | null;
  body: string | null;
  received_at: string | null;
  category: string | null;
  priority: string;
  triage_score: number | null;
  status: string;
  tags: string[];
  triaged: boolean;
  created_at: string;
  updated_at: string;
}

export interface MailDraft {
  id: string;
  in_reply_to: string | null;
  to_addrs: string[];
  subject: string | null;
  body: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface MailTriageSummary {
  total: number;
  unread: number;
  triaged: number;
  untriaged: number;
  by_category: Record<string, number>;
  by_priority: Record<string, number>;
}

export const MAIL_CATEGORIES = ["urgent", "respond", "fyi", "newsletter", "spam", "archive"] as const;

// ── Ops Team (agentic company) ──────────────────────────────────────────────
export interface OpsHealth {
  success_rate: number | null;
  avg_cost_usd: number;
  p50_ms: number;
  last_result: string | null;
  last_run_at?: string;
  runs: number;
}
export interface OpsUsage {
  plan: string;
  plan_name: string;
  price_eur_cents: number | null;
  runs_today: number;
  runs_month: number;
  cost_usd_month: number;
  daily_cap: number | null;
  remaining_today: number | null;
  limits: Record<string, unknown>;
}
export interface Department {
  id: string;
  slug: string;
  name: string;
  head_lens: string | null;
  mandate: string;
  kpis: { key: string; label: string; target: string }[];
  status: "provisioning" | "live" | "failing";
  paused: boolean;
  guardrails: Record<string, unknown>;
  health: OpsHealth | Record<string, never>;
  jobs: string[];
  primary_job: string | null;
  created_at: string;
  updated_at: string;
}
export interface OpsTask {
  id: string;
  department_id: string;
  job: string;
  trigger: string;
  title: string | null;
  status: "queued" | "working" | "done" | "blocked" | "halted";
  accepted: boolean | null;
  cost_usd: number;
  wall_ms: number;
  tool_calls: number;
  output_artifact_id: string | null;
  error: string | null;
  created_at: string;
  reason?: string;
  summary?: string;
}
export interface OpsEvent {
  id: string;
  department_id: string | null;
  task_id: string | null;
  kind: string;
  summary: string;
  ts: string;
}

// ── Finance connector (bank / accounting via API) ───────────────────────────
export interface ProviderKey {
  name: string;
  set: boolean;
}
export interface ProviderStatus {
  id: string;
  name: string;
  kind: "bank" | "accounting" | string;
  implemented: boolean;
  configured: boolean;
  required_keys: ProviderKey[];
}
export interface FinanceConnection {
  id: string;
  provider: string;
  institution: string | null;
  status: string;
  accounts_count: number;
  last_synced_at: string | null;
  token_masked: string;
  created_at: string;
}
export interface FinanceConnectStatus {
  providers: ProviderStatus[];
  connections: FinanceConnection[];
  plaid_env: string;
}

// ── Connector kit (system-of-record connectors) ─────────────────────────────
export interface ConnectProvider {
  id: string;
  kind: string;
  actions?: { action: string; params: string[]; label?: string }[];
}
export interface OutboundAction {
  id: string;
  provider: string;
  connection_id: string | null;
  action: string;
  params: Record<string, unknown>;
  status: "pending" | "executed" | "rejected" | "failed";
  result: Record<string, unknown> | null;
  error: string | null;
  department_id: string | null;
  requested_by: string;
  created_at: string;
}
export interface Connection {
  id: string;
  provider: string;
  kind: string;
  external_account: string | null;
  status: string;
  token_masked: string;
  last_synced_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}
export interface ConnectStatus {
  providers: ConnectProvider[];
  connections: Connection[];
}

export const vigil = {
  connect: {
    status: () => vigilCall<ConnectStatus>("GET", "/v1/connect/status"),
    token: (provider: string, token: string, account?: string) =>
      vigilCall<{ connection: Connection }>("POST", `/v1/connect/${provider}/token`, { token, ...(account ? { account } : {}) }),
    sync: (provider: string, connection_id: string) =>
      vigilCall<Record<string, unknown>>("POST", `/v1/connect/${provider}/sync`, { connection_id }),
    disconnect: (id: string) =>
      vigilCall<{ disconnected: string }>("DELETE", `/v1/connect/connections/${id}`),
    actions: (status?: string) =>
      vigilCall<{ actions: OutboundAction[] }>("GET", `/v1/connect/actions${status ? `?status=${status}` : ""}`),
    propose: (connection_id: string, action: string, params: Record<string, unknown>) =>
      vigilCall<{ action: OutboundAction }>("POST", "/v1/connect/actions", { connection_id, action, params }),
    approve: (id: string) => vigilCall<{ action: OutboundAction }>("POST", `/v1/connect/actions/${id}/approve`),
    reject: (id: string) => vigilCall<{ action: OutboundAction }>("POST", `/v1/connect/actions/${id}/reject`),
  },
  ops: {
    departments: () => vigilCall<{ departments: Department[] }>("GET", "/v1/ops/departments"),
    department: (id: string) => vigilCall<Department>("GET", `/v1/ops/departments/${id}`),
    run: (id: string, job?: string, input?: Record<string, unknown>) =>
      vigilCall<{ task: OpsTask }>("POST", `/v1/ops/departments/${id}/run`, {
        ...(job ? { job } : {}),
        ...(input ? { input } : {}),
      }),
    selftest: (id: string) => vigilCall<{ task: OpsTask }>("POST", `/v1/ops/departments/${id}/selftest`),
    health: (id: string) => vigilCall<{ health: OpsHealth }>("GET", `/v1/ops/departments/${id}/health`),
    tasks: (departmentId?: string, limit = 50) => {
      const qs = new URLSearchParams();
      if (departmentId) qs.set("department", departmentId);
      qs.set("limit", String(limit));
      return vigilCall<{ tasks: OpsTask[] }>("GET", `/v1/ops/tasks?${qs.toString()}`);
    },
    feed: (limit = 30) => vigilCall<{ events: OpsEvent[] }>("GET", `/v1/ops/feed?limit=${limit}`),
    usage: () => vigilCall<OpsUsage>("GET", "/v1/ops/usage"),
    pauseAll: () => vigilCall<{ paused: number }>("POST", "/v1/ops/pause-all"),
    resumeAll: () => vigilCall<{ resumed: number }>("POST", "/v1/ops/resume-all"),
  },
  council: {
    tasks: () => vigilCall<{ tasks: Record<string, CouncilTaskInfo> }>("GET", "/v1/council/tasks"),
    orchestrate: (task: string, transcript: string, question?: string) =>
      vigilCall<CouncilRecord>("POST", "/v1/council/orchestrate", { task, transcript, question }),
  },
  rooms: {
    create: (title: string, lens?: string) => vigilCall<Room>("POST", "/v1/rooms", { title, lens }),
    list: () => vigilCall<{ rooms: Room[] }>("GET", "/v1/rooms"),
    get: (id: string) => vigilCall<Room>("GET", `/v1/rooms/${id}`),
    remove: (id: string) => vigilCall("DELETE", `/v1/rooms/${id}`),
    addMember: (id: string, member: { id: string; name?: string; title?: string; lens?: string }) =>
      vigilCall<RoomMember>("POST", `/v1/rooms/${id}/members`, member),
    postMessage: (id: string, text: string, speaker = "You") =>
      vigilCall("POST", `/v1/rooms/${id}/messages`, { text, speaker }),
    transcript: (id: string) =>
      vigilCall<{ transcript: Room["transcript"] }>("GET", `/v1/rooms/${id}/transcript`),
    importTranscript: (id: string, lines: string[], source = "Meet") =>
      vigilCall<{ imported: number; transcript: Room["transcript"] }>(
        "POST",
        `/v1/rooms/${id}/import-transcript`,
        { lines, source },
      ),
    interventionCheck: (id: string, topic?: string, activeSpecialties?: string[]) =>
      vigilCall<LiveIntervention>("POST", `/v1/rooms/${id}/intervention-check`, {
        topic,
        active_specialties: activeSpecialties,
      }),
    weights: (id: string) =>
      vigilCall<{ weights: Record<string, number>; defaults: Record<string, number> }>("GET", `/v1/rooms/${id}/weights`),
    avatarStatus: () =>
      vigilCall<{ provider_order: string[]; tavus: { configured: boolean }; beyond_presence: { configured: boolean } }>("GET", "/v1/rooms/avatar/status"),
    startAvatar: (id: string, input: { persona: string; language?: string; greeting?: string; evidence?: string }) =>
      vigilCall<AvatarSession>("POST", `/v1/rooms/${id}/avatar-session`, input),
    endAvatar: (id: string) => vigilCall("DELETE", `/v1/rooms/${id}/avatar-session`),
    livekitToken: (id: string) => vigilCall<LiveKitJoin>("POST", `/v1/rooms/${id}/livekit-token`),
    share: (id: string) => vigilCall<{ share_token: string }>("POST", `/v1/rooms/${id}/share`),
    summarize: (id: string) => vigilCall<MeetingSummary>("POST", `/v1/rooms/${id}/summarize`, {}),
    bringAgent: (id: string, persona: string, evidence?: string) =>
      vigilCall<{ dispatched: boolean; persona: string; room: string }>("POST", `/v1/rooms/${id}/bring-agent`, { persona, evidence }),
  },
  studio: {
    brainstorm: (brief: string, kind: string, grounding?: string) =>
      vigilCall<{ kind: string; brief: string; stub: boolean; plan: BrainstormPlan }>(
        "POST",
        "/v1/artifacts/brainstorm",
        { brief, kind, grounding },
      ),
    create: (input: { title: string; kind: string; brief: string; approach: string; grounding?: string }) =>
      vigilCall<Artifact>("POST", "/v1/artifacts", input),
    list: () => vigilCall<{ artifacts: Artifact[] }>("GET", "/v1/artifacts"),
    get: (id: string) => vigilCall<Artifact>("GET", `/v1/artifacts/${id}`),
    remove: (id: string) => vigilCall("DELETE", `/v1/artifacts/${id}`),
    refine: (id: string, instruction: string) =>
      vigilCall<Artifact>("POST", `/v1/artifacts/${id}/refine`, { instruction }),
    saveCanvas: (id: string, patch: { canvas?: MeetingCanvas; tldraw?: unknown }) =>
      vigilCall<{ saved: string }>("PATCH", `/v1/artifacts/${id}/canvas`, patch),
    canvasBrainstorm: (input: { prompt?: string; board_text?: string; lens?: string; topic?: string }) =>
      vigilCall<CanvasBrainstormResult>("POST", "/v1/artifacts/canvas-brainstorm", input),
    blankCanvas: (title?: string) => vigilCall<Artifact>("POST", "/v1/artifacts/blank-canvas", { title }),
    canvasDiagram: (input: { prompt: string; board_text?: string; topic?: string }) =>
      vigilCall<{ nodes: MeetingCanvasNode[]; edges: { from: string; to: string }[] }>(
        "POST",
        "/v1/artifacts/canvas-diagram",
        input,
      ),
  },
  finance: {
    accounts: () => vigilCall<{ accounts: FinanceAccount[] }>("GET", "/v1/finance/accounts"),
    addAccount: (name: string, type: string) =>
      vigilCall<FinanceAccount>("POST", "/v1/finance/accounts", { name, type }),
    transactions: (params?: { status?: string; category?: string; limit?: number }) => {
      const qs = new URLSearchParams();
      if (params?.status) qs.set("status", params.status);
      if (params?.category) qs.set("category", params.category);
      if (params?.limit) qs.set("limit", String(params.limit));
      const suffix = qs.toString() ? `?${qs.toString()}` : "";
      return vigilCall<{ transactions: FinanceTxn[] }>("GET", `/v1/finance/transactions${suffix}`);
    },
    addTransaction: (input: {
      amount: number;
      description?: string;
      txn_date?: string;
      currency?: string;
      category?: string;
      account_id?: string;
      source?: string;
    }) => vigilCall<FinanceTxn>("POST", "/v1/finance/transactions", input),
    updateTransaction: (id: string, patch: Partial<Pick<FinanceTxn, "description" | "amount" | "category" | "account_id" | "status" | "txn_date">>) =>
      vigilCall<FinanceTxn>("PATCH", `/v1/finance/transactions/${id}`, patch),
    removeTransaction: (id: string) => vigilCall("DELETE", `/v1/finance/transactions/${id}`),
    summary: () => vigilCall<FinanceSummary>("GET", "/v1/finance/summary"),
    connect: {
      status: () => vigilCall<FinanceConnectStatus>("GET", "/v1/finance/connect/status"),
      keys: (provider: string, values: Record<string, string>) =>
        vigilCall<{ saved: number; status: FinanceConnectStatus }>("POST", "/v1/finance/connect/keys", { provider, values }),
      linkToken: () => vigilCall<{ link_token: string | null }>("POST", "/v1/finance/connect/link-token"),
      sandbox: () => vigilCall<{ connection: FinanceConnection }>("POST", "/v1/finance/connect/sandbox"),
      exchange: (public_token: string, institution?: string) =>
        vigilCall<{ connection: FinanceConnection }>("POST", "/v1/finance/connect/exchange", { public_token, institution }),
      sync: (connection_id?: string) =>
        vigilCall<{ accounts: number; transactions_added: number; connections: number }>(
          "POST", "/v1/finance/connect/sync", connection_id ? { connection_id } : {}),
      disconnect: (id: string) => vigilCall<{ disconnected: string }>("DELETE", `/v1/finance/connect/connections/${id}`),
    },
  },
  crm: {
    contacts: () => vigilCall<{ contacts: CrmContact[] }>("GET", "/v1/crm/contacts"),
    addContact: (input: Partial<Omit<CrmContact, "id" | "created_at" | "updated_at">> & { name: string }) =>
      vigilCall<CrmContact>("POST", "/v1/crm/contacts", input),
    updateContact: (id: string, patch: Partial<Omit<CrmContact, "id" | "created_at" | "updated_at">>) =>
      vigilCall<CrmContact>("PATCH", `/v1/crm/contacts/${id}`, patch),
    removeContact: (id: string) => vigilCall("DELETE", `/v1/crm/contacts/${id}`),
    deals: (stage?: string) =>
      vigilCall<{ deals: CrmDeal[] }>("GET", `/v1/crm/deals${stage ? `?stage=${encodeURIComponent(stage)}` : ""}`),
    addDeal: (input: Partial<Omit<CrmDeal, "id" | "created_at" | "updated_at">> & { title: string }) =>
      vigilCall<CrmDeal>("POST", "/v1/crm/deals", input),
    updateDeal: (id: string, patch: Partial<Omit<CrmDeal, "id" | "created_at" | "updated_at">>) =>
      vigilCall<CrmDeal>("PATCH", `/v1/crm/deals/${id}`, patch),
    removeDeal: (id: string) => vigilCall("DELETE", `/v1/crm/deals/${id}`),
    pipeline: () => vigilCall<CrmPipeline>("GET", "/v1/crm/pipeline"),
  },
  mail: {
    messages: (params?: { category?: string; status?: string; folder?: string; limit?: number }) => {
      const qs = new URLSearchParams();
      if (params?.category) qs.set("category", params.category);
      if (params?.status) qs.set("status", params.status);
      if (params?.folder) qs.set("folder", params.folder);
      if (params?.limit) qs.set("limit", String(params.limit));
      const suffix = qs.toString() ? `?${qs.toString()}` : "";
      return vigilCall<{ messages: MailMessage[] }>("GET", `/v1/mail/messages${suffix}`);
    },
    ingest: (input: Partial<Omit<MailMessage, "id" | "created_at" | "updated_at" | "triaged" | "triage_score">>) =>
      vigilCall<MailMessage>("POST", "/v1/mail/messages", input),
    sync: (folder = "INBOX", limit = 50) =>
      vigilCall<{ available: boolean; reason: string | null; fetched: number; synced: number }>(
        "POST",
        `/v1/mail/sync?folder=${encodeURIComponent(folder)}&limit=${limit}`,
      ),
    update: (id: string, patch: { category?: string; priority?: string; status?: string; tags?: string[] }) =>
      vigilCall<MailMessage>("PATCH", `/v1/mail/messages/${id}`, patch),
    triage: (id: string) =>
      vigilCall<{ message: MailMessage; classification: Record<string, unknown>; stub: boolean }>(
        "POST",
        `/v1/mail/messages/${id}/triage`,
      ),
    remove: (id: string) => vigilCall("DELETE", `/v1/mail/messages/${id}`),
    summary: () => vigilCall<MailTriageSummary>("GET", "/v1/mail/triage/summary"),
    drafts: () => vigilCall<{ drafts: MailDraft[] }>("GET", "/v1/mail/drafts"),
    addDraft: (input: { to_addrs?: string[]; subject?: string; body?: string; in_reply_to?: string }) =>
      vigilCall<MailDraft>("POST", "/v1/mail/drafts", input),
    updateDraft: (id: string, patch: { to_addrs?: string[]; subject?: string; body?: string; status?: string }) =>
      vigilCall<MailDraft>("PATCH", `/v1/mail/drafts/${id}`, patch),
    removeDraft: (id: string) => vigilCall("DELETE", `/v1/mail/drafts/${id}`),
  },
};

// ── Google Meet bot ─────────────────────────────────────────────────────────
// Unlike the rest of this file, these call /api/plugins/google_meet/* — the
// dashboard plugin API on the OVH Hermes — through the Supabase-gated ops
// proxy (web/api/ops.js), NOT the gateway. That's where the Playwright Meet
// bot actually runs. One product login covers it (the proxy injects the
// dashboard session token).
export interface MeetBotStatus {
  success?: boolean;
  ok?: boolean;
  state?: string;
  url?: string;
  mode?: string;
  reason?: string;
  error?: string;
  [k: string]: unknown;
}

async function meetCall<T = MeetBotStatus>(method: string, path: string, body?: unknown): Promise<T> {
  const token = await getAccessToken();
  if (!token) throw new GatewayError("not signed in", "NO_SESSION");
  const res = await fetch(`/api/plugins/google_meet/${path}`, {
    method,
    headers: {
      authorization: `Bearer ${token}`,
      ...(body != null ? { "content-type": "application/json" } : {}),
    },
    body: body != null ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const txt = await res.text().catch(() => res.statusText);
    throw new GatewayError(`meet ${path}: HTTP ${res.status} ${txt}`, "HTTP_ERROR", res.status);
  }
  return res.json();
}

export const googleMeet = {
  join: (url: string, persona: string, mode: "transcribe" | "realtime" = "transcribe") =>
    meetCall("POST", "join", { url, mode, guest_name: `VIGIL ${persona}` }),
  status: () => meetCall("GET", "status"),
  transcript: (last?: number) =>
    meetCall<{ transcript?: string; lines?: string[] } & MeetBotStatus>(
      "GET",
      last ? `transcript?last=${last}` : "transcript",
    ),
  say: (text: string) => meetCall("POST", "say", { text }),
  leave: () => meetCall("POST", "leave"),
};

// ── SSE helpers (fetch-based so we can send the bearer token) ───────────────
async function* sseStream(
  path: string,
  init: { method: string; body?: unknown },
): AsyncGenerator<SseEvent> {
  const token = await getAccessToken();
  if (!token) throw new GatewayError("not signed in to VIGIL", "NO_SESSION");
  const res = await fetch(`${WW_BASE}${path}`, {
    method: init.method,
    headers: {
      "content-type": "application/json",
      accept: "text/event-stream",
      authorization: `Bearer ${token}`,
    },
    body: init.body != null ? JSON.stringify(init.body) : undefined,
  });
  if (!res.ok || !res.body) {
    throw new GatewayError(`stream failed: HTTP ${res.status}`, "HTTP_ERROR", res.status);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const evt = parseFrame(frame);
      if (evt) yield evt;
    }
  }
}

function parseFrame(frame: string): SseEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return { event, data: { raw: dataLines.join("\n") } };
  }
}

/** Convene the council over a room's transcript; yields stage events then `complete`. */
export function streamRoomCouncil(
  roomId: string,
  task?: string,
  question?: string,
  source: "summary" | "transcript" = "transcript",
): AsyncGenerator<SseEvent> {
  const qs = new URLSearchParams();
  if (task) qs.set("task", task);
  if (question) qs.set("question", question);
  if (source) qs.set("source", source);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return sseStream(`/v1/rooms/${roomId}/stream${suffix}`, { method: "GET" });
}

/** Stream a one-off council orchestration (no room). */
export function streamOrchestrate(task: string, transcript: string, question?: string): AsyncGenerator<SseEvent> {
  return sseStream("/v1/council/orchestrate/stream", { method: "POST", body: { task, transcript, question } });
}
