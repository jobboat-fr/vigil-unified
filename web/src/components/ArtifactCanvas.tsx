import { useCallback, useRef, useState } from "react";
import { vigil, type Artifact, type MeetingCanvasNode } from "@/lib/vigil";

// Editable post-meeting artifact canvas: an auto-laid-out decision flow you can
// drag + rename, plus an editable action-items table. The draw.io-style canvas,
// but the layout is AI-generated so you start from something, not a blank page.
// (tldraw is the planned upgrade for free-form drawing; this ships the core
// loop — render → edit → save — today.)

const NODE_W = 150;
const NODE_H = 46;
const KIND: Record<string, { c: string; label: string }> = {
  problem: { c: "#2563EB", label: "problem" },
  decision: { c: "#7C3AED", label: "decision" },
  outcome: { c: "#059669", label: "outcome" },
};

export function ArtifactCanvas({ artifact, onBack }: { artifact: Artifact; onBack?: () => void }) {
  const seed = artifact.canvas ?? { nodes: [], edges: [], table: { columns: ["Action item", "Owner", "Due"], rows: [] } };
  const [nodes, setNodes] = useState<MeetingCanvasNode[]>(seed.nodes ?? []);
  const edges = seed.edges ?? [];
  const [table, setTable] = useState(seed.table ?? { columns: ["Action item", "Owner", "Due"], rows: [] as string[][] });
  const [editing, setEditing] = useState<{ id: string; value: string } | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const canvasRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ id: string; dx: number; dy: number } | null>(null);

  const onMove = useCallback((e: MouseEvent) => {
    const d = drag.current;
    const c = canvasRef.current;
    if (!d || !c) return;
    const rect = c.getBoundingClientRect();
    const x = Math.max(0, Math.min(e.clientX - rect.left - d.dx, rect.width - NODE_W));
    const y = Math.max(0, e.clientY - rect.top - d.dy);
    setNodes((ns) => ns.map((n) => (n.id === d.id ? { ...n, x, y } : n)));
    setDirty(true);
    setSaved(false);
  }, []);
  const onUp = useCallback(() => {
    drag.current = null;
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", onUp);
  }, [onMove]);
  const startDrag = (e: React.MouseEvent, n: MeetingCanvasNode) => {
    if (editing) return;
    const c = canvasRef.current;
    if (!c) return;
    const rect = c.getBoundingClientRect();
    drag.current = { id: n.id, dx: e.clientX - rect.left - n.x, dy: e.clientY - rect.top - n.y };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const commitLabel = () => {
    if (!editing) return;
    setNodes((ns) => ns.map((n) => (n.id === editing.id ? { ...n, label: editing.value } : n)));
    setEditing(null);
    setDirty(true);
    setSaved(false);
  };

  const editCell = (r: number, c: number, v: string) => {
    setTable((t) => {
      const rows = t.rows.map((row) => [...row]);
      rows[r][c] = v;
      return { ...t, rows };
    });
    setDirty(true);
    setSaved(false);
  };
  const addRow = () => {
    setTable((t) => ({ ...t, rows: [...t.rows, t.columns.map(() => "")] }));
    setDirty(true);
  };
  const delRow = (r: number) => {
    setTable((t) => ({ ...t, rows: t.rows.filter((_, i) => i !== r) }));
    setDirty(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      await vigil.studio.saveCanvas(artifact.id, { canvas: { nodes, edges, table } });
      setDirty(false);
      setSaved(true);
    } catch {
      /* surfaced by the disabled state; keep it simple */
    } finally {
      setSaving(false);
    }
  };

  const center = (n: MeetingCanvasNode) => ({ x: n.x + NODE_W / 2, y: n.y + NODE_H / 2 });
  const byId = (id: string) => nodes.find((n) => n.id === id);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        {onBack && (
          <button onClick={onBack} className="text-text-secondary hover:text-foreground text-sm">← back</button>
        )}
        <span className="font-medium">{artifact.title}</span>
        <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400">canvas</span>
        <div className="ml-auto flex items-center gap-2">
          {saved && <span className="text-xs text-emerald-400">saved</span>}
          <Button onClick={() => void save()} disabled={!dirty || saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>

      <div
        ref={canvasRef}
        className="relative rounded-lg border border-current/15 overflow-hidden"
        style={{ height: 320, background: "var(--color-background-secondary, rgba(127,127,127,0.06))" }}
      >
        <svg className="absolute inset-0 pointer-events-none" width="100%" height="100%">
          {edges.map((e, i) => {
            const a = byId(e.from);
            const b = byId(e.to);
            if (!a || !b) return null;
            const p = center(a);
            const q = center(b);
            return <line key={i} x1={p.x} y1={p.y} x2={q.x} y2={q.y} stroke="currentColor" strokeOpacity={0.3} strokeWidth={1.5} />;
          })}
        </svg>
        {nodes.map((n) => {
          const k = KIND[n.kind] ?? KIND.decision;
          return (
            <div
              key={n.id}
              onMouseDown={(e) => startDrag(e, n)}
              onDoubleClick={() => setEditing({ id: n.id, value: n.label })}
              className="absolute select-none rounded-md text-xs flex items-center justify-center text-center px-2"
              style={{
                left: n.x,
                top: n.y,
                width: NODE_W,
                minHeight: NODE_H,
                cursor: editing?.id === n.id ? "text" : "grab",
                border: `1.5px solid ${k.c}`,
                background: "var(--color-background-primary, rgba(127,127,127,0.12))",
                color: "inherit",
              }}
              title={`${k.label} — double-click to rename`}
            >
              {editing?.id === n.id ? (
                <input
                  autoFocus
                  value={editing.value}
                  onChange={(e) => setEditing({ id: n.id, value: e.target.value })}
                  onBlur={commitLabel}
                  onKeyDown={(e) => { if (e.key === "Enter") commitLabel(); }}
                  className="w-full bg-transparent text-xs text-center outline-none"
                />
              ) : (
                n.label
              )}
            </div>
          );
        })}
        {nodes.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center text-text-secondary text-xs">
            No diagram yet — it's generated when you close a meeting.
          </div>
        )}
      </div>

      <div>
        <div className="text-[10px] font-mono uppercase tracking-wide text-text-secondary mb-1.5">Action items</div>
        <table className="w-full text-xs border border-current/15 rounded-lg overflow-hidden">
          <thead>
            <tr className="text-text-secondary">
              {table.columns.map((c) => (
                <th key={c} className="text-left px-2.5 py-1.5 border-b border-current/15 font-normal">{c}</th>
              ))}
              <th className="w-8 border-b border-current/15" aria-label="row actions" />
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, r) => (
              <tr key={r}>
                {row.map((cell, c) => (
                  <td key={c} className="px-1 py-0.5 border-b border-current/10">
                    <input
                      value={cell}
                      onChange={(e) => editCell(r, c, e.target.value)}
                      className="w-full bg-transparent px-1.5 py-1 outline-none focus:bg-current/5 rounded"
                    />
                  </td>
                ))}
                <td className="text-center border-b border-current/10">
                  <button onClick={() => delRow(r)} className="text-text-secondary hover:text-rose-400" aria-label="delete row">×</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button onClick={addRow} className="mt-2 text-xs text-text-secondary hover:text-foreground">+ add row</button>
      </div>

      {artifact.content && (
        <details className="text-sm">
          <summary className="cursor-pointer text-text-secondary text-xs">Full summary</summary>
          <pre className="whitespace-pre-wrap mt-2 text-[13px] leading-relaxed">{artifact.content}</pre>
        </details>
      )}
    </div>
  );
}

function Button({ children, onClick, disabled }: { children: React.ReactNode; onClick?: () => void; disabled?: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="text-xs px-3 py-1.5 rounded border border-current/30 hover:bg-current/5 disabled:opacity-40"
    >
      {children}
    </button>
  );
}
