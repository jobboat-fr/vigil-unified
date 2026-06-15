import { ScaffoldPage } from "./scaffold";

export default function StudioPage() {
  return (
    <ScaffoldPage
      title="Studio"
      tagline="Draft, refine, and crystallize artifacts — proposals, briefs, contracts — with the agent."
      points={[
        "Create an artifact and iterate with the agent in a side chat.",
        "Crystallize a session or meeting transcript into a structured document.",
        "Grounded in the Vault so drafts cite the user's real documents.",
      ]}
      source="vigil-core /v1/artifacts (mcp-vigil — to wire)"
    />
  );
}
