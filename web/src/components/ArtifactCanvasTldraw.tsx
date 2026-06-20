import { useCallback, useRef, useState } from "react";
import { Tldraw, toRichText, createShapeId, type Editor, type TLShapeId, type TLDefaultColorStyle } from "tldraw";
import "tldraw/tldraw.css";
import { getAssetUrlsByMetaUrl } from "@tldraw/assets/urls";
import { vigil, type Artifact, type MeetingCanvas, type CanvasBlock } from "@/lib/vigil";

// The brainstorming canvas (phases 1+2): a real tldraw board seeded from the
// council's decision flow, PLUS an agent brainstorm panel — type a prompt or
// tap a lens (Risks, Gaps, Council…) and the council drops fresh blocks onto
// the board, aware of what's already there (and of your selection).

const assetUrls = getAssetUrlsByMetaUrl();
const KIND_COLOR: Record<string, TLDefaultColorStyle> = { problem: "blue", decision: "violet", outcome: "green" };
const TLD_COLORS = new Set([
  "black", "blue", "green", "grey", "light-blue", "light-green", "light-red",
  "light-violet", "orange", "red", "violet", "yellow", "white",
]);

const LENSES: { key: string; label: string }[] = [
  { key: "expand", label: "Expand" },
  { key: "risks", label: "Risks" },
  { key: "missing", label: "Gaps" },
  { key: "next_steps", label: "Next steps" },
  { key: "critique", label: "Devil's advocate" },
  { key: "council", label: "Council" },
  { key: "summarize", label: "Summarize" },
];

function richTextToString(rt: unknown): string {
  if (!rt) return "";
  if (typeof rt === "string") return rt;
  let out = "";
  const walk = (n: { text?: string; content?: unknown[] } | unknown) => {
    const node = n as { text?: string; content?: unknown[] };
    if (!node) return;
    if (typeof node.text === "string") out += node.text;
    if (Array.isArray(node.content)) node.content.forEach(walk);
  };
  walk(rt);
  return out.trim();
}

export function ArtifactCanvasTldraw({ artifact }: { artifact: Artifact }) {
  const editorRef = useRef<Editor | null>(null);
  const seeded = useRef(false);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const onMount = useCallback(
    (editor: Editor) => {
      editorRef.current = editor;
      const persisted = artifact.tldraw as { document?: unknown } | null;
      if (persisted && persisted.document) {
        try {
          editor.loadSnapshot(persisted as Parameters<typeof editor.loadSnapshot>[0]);
        } catch {
          if (!seeded.current) seedFromCanvas(editor, artifact.canvas);
        }
      } else if (!seeded.current) {
        seedFromCanvas(editor, artifact.canvas);
      }
      seeded.current = true;

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

  const run = async (lens: string, p = "") => {
    const editor = editorRef.current;
    if (!editor) return;
    setBusy(true);
    setErr("");
    try {
      const sel = editor.getSelectedShapes();
      const shapes = sel.length ? sel : editor.getCurrentPageShapes();
      const board = shapes
        .map((s) => richTextToString((s.props as { richText?: unknown }).richText))
        .filter(Boolean)
        .map((l) => `- ${l}`)
        .join("\n");
      const res = await vigil.studio.canvasBrainstorm({ prompt: p, board_text: board, lens, topic: artifact.title });
      placeBlocks(editor, res.blocks || []);
      setPrompt("");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const diagram = async () => {
    const editor = editorRef.current;
    if (!editor) return;
    setBusy(true);
    setErr("");
    try {
      const board = editor
        .getCurrentPageShapes()
        .map((s) => richTextToString((s.props as { richText?: unknown }).richText))
        .filter(Boolean)
        .map((l) => `- ${l}`)
        .join("\n");
      const res = await vigil.studio.canvasDiagram({
        prompt: prompt || "Diagram the key flow on this board",
        board_text: board,
        topic: artifact.title,
      });
      placeDiagram(editor, res.nodes || [], res.edges || []);
      setPrompt("");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ position: "relative", width: "100%", height: "70vh", borderRadius: 12, overflow: "hidden" }}>
      <Tldraw assetUrls={assetUrls} onMount={onMount} />
      <div
        onPointerDown={(e) => e.stopPropagation()}
        onWheelCapture={(e) => e.stopPropagation()}
        style={{
          position: "absolute", top: 8, left: 8, zIndex: 300, width: 278,
          background: "var(--color-background-primary, #ffffff)",
          border: "1px solid rgba(127,127,127,0.25)", borderRadius: 10, padding: 10,
          fontFamily: "var(--font-sans)",
        }}
      >
        <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
          <input
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Brainstorm with the agent…"
            onKeyDown={(e) => { if (e.key === "Enter" && prompt.trim()) void run("ideas", prompt); }}
            style={{ flex: 1, fontSize: 13, padding: "6px 8px", borderRadius: 6, border: "1px solid rgba(127,127,127,0.25)", background: "transparent", color: "inherit", outline: "none" }}
          />
          <button
            disabled={busy || !prompt.trim()}
            onClick={() => void run("ideas", prompt)}
            style={{ fontSize: 12, padding: "6px 10px", borderRadius: 6, border: "1px solid rgba(127,127,127,0.3)", background: "transparent", color: "inherit", opacity: busy || !prompt.trim() ? 0.5 : 1 }}
          >
            {busy ? "…" : "Go"}
          </button>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
          {LENSES.map((l) => (
            <button
              key={l.key}
              disabled={busy}
              onClick={() => void run(l.key)}
              style={{ fontSize: 11, padding: "4px 9px", borderRadius: 999, border: "1px solid rgba(127,127,127,0.25)", background: "transparent", color: "var(--color-text-secondary, #888)", opacity: busy ? 0.5 : 1 }}
            >
              {l.label}
            </button>
          ))}
          <button
            disabled={busy}
            onClick={() => void diagram()}
            title="Agent draws an editable diagram (uses the prompt above)"
            style={{ fontSize: 11, padding: "4px 9px", borderRadius: 999, border: "1px solid var(--color-text-info, #4a90d9)", background: "transparent", color: "var(--color-text-info, #4a90d9)", opacity: busy ? 0.5 : 1 }}
          >
            ◇ Diagram
          </button>
        </div>
        <div style={{ fontSize: 10, color: "var(--color-text-tertiary, #999)", marginTop: 7 }}>
          Select blocks to brainstorm on just those · type a prompt then ◇ Diagram.
        </div>
        {err && <div style={{ fontSize: 11, color: "#ff3366", marginTop: 4 }}>{err}</div>}
      </div>
    </div>
  );
}

function placeBlocks(editor: Editor, blocks: CanvasBlock[]) {
  if (!blocks.length) return;
  const vb = editor.getViewportPageBounds();
  const startX = vb.midX - 240;
  const startY = vb.midY - 120;
  const created: TLShapeId[] = [];
  blocks.forEach((b, i) => {
    const id = createShapeId();
    created.push(id);
    editor.createShape({
      id,
      type: "note",
      x: startX + (i % 3) * 230,
      y: startY + Math.floor(i / 3) * 230,
      props: {
        color: (TLD_COLORS.has(b.color) ? b.color : "yellow") as TLDefaultColorStyle,
        richText: toRichText(b.lens ? `${b.lens}: ${b.text}` : b.text),
      },
    });
  });
  if (created.length) editor.setSelectedShapes(created);
}

function placeDiagram(
  editor: Editor,
  nodes: { id: string; label: string; kind: string; x: number; y: number }[],
  edges: { from: string; to: string }[],
) {
  if (!nodes.length) return;
  const vb = editor.getViewportPageBounds();
  const ox = vb.minX + 40;
  const oy = vb.minY + 40;
  const idMap = new Map<string, TLShapeId>();
  for (const n of nodes) {
    const id = createShapeId();
    idMap.set(n.id, id);
    editor.createShape({
      id,
      type: "geo",
      x: ox + (n.x ?? 0),
      y: oy + (n.y ?? 0),
      props: { geo: "rectangle", w: 170, h: 64, color: KIND_COLOR[n.kind] ?? "black", richText: toRichText(n.label || "") },
    });
  }
  for (const e of edges) {
    const a = idMap.get(e.from);
    const b = idMap.get(e.to);
    if (!a || !b) continue;
    const sa = editor.getShape(a) as { x: number; y: number } | undefined;
    const sb = editor.getShape(b) as { x: number; y: number } | undefined;
    if (sa && sb) {
      try {
        editor.createShape({ type: "arrow", props: { start: { x: sa.x + 170, y: sa.y + 32 }, end: { x: sb.x, y: sb.y + 32 } } });
      } catch {
        /* best-effort */
      }
    }
  }
  editor.setSelectedShapes([...idMap.values()]);
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
    if (!from || !to) continue;
    try {
      const a = editor.getShape(from) as { x: number; y: number } | undefined;
      const b = editor.getShape(to) as { x: number; y: number } | undefined;
      if (a && b) {
        editor.createShape({
          type: "arrow",
          props: { start: { x: a.x + 170, y: a.y + 32 }, end: { x: b.x, y: b.y + 32 } },
        });
      }
    } catch {
      /* arrows best-effort on seed */
    }
  }

  (canvas.table?.rows ?? []).forEach((row, i) => {
    const [task, owner, due] = row;
    const text = [task, owner && `→ ${owner}`, due && `(${due})`].filter(Boolean).join(" ");
    editor.createShape({
      id: createShapeId(),
      type: "note",
      x: 60 + (i % 3) * 230,
      y: 280 + Math.floor(i / 3) * 230,
      props: { color: "yellow", richText: toRichText(text) },
    });
  });

  editor.zoomToFit();
}
