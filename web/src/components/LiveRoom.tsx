import "@livekit/components-styles";
import { LiveKitRoom, VideoConference } from "@livekit/components-react";

/**
 * The shared real-time meeting room — one LiveKit room that the host, human
 * guests, and (next) the AI agent all join. VideoConference is the prebuilt
 * Google-Meet-style UI: participant tiles, mic/cam toggles, screen-share, and
 * the participant list. Everyone with a token to the same `room` is in the
 * same call, seeing/hearing each other.
 */
export function LiveRoom({
  token,
  url,
  onLeave,
}: {
  token: string;
  url: string;
  onLeave?: () => void;
}) {
  return (
    <LiveKitRoom
      token={token}
      serverUrl={url}
      connect
      audio
      video
      data-lk-theme="default"
      style={{ height: "100%", width: "100%" }}
      onDisconnected={onLeave}
    >
      <VideoConference />
    </LiveKitRoom>
  );
}
