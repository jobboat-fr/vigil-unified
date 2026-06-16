import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Button } from "@nous-research/ui/ui/components/button";
import { vigil, streamRoomCouncil, type Room, type CouncilRecord, type SseEvent } from "@/lib/vigil";
import { GatewayError } from "@/lib/ww";

// The 4 council lenses, aligned with the Deal Board advisor templates.
const LENSES = [
  { key: "cfo_review", member: "cfo", label: "CFO", color: "#2563EB" },
  { key: "tech_review", member: "cto", label: "CTO", color: "#7C3AED" },
  { key: "legal_review", member: "legal", label: "Legal", color: "#059669" },
  { key: "product_review", member: "product", label: "Product", color: "#DB2777" },
] as const;

const STAGE_LABEL: Record<string, string> = {
  start: "Council convened",
  primary_done: "Primary advisor responded",
  reviewer_done: "Reviewer scored",
  consensus_result: "Consensus computed",
  chairman_done: "Chairman synthesized",
  behavioral_done: "Behavioral overlay",
  complete: "Verdict ready",
  error: "Error",
};

export default function MeetingRoomPage() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [active, setActive] = useState<Room | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [speaker, setSpeaker] = useState("You");
  const [text, setText] = useState("");
  const [convening, setConvening] = useState(false);
  const [events, setEvents] = useState<SseEvent[]>([]);
  const [record, setRecord] = useState<CouncilRecord | null>(null);

  const refresh = useCallback(async () => {
    try {
      const { rooms } = await vigil.rooms.list();
      setRooms(rooms);
      setAuthError(null);
    } catch (e) {
      if (e instanceof GatewayError && e.code === "NO_SESSION") setAuthError("Sign in to VIGIL to use the Meeting Room.");
      else setAuthError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const reloadActive = useCallback(async (id: string) => {
    setActive(await vigil.rooms.get(id));
  }, []);

  const createRoom = async () => {
    const room = await vigil.rooms.create(`Advisory Session ${new Date().toLocaleString()}`, "cfo_review");
    await refresh();
    setActive(room);
    setRecord(null);
    setEvents([]);
  };

  const addAdvisor = async (memberId: string) => {
    if (!active) return;
    await vigil.rooms.addMember(active.id, { id: memberId });
    await reloadActive(active.id);
  };

  const sendMessage = async () => {
    if (!active || !text.trim()) return;
    await vigil.rooms.postMessage(active.id, text.trim(), speaker.trim() || "You");
    setText("");
    await reloadActive(active.id);
  };

  const convene = async (lens: string) => {
    if (!active || convening) return;
    setConvening(true);
    setEvents([]);
    setRecord(null);
    try {
      for await (const evt of streamRoomCouncil(active.id, lens)) {
        setEvents((prev) => [...prev, evt]);
        if (evt.event === "complete") {
          const rec = (evt.data as { record?: CouncilRecord }).record;
          if (rec) setRecord(rec);
        }
      }
    } catch (e) {
      setEvents((prev) => [...prev, { event: "error", data: { error: (e as Error).message } }]);
    } finally {
      setConvening(false);
    }
  };

  if (authError) {
    return (
      <Card>
        <CardHeader><CardTitle>Meeting Room</CardTitle></CardHeader>
        <CardContent><p className="text-text-secondary text-sm py-6 text-center">{authError}</p></CardContent>
      </Card>
    );
  }

  const verdict = record?.verdict;
  const fi = verdict?.final_intervention;

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[260px_1fr_minmax(320px,420px)] gap-4">
      {/* Rooms */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Rooms · {rooms.length}</CardTitle>
          <Button size="sm" onClick={() => void createRoom()}>New</Button>
        </CardHeader>
        <CardContent>
          {rooms.length === 0 ? (
            <p className="text-text-secondary text-sm py-4 text-center">No rooms yet. Create one.</p>
          ) : (
            <ul className="space-y-1">
              {rooms.map((r) => (
                <li key={r.id}>
                  <button
                    onClick={() => void reloadActive(r.id)}
                    className={`w-full text-left rounded px-2 py-1.5 text-sm ${active?.id === r.id ? "bg-current/10 font-medium" : "hover:bg-current/5"}`}
                  >
                    <span className="block truncate text-foreground/90">{r.title}</span>
                    <span className="block text-[10px] text-text-secondary">{r.members.length} advisors · {r.transcript.length} msgs</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* Room detail */}
      <Card>
        <CardHeader><CardTitle>{active ? active.title : "Select a room"}</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          {!active ? (
            <p className="text-text-secondary text-sm py-6 text-center">Pick a room on the left, or create one.</p>
          ) : (
            <>
              {/* Deal Board */}
              <div>
                <div className="text-[10px] font-mono uppercase tracking-wide text-text-secondary mb-1.5">Deal Board — invite advisors</div>
                <div className="flex flex-wrap gap-2">
                  {LENSES.map((l) => {
                    const added = active.members.some((m) => m.id === l.member);
                    return (
                      <button
                        key={l.member}
                        onClick={() => void addAdvisor(l.member)}
                        className="text-xs px-2.5 py-1 rounded-full border"
                        style={{ borderColor: `${l.color}66`, color: l.color, background: added ? `${l.color}1a` : "transparent" }}
                      >
                        {added ? "✓ " : "+ "}{l.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Transcript */}
              <div>
                <div className="text-[10px] font-mono uppercase tracking-wide text-text-secondary mb-1.5">Transcript · {active.transcript.length}</div>
                <ul className="space-y-1 max-h-[34vh] overflow-y-auto pr-1">
                  {active.transcript.map((m, i) => (
                    <li key={i} className="text-sm leading-snug">
                      <span className="font-mono text-foreground/90">{m.speaker}:</span>{" "}
                      <span className="text-foreground/80">{m.text}</span>
                    </li>
                  ))}
                  {active.transcript.length === 0 && (
                    <li className="text-text-secondary text-sm">Empty — add what was said, then convene the council.</li>
                  )}
                </ul>
              </div>

              {/* Message input */}
              <div className="flex gap-2">
                <input
                  value={speaker}
                  onChange={(e) => setSpeaker(e.target.value)}
                  className="w-24 rounded border border-current/20 bg-transparent px-2 py-1.5 text-sm"
                  placeholder="Speaker"
                />
                <input
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") void sendMessage(); }}
                  className="flex-1 rounded border border-current/20 bg-transparent px-2 py-1.5 text-sm"
                  placeholder="What was said…"
                />
                <Button size="sm" onClick={() => void sendMessage()} disabled={!text.trim()}>Add</Button>
              </div>

              {/* Convene */}
              <div>
                <div className="text-[10px] font-mono uppercase tracking-wide text-text-secondary mb-1.5">Convene council</div>
                <div className="flex flex-wrap gap-2">
                  {LENSES.map((l) => (
                    <Button key={l.key} size="sm" disabled={convening} onClick={() => void convene(l.key)}>
                      {l.label} review
                    </Button>
                  ))}
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Council stream + verdict */}
      <Card>
        <CardHeader><CardTitle>{convening ? "Council in session…" : "Council"}</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {events.length === 0 && !record ? (
            <p className="text-text-secondary text-sm py-6 text-center">Convene a council to see advisors weigh in.</p>
          ) : (
            <ul className="space-y-1">
              {events.map((e, i) => (
                <li key={i} className="text-xs flex items-center gap-2">
                  <span className="text-text-secondary">{e.event === "complete" ? "✓" : e.event === "error" ? "✕" : "•"}</span>
                  <span className="text-foreground/85">{STAGE_LABEL[e.event] || e.event}</span>
                  {typeof (e.data as { model?: string }).model === "string" && (
                    <span className="text-text-secondary font-mono">{(e.data as { model?: string }).model}</span>
                  )}
                  {typeof (e.data as { weighted_overall?: number }).weighted_overall === "number" && (
                    <span className="text-text-secondary">score {(e.data as { weighted_overall?: number }).weighted_overall}</span>
                  )}
                </li>
              ))}
            </ul>
          )}

          {verdict && fi && (
            <div className="rounded-lg border border-current/15 p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-mono uppercase tracking-wide text-text-secondary">Verdict</span>
                <span
                  className="text-xs font-mono px-2 py-0.5 rounded"
                  style={{
                    color: verdict.readiness_pass ? "#00ff88" : "#f59e0b",
                    background: verdict.readiness_pass ? "#00ff881a" : "#f59e0b1a",
                  }}
                >
                  readiness {verdict.readiness_score} · {verdict.consensus_reached ? "consensus" : "chairman"}
                </span>
              </div>
              {fi.intervention_text && <p className="text-sm text-foreground/90">{fi.intervention_text}</p>}
              {fi.category && <p className="text-xs text-text-secondary">Category: {fi.category} · confidence {fi.confidence ?? "—"}</p>}
              {fi.reasoning && <p className="text-xs text-text-secondary italic">{fi.reasoning}</p>}
              <p className="text-[10px] text-text-secondary font-mono">
                {record.totals.n_llm_calls} calls · {record.totals.latency_ms_total}ms · ${record.totals.cost_usd}
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
