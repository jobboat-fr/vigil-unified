import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Button } from "@nous-research/ui/ui/components/button";
import { vigil, streamRoomCouncil, type Room, type CouncilRecord, type SseEvent, type LiveIntervention, type MeetingSummary } from "@/lib/vigil";
import { LiveRoom } from "@/components/LiveRoom";

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
  const [persona, setPersona] = useState<string>("CFO");
  const [liveJoin, setLiveJoin] = useState<{ token: string; url: string } | null>(null);
  const [inviteLink, setInviteLink] = useState<string>("");
  const [liveBusy, setLiveBusy] = useState(false);
  const [liveErr, setLiveErr] = useState<string>("");
  const [summary, setSummary] = useState<MeetingSummary | null>(null);
  const [summarizing, setSummarizing] = useState(false);

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

  // Reset live-meeting/summary state when switching to a different room.
  useEffect(() => {
    setLiveJoin(null);
    setInviteLink("");
    setLiveErr("");
    setSummary(null);
  }, [active?.id]);

  const summarizeMeeting = async () => {
    if (!active) return;
    setSummarizing(true);
    try {
      setSummary(await vigil.rooms.summarize(active.id));
    } catch (e) {
      setLiveErr((e as Error).message);
    } finally {
      setSummarizing(false);
    }
  };

  // Start the shared live room: mint the host's LiveKit token + an invite link,
  // then drop the host into the same room everyone (and, next, the agent) joins.
  const startLiveMeeting = async () => {
    if (!active) return;
    setLiveBusy(true);
    setLiveErr("");
    try {
      const [t, s] = await Promise.all([vigil.rooms.livekitToken(active.id), vigil.rooms.share(active.id)]);
      if (!t.url) throw new Error("LiveKit isn't configured on the gateway.");
      setLiveJoin({ token: t.token, url: t.url });
      setInviteLink(`${window.location.origin}/join/${s.share_token}`);
    } catch (e) {
      setLiveErr((e as Error).message);
    } finally {
      setLiveBusy(false);
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

  // Full-screen shared live room (the "Zoom") — host + human guests + (next) the agent.
  if (liveJoin) {
    return (
      <div className="fixed inset-0 z-50 flex flex-col" style={{ background: "#07080d" }}>
        <div className="flex items-center justify-between px-3 py-2" style={{ borderBottom: "1px solid #ffffff14", color: "#e7e9f3" }}>
          <span className="text-sm font-semibold">{active?.title || "Live meeting"}</span>
          <div className="flex items-center gap-2">
            {inviteLink && (
              <button
                onClick={() => void navigator.clipboard?.writeText(inviteLink)}
                className="rounded px-2 py-1 text-xs"
                style={{ border: "1px solid #ffffff33" }}
                title={inviteLink}
              >
                Copy invite link
              </button>
            )}
            <button onClick={() => setLiveJoin(null)} className="rounded px-2 py-1 text-xs" style={{ color: "#fb7185", border: "1px solid #fb7185" }}>Leave</button>
          </div>
        </div>
        <div className="flex-1 min-h-0">
          <LiveRoom token={liveJoin.token} url={liveJoin.url} onLeave={() => setLiveJoin(null)} />
        </div>
      </div>
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

              {/* Live meeting — one shared room (host + human guests + the AI agent) */}
              <div>
                <div className="text-[10px] font-mono uppercase tracking-wide text-text-secondary mb-1.5">Live meeting</div>
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs text-text-secondary">AI seat:</span>
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
                  <Button size="sm" disabled={liveBusy} onClick={() => void startLiveMeeting()}>
                    {liveBusy ? "Starting…" : "🎥 Start live meeting"}
                  </Button>
                  <p className="text-text-secondary text-[11px]">Opens a shared video room. Invite humans with the link; your AI {persona} joins the same call.</p>
                  {inviteLink && (
                    <div className="flex items-center gap-2 text-xs">
                      <input readOnly value={inviteLink} className="flex-1 rounded border border-current/20 bg-transparent px-2 py-1 font-mono" onFocus={(e) => e.currentTarget.select()} />
                      <button className="text-text-secondary hover:text-foreground" onClick={() => void navigator.clipboard?.writeText(inviteLink)}>Copy</button>
                    </div>
                  )}
                  {liveErr && <p className="text-xs" style={{ color: "#ff3366" }}>{liveErr}</p>}
                </div>
              </div>

              {/* Post-meeting: summarize → artifact + commitments + guest onboarding */}
              <div>
                <div className="text-[10px] font-mono uppercase tracking-wide text-text-secondary mb-1.5">Close the meeting</div>
                <Button size="sm" disabled={summarizing || active.transcript.length === 0} onClick={() => void summarizeMeeting()}>
                  {summarizing ? "Summarizing…" : "Summarize & close"}
                </Button>
                {summary && (
                  <div className="mt-2 rounded-lg border border-current/15 p-3 space-y-2 text-sm">
                    <div className="flex flex-wrap gap-3 text-xs text-text-secondary">
                      {summary.artifact_id && <span>✓ Saved to Studio</span>}
                      <span>{summary.commitments_saved} commitments</span>
                      <span>{summary.contacts_saved} guests → CRM</span>
                    </div>
                    {summary.summary_markdown && (
                      <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-current/5 p-2 text-xs leading-relaxed">{summary.summary_markdown}</pre>
                    )}
                    {summary.commitments.length > 0 && (
                      <div className="text-xs">
                        <span className="text-text-secondary">Action items:</span>
                        <ul className="list-disc pl-4">
                          {summary.commitments.map((c, i) => <li key={i}>{c.text}{c.owner ? ` — ${c.owner}` : ""}</li>)}
                        </ul>
                      </div>
                    )}
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
