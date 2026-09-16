import { useState } from "react";
import { createPortal } from "react-dom";
import { Video } from "lucide-react";
import { LiveRoom } from "@/components/LiveRoom";
import { vigil, type SlotRoomJoin } from "@/lib/vigil";
import type { GatewayError } from "@/lib/ww";
import type { Slot } from "@/lib/learn";

/** Un créneau a une salle s'il est à distance ou mixte, et pas annulé. */
export const creneauDistant = (s: Pick<Slot, "modality" | "status">) =>
  (s.modality === "distanciel" || s.modality === "mixte") && s.status !== "cancelled";

const heure = (iso: string) =>
  new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });

function message(e: GatewayError): string {
  const d = (e.detail ?? {}) as { error?: string; opens_at?: string };
  switch (d.error) {
    case "too_early":
      return d.opens_at ? `La salle ouvre à ${heure(d.opens_at)}.` : "La salle n'est pas encore ouverte.";
    case "slot_over":
      return "Ce créneau est terminé.";
    case "not_enrolled":
      return "Vous n'êtes pas inscrit à cette session.";
    case "not_in_session":
      return "Vous n'animez pas ce créneau.";
    case "slot_cancelled":
      return "Ce créneau est annulé.";
    case "not_remote":
      return "Ce créneau a lieu en présentiel.";
    case "meeting_closed":
      return "La séance est close.";
    case "livekit_not_configured":
      return "La vidéo n'est pas encore disponible sur la plateforme.";
    default:
      return e.message || "Impossible d'ouvrir la salle.";
  }
}

/**
 * « Rejoindre » sur un créneau à distance : demande l'entrée à la passerelle, qui vérifie
 * rôle, inscription, organisme et horaire, puis ouvre la salle en plein écran.
 * Le bouton n'affirme rien : c'est la passerelle qui dit oui ou non, avec la raison.
 */
export function RejoindreSalle({ slot, compact = false }: { slot: Slot; compact?: boolean }) {
  const [join, setJoin] = useState<SlotRoomJoin | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [attente, setAttente] = useState(false);

  if (!creneauDistant(slot)) return null;

  const entrer = async () => {
    setAttente(true);
    setErreur(null);
    try {
      setJoin(await vigil.rooms.joinSlot(slot.id));
    } catch (e) {
      setErreur(message(e as GatewayError));
    } finally {
      setAttente(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => void entrer()}
        disabled={attente}
        className={
          compact
            ? "border-current/20 inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] hover:bg-current/5 disabled:opacity-50"
            : "border-current/20 inline-flex items-center gap-1.5 rounded border px-3 py-1.5 text-sm hover:bg-current/5 disabled:opacity-50"
        }
      >
        <Video className={compact ? "h-3 w-3" : "h-4 w-4"} aria-hidden />
        {attente ? "Ouverture…" : "Rejoindre"}
      </button>
      {erreur && <div className="mt-1 text-[11px] text-amber-500">{erreur}</div>}
      {join &&
        createPortal(
          <div className="fixed inset-0 z-[100] flex flex-col" style={{ background: "#07080d" }}>
            <div className="flex items-center justify-between px-4 py-2 text-xs text-white/70">
              <span className="truncate">
                {join.title} · {join.role === "host" ? "vous animez" : "participant"}
              </span>
            </div>
            <div className="min-h-0 flex-1">
              <LiveRoom token={join.token} url={join.url ?? ""} onLeave={() => setJoin(null)} />
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
