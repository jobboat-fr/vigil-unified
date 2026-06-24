import { useState } from "react";
import { useParams } from "react-router-dom";
import { joinGuestRoom, type GuestRoomJoin } from "@/lib/vigil";
import { LiveRoom } from "@/components/LiveRoom";

/**
 * Public page for EXTERNAL (non-account) guests. Opened via the host's invite
 * link (/join/:shareToken). The guest enters a name and joins the SAME LiveKit
 * room as the host + the AI agent — one shared call.
 */
export default function GuestMeetingPage() {
  const { shareToken = "" } = useParams();
  const [name, setName] = useState("");
  const [joining, setJoining] = useState(false);
  const [join, setJoin] = useState<GuestRoomJoin | null>(null);
  const [error, setError] = useState("");

  const doJoin = async () => {
    if (!name.trim()) return;
    setJoining(true);
    setError("");
    try {
      setJoin(await joinGuestRoom(shareToken, name.trim()));
    } catch (e) {
      const msg = (e as Error).message || "";
      if (/livekit|not_configured|503/i.test(msg)) {
        setError("The host hasn't started the live video yet. Ask them to click “Start live meeting”, then reopen this link.");
      } else if (/invalid_share|404/i.test(msg)) {
        setError("This invite link is invalid or has expired.");
      } else {
        setError(msg || "Could not join the meeting.");
      }
    } finally {
      setJoining(false);
    }
  };

  const A = "#7c5cff", B = "#22d3ee";

  if (join?.token && join.url) {
    return (
      <div style={{ height: "100dvh", background: "#07080d" }}>
        <LiveRoom token={join.token} url={join.url} onLeave={() => setJoin(null)} />
      </div>
    );
  }

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
          onKeyDown={(e) => { if (e.key === "Enter") void doJoin(); }}
          placeholder="Your name"
          className="w-full rounded-md border border-white/15 bg-transparent px-3 py-2 text-sm outline-none focus:border-white/40"
        />
        <button
          onClick={() => void doJoin()}
          disabled={joining || !name.trim()}
          className="w-full rounded-xl px-5 py-3 text-sm font-semibold text-[#07080d] disabled:opacity-50"
          style={{ background: `linear-gradient(90deg,${A},${B})` }}
        >
          {joining ? "Joining…" : "Join meeting"}
        </button>
        {error && <p className="text-xs" style={{ color: "#fb7185" }}>{error}</p>}
      </div>
    </div>
  );
}
