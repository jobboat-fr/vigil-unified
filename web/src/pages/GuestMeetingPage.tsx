import { useState } from "react";
import { MarqueVtlvs } from "@/components/MarqueVtlvs";
import { METAL } from "@/lib/brand";
import { useParams } from "react-router-dom";
import { joinGuestRoom, type GuestRoomJoin } from "@/lib/vigil";
import type { GatewayError } from "@/lib/ww";
import { LiveRoom } from "@/components/LiveRoom";
import { expliquerCourt } from "@/lib/refus";

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
      const err = e as GatewayError;
      const code = (err.detail as { error?: string } | undefined)?.error ?? "";
      if (code === "expired_share_token") {
        setError("Ce lien d'invitation a expiré. Demandez un nouveau lien à l'organisateur.");
      } else if (code === "meeting_closed") {
        setError("Cette réunion est terminée.");
      } else if (code === "invalid_share_token" || err.status === 404) {
        setError("Ce lien d'invitation n'est pas valide.");
      } else if (code === "livekit_not_configured" || err.status === 503) {
        setError("La vidéo n'est pas encore disponible. Réessayez dans un instant.");
      } else {
        // Même défaut, même correction : le repli affichait le message brut de la
        // passerelle à un invité qui n'a pas de compte et ne peut rien en faire.
        setError(expliquerCourt(err, "cette réunion"));
      }
    } finally {
      setJoining(false);
    }
  };


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
        <MarqueVtlvs hauteur={44} titre="VTLVS" />
        <div>
          <h1 className="text-lg font-bold tracking-[0.05em]">Vous êtes invité à une réunion</h1>
          <p className="mt-1 text-sm text-white/55">Indiquez votre nom pour rejoindre. Aucun compte n'est nécessaire.</p>
        </div>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void doJoin(); }}
          placeholder="Votre nom"
          className="w-full rounded-md border border-white/15 bg-transparent px-3 py-2 text-sm outline-none focus:border-white/40"
        />
        <button
          onClick={() => void doJoin()}
          disabled={joining || !name.trim()}
          className="w-full rounded-xl px-5 py-3 text-sm font-semibold transition-[filter] duration-150 hover:brightness-[1.04] active:brightness-[0.97] disabled:opacity-50"
          style={{
            background: METAL.plaque,
            color: METAL.encre,
            boxShadow: `inset 0 1px 0 ${METAL.areteHaute}, inset 0 -1px 0 ${METAL.areteBasse}`,
          }}
        >
          {joining ? "Connexion…" : "Rejoindre la réunion"}
        </button>
        {error && <p className="text-xs" style={{ color: "var(--color-destructive)" }}>{error}</p>}
      </div>
    </div>
  );
}
