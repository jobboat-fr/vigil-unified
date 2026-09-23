import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Button } from "@nous-research/ui/ui/components/button";
import { vigil, googleMeet, streamRoomCouncil, type Room, type CouncilRecord, type SseEvent, type LiveIntervention, type MeetingSummary, type MeetBotStatus, type AvatarSession } from "@/lib/vigil";
import { LiveRoom } from "@/components/LiveRoom";
import { EcartsEmargement } from "@/components/EcartsEmargement";
import { expliquer, expliquerCourt } from "@/lib/refus";
import { Refus } from "@/components/Refus";

const PERSONAS = ["CFO", "CTO", "COO", "CRM", "CRO", "advisor"] as const;
import { METAL } from "@/lib/brand";

// The 4 council lenses, aligned with the Deal Board advisor templates.
const LENSES = [
  { key: "cfo_review", member: "cfo", label: "CFO", color: "var(--color-primary)" },
  { key: "tech_review", member: "cto", label: "CTO", color: "#7C3AED" },
  { key: "legal_review", member: "legal", label: "Legal", color: "var(--color-success)" },
  { key: "product_review", member: "product", label: "Product", color: "#DB2777" },
] as const;

const STAGE_LABEL: Record<string, string> = {
  start: "Conseil convoqué",
  primary_done: "Premier avis rendu",
  reviewer_done: "Contre-avis noté",
  consensus_result: "Consensus calculé",
  chairman_done: "Synthèse rendue",
  behavioral_done: "Profil de comportement",
  complete: "Avis disponible",
  error: "Error",
};

/**
 * Une erreur née dans le navigateur, écrite comme une réponse de la passerelle.
 *
 * Elle traverse ensuite le même traducteur que les vraies : un seul jeu de phrases, un
 * seul rendu, et rien à retenir de particulier pour les cas locaux.
 */
const erreurLocale = (status: number, code: string, detail: string) => ({
  status,
  code,
  detail: { error: code, detail },
});

export default function MeetingRoomPage() {
  const navigate = useNavigate();
  const [rooms, setRooms] = useState<Room[]>([]);
  const [active, setActive] = useState<Room | null>(null);
  const [authError, setAuthError] = useState<unknown>(null);
  const [speaker, setSpeaker] = useState("You");
  const [text, setText] = useState("");
  const [convening, setConvening] = useState(false);
  const [events, setEvents] = useState<SseEvent[]>([]);
  const [record, setRecord] = useState<CouncilRecord | null>(null);
  const [liveAdvisor, setLiveAdvisor] = useState(false);
  const [suggestion, setSuggestion] = useState<LiveIntervention | null>(null);
  const [persona, setPersona] = useState<string>("CFO");
  // Which meeting mode the user is setting up: video room, Google Meet, or an
  // async council review. Null = they haven't chosen yet (the guided step).
  const [setupMode, setSetupMode] = useState<"live" | "meet" | "council" | null>(null);
  const [liveJoin, setLiveJoin] = useState<{ token: string; url: string } | null>(null);
  const [inviteLink, setInviteLink] = useState<string>("");
  const [liveBusy, setLiveBusy] = useState(false);
  const [liveErr, setLiveErr] = useState<unknown>(null);
  const [agentBusy, setAgentBusy] = useState(false);
  const [agentIn, setAgentIn] = useState(false);
  const [avatarSession, setAvatarSession] = useState<AvatarSession | null>(null);
  const [summary, setSummary] = useState<MeetingSummary | null>(null);
  const [summarizing, setSummarizing] = useState(false);
  // Real Google Meet bot (Playwright on OVH, via the ops proxy).
  const [meetUrl, setMeetUrl] = useState("");
  const [meetMode, setMeetMode] = useState<"transcribe" | "realtime">("realtime");
  const [meetStatus, setMeetStatus] = useState<MeetBotStatus | null>(null);
  const [meetBusy, setMeetBusy] = useState(false);
  const [meetErr, setMeetErr] = useState<unknown>(null);
  const [meetImported, setMeetImported] = useState<number | null>(null);
  const [sayText, setSayText] = useState("");

  const sendToMeet = async () => {
    const url = meetUrl.trim();
    if (!/^https:\/\/meet\.google\.com\//.test(url)) {
      setMeetErr(erreurLocale(422, "lien_meet_invalide", "Collez un lien de la forme https://meet.google.com/…"));
      return;
    }
    setMeetBusy(true);
    setMeetErr(null);
    try {
      const res = await googleMeet.join(url, persona, meetMode);
      setMeetStatus(res);
      if (res.success === false || res.error)
        setMeetErr(erreurLocale(502, "meet_join_failed", res.error || "La connexion à Google Meet n'a pas abouti."));
    } catch (e) {
      setMeetErr(e);
    } finally {
      setMeetBusy(false);
    }
  };
  const refreshMeetStatus = async () => {
    try {
      setMeetStatus(await googleMeet.status());
    } catch (e) {
      setMeetErr(e);
    }
  };
  const sayInMeet = async () => {
    const t = sayText.trim();
    if (!t) return;
    setMeetBusy(true);
    try {
      await googleMeet.say(t);
      setSayText("");
    } catch (e) {
      setMeetErr(e);
    } finally {
      setMeetBusy(false);
    }
  };
  // Bridge the Google Meet bot's captions into the active room's transcript
  // (deduped server-side) so the SAME summarize→artifact flow covers Meet too.
  const pullMeetIntoRoom = async (roomId: string): Promise<number> => {
    try {
      const t = await googleMeet.transcript();
      const lines = (t.lines as string[] | undefined) || [];
      if (!lines.length) return 0;
      const res = await vigil.rooms.importTranscript(roomId, lines, "Meet");
      return res.imported;
    } catch {
      return 0; // best-effort — never block close/leave on the bridge
    }
  };

  const pullMeetNow = async () => {
    if (!active) return;
    setMeetBusy(true);
    try {
      const n = await pullMeetIntoRoom(active.id);
      setMeetImported(n);
      await reloadActive(active.id);
    } catch (e) {
      setMeetErr(e);
    } finally {
      setMeetBusy(false);
    }
  };

  const leaveMeet = async () => {
    setMeetBusy(true);
    try {
      // Capture the transcript into the room BEFORE leaving — once the bot
      // leaves, its transcript is gone.
      if (active) {
        const n = await pullMeetIntoRoom(active.id);
        if (n) { setMeetImported(n); await reloadActive(active.id); }
      }
      await googleMeet.leave();
      setMeetStatus(null);
    } catch (e) {
      setMeetErr(e);
    } finally {
      setMeetBusy(false);
    }
  };

  const refresh = useCallback(async () => {
    try {
      const { rooms } = await vigil.rooms.list();
      setRooms(rooms);
      setAuthError(null);
    } catch (e) {
      // Le cas NO_SESSION était traité ici par une phrase en anglais, dans une application
      // en français. Le traducteur commun connaît déjà ce code et rend « Votre session a
      // expiré » avec le bon geste : le laisser faire supprime la seule phrase non
      // traduite de la page.
      setAuthError(e);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot load on mount
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

  const convene = async (lens: string, source: "summary" | "transcript" = "transcript") => {
    if (!active || convening) return;
    setConvening(true);
    setEvents([]);
    setRecord(null);
    try {
      for await (const evt of streamRoomCouncil(active.id, lens, undefined, source)) {
        setEvents((prev) => [...prev, evt]);
        if (evt.event === "complete") {
          const rec = (evt.data as { record?: CouncilRecord }).record;
          if (rec) setRecord(rec);
        }
      }
    } catch (e) {
      setEvents((prev) => [...prev, { event: "error", data: { error: expliquerCourt(e) } }]);
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
    // eslint-disable-next-line react-hooks/set-state-in-effect -- deliberate reset on room change
    setLiveJoin(null);
    setInviteLink("");
    setLiveErr(null);
    setSummary(null);
    setAgentIn(false);
    setAvatarSession(null);
  }, [active?.id]);

  // Close the meeting: summarize (the backend marks the room closed + makes the
  // AI agent leave) → then convene the departments' council over the SUMMARY only
  // (token-economical — the council never sees the full transcript). The summary +
  // the live council both render below.
  const summarizeMeeting = async () => {
    if (!active) return;
    setSummarizing(true);
    try {
      // Fold in any live Google Meet captions first, so closing the meeting
      // produces the summary whether the call ran in-app or on Meet.
      await pullMeetIntoRoom(active.id);
      const s = await vigil.rooms.summarize(active.id);
      setSummary(s);
      await reloadActive(active.id); // room is now closed + summary persisted
      setSummarizing(false);
      // Req: departments review/feedback AFTER summarization, on the summary only.
      if (s.summary_markdown) {
        await convene(active.lens || "cfo_review", "summary");
      }
    } catch (e) {
      setLiveErr(e);
      setSummarizing(false);
    }
  };

  // Owner ends the meeting: leave the live video and run the close→summary→council
  // flow. Triggered from the live-meeting "Terminer la réunion" control (req: summarize as
  // soon as the owner closes the meeting).
  const closeMeeting = async () => {
    setLiveJoin(null);
    await summarizeMeeting();
  };

  // Start the shared live room: mint the host's LiveKit token + an invite link,
  // then drop the host into the same room everyone (and, next, the agent) joins.
  const startLiveMeeting = async () => {
    if (!active) return;
    setLiveBusy(true);
    setLiveErr(null);
    try {
      const [t, s] = await Promise.all([vigil.rooms.livekitToken(active.id), vigil.rooms.share(active.id)]);
      if (!t.url) {
        // Une `Error` nue n'a pas de statut : le traducteur la lisait comme une requête
        // jamais partie et conseillait de vérifier sa connexion réseau. Le réseau va très
        // bien ; c'est la passerelle qui n'a pas de LiveKit.
        setLiveErr(erreurLocale(503, "livekit_not_configured", "La visioconférence n'est pas configurée sur la passerelle."));
        return;
      }
      setLiveJoin({ token: t.token, url: t.url });
      setInviteLink(`${window.location.origin}/join/${s.share_token}`);
    } catch (e) {
      setLiveErr(e);
    } finally {
      setLiveBusy(false);
    }
  };

  // Bring the AI advisor avatar into the meeting: Tavus primary → Beyond
  // Presence fallback (gateway avatar.py). The returned session is rendered as
  // a real video presence (Tavus CVI iframe, or Beyond's embeddable URL).
  const bringAgentIn = async () => {
    if (!active) return;
    setAgentBusy(true);
    setLiveErr(null);
    try {
      const evidence = active.transcript.map((m) => `${m.speaker}: ${m.text}`).join("\n");
      // La passerelle envoie le worker LiveKit dans CETTE salle (POST /v1/rooms/{id}/bring-agent).
      // AZZMIN y apparaît comme participant, avec son avatar (Beyond Presence, Tavus en secours),
      // et ne parle que quand l'algorithme d'intervention le décide.
      await vigil.rooms.bringAgent(active.id, "AZZMIN", evidence || undefined);
      setAgentIn(true);
    } catch (e) {
      setLiveErr(e);
    } finally {
      setAgentBusy(false);
    }
  };

  const dismissAvatar = async () => {
    setAvatarSession(null);
    setAgentIn(false);
    if (active) await vigil.rooms.endAvatar(active.id).catch(() => {});
  };

  if (authError != null) {
    return (
      <Card>
        <CardHeader><CardTitle>Salle de réunion</CardTitle></CardHeader>
        <CardContent className="py-6">
          <Refus erreur={authError} quoi="la salle de réunion" onReessayer={() => void refresh()} />
        </CardContent>
      </Card>
    );
  }

  // Full-screen shared live room (the "Zoom") — host + human guests + (next) the agent.
  if (liveJoin) {
    return (
      <div role="dialog" aria-modal="true" aria-label={active?.title ? `Réunion en cours: ${active.title}` : "Réunion en cours"} className="fixed inset-0 z-50 flex flex-col" style={{ background: "#07080d" }}>
        <div className="flex items-center justify-between px-3 py-2" style={{ borderBottom: "1px solid #ffffff14", color: "#e7e9f3" }}>
          <span className="text-sm font-semibold">
            {active?.title || "Réunion en cours"}
            {/* En pleine réunion, l'erreur doit se voir ici : le panneau du tableau de bord est masqué. */}
            {liveErr != null && (
              // Pas de place pour un bloc ici : une ligne. La couleur suit le registre —
              // l'ambre d'un incident, le blanc cassé d'une limite ou d'une attente. Tout
              // en rouge disait « panne » pour des refus qui n'en sont pas.
              <span
                className="ml-3 text-xs font-normal"
                style={{ color: expliquer(liveErr).registre === "panne" ? "#ff8a8a" : "#e7e9f3b8" }}
              >
                {expliquerCourt(liveErr, "la visioconférence")}
              </span>
            )}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => void bringAgentIn()}
              disabled={agentBusy || agentIn}
              className="rounded px-2 py-1 text-xs font-semibold transition-[filter] duration-150 hover:brightness-[1.04] active:brightness-[0.97] disabled:opacity-50"
              style={{
                color: METAL.encre,
                background: METAL.plaque,
                boxShadow: `inset 0 1px 0 ${METAL.areteHaute}, inset 0 -1px 0 ${METAL.areteBasse}`,
              }}
            >
              {agentBusy ? "AZZMIN arrive…" : agentIn ? "AZZMIN est dans la réunion" : "Faire entrer AZZMIN"}
            </button>
            {inviteLink && (
              <button
                onClick={() => void navigator.clipboard?.writeText(inviteLink)}
                className="rounded px-2 py-1 text-xs"
                style={{ border: "1px solid #ffffff33" }}
                title={inviteLink}
              >
                Copier le lien d'invitation
              </button>
            )}
            <button onClick={() => setLiveJoin(null)} className="rounded px-2 py-1 text-xs" style={{ color: "#e7e9f3", border: "1px solid #ffffff33" }}>Minimize</button>
            <button onClick={() => void closeMeeting()} disabled={summarizing} className="rounded px-2 py-1 text-xs font-semibold" style={{ color: "#fff", background: "var(--color-destructive)" }}>
              {summarizing ? "Closing…" : "⏹ Terminer la réunion"}
            </button>
          </div>
        </div>
        <div className="flex min-h-0 flex-1">
          <div className="flex min-h-0 flex-1 flex-col md:flex-row">
            <div className="min-h-0 flex-1"><LiveRoom token={liveJoin.token} url={liveJoin.url} onLeave={() => setLiveJoin(null)} /></div>
            {avatarSession && (
              <div className="relative min-h-0 flex-1" style={{ borderLeft: "1px solid #ffffff14", background: "#000" }}>
                <div className="absolute left-2 top-2 z-10 flex items-center gap-2 rounded-full px-2 py-1 text-[10px] font-semibold" style={{ background: "#0b2239cc", color: "var(--color-success)" }}>
                  <span className="vigil-breathe">●</span> AI {persona} · {avatarSession.provider === "tavus" ? "Tavus" : "Beyond Presence"}
                  <button onClick={() => void dismissAvatar()} className="ml-1 opacity-70 hover:opacity-100" title="Retirer l'avatar">✕</button>
                </div>
                {avatarSession.conversation_url ? (
                  <iframe
                    title={`AI ${persona} avatar`}
                    src={avatarSession.conversation_url}
                    className="h-full w-full border-0"
                    allow="camera; microphone; autoplay; display-capture; fullscreen"
                  />
                ) : (
                  <div className="flex h-full items-center justify-center p-4 text-center text-xs" style={{ color: "#e7e9f3aa" }}>
                    Avatar is live on {avatarSession.provider} but returned no embeddable URL.
                  </div>
                )}
              </div>
            )}
          </div>
          {/* In-meeting controls — transcription + listening live HERE, not on the dashboard */}
          <div className="flex w-80 min-w-0 flex-col" style={{ borderLeft: "1px solid #ffffff14", color: "#e7e9f3" }}>
            <div className="flex items-center justify-between px-3 py-2" style={{ borderBottom: "1px solid #ffffff14" }}>
              <span className="text-[10px] font-mono uppercase tracking-wide" style={{ opacity: 0.7 }}>Avis en direct</span>
              <button
                onClick={() => { setLiveAdvisor((v) => !v); setSuggestion(null); }}
                className="text-xs px-2.5 py-1 rounded-full border"
                style={{ borderColor: liveAdvisor ? "#00ff8866" : "#ffffff33", color: liveAdvisor ? "#00ff88" : "#e7e9f3", background: liveAdvisor ? "#00ff881a" : "transparent" }}
              >
                {liveAdvisor ? "● Listening" : "○ Listen off"}
              </button>
            </div>
            {suggestion?.speak && (
              <div className="m-3 overflow-hidden rounded-lg border p-2.5 space-y-2" style={{ borderColor: "rgba(122,162,255,0.38)", background: "rgba(122,162,255,0.08)" }}>
                <div className="flex items-center gap-2"><span aria-hidden className="h-3 w-[2px] rounded-full" style={{ background: METAL.accentSombre }} /><span className="text-[10px] font-mono uppercase" style={{ color: METAL.accentSombre }}>Un avis demande la parole</span></div>
                <p className="text-sm">{suggestion.message}</p>
                <div className="flex gap-2"><Button size="sm" onClick={() => void acceptSuggestion()}>Add</Button><button className="text-xs" style={{ opacity: 0.7 }} onClick={() => setSuggestion(null)}>Dismiss</button></div>
              </div>
            )}
            <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
              <div className="text-[10px] font-mono uppercase tracking-wide mb-1.5" style={{ opacity: 0.7 }}>Transcript · {active?.transcript.length ?? 0}</div>
              <ul className="space-y-1">
                {(active?.transcript ?? []).map((m, i) => (
                  <li key={i} className="text-sm leading-snug"><span className="font-mono" style={{ opacity: 0.9 }}>{m.speaker}:</span> <span style={{ opacity: 0.8 }}>{m.text}</span></li>
                ))}
                {(active?.transcript.length ?? 0) === 0 && <li className="text-xs" style={{ opacity: 0.6 }}>Les sous-titres et les notes s'affichent ici.</li>}
              </ul>
            </div>
            <div className="flex gap-2 px-3 py-2" style={{ borderTop: "1px solid #ffffff14" }}>
              <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void sendMessage(); }} aria-label="Note de réunion" placeholder="Note what was said…" className="flex-1 rounded border bg-transparent px-2 py-1 text-sm" style={{ borderColor: "#ffffff33", color: "#e7e9f3" }} />
              <Button size="sm" onClick={() => void sendMessage()} disabled={!text.trim()}>Add</Button>
            </div>
          </div>
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
            <p className="text-text-secondary text-sm py-4 text-center">Aucune salle. Créez-en une.</p>
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

      {/* Room detail — guided, mode-first setup */}
      <Card>
        <CardHeader>
          <CardTitle>{active ? active.title : "Choisir une salle"}</CardTitle>
          {active && <p className="text-text-secondary text-xs mt-0.5">Trois étapes pour préparer la réunion.</p>}
        </CardHeader>
        <CardContent className="space-y-6">
          {!active ? (
            <div className="py-10 text-center">
              <div className="text-3xl mb-2">🗓️</div>
              <p className="text-text-secondary text-sm">Choisissez une salle à gauche, ou créez-en une pour commencer.</p>
            </div>
          ) : (
            <>
              {/* STEP 1 — advisors */}
              <section>
                <StepHeader n={1} title="Choisir les points de vue" hint="Qui doit se prononcer — choisissez les points de vue utiles à cette décision." />
                <div className="flex flex-wrap gap-2">
                  {LENSES.map((l) => {
                    const added = active.members.some((m) => m.id === l.member);
                    return (
                      <button
                        key={l.member}
                        onClick={() => void addAdvisor(l.member)}
                        className="text-xs px-3 py-1.5 rounded-full border font-medium transition"
                        style={{ borderColor: `${l.color}66`, color: l.color, background: added ? `${l.color}22` : "transparent" }}
                      >
                        {added ? "✓ " : "+ "}{l.label}
                      </button>
                    );
                  })}
                </div>
                {active.members.length > 0 && (
                  <p className="text-text-secondary text-[11px] mt-2">{active.members.length} advisor{active.members.length > 1 ? "s" : ""} on the board.</p>
                )}
              </section>

              {/* STEP 2 — how do you want to meet? */}
              <section>
                <StepHeader n={2} title="Comment souhaitez-vous vous réunir ?" hint="Choisissez une option — sa configuration apparaît en dessous." />
                <div className="grid gap-2 sm:grid-cols-3">
                  <ModeTile emoji="🎥" title="Salle vidéo intégrée" desc="AI advisor avatar + invite humans" active={setupMode === "live"} onClick={() => setSetupMode("live")} />
                  <ModeTile emoji="🔗" title="Google Meet" desc="Envoyer l'assistant dans votre réunion Meet" active={setupMode === "meet"} onClick={() => setSetupMode("meet")} />
                  <ModeTile emoji="🧠" title="Revue du conseil" desc="Le conseil délibère à partir de vos notes" active={setupMode === "council"} onClick={() => setSetupMode("council")} />
                </div>
              </section>

              {/* STEP 3 — contextual setup for the chosen mode */}
              {setupMode && (
                <section>
                  <StepHeader n={3} title="Configurer" hint="" />

                  {setupMode === "live" && (
                    <div className="space-y-3 rounded-xl border border-current/10 p-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs text-text-secondary">Siège de l'assistant :</span>
                        {PERSONAS.map((p) => (
                          <button key={p} onClick={() => setPersona(p)} className="text-xs px-2.5 py-1 rounded-full border" style={{ borderColor: "currentColor", opacity: persona === p ? 1 : 0.4 }}>{p}</button>
                        ))}
                      </div>
                      <Button disabled={liveBusy} onClick={() => void startLiveMeeting()}>{liveBusy ? "Starting…" : "🎥 Start live meeting"}</Button>
                      <p className="text-text-secondary text-[11px]">Opens a shared video room. Share the invite link with people; then use "Bring in AI {persona}" inside the room to add the avatar (Tavus, Beyond Presence fallback).</p>
                      {inviteLink && (
                        <div className="flex items-center gap-2 text-xs">
                          <input aria-label="Lien d'invitation" readOnly value={inviteLink} className="flex-1 rounded border border-current/20 bg-transparent px-2 py-1 font-mono" onFocus={(e) => e.currentTarget.select()} />
                          <button className="text-text-secondary hover:text-foreground" onClick={() => void navigator.clipboard?.writeText(inviteLink)}>Copy</button>
                        </div>
                      )}
                      {liveErr != null && <Refus erreur={liveErr} quoi="la visioconférence" compact className="mt-2" />}
                    </div>
                  )}

                  {setupMode === "meet" && (
                    <div className="space-y-3 rounded-xl border border-current/10 p-4">
                      <label className="block text-xs text-text-secondary">Collez votre lien Google Meet</label>
                      <input value={meetUrl} onChange={(e) => setMeetUrl(e.target.value)} aria-label="Lien Google Meet" placeholder="https://meet.google.com/abc-defg-hij" className="w-full rounded border border-current/20 bg-transparent px-2 py-1.5 text-xs font-mono" />
                      <div className="flex flex-wrap items-center gap-3">
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-text-secondary">Seat:</span>
                          {PERSONAS.slice(0, 4).map((p) => (
                            <button key={p} onClick={() => setPersona(p)} className="text-xs px-2 py-0.5 rounded-full border" style={{ borderColor: "currentColor", opacity: persona === p ? 1 : 0.4 }}>{p}</button>
                          ))}
                        </div>
                        <label className="flex items-center gap-1.5 text-xs text-text-secondary">
                          <input type="checkbox" checked={meetMode === "realtime"} onChange={(e) => setMeetMode(e.target.checked ? "realtime" : "transcribe")} />
                          Le laisser parler (voix ElevenLabs)
                        </label>
                      </div>
                      <Button disabled={meetBusy || !meetUrl.trim()} onClick={() => void sendToMeet()}>{meetBusy ? "Sending…" : `Send ${persona} to Meet`}</Button>
                      <p className="text-text-secondary text-[11px]">A VIGIL bot joins as a guest — admit it from the lobby. {meetMode === "realtime" ? "Il écoute et prend la parole pendant la réunion." : "Il retranscrit la réunion dans cette salle."}</p>
                      {meetStatus && (
                        <div className="rounded-lg border border-current/10 p-2 space-y-2">
                          <div className="flex flex-wrap items-center gap-2 text-xs">
                            <span className="rounded-full px-2 py-0.5" style={{ background: "#1f7a4c22", color: "var(--color-success)" }}>{meetStatus.state || (meetStatus.ok ? "in call" : meetStatus.reason || "—")}</span>
                            <button className="text-text-secondary hover:text-foreground" onClick={() => void refreshMeetStatus()}>Refresh</button>
                            <button className="text-text-secondary hover:text-foreground" disabled={meetBusy} onClick={() => void pullMeetNow()}>Récupérer la transcription</button>
                            <button className="text-text-secondary hover:text-foreground" onClick={() => void leaveMeet()}>Leave</button>
                            {meetImported !== null && <span className="text-text-secondary">+{meetImported} lines → room</span>}
                          </div>
                          {meetMode === "realtime" && (
                            <div className="flex items-center gap-2 text-xs">
                              <input value={sayText} onChange={(e) => setSayText(e.target.value)} aria-label="Parler au nom de l'assistant" placeholder={`Make ${persona} say…`} onKeyDown={(e) => { if (e.key === "Enter") void sayInMeet(); }} className="flex-1 rounded border border-current/20 bg-transparent px-2 py-1" />
                              <button className="text-text-secondary hover:text-foreground" onClick={() => void sayInMeet()}>Say</button>
                            </div>
                          )}
                        </div>
                      )}
                      {meetErr != null && <Refus erreur={meetErr} quoi="Google Meet" compact className="mt-2" />}
                    </div>
                  )}

                  {setupMode === "council" && (
                    <div className="space-y-3 rounded-xl border border-current/10 p-4">
                      <p className="text-text-secondary text-[11px]">Notez les points à trancher ci-dessous, puis convoquez un point de vue. Le conseil délibère en arrière-plan et rend son avis à droite.</p>
                      <div className="flex flex-wrap gap-2">
                        {LENSES.map((l) => (
                          <Button key={l.key} size="sm" disabled={convening} onClick={() => void convene(l.key)}>{l.label} review</Button>
                        ))}
                      </div>
                      <label className="flex items-center gap-2 text-xs text-text-secondary pt-1">
                        <button onClick={() => { setLiveAdvisor((v) => !v); setSuggestion(null); }} className="text-xs px-2.5 py-1 rounded-full border" style={{ borderColor: liveAdvisor ? "#1f7a4c66" : "currentColor", color: liveAdvisor ? "var(--color-success)" : undefined, background: liveAdvisor ? "#1f7a4c14" : "transparent" }}>
                          {liveAdvisor ? "● Avis en direct listening" : "○ Avis en direct off"}
                        </button>
                        <span>Lève la main lorsqu'il a quelque chose à dire.</span>
                      </label>
                      {suggestion?.speak && (
                        <div className="overflow-hidden rounded-lg border p-3 space-y-2" style={{ borderColor: "rgba(122,162,255,0.38)", background: "rgba(122,162,255,0.08)" }}>
                          <div className="flex items-center gap-2"><span aria-hidden className="h-3 w-[2px] rounded-full" style={{ background: METAL.accentSombre }} /><span className="text-[10px] font-mono uppercase tracking-wide" style={{ color: METAL.accentSombre }}>Un avis demande la parole</span></div>
                          <p className="text-sm text-foreground/90">{suggestion.message}</p>
                          <div className="flex gap-2"><Button size="sm" onClick={() => void acceptSuggestion()}>Ajouter aux notes</Button><button className="text-xs text-text-secondary hover:text-foreground" onClick={() => setSuggestion(null)}>Dismiss</button></div>
                        </div>
                      )}
                    </div>
                  )}
                </section>
              )}

              {/* Notes & transcript — supporting, always available */}
              <section>
                <div className="text-xs font-semibold text-text-secondary mb-2">Notes &amp; transcript · {active.transcript.length}</div>
                <ul className="space-y-1 max-h-[26vh] overflow-y-auto pr-1 mb-2">
                  {active.transcript.map((m, i) => (
                    <li key={i} className="text-sm leading-snug"><span className="font-mono text-foreground/90">{m.speaker}:</span> <span className="text-foreground/80">{m.text}</span></li>
                  ))}
                  {active.transcript.length === 0 && <li className="text-text-secondary text-sm">Vide — notez ce qui se dit, ou laissez l'assistant Meet le remplir.</li>}
                </ul>
                <div className="flex gap-2">
                  <input value={speaker} onChange={(e) => setSpeaker(e.target.value)} className="w-24 rounded border border-current/20 bg-transparent px-2 py-1.5 text-sm" aria-label="Nom de l'intervenant" placeholder="Speaker" />
                  <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void sendMessage(); }} className="flex-1 rounded border border-current/20 bg-transparent px-2 py-1.5 text-sm" aria-label="Ligne de transcription" placeholder="What was said…" />
                  <Button size="sm" onClick={() => void sendMessage()} disabled={!text.trim()}>Add</Button>
                </div>
              </section>

              {/* Close & summarize — the finish line */}
              <section className="border-t border-current/10 pt-4">
                <Button disabled={summarizing || (active.transcript.length === 0 && !meetStatus)} onClick={() => void summarizeMeeting()}>
                  {summarizing ? "Summarizing…" : "✓ Summarize & close meeting"}
                </Button>
                <p className="text-text-secondary text-[11px] mt-1.5">Pulls in the Google Meet captions (if any), writes a summary + action items to Studio, and files guests into CRM.</p>
                {summary && (
                  <div className="mt-3 rounded-lg border border-current/15 p-3 space-y-2 text-sm">
                    <div className="flex flex-wrap gap-3 text-xs text-text-secondary">
                      {summary.artifact_id && <button className="underline hover:text-foreground" onClick={() => navigate(`/studio?artifact=${summary.artifact_id}`)}>✓ Ouvrir dans le Studio</button>}
                      <span>{summary.commitments_saved} engagements</span>
                      {active.kind !== "formation" && <span>{summary.contacts_saved} invités → CRM</span>}
                      {active.kind === "formation" && (
                        summary.vault_object_id
                          ? <span>✓ Compte rendu déposé au coffre de la session</span>
                          : <span className="text-amber-500">Compte rendu non déposé au coffre{summary.vault_error ? ` (${summary.vault_error})` : summary.stub ? " (assistant indisponible)" : ""}</span>
                      )}
                    </div>
                    {active.kind === "formation" && <EcartsEmargement roomId={active.id} />}
                    {summary.summary_markdown && <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-current/5 p-2 text-xs leading-relaxed">{summary.summary_markdown}</pre>}
                    {summary.commitments.length > 0 && (
                      <div className="text-xs"><span className="text-text-secondary">Décisions à suivre :</span><ul className="list-disc pl-4">{summary.commitments.map((c, i) => <li key={i}>{c.text}{c.owner ? ` — ${c.owner}` : ""}</li>)}</ul></div>
                    )}
                  </div>
                )}
              </section>
            </>
          )}
        </CardContent>
      </Card>

      {/* Council stream + verdict */}
      <Card>
        <CardHeader><CardTitle>{convening ? "Council in session…" : "Council"}</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {events.length === 0 && !record ? (
            <p className="text-text-secondary text-sm py-6 text-center">Convoquez un conseil pour voir les avis.</p>
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
                    color: verdict.readiness_pass ? "#00ff88" : "var(--color-warning)",
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

// ── Guided-setup UI helpers ───────────────────────────────────────────────
function StepHeader({ n, title, hint }: { n: number; title: string; hint: string }) {
  return (
    <div className="mb-2.5">
      <div className="flex items-center gap-2">
        <span
          className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold"
          style={{ background: "var(--color-primary)", color: "#0b2239" }}
        >
          {n}
        </span>
        <span className="text-sm font-semibold">{title}</span>
      </div>
      {hint && <p className="text-text-secondary text-[11px] mt-1 ml-7">{hint}</p>}
    </div>
  );
}

function ModeTile({
  emoji,
  title,
  desc,
  active,
  onClick,
}: {
  emoji: string;
  title: string;
  desc: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="vigil-lift flex flex-col items-start gap-1 rounded-xl border p-3 text-left transition"
      style={{
        borderColor: active ? "var(--color-success)" : "currentColor",
        background: active ? "#1f7a4c14" : "transparent",
        opacity: active ? 1 : 0.72,
      }}
      aria-pressed={active}
    >
      <span className="text-xl">{emoji}</span>
      <span className="text-sm font-semibold">{title}</span>
      <span className="text-text-secondary text-[11px] leading-tight">{desc}</span>
    </button>
  );
}
