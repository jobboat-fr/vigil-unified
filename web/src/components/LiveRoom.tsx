import "@livekit/components-styles";
import {
  ControlBar,
  GridLayout,
  LiveKitRoom,
  ParticipantTile,
  RoomAudioRenderer,
  StartAudio,
  useConnectionState,
  useTracks,
} from "@livekit/components-react";
import { ConnectionState, Track } from "livekit-client";

/**
 * La salle en direct — une salle LiveKit où l'hôte, les invités et l'agent se rejoignent.
 *
 * Composée à partir des briques de LiveKit plutôt que de `VideoConference` : le préfabriqué
 * affichait ses messages en anglais (« Start Audio », « Connecting ») sans moyen de les
 * traduire, et ils recouvraient le titre sur téléphone (capture d'Azer, 29/09). La barre de
 * commandes est en variante « minimal » : des icônes, aucun libellé anglais.
 */
function EtatConnexion() {
  const etat = useConnectionState();
  const texte =
    etat === ConnectionState.Connecting ? "Connexion à la salle…"
      : etat === ConnectionState.Reconnecting ? "Reconnexion…"
        : etat === ConnectionState.Disconnected ? "Déconnecté de la salle"
          : null;
  if (!texte) return null;
  return (
    <div
      role="status"
      className="pointer-events-none absolute inset-x-0 top-3 z-20 mx-auto w-fit max-w-[90%] rounded-full px-4 py-1.5 text-sm"
      style={{ background: "rgba(11,34,57,0.85)", color: "#e7e9f3" }}
    >
      {texte}
    </div>
  );
}

function Grille() {
  const pistes = useTracks(
    [
      { source: Track.Source.Camera, withPlaceholder: true },
      { source: Track.Source.ScreenShare, withPlaceholder: false },
    ],
    { onlySubscribed: false },
  );
  return (
    <GridLayout tracks={pistes} className="min-h-0 flex-1">
      <ParticipantTile />
    </GridLayout>
  );
}

export function LiveRoom({ token, url, onLeave }: { token: string; url: string; onLeave?: () => void }) {
  return (
    <LiveKitRoom
      token={token}
      serverUrl={url}
      connect
      audio
      video
      data-lk-theme="default"
      className="relative flex h-full w-full flex-col"
      onDisconnected={onLeave}
    >
      <EtatConnexion />
      <Grille />
      <ControlBar variation="minimal" controls={{ chat: false, settings: false }} />
      <RoomAudioRenderer />
      {/* Le navigateur bloque le son tant que la personne n'a pas touché la page. */}
      <StartAudio
        label="Activer le son de la réunion"
        className="absolute inset-x-0 bottom-20 z-20 mx-auto w-fit rounded-full px-4 py-2 text-sm font-semibold"
      />
    </LiveKitRoom>
  );
}
