import { useCallback, useRef } from "react";
import { Tldraw, toRichText, createShapeId, type Editor, type TLShapeId, type TLDefaultColorStyle } from "tldraw";
import "tldraw/tldraw.css";
import { getAssetUrlsByMetaUrl } from "@tldraw/assets/urls";
import { vigil, type Artifact, type MeetingCanvas } from "@/lib/vigil";

// Phase 1 of the brainstorming canvas: a real tldraw infinite canvas (draw.io
// class — free-form blocks, connectors, sticky notes, draw tools) seeded from
// the council's decision flow, and persisted to artifacts.tldraw. Later phases
// hang the agent (brainstorm + diagram skills) and Vault files off this.

// Self-hosted assets (fonts/icons/translations) so nothing loads from a CDN —
// keeps it inside the app's CSP.
const assetUrls = getAssetUrlsByMetaUrl();

const KIND_COLOR: Record<string, TLDefaultColorStyle> = { problem: "blue", decision: "violet", outcome: "green" };

export function ArtifactCanvasTldraw({ artifact }: { artifact: Artifact }) {
  const seeded = useRef(false);

  const onMount = useCallback(
    (editor: Editor) => {
      // Reopen the saved drawing if the user has edited before.
      const persisted = artifact.tldraw as { document?: unknown; session?: unknown } | null;
      if (persisted && (persisted as { document?: unknown }).document) {
        try {
          editor.loadSnapshot(persisted as Parameters<typeof editor.loadSnapshot>[0]);
        } catch {
          if (!seeded.current) seedFromCanvas(editor, artifact.canvas);
        }
      } else if (!seeded.current) {
        seedFromCanvas(editor, artifact.canvas);
      }
      seeded.current = true;

      // Persist on change, debounced, so edits survive a reload.
      let t: ReturnType<typeof setTimeout> | undefined;
      editor.store.listen(
        () => {
          clearTimeout(t);
          t = setTimeout(() => {
            void vigil.studio.saveCanvas(artifact.id, { tldraw: editor.getSnapshot() });
          }, 1500);
        },
        { source: "user", scope: "document" },
      );
    },
    [artifact],
  );

  return (
    <div style={{ position: "relative", width: "100%", height: "70vh", borderRadius: 12, overflow: "hidden" }}>
      <Tldraw assetUrls={assetUrls} onMount={onMount} />
    </div>
  );
}

function seedFromCanvas(editor: Editor, canvas: MeetingCanvas | null) {
  if (!canvas) return;
  const idMap = new Map<string, TLShapeId>();

  for (const n of canvas.nodes ?? []) {
    const id = createShapeId();
    idMap.set(n.id, id);
    editor.createShape({
      id,
      type: "geo",
      x: n.x ?? 60,
      y: n.y ?? 60,
      props: {
        geo: "rectangle",
        w: 170,
        h: 64,
        color: KIND_COLOR[n.kind] ?? "black",
        richText: toRichText(n.label || ""),
      },
    });
  }

  for (const e of canvas.edges ?? []) {
    const from = idMap.get(e.from);
    const to = idMap.get(e.to);
    if (from && to) {
      try {
        const a = editor.getShape(from);
        const b = editor.getShape(to);
        if (a && b) {
          editor.createShape({
            type: "arrow",
            props: {
              start: { x: (a as { x: number }).x + 170, y: (a as { y: number }).y + 32 },
              end: { x: (b as { x: number }).x, y: (b as { y: number }).y + 32 },
            },
          });
        }
      } catch {
        /* arrows are best-effort on seed; the user can draw them */
      }
    }
  }

  // Action items as sticky notes, laid out under the flow.
  const rows = (canvas.table?.rows ?? []);
  rows.forEach((row, i) => {
    const [task, owner, due] = row;
    const text = [task, owner && `→ ${owner}`, due && `(${due})`].filter(Boolean).join(" ");
    editor.createShape({
      type: "note",
      x: 60 + (i % 3) * 230,
      y: 260 + Math.floor(i / 3) * 230,
      props: { color: "yellow", richText: toRichText(text) },
    });
  });

  editor.zoomToFit();
}
