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
  stub: boolean;
  revisions: number;
  created_at: string;
  updated_at: string;
}

export const vigil = {
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
  },
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
export function streamRoomCouncil(roomId: string, task?: string, question?: string): AsyncGenerator<SseEvent> {
  const qs = new URLSearchParams();
  if (task) qs.set("task", task);
  if (question) qs.set("question", question);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return sseStream(`/v1/rooms/${roomId}/stream${suffix}`, { method: "GET" });
}

/** Stream a one-off council orchestration (no room). */
export function streamOrchestrate(task: string, transcript: string, question?: string): AsyncGenerator<SseEvent> {
  return sseStream("/v1/council/orchestrate/stream", { method: "POST", body: { task, transcript, question } });
}
