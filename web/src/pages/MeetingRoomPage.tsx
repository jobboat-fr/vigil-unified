import { ScaffoldPage } from "./scaffold";

export default function MeetingRoomPage() {
  return (
    <ScaffoldPage
      title="Meeting Room"
      tagline="Live advisory sessions and the AI Council — the agent joins, transcribes, and contributes."
      points={[
        "Run a council of advisors over a topic; each weighs in, a chairman synthesizes.",
        "Hermes joins Google Meet / Teams, scrapes captions to a live transcript, and can speak.",
        "Transcript feeds decisions, artifacts, and the behavioral learning loop.",
      ]}
      source="vigil-core /v1/rooms + google_meet plugin (mcp-vigil — to wire)"
    />
  );
}
