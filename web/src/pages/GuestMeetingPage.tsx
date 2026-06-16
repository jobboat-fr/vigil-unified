import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { resolvePublicMeeting, type PublicMeeting } from "@/lib/vigil";

/**
 * Public meeting page for EXTERNAL (non-account) guests. Opened via a share
 * link (/join/:shareToken). Resolves the token to the live room — the SAME room
 * the host + the AI avatar are in — and embeds it full-screen (the Tavus/Daily
 * room is a Google-Meet-style UI: tiles, mic/cam, screen-share, participants).
 */
export default function GuestMeetingPage() {
  const { shareToken = "" } = useParams();
  const [name, setName] = useState("");
  const [joined, setJoined] = useState(false);
  const [meeting, setMeeting] = useState<PublicMeeting | null>(null);
  const [error, setError] = useState<string>("");
  const polling = useRef<number | null>(null);

  // Once the guest clicks Join, poll until the host has a live room.
  useEffect(() => {
    if (!joined) return;
    let on = true;
    const tick = async () => {
      try {
        const m = await resolvePublicMeeting(shareToken);
        if (!on) return;
        setMeeting(m);
        setError("");
        if (m.has_live && polling.current) {
          window.clearInterval(polling.current);
          polling.current = null;
        }
      } catch (e) {
        if (on) setError((e as Error).message);
      }
    };
    void tick();
    polling.current = window.setInterval(() => void tick(), 5000);
    return () => {
      on = false;
      if (polling.current) window.clearInterval(polling.current);
    };
  }, [joined, shareToken]);

  const A = "#7c5cff", B = "#22d3ee";

  // Lobby
  if (!joined) {
    return (
      <div style={{ background: "#07080d", color: "#e7e9f3", minHeight: "100dvh" }} className="flex items-center justify-center p-4">
        <div className="w-full max-w-sm flex flex-col items-center gap-5 text-center">
          <img src="/vigil-mark.svg" alt="" width={44} height={44} />
          <div>
            <h1 className="text-lg font-bold tracking-[0.05em]">You're invited to a VIGIL meeting</h1>
            <p className="mt-1 text-sm text-white/55">Enter your name to join. No account needed.</p>
          </div>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") setJoined(true); }}
            placeholder="Your name"
            className="w-full rounded-md border border-white/15 bg-transparent px-3 py-2 text-sm outline-none focus:border-white/40"
          />
          <button
            onClick={() => setJoined(true)}
            className="w-full rounded-xl px-5 py-3 text-sm font-semibold text-[#07080d]"
            style={{ background: `linear-gradient(90deg,${A},${B})` }}
          >
            Join meeting
          </button>
        </div>
      </div>
    );
  }

  // In the meeting
  return (
    <div style={{ background: "#07080d", color: "#e7e9f3", minHeight: "100dvh" }} className="flex flex-col">
      <header className="flex items-center justify-between px-4 py-2" style={{ borderBottom: "1px solid #ffffff12" }}>
        <div className="flex items-center gap-2 text-sm">
          <img src="/vigil-mark.svg" alt="" width={20} height={20} />
          <span className="font-semibold">{meeting?.room_title || "VIGIL meeting"}</span>
          {meeting?.persona && <span className="text-white/45 text-xs">AI {meeting.persona} in the room</span>}
        </div>
        <span className="text-xs text-white/45">{name || "Guest"}</span>
      </header>

      <div className="flex-1">
        {meeting?.has_live && meeting.live_url ? (
          <iframe
            title="VIGIL meeting"
            src={meeting.live_url}
            allow="camera; microphone; autoplay; display-capture; fullscreen"
            className="h-full w-full border-0"
            style={{ minHeight: "calc(100dvh - 44px)" }}
          />
        ) : (
          <div className="flex h-full min-h-[70vh] flex-col items-center justify-center gap-3 text-center">
            <div className="h-2 w-2 animate-pulse rounded-full" style={{ background: B }} />
            <p className="text-sm text-white/60">Waiting for the host to start the meeting…</p>
            {error && <p className="text-xs" style={{ color: "#fb7185" }}>{error}</p>}
          </div>
        )}
      </div>
    </div>
  );
}
