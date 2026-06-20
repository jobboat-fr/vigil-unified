import { useMemo } from "react";
import type { Node, Edge } from "@xyflow/react";
import { MarkerType } from "@xyflow/react";
import { CanvasWorkspace, type CanvasData } from "./canvas/CanvasWorkspace";
import { vigil, type Artifact, type MeetingCanvas } from "@/lib/vigil";

// The infinite brainstorming board — the original VIGIL artifact canvas
// (React Flow + the custom VigilNode), routed to this project's council.
//
//  • Seeds from the council's post-meeting decision flow (artifact.canvas:
//    problem→decision→outcome nodes + an action-items table) the FIRST time;
//    after that the editable React Flow graph is persisted to artifact.tldraw
//    ({ reactflow: { nodes, edges } }) and reloaded verbatim.
//  • The top-right panel calls the council: lenses → /artifacts/canvas-brainstorm
//    (winny/council/canvas_brainstorm.py), "Draw a diagram" →
//    /artifacts/canvas-diagram (winny/council/structurer.diagram_from_prompt).

// council canvas kind → VigilNode shape/color
const KIND_NODE: Record<string, { shape: string; color: string }> = {
  problem:  { shape: "block",     color: "#00e5ff" },
  decision: { shape: "decision",  color: "#a78bfa" },
  outcome:  { shape: "milestone", color: "#34d399" },
};

const EDGE_COLOR = "#00e5ff";

function edge(source: string, target: string, i: number): Edge {
  return {
    id: `e${source}-${target}-${i}`,
    source,
    target,
    type: "default",
    animated: true,
    markerEnd: { type: MarkerType.ArrowClosed, color: EDGE_COLOR, width: 14, height: 14 },
    style: { stroke: EDGE_COLOR, strokeWidth: 1.5 },
  };
}

/** Seed a fresh React Flow graph from the council's MeetingCanvas. */
function seedFromCanvas(canvas: MeetingCanvas | null): CanvasData {
  if (!canvas) return { nodes: [], edges: [] };
  const nodes: Node[] = [];

  for (const n of canvas.nodes ?? []) {
    const km = KIND_NODE[n.kind] || { shape: "block", color: "#00e5ff" };
    nodes.push({
      id: n.id,
      type: "vigil",
      position: { x: n.x ?? 60, y: n.y ?? 60 },
      data: { label: n.label, kind: n.kind, shape: km.shape, color: km.color },
    });
  }

  const edges: Edge[] = (canvas.edges ?? [])
    .filter((e) => e.from && e.to)
    .map((e, i) => edge(e.from, e.to, i));

  // Action-items table → a row of editable "action" pills beneath the flow.
  (canvas.table?.rows ?? []).forEach((row, i) => {
    const [task, owner, due] = row;
    if (!task) return;
    const label = [task, owner && `→ ${owner}`, due && `(${due})`].filter(Boolean).join(" ");
    nodes.push({
      id: `act${i}`,
      type: "vigil",
      position: { x: 60 + (i % 3) * 240, y: 360 + Math.floor(i / 3) * 120 },
      data: { label, kind: "action", shape: "action", color: "#fbbf24" },
    });
  });

  return { nodes, edges };
}

export function ArtifactCanvas({ artifact }: { artifact: Artifact }) {
  // Prefer the persisted, hand-edited React Flow graph; else seed from the
  // council's decision flow. Recomputed only when the artifact identity changes
  // (CanvasWorkspace is keyed on artifact.id so its internal state resets too).
  const initial = useMemo<CanvasData>(() => {
    const persisted = (artifact.tldraw as { reactflow?: CanvasData } | null)?.reactflow;
    // If a React Flow graph was ever saved, honor it verbatim — even when empty
    // (you deliberately cleared the board), so it stays exactly as you left it
    // rather than re-seeding from the meeting flow.
    if (persisted && Array.isArray(persisted.nodes)) {
      return { nodes: persisted.nodes, edges: persisted.edges ?? [] };
    }
    return seedFromCanvas(artifact.canvas);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifact.id]);

  const save = (data: CanvasData) => {
    // Strip transient React Flow runtime fields before persisting.
    const nodes = data.nodes.map((n) => ({
      id: n.id,
      type: n.type,
      position: n.position,
      data: n.data,
    }));
    const edges = data.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: e.type,
      label: e.label,
      animated: e.animated,
      markerEnd: e.markerEnd,
      style: e.style,
    }));
    void vigil.studio.saveCanvas(artifact.id, { tldraw: { reactflow: { nodes, edges } } });
  };

  const onBrainstorm = async (input: { prompt: string; board_text: string; lens: string }) => {
    const res = await vigil.studio.canvasBrainstorm({ ...input, topic: artifact.title });
    return res.blocks || [];
  };

  const onDiagram = async (input: { prompt: string; board_text: string }) => {
    const res = await vigil.studio.canvasDiagram({ ...input, topic: artifact.title });
    return { nodes: res.nodes || [], edges: res.edges || [] };
  };

  return (
    <div
      style={{ position: "relative", width: "100%", height: "70vh", borderRadius: 12, overflow: "hidden", background: "#050507" }}
    >
      <CanvasWorkspace
        key={artifact.id}
        initialNodes={initial.nodes}
        initialEdges={initial.edges}
        onCanvasChange={save}
        onBrainstorm={onBrainstorm}
        onDiagram={onDiagram}
      />
    </div>
  );
}
