import { useCallback, useRef, useState, useEffect } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type Connection,
  type OnConnect,
  BackgroundVariant,
  Panel,
  useReactFlow,
  ReactFlowProvider,
  MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  Square, Diamond, StickyNote, Circle, Minus, Star,
  Grid3X3, Spline, Minus as LineIcon, CornerDownRight, Sparkles, GitBranch,
} from 'lucide-react';
import { VigilNode, type VigilNodeData, type BlockShape, PALETTE } from './VigilNode';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface CanvasData {
  nodes: Node[];
  edges: Edge[];
}

/** A brainstorm block returned by the council (winny/council/canvas_brainstorm). */
export interface BrainstormBlock {
  text: string;
  kind?: string;
  color?: string;
  lens?: string | null;
}

/** A diagram graph returned by the council (winny/council/structurer.diagram_from_prompt). */
export interface DiagramGraph {
  nodes: { id: string; label: string; kind: string }[];
  edges: { from: string; to: string }[];
}

type EdgeStyle = 'smooth' | 'straight' | 'step';

interface Props {
  initialNodes?: Node[];
  initialEdges?: Edge[];
  onCanvasChange?: (data: CanvasData) => void;
  color?: string;
  /** Ask the council to drop fresh blocks onto the board (lens-driven). */
  onBrainstorm?: (input: { prompt: string; board_text: string; lens: string }) => Promise<BrainstormBlock[]>;
  /** Ask the council to draw an editable node/edge diagram from a prompt. */
  onDiagram?: (input: { prompt: string; board_text: string }) => Promise<DiagramGraph>;
}

const nodeTypes = { vigil: VigilNode, default: VigilNode };

// ─── Block type palette ───────────────────────────────────────────────────────

const BLOCK_TYPES: {
  label: string;
  kind: string;
  shape: BlockShape;
  color: string;
  Icon: React.ComponentType<{ className?: string; style?: React.CSSProperties }>;
}[] = [
  { label: 'Block',     kind: 'block',     shape: 'block',     color: '#00e5ff', Icon: Square       },
  { label: 'Decision',  kind: 'decision',  shape: 'decision',  color: '#a78bfa', Icon: Diamond      },
  { label: 'Note',      kind: 'note',      shape: 'note',      color: '#34d399', Icon: StickyNote   },
  { label: 'Circle',    kind: 'circle',    shape: 'circle',    color: '#00e5ff', Icon: Circle       },
  { label: 'Action',    kind: 'action',    shape: 'action',    color: '#fbbf24', Icon: Minus        },
  { label: 'Milestone', kind: 'milestone', shape: 'milestone', color: '#e8b544', Icon: Star         },
];

// AI brainstorm lenses — each maps to a council lens in canvas_brainstorm.py.
const LENSES: { key: string; label: string }[] = [
  { key: 'ideas',      label: 'Ideas' },
  { key: 'expand',     label: 'Expand' },
  { key: 'risks',      label: 'Risks' },
  { key: 'missing',    label: 'Gaps' },
  { key: 'next_steps', label: 'Next steps' },
  { key: 'critique',   label: "Devil's advocate" },
  { key: 'council',    label: 'Council' },
];

// council diagram kind → VigilNode shape/color
const DIAGRAM_KIND: Record<string, { shape: BlockShape; color: string }> = {
  problem:  { shape: 'block',     color: '#00e5ff' },
  decision: { shape: 'decision',  color: '#a78bfa' },
  outcome:  { shape: 'milestone', color: '#34d399' },
};

// ─── Edge style helpers ───────────────────────────────────────────────────────

function edgeType(style: EdgeStyle): string {
  return style === 'step' ? 'step' : style === 'straight' ? 'straight' : 'default';
}

// ─── Canvas inner ─────────────────────────────────────────────────────────────

function CanvasInner({ initialNodes = [], initialEdges = [], onCanvasChange, color = '#00e5ff', onBrainstorm, onDiagram }: Props) {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
  const [edgeStyle, setEdgeStyle]         = useState<EdgeStyle>('smooth');
  const [snapGrid, setSnapGrid]           = useState(false);
  const [contextMenu, setContextMenu]     = useState<{ x: number; y: number; flowX: number; flowY: number } | null>(null);
  const [edgeLabelMenu, setEdgeLabelMenu] = useState<{ edgeId: string; x: number; y: number; label: string } | null>(null);
  const [activeColor, setActiveColor]     = useState(color);
  const idCounter                         = useRef(initialNodes.length + 1);
  const reactFlow                         = useReactFlow();
  const wrapperRef                        = useRef<HTMLDivElement>(null);

  // ── AI brainstorm panel state ───────────────────────────────────────────────
  const [prompt, setPrompt] = useState('');
  const [busy, setBusy]     = useState(false);
  const [aiErr, setAiErr]   = useState('');

  // ── Propagate changes to parent (covers ALL changes including node-internal) ─
  // Debounced auto-save, with a guaranteed flush of the pending edit on unmount
  // (e.g. closing the artifact) and when the tab is hidden — so the board is
  // always persisted exactly as you last left it, never losing the final change.
  const isFirstRender = useRef(true);
  const saveTimer     = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingSave   = useRef(false);
  const latestData    = useRef<CanvasData>({ nodes: initialNodes, edges: initialEdges });
  const onChangeRef   = useRef(onCanvasChange);
  useEffect(() => { onChangeRef.current = onCanvasChange; }, [onCanvasChange]);

  const flushSave = useCallback(() => {
    if (saveTimer.current) { clearTimeout(saveTimer.current); saveTimer.current = null; }
    if (pendingSave.current) {
      pendingSave.current = false;
      onChangeRef.current?.(latestData.current);
    }
  }, []);

  useEffect(() => {
    latestData.current = { nodes, edges };
    if (isFirstRender.current) { isFirstRender.current = false; return; }
    if (saveTimer.current) clearTimeout(saveTimer.current);
    pendingSave.current = true;
    saveTimer.current = setTimeout(() => {
      pendingSave.current = false;
      saveTimer.current = null;
      onChangeRef.current?.({ nodes, edges });
    }, 600);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges]);

  // Flush on unmount (Close / navigation) and when the tab is hidden.
  useEffect(() => {
    const onHide = () => { if (document.visibilityState === "hidden") flushSave(); };
    document.addEventListener("visibilitychange", onHide);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      flushSave();
    };
  }, [flushSave]);

  // ── Connect ───────────────────────────────────────────────────────────────
  const onConnect: OnConnect = useCallback((connection: Connection) => {
    setEdges((eds) =>
      addEdge({
        ...connection,
        type: edgeType(edgeStyle),
        animated: true,
        markerEnd: { type: MarkerType.ArrowClosed, color: activeColor, width: 14, height: 14 },
        style: { stroke: activeColor, strokeWidth: 1.5 },
      }, eds)
    );
  }, [edgeStyle, activeColor, setEdges]);

  // ── Add node ──────────────────────────────────────────────────────────────
  const addNode = useCallback((
    label = 'New block',
    kind  = 'block',
    shape: BlockShape = 'block',
    nodeColor = activeColor,
  ) => {
    const id = `n${idCounter.current++}`;
    const position = contextMenu
      ? { x: contextMenu.flowX, y: contextMenu.flowY }
      : { x: 120 + Math.random() * 280, y: 80 + Math.random() * 200 };

    const newNode: Node = {
      id,
      type: 'vigil',
      position,
      data: { label, kind, shape, color: nodeColor } as VigilNodeData,
    };
    setNodes((nds) => [...nds, newNode]);
    setContextMenu(null);
  }, [activeColor, contextMenu, setNodes]);

  // ── AI: where to drop new blocks (center of the current viewport) ───────────
  const viewportCenter = useCallback(() => {
    const el = wrapperRef.current;
    if (!el) return { x: 200, y: 160 };
    const r = el.getBoundingClientRect();
    return reactFlow.screenToFlowPosition({ x: r.left + r.width / 2, y: r.top + r.height / 2 });
  }, [reactFlow]);

  // Build a markdown-ish board context from the given nodes (or all).
  const boardText = useCallback((subset?: Node[]) => {
    const src = subset && subset.length ? subset : nodes;
    return src
      .map((n) => {
        const d = n.data as VigilNodeData;
        const desc = d.description ? ` — ${d.description}` : '';
        return d.label ? `- ${d.label}${desc}` : '';
      })
      .filter(Boolean)
      .join('\n');
  }, [nodes]);

  // ── AI: brainstorm a lens → drop council blocks onto the board ──────────────
  const runLens = useCallback(async (lens: string, p = '') => {
    if (!onBrainstorm) return;
    setBusy(true); setAiErr('');
    try {
      const selected = nodes.filter((n) => n.selected);
      const blocks = await onBrainstorm({ prompt: p, board_text: boardText(selected), lens });
      if (blocks.length) {
        const base = viewportCenter();
        const created: Node[] = blocks.map((b, i) => ({
          id: `n${idCounter.current++}`,
          type: 'vigil',
          position: { x: base.x - 240 + (i % 3) * 230, y: base.y - 120 + Math.floor(i / 3) * 200 },
          selected: true,
          data: {
            label: b.text,
            kind: b.lens || b.kind || lens,
            shape: 'note',
            color: b.color || '#34d399',
          } as VigilNodeData,
        }));
        setNodes((nds) => [...nds.map((n) => ({ ...n, selected: false })), ...created]);
      }
      setPrompt('');
    } catch (e) {
      setAiErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [onBrainstorm, nodes, boardText, viewportCenter, setNodes]);

  // ── AI: draw an editable diagram from a prompt ──────────────────────────────
  const runDiagram = useCallback(async () => {
    if (!onDiagram) return;
    setBusy(true); setAiErr('');
    try {
      const graph = await onDiagram({ prompt: prompt || 'Diagram the key flow on this board', board_text: boardText() });
      if (graph.nodes.length) {
        const base = viewportCenter();
        const idMap = new Map<string, string>();
        const cols: Record<string, number> = { problem: 0, decision: 1, outcome: 2 };
        const colCount: Record<number, number> = {};
        const created: Node[] = graph.nodes.map((n) => {
          const km = DIAGRAM_KIND[n.kind] || { shape: 'block' as BlockShape, color: '#00e5ff' };
          const col = cols[n.kind] ?? 1;
          const row = (colCount[col] = (colCount[col] ?? 0) + 1) - 1;
          const id = `n${idCounter.current++}`;
          idMap.set(n.id, id);
          return {
            id,
            type: 'vigil',
            position: { x: base.x - 240 + col * 240, y: base.y - 120 + row * 150 },
            data: { label: n.label, kind: n.kind, shape: km.shape, color: km.color } as VigilNodeData,
          };
        });
        const newEdges: Edge[] = graph.edges
          .map((e) => ({ from: idMap.get(e.from), to: idMap.get(e.to) }))
          .filter((e): e is { from: string; to: string } => !!e.from && !!e.to)
          .map((e) => ({
            id: `e${e.from}-${e.to}-${idCounter.current++}`,
            source: e.from,
            target: e.to,
            type: edgeType(edgeStyle),
            animated: true,
            markerEnd: { type: MarkerType.ArrowClosed, color: activeColor, width: 14, height: 14 },
            style: { stroke: activeColor, strokeWidth: 1.5 },
          }));
        setNodes((nds) => [...nds.map((n) => ({ ...n, selected: false })), ...created]);
        setEdges((eds) => [...eds, ...newEdges]);
      }
      setPrompt('');
    } catch (e) {
      setAiErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [onDiagram, prompt, boardText, viewportCenter, edgeStyle, activeColor, setNodes, setEdges]);

  // ── Context menu ──────────────────────────────────────────────────────────
  const onPaneContextMenu = useCallback((event: MouseEvent | React.MouseEvent) => {
    event.preventDefault();
    setEdgeLabelMenu(null);
    const flowPos = reactFlow.screenToFlowPosition({ x: event.clientX, y: event.clientY });
    setContextMenu({ x: event.clientX, y: event.clientY, flowX: flowPos.x, flowY: flowPos.y });
  }, [reactFlow]);

  const onPaneClick = useCallback(() => {
    setContextMenu(null);
    setEdgeLabelMenu(null);
  }, []);

  // ── Edge double-click → label ─────────────────────────────────────────────
  const onEdgeDoubleClick = useCallback((_event: React.MouseEvent, edge: Edge) => {
    setEdgeLabelMenu({
      edgeId: edge.id,
      x: _event.clientX,
      y: _event.clientY,
      label: typeof edge.label === 'string' ? edge.label : '',
    });
  }, []);

  const commitEdgeLabel = useCallback((label: string) => {
    if (!edgeLabelMenu) return;
    setEdges((eds) =>
      eds.map((e) => e.id === edgeLabelMenu.edgeId
        ? { ...e, label, labelStyle: { fill: '#e2e8f0', fontSize: 11 }, labelBgStyle: { fill: 'rgba(5,7,10,0.85)' }, labelBgPadding: [4, 3] as [number, number] }
        : e
      )
    );
    setEdgeLabelMenu(null);
  }, [edgeLabelMenu, setEdges]);

  // ── Keyboard ──────────────────────────────────────────────────────────────
  const onKeyDown = useCallback((event: KeyboardEvent) => {
    const tag = (document.activeElement as HTMLElement)?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA') return;

    if (event.key === 'Delete' || event.key === 'Backspace') {
      const selIds = new Set(nodes.filter((n) => n.selected).map((n) => n.id));
      if (selIds.size === 0) return;
      setNodes((nds) => nds.filter((n) => !selIds.has(n.id)));
      setEdges((eds) => eds.filter((e) => !selIds.has(e.source) && !selIds.has(e.target)));
    }

    // Cmd/Ctrl + D → duplicate selected
    if ((event.metaKey || event.ctrlKey) && event.key === 'd') {
      event.preventDefault();
      const sel = nodes.filter((n) => n.selected);
      if (!sel.length) return;
      const dupes = sel.map((n) => ({
        ...n,
        id: `n${idCounter.current++}`,
        position: { x: n.position.x + 50, y: n.position.y + 50 },
        selected: false,
      }));
      setNodes((nds) => [...nds.map((n) => ({ ...n, selected: false })), ...dupes]);
    }

    // Cmd/Ctrl + A → select all
    if ((event.metaKey || event.ctrlKey) && event.key === 'a') {
      event.preventDefault();
      setNodes((nds) => nds.map((n) => ({ ...n, selected: true })));
    }
  }, [nodes, setNodes, setEdges]);

  useEffect(() => {
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onKeyDown]);

  // ─────────────────────────────────────────────────────────────────────────

  return (
    <div ref={wrapperRef} className="w-full h-full relative">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onPaneContextMenu={onPaneContextMenu}
        onPaneClick={onPaneClick}
        onEdgeDoubleClick={onEdgeDoubleClick}
        deleteKeyCode={null}
        nodeTypes={nodeTypes}
        snapToGrid={snapGrid}
        snapGrid={[20, 20]}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        proOptions={{ hideAttribution: true }}
        className="bg-transparent"
        defaultEdgeOptions={{
          animated: true,
          style: { stroke: activeColor, strokeWidth: 1.5 },
          markerEnd: { type: MarkerType.ArrowClosed, color: activeColor, width: 14, height: 14 },
        }}
      >
        {/* ── Grid background ── */}
        <Background
          variant={snapGrid ? BackgroundVariant.Lines : BackgroundVariant.Dots}
          gap={snapGrid ? 20 : 24}
          size={snapGrid ? 0.5 : 1}
          color={snapGrid ? 'rgba(255,255,255,0.03)' : 'rgba(255,255,255,0.04)'}
        />

        {/* ── Controls ── */}
        <Controls
          showInteractive={false}
          className="!bg-dark-900/80 !border-white/[0.08] !rounded-xl !shadow-xl [&>button]:!bg-transparent [&>button]:!border-white/[0.08] [&>button]:!text-dark-100 [&>button:hover]:!text-cyan-electric [&>button]:!rounded-lg"
        />

        {/* ── MiniMap ── */}
        <MiniMap
          nodeStrokeColor={activeColor}
          nodeColor="rgba(5,7,10,0.9)"
          maskColor="rgba(5,7,10,0.85)"
          className="!bg-dark-900/60 !border-white/[0.06] !rounded-xl"
        />

        {/* ── Top-left: Block palette ── */}
        <Panel position="top-left">
          <div className="flex flex-col gap-2">
            {/* Block type buttons */}
            <div className="flex items-center gap-1 bg-dark-900/80 border border-white/[0.08] rounded-xl px-2 py-1.5 backdrop-blur-sm shadow-xl">
              {BLOCK_TYPES.map(({ label, kind, shape, color: c, Icon }) => (
                <button
                  key={kind}
                  onClick={() => addNode(label, kind, shape, c)}
                  title={`Add ${label}`}
                  className="group flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[10px] font-mono tracking-wider text-dark-200/60 hover:text-dark-50 hover:bg-white/[0.06] transition-all"
                >
                  <Icon className="w-3.5 h-3.5 transition-colors" style={{ color: c }} />
                  <span className="hidden sm:inline">{label.toUpperCase()}</span>
                </button>
              ))}
            </div>

            {/* Edge style + grid row */}
            <div className="flex items-center gap-1 bg-dark-900/80 border border-white/[0.08] rounded-xl px-2 py-1.5 backdrop-blur-sm shadow-xl">
              <span className="text-[9px] font-mono text-dark-300/30 mr-1">EDGE</span>
              {([
                { s: 'smooth'  as EdgeStyle, Icon: Spline,        label: 'Smooth' },
                { s: 'straight'as EdgeStyle, Icon: LineIcon,      label: 'Straight' },
                { s: 'step'    as EdgeStyle, Icon: CornerDownRight,label: 'Step' },
              ] as const).map(({ s, Icon, label }) => (
                <button
                  key={s}
                  onClick={() => setEdgeStyle(s)}
                  title={`${label} edges`}
                  className={`w-7 h-7 rounded-lg flex items-center justify-center transition-all ${
                    edgeStyle === s ? 'bg-white/10 text-dark-50' : 'text-dark-300/40 hover:text-dark-100 hover:bg-white/[0.06]'
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                </button>
              ))}

              <div className="w-px h-4 bg-white/[0.06] mx-1" />

              {/* Grid snap */}
              <button
                onClick={() => setSnapGrid((v) => !v)}
                title="Snap to grid"
                className={`w-7 h-7 rounded-lg flex items-center justify-center transition-all ${
                  snapGrid ? 'bg-white/10 text-cyan-electric' : 'text-dark-300/40 hover:text-dark-100 hover:bg-white/[0.06]'
                }`}
              >
                <Grid3X3 className="w-3.5 h-3.5" />
              </button>

              <div className="w-px h-4 bg-white/[0.06] mx-1" />

              {/* Active color dot row (for new edges) */}
              <span className="text-[9px] font-mono text-dark-300/30 mr-1">COLOR</span>
              {PALETTE.map((c) => (
                <button
                  key={c}
                  onClick={() => setActiveColor(c)}
                  title="Edge color"
                  className="w-3.5 h-3.5 rounded-full border transition-all hover:scale-110"
                  style={{
                    backgroundColor: c,
                    borderColor: activeColor === c ? 'rgba(255,255,255,0.6)' : 'transparent',
                    transform: activeColor === c ? 'scale(1.25)' : undefined,
                  }}
                />
              ))}
            </div>
          </div>
        </Panel>

        {/* ── Top-right: AI brainstorm panel (council-wired) ── */}
        {(onBrainstorm || onDiagram) && (
          <Panel position="top-right">
            <div
              className="w-[270px] bg-dark-900/85 border border-white/[0.08] rounded-xl px-3 py-2.5 backdrop-blur-md shadow-xl"
              onMouseDown={(e) => e.stopPropagation()}
            >
              <div className="flex items-center gap-1.5 mb-2">
                <Sparkles className="w-3.5 h-3.5 text-cyan-electric" />
                <span className="text-[10px] font-mono tracking-[0.18em] text-dark-100/70 uppercase">Brainstorm with the council</span>
              </div>

              <div className="flex gap-1.5 mb-2">
                <input
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder="Ask the agent…"
                  onKeyDown={(e) => { if (e.key === 'Enter' && prompt.trim() && !busy) void runLens('ideas', prompt); }}
                  className="flex-1 bg-dark-800/60 border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-xs text-dark-50 placeholder:text-dark-300/30 outline-none focus:border-cyan-electric/30"
                />
                <button
                  disabled={busy || !prompt.trim()}
                  onClick={() => void runLens('ideas', prompt)}
                  className="px-2.5 py-1.5 rounded-lg text-xs text-dark-50 border border-white/[0.08] hover:bg-white/[0.06] disabled:opacity-40 transition-all"
                >
                  {busy ? '…' : 'Go'}
                </button>
              </div>

              {onBrainstorm && (
                <div className="flex flex-wrap gap-1 mb-2">
                  {LENSES.map((l) => (
                    <button
                      key={l.key}
                      disabled={busy}
                      onClick={() => void runLens(l.key)}
                      className="px-2 py-1 rounded-full text-[10px] text-dark-200/70 border border-white/[0.08] hover:text-dark-50 hover:bg-white/[0.06] disabled:opacity-40 transition-all"
                    >
                      {l.label}
                    </button>
                  ))}
                </div>
              )}

              {onDiagram && (
                <button
                  disabled={busy}
                  onClick={() => void runDiagram()}
                  title="The agent draws an editable diagram (uses the prompt above)"
                  className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-lg text-[11px] text-cyan-electric border border-cyan-electric/30 hover:bg-cyan-electric/10 disabled:opacity-40 transition-all"
                >
                  <GitBranch className="w-3.5 h-3.5" /> Draw a diagram
                </button>
              )}

              <p className="text-[9px] text-dark-300/40 mt-2 leading-relaxed">
                Select blocks first to brainstorm on just those. Output drops as editable nodes.
              </p>
              {aiErr && <p className="text-[10px] text-red-400 mt-1">{aiErr}</p>}
            </div>
          </Panel>
        )}

        {/* ── Bottom-left: hints ── */}
        <Panel position="bottom-left">
          <p className="text-[9px] font-mono text-dark-200/20 bg-dark-900/60 backdrop-blur-sm px-2.5 py-1.5 rounded-lg border border-white/[0.04]">
            Right-click canvas to add · Double-click node to rename · Double-click edge to label · Select + Del to remove · ⌘D duplicate · ⌘A select all
          </p>
        </Panel>
      </ReactFlow>

      {/* ── Pane context menu ──────────────────────────────────────────────── */}
      {contextMenu && (
        <div
          className="fixed z-50 bg-dark-900/97 border border-white/[0.09] rounded-xl shadow-[0_8px_40px_rgba(0,0,0,0.6)] backdrop-blur-xl py-1.5 min-w-[200px]"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <p className="px-4 py-1.5 text-[8px] font-mono tracking-[0.2em] text-dark-300/40">ADD BLOCK</p>
          {BLOCK_TYPES.map(({ label, kind, shape, color: c, Icon }) => (
            <button
              key={kind}
              onClick={() => addNode(label, kind, shape, c)}
              className="w-full text-left px-4 py-2 text-xs text-dark-100/70 hover:text-dark-50 hover:bg-white/[0.04] transition-colors flex items-center gap-3"
            >
              <span className="w-6 h-6 rounded-lg flex items-center justify-center" style={{ backgroundColor: `${c}15` }}>
                <Icon className="w-3.5 h-3.5" style={{ color: c }} />
              </span>
              {label}
            </button>
          ))}
        </div>
      )}

      {/* ── Edge label popup ───────────────────────────────────────────────── */}
      {edgeLabelMenu && (
        <div
          className="fixed z-50 bg-dark-900/97 border border-white/[0.09] rounded-xl shadow-[0_8px_40px_rgba(0,0,0,0.6)] backdrop-blur-xl p-3 min-w-[220px]"
          style={{ left: edgeLabelMenu.x - 110, top: edgeLabelMenu.y - 56 }}
          onClick={(e) => e.stopPropagation()}
        >
          <p className="text-[8px] font-mono tracking-[0.2em] text-dark-300/40 mb-2">EDGE LABEL</p>
          <input
            autoFocus
            defaultValue={edgeLabelMenu.label}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitEdgeLabel(e.currentTarget.value);
              if (e.key === 'Escape') setEdgeLabelMenu(null);
            }}
            onBlur={(e) => commitEdgeLabel(e.target.value)}
            placeholder="Label this connection…"
            className="w-full bg-dark-800/50 border border-white/[0.08] rounded-lg px-3 py-2 text-xs text-dark-50 placeholder:text-dark-300/30 focus:outline-none focus:border-cyan-electric/30"
          />
          <p className="text-[9px] text-dark-300/30 mt-1.5">Enter to save · Esc to cancel</p>
        </div>
      )}
    </div>
  );
}

// ─── Exported wrapper ─────────────────────────────────────────────────────────

export function CanvasWorkspace(props: Props) {
  return (
    <ReactFlowProvider>
      <CanvasInner {...props} />
    </ReactFlowProvider>
  );
}
