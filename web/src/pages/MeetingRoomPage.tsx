import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Button } from "@nous-research/ui/ui/components/button";
import { vigil, streamRoomCouncil, type Room, type CouncilRecord, type SseEvent, type LiveIntervention, type AvatarSession } from "@/lib/vigil";

const PERSONAS = ["CFO", "CTO", "COO", "CRM", "CRO", "advisor"] as const;
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
  const [liveAdvisor, setLiveAdvisor] = useState(false);
  const [suggestion, setSuggestion] = useState<LiveIntervention | null>(null);
  const [avatarSession, setAvatarSession] = useState<AvatarSession | null>(null);
  const [persona, setPersona] = useState<string>("CFO");
  const [avatarBusy, setAvatarBusy] = useState(false);
  const [shareLink, setShareLink] = useState<string>("");
  const [avatarErr, setAvatarErr] = useState<string>("");

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

  // Live Advisor: heartbeat-poll the intervention engine while a meeting is live.
  useEffect(() => {
    if (!liveAdvisor || !active) return;
    let on = true;
    const tick = async () => {
      try {
        const d = await vigil.rooms.interventionCheck(active.id, active.title);
        if (on && d.speak) setSuggestion(d);
      } catch {
        /* transient — keep polling */
      }
    };
    void tick();
    const id = setInterval(() => void tick(), 12_000);
    return () => { on = false; clearInterval(id); };
  }, [liveAdvisor, active]);

  const acceptSuggestion = async () => {
    if (!active || !suggestion?.message) return;
    await vigil.rooms.postMessage(active.id, suggestion.message, "VIGIL");
    setSuggestion(null);
    await reloadActive(active.id);
  };

  // Reset avatar/share state when switching to a different room.
  useEffect(() => {
    setAvatarSession(null);
    setShareLink("");
    setAvatarErr("");
  }, [active?.id]);

  const bringAvatar = async () => {
    if (!active) return;
    setAvatarBusy(true);
    setAvatarErr("");
    try {
      const transcript = active.transcript.map((m) => `${m.speaker}: ${m.text}`).join("\n");
      const session = await vigil.rooms.startAvatar(active.id, {
        persona,
        evidence: transcript || undefined,
      });
      setAvatarSession(session);
    } catch (e) {
      setAvatarErr((e as Error).message);
    } finally {
      setAvatarBusy(false);
    }
  };

  const endAvatarSession = async () => {
    if (!active) return;
    try { await vigil.rooms.endAvatar(active.id); } catch { /* ignore */ }
    setAvatarSession(null);
  };

  // Guests join the SAME room as the avatar — Tavus brings its own room, so the
  // guest link is the conversation_url.
  const makeShare = () => {
    if (avatarSession?.conversation_url) setShareLink(avatarSession.conversation_url);
    else setAvatarErr("Bring in the AI advisor first, then share the meeting link.");
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

              {/* Live Advisor — the AI raises its hand on a heartbeat */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[10px] font-mono uppercase tracking-wide text-text-secondary">Live advisor</span>
                  <button
                    onClick={() => { setLiveAdvisor((v) => !v); setSuggestion(null); }}
                    className="text-xs px-2.5 py-1 rounded-full border"
                    style={{
                      borderColor: liveAdvisor ? "#00ff8866" : "currentColor",
                      color: liveAdvisor ? "#00ff88" : undefined,
                      background: liveAdvisor ? "#00ff881a" : "transparent",
                    }}
                  >
                    {liveAdvisor ? "● Listening" : "○ Off"}
                  </button>
                </div>
                {liveAdvisor && !suggestion && (
                  <p className="text-text-secondary text-xs">Listening to the transcript — the advisor will raise its hand only when it has something worth saying.</p>
                )}
                {suggestion?.speak && (
                  <div className="rounded-lg border p-3 space-y-2" style={{ borderColor: "#7c5cff66", background: "#7c5cff14" }}>
                    <div className="flex items-center gap-2">
                      <span className="text-sm">✋</span>
                      <span className="text-[10px] font-mono uppercase tracking-wide" style={{ color: "#7c5cff" }}>Advisor wants to speak</span>
                      {suggestion.urgency && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ color: suggestion.urgency === "high" ? "#ff3366" : "#f59e0b", border: "1px solid currentColor" }}>{suggestion.urgency}</span>
                      )}
                    </div>
                    <p className="text-sm text-foreground/90">{suggestion.message}</p>
                    {suggestion.reason && <p className="text-xs text-text-secondary">{suggestion.reason}{suggestion.touched_specialties?.length ? ` · ${suggestion.touched_specialties.join(", ")}` : ""}</p>}
                    <div className="flex gap-2">
                      <Button size="sm" onClick={() => void acceptSuggestion()}>Add to transcript</Button>
                      <button className="text-xs text-text-secondary hover:text-foreground" onClick={() => setSuggestion(null)}>Dismiss</button>
                    </div>
                  </div>
                )}
              </div>

              {/* AI advisor video avatar (Tavus → Beyond) */}
              <div>
                <div className="text-[10px] font-mono uppercase tracking-wide text-text-secondary mb-1.5">AI advisor · video</div>
                {!avatarSession ? (
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs text-text-secondary">Persona:</span>
                      {PERSONAS.map((p) => (
                        <button
                          key={p}
                          onClick={() => setPersona(p)}
                          className="text-xs px-2 py-0.5 rounded-full border"
                          style={{ borderColor: "currentColor", opacity: persona === p ? 1 : 0.4 }}
                        >
                          {p}
                        </button>
                      ))}
                    </div>
                    <Button size="sm" disabled={avatarBusy} onClick={() => void bringAvatar()}>
                      {avatarBusy ? "Bringing in…" : `Bring in AI ${persona}`}
                    </Button>
                    {avatarErr && <p className="text-xs" style={{ color: "#ff3366" }}>{avatarErr}</p>}
                  </div>
                ) : (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-text-secondary">
                        {avatarSession.persona} · {avatarSession.provider} · {avatarSession.status}
                      </span>
                      <button className="text-xs text-text-secondary hover:text-foreground" onClick={() => void endAvatarSession()}>End</button>
                    </div>
                    {avatarSession.conversation_url ? (
                      <iframe
                        title="AI advisor"
                        src={avatarSession.conversation_url}
                        allow="camera; microphone; autoplay; display-capture; fullscreen"
                        className="w-full rounded-lg border border-current/15"
                        style={{ aspectRatio: "16/9", minHeight: 240 }}
                      />
                    ) : (
                      <p className="text-text-secondary text-xs">Session started ({avatarSession.provider}) — no embeddable URL returned.</p>
                    )}
                    <div className="flex items-center gap-2">
                      <Button size="sm" onClick={makeShare}>Copy meeting link for guests</Button>
                    </div>
                    {shareLink && (
                      <div className="flex items-center gap-2 text-xs">
                        <input readOnly value={shareLink} className="flex-1 rounded border border-current/20 bg-transparent px-2 py-1 font-mono" onFocus={(e) => e.currentTarget.select()} />
                        <button className="text-text-secondary hover:text-foreground" onClick={() => void navigator.clipboard?.writeText(shareLink)}>Copy</button>
                      </div>
                    )}
                    {avatarErr && <p className="text-xs" style={{ color: "#ff3366" }}>{avatarErr}</p>}
                  </div>
                )}
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
