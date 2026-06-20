import { memo, useState, useRef, useCallback, useEffect } from 'react';
import { Handle, Position, type NodeProps, useReactFlow } from '@xyflow/react';
import {
  Square, Diamond, StickyNote, Circle, Minus, Star,
  Copy, Trash2, AlignLeft, Check,
} from 'lucide-react';

// ─── Types ────────────────────────────────────────────────────────────────────

export type BlockShape = 'block' | 'decision' | 'note' | 'circle' | 'action' | 'milestone';

export type VigilNodeData = {
  label: string;
  kind?: string;
  shape?: BlockShape;
  color?: string;
  description?: string;
};

// ─── Constants ────────────────────────────────────────────────────────────────

export const PALETTE = ['#00e5ff', '#a78bfa', '#34d399', '#fbbf24', '#f87171', '#e8b544'];

const KIND_DEFAULTS: Record<string, { color: string; shape: BlockShape }> = {
  decision:  { color: '#a78bfa', shape: 'decision'  },
  note:      { color: '#34d399', shape: 'note'      },
  action:    { color: '#fbbf24', shape: 'action'    },
  risk:      { color: '#f87171', shape: 'block'     },
  circle:    { color: '#00e5ff', shape: 'circle'    },
  milestone: { color: '#e8b544', shape: 'milestone' },
};

const SHAPE_OPTIONS: { shape: BlockShape; label: string; Icon: React.ComponentType<{ className?: string }> }[] = [
  { shape: 'block',     label: 'Block',     Icon: Square     },
  { shape: 'decision',  label: 'Decision',  Icon: Diamond    },
  { shape: 'note',      label: 'Note',      Icon: StickyNote },
  { shape: 'circle',    label: 'Circle',    Icon: Circle     },
  { shape: 'action',    label: 'Action',    Icon: Minus      },
  { shape: 'milestone', label: 'Milestone', Icon: Star       },
];

// ─── Handle helper ────────────────────────────────────────────────────────────

function Handles({ color }: { color: string }) {
  const cls =
    '!w-3 !h-3 !bg-dark-800 !border-2 !rounded-full transition-all duration-150 ' +
    '!opacity-0 group-hover:!opacity-100 hover:!scale-125 hover:!bg-white/20';
  const style = { borderColor: `${color}80` };
  return (
    <>
      <Handle type="target"  position={Position.Top}    className={cls} style={style} />
      <Handle type="source"  position={Position.Bottom} className={cls} style={style} />
      <Handle type="source"  position={Position.Left}   className={cls} style={{ ...style, top: '50%' }} />
      <Handle type="source"  position={Position.Right}  className={cls} style={{ ...style, top: '50%' }} />
    </>
  );
}

// ─── Floating toolbar ─────────────────────────────────────────────────────────

interface ToolbarProps {
  shape: BlockShape;
  color: string;
  hasDesc: boolean;
  onShape: (s: BlockShape) => void;
  onColor: (c: string) => void;
  onDescToggle: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
}

function NodeToolbar({ shape, color, hasDesc, onShape, onColor, onDescToggle, onDuplicate, onDelete }: ToolbarProps) {
  return (
    <div
      className="absolute -top-14 left-1/2 -translate-x-1/2 z-[9999] nodrag nopan nowheel pointer-events-auto"
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="flex items-center gap-0.5 bg-dark-900/98 border border-white/[0.1] rounded-xl px-2 py-1.5 shadow-[0_8px_32px_rgba(0,0,0,0.6)] backdrop-blur-xl whitespace-nowrap">

        {/* Shape picker */}
        {SHAPE_OPTIONS.map(({ shape: s, label, Icon }) => (
          <button
            key={s}
            onClick={() => onShape(s)}
            title={label}
            className={`w-7 h-7 rounded-lg flex items-center justify-center transition-all ${
              shape === s
                ? 'bg-white/10 text-dark-50'
                : 'text-dark-300/50 hover:text-dark-100 hover:bg-white/[0.06]'
            }`}
          >
            <Icon className="w-3.5 h-3.5" />
          </button>
        ))}

        <div className="w-px h-4 bg-white/[0.08] mx-1" />

        {/* Color swatches */}
        {PALETTE.map((c) => (
          <button
            key={c}
            onClick={() => onColor(c)}
            title={c}
            className="relative w-4 h-4 rounded-full border border-transparent hover:scale-110 transition-all"
            style={{ backgroundColor: c, borderColor: color === c ? 'rgba(255,255,255,0.6)' : 'transparent', transform: color === c ? 'scale(1.2)' : undefined }}
          >
            {color === c && (
              <Check className="absolute inset-0 w-full h-full p-0.5 text-dark-900" />
            )}
          </button>
        ))}

        <div className="w-px h-4 bg-white/[0.08] mx-1" />

        {/* Description toggle */}
        <button
          onClick={onDescToggle}
          title="Toggle description"
          className={`w-7 h-7 rounded-lg flex items-center justify-center transition-all ${
            hasDesc ? 'text-cyan-electric bg-cyan-electric/10' : 'text-dark-300/50 hover:text-dark-100 hover:bg-white/[0.06]'
          }`}
        >
          <AlignLeft className="w-3.5 h-3.5" />
        </button>

        {/* Duplicate */}
        <button
          onClick={onDuplicate}
          title="Duplicate"
          className="w-7 h-7 rounded-lg flex items-center justify-center text-dark-300/50 hover:text-dark-100 hover:bg-white/[0.06] transition-all"
        >
          <Copy className="w-3.5 h-3.5" />
        </button>

        {/* Delete */}
        <button
          onClick={onDelete}
          title="Delete"
          className="w-7 h-7 rounded-lg flex items-center justify-center text-red-400/50 hover:text-red-400 hover:bg-red-400/[0.08] transition-all"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>
      {/* Arrow */}
      <div className="absolute -bottom-1.5 left-1/2 -translate-x-1/2 w-3 h-1.5 overflow-hidden">
        <div className="w-2 h-2 bg-dark-900/98 border-b border-r border-white/[0.1] rotate-45 mx-auto -mt-1" />
      </div>
    </div>
  );
}

// ─── Content ──────────────────────────────────────────────────────────────────

interface ContentProps {
  d: VigilNodeData;
  editing: boolean;
  labelDraft: string;
  editingDesc: boolean;
  descDraft: string;
  inputRef: React.RefObject<HTMLInputElement | null>;
  descRef: React.RefObject<HTMLTextAreaElement | null>;
  onLabelChange: (v: string) => void;
  onLabelCommit: () => void;
  onLabelKey: (e: React.KeyboardEvent) => void;
  onDoubleClick: () => void;
  onDescChange: (v: string) => void;
  onDescCommit: () => void;
  onDescKey: (e: React.KeyboardEvent) => void;
  onDescDoubleClick: () => void;
  center?: boolean;
}

function NodeContent({ d, editing, labelDraft, editingDesc, descDraft,
  inputRef, descRef, onLabelChange, onLabelCommit, onLabelKey, onDoubleClick,
  onDescChange, onDescCommit, onDescKey, onDescDoubleClick, center }: ContentProps) {
  return (
    <div className={`${center ? 'text-center' : ''} w-full`}>
      {d.kind && (
        <p className="text-[8px] font-mono tracking-[0.2em] uppercase mb-1 opacity-50"
           style={{ color: d.color || '#00e5ff' }}>
          {d.kind}
        </p>
      )}
      {editing ? (
        <input
          ref={inputRef}
          value={labelDraft}
          onChange={(e) => onLabelChange(e.target.value)}
          onBlur={onLabelCommit}
          onKeyDown={onLabelKey}
          className={`text-sm font-medium bg-transparent border-b border-cyan-electric/40 outline-none w-full leading-snug text-dark-50 ${center ? 'text-center' : ''}`}
          autoFocus
        />
      ) : (
        <p
          className="text-sm font-medium text-dark-50 leading-snug cursor-text select-none"
          onDoubleClick={onDoubleClick}
        >
          {d.label || 'Unnamed block'}
        </p>
      )}

      {(d.description || editingDesc) && (
        <div className="mt-1.5">
          {editingDesc ? (
            <textarea
              ref={descRef}
              value={descDraft}
              onChange={(e) => onDescChange(e.target.value)}
              onBlur={onDescCommit}
              onKeyDown={onDescKey}
              className="text-[11px] text-dark-100/60 bg-transparent outline-none resize-none w-full leading-relaxed border-b border-white/10 placeholder:text-dark-300/30"
              rows={2}
              placeholder="Add description…"
              autoFocus
            />
          ) : (
            <p
              className="text-[11px] text-dark-100/40 leading-relaxed cursor-text line-clamp-3"
              onDoubleClick={onDescDoubleClick}
            >
              {d.description}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Main node component ──────────────────────────────────────────────────────

function VigilNodeComponent({ id, data, selected }: NodeProps) {
  const d = data as VigilNodeData;
  const kindDef = d.kind ? KIND_DEFAULTS[d.kind] : null;
  const shape: BlockShape = d.shape || kindDef?.shape || 'block';
  const color = d.color || kindDef?.color || '#00e5ff';

  const reactFlow = useReactFlow();

  // Label editing
  const [editing, setEditing]         = useState(false);
  const [labelDraft, setLabelDraft]   = useState(d.label);
  const inputRef = useRef<HTMLInputElement>(null);

  // Description editing
  const [editingDesc, setEditingDesc] = useState(false);
  const [descDraft, setDescDraft]     = useState(d.description || '');
  const descRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { setLabelDraft(d.label); }, [d.label]);
  useEffect(() => { setDescDraft(d.description || ''); }, [d.description]);

  // Helpers
  const updateData = useCallback((patch: Partial<VigilNodeData>) => {
    reactFlow.setNodes((nds) =>
      nds.map((n) => n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)
    );
  }, [id, reactFlow]);

  const commitLabel = useCallback(() => {
    setEditing(false);
    const val = labelDraft.trim();
    if (val && val !== d.label) updateData({ label: val });
    else setLabelDraft(d.label);
  }, [labelDraft, d.label, updateData]);

  const commitDesc = useCallback(() => {
    setEditingDesc(false);
    updateData({ description: descDraft.trim() || undefined });
  }, [descDraft, updateData]);

  const startEdit = useCallback(() => {
    setEditing(true);
    setTimeout(() => inputRef.current?.select(), 30);
  }, []);

  const startDescEdit = useCallback(() => {
    setEditingDesc(true);
    setTimeout(() => descRef.current?.focus(), 30);
  }, []);

  const handleDelete = useCallback(() => {
    reactFlow.setNodes((nds) => nds.filter((n) => n.id !== id));
    reactFlow.setEdges((eds) => eds.filter((e) => e.source !== id && e.target !== id));
  }, [id, reactFlow]);

  const handleDuplicate = useCallback(() => {
    const node = reactFlow.getNode(id);
    if (!node) return;
    reactFlow.setNodes((nds) => [
      ...nds,
      { ...node, id: `n${Date.now()}`, position: { x: node.position.x + 50, y: node.position.y + 50 }, selected: false },
    ]);
  }, [id, reactFlow]);

  const handleShape = useCallback((s: BlockShape) => updateData({ shape: s }), [updateData]);
  const handleColor = useCallback((c: string) => updateData({ color: c }), [updateData]);

  const toggleDesc = useCallback(() => {
    if (d.description) {
      updateData({ description: undefined });
    } else {
      startDescEdit();
    }
  }, [d.description, updateData, startDescEdit]);

  // Shared content props
  const contentProps: ContentProps = {
    d, editing, labelDraft, editingDesc, descDraft, inputRef, descRef,
    onLabelChange: setLabelDraft,
    onLabelCommit: commitLabel,
    onLabelKey: (e) => {
      if (e.key === 'Enter') commitLabel();
      if (e.key === 'Escape') { setEditing(false); setLabelDraft(d.label); }
    },
    onDoubleClick: startEdit,
    onDescChange: setDescDraft,
    onDescCommit: commitDesc,
    onDescKey: (e) => { if (e.key === 'Escape') { setEditingDesc(false); setDescDraft(d.description || ''); } },
    onDescDoubleClick: startDescEdit,
  };

  const toolbar = selected ? (
    <NodeToolbar
      shape={shape} color={color} hasDesc={!!d.description}
      onShape={handleShape} onColor={handleColor} onDescToggle={toggleDesc}
      onDuplicate={handleDuplicate} onDelete={handleDelete}
    />
  ) : null;

  // ── Block (default) ────────────────────────────────────────────────────────
  if (shape === 'block') {
    return (
      <div
        className="group relative rounded-xl border px-4 py-3 min-w-[140px] max-w-[260px] backdrop-blur-md transition-all duration-200"
        style={{
          background: 'rgba(5,7,10,0.88)',
          borderColor: selected ? color : `${color}30`,
          boxShadow: selected ? `0 0 0 1px ${color}40, 0 0 24px ${color}18` : `0 2px 8px rgba(0,0,0,0.3)`,
        }}
      >
        {toolbar}
        <Handles color={color} />
        <NodeContent {...contentProps} />
      </div>
    );
  }

  // ── Decision (diamond) ─────────────────────────────────────────────────────
  if (shape === 'decision') {
    const size = 150;
    const inner = 100;
    return (
      <div className="group relative" style={{ width: size, height: size }}>
        {toolbar}
        {/* Diamond background */}
        <div
          style={{
            position: 'absolute',
            width: inner, height: inner,
            top: '50%', left: '50%',
            transform: 'translate(-50%, -50%) rotate(45deg)',
            background: 'rgba(5,7,10,0.90)',
            border: `1.5px solid ${selected ? color : `${color}40`}`,
            boxShadow: selected ? `0 0 24px ${color}22` : '0 2px 8px rgba(0,0,0,0.3)',
          }}
        />
        {/* Content (counter-rotated) */}
        <div
          style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 18px' }}
        >
          <NodeContent {...contentProps} center />
        </div>
        {/* Handles at 4 compass points */}
        <Handle type="target"  position={Position.Top}    className="!w-3 !h-3 !bg-dark-800 !border-2 !rounded-full !opacity-0 group-hover:!opacity-100 transition-all" style={{ borderColor: `${color}80`, left: '50%' }} />
        <Handle type="source"  position={Position.Bottom} className="!w-3 !h-3 !bg-dark-800 !border-2 !rounded-full !opacity-0 group-hover:!opacity-100 transition-all" style={{ borderColor: `${color}80`, left: '50%' }} />
        <Handle type="source"  position={Position.Left}   className="!w-3 !h-3 !bg-dark-800 !border-2 !rounded-full !opacity-0 group-hover:!opacity-100 transition-all" style={{ borderColor: `${color}80`, top: '50%' }} />
        <Handle type="source"  position={Position.Right}  className="!w-3 !h-3 !bg-dark-800 !border-2 !rounded-full !opacity-0 group-hover:!opacity-100 transition-all" style={{ borderColor: `${color}80`, top: '50%' }} />
      </div>
    );
  }

  // ── Note (sticky) ──────────────────────────────────────────────────────────
  if (shape === 'note') {
    return (
      <div
        className="group relative min-w-[160px] max-w-[280px] transition-all duration-200"
        style={{ filter: selected ? `drop-shadow(0 0 12px ${color}30)` : undefined }}
      >
        {toolbar}
        <div
          className="px-4 pt-3 pb-4"
          style={{
            background: `rgba(5,7,10,0.92)`,
            borderTop: `3px solid ${color}`,
            borderLeft: `1px solid ${color}20`,
            borderRight: `1px solid ${color}10`,
            borderBottom: `1px solid ${color}10`,
            borderRadius: '0 8px 8px 8px',
            boxShadow: selected ? `0 0 0 1px ${color}30, 0 4px 20px rgba(0,0,0,0.4)` : '0 2px 8px rgba(0,0,0,0.3)',
          }}
        >
          {/* Fold corner */}
          <div style={{
            position: 'absolute', top: 0, right: 0, width: 0, height: 0,
            borderStyle: 'solid',
            borderWidth: '0 14px 14px 0',
            borderColor: `transparent rgba(5,7,10,0.95) transparent transparent`,
          }} />
          <NodeContent {...contentProps} />
        </div>
        <Handles color={color} />
      </div>
    );
  }

  // ── Circle ─────────────────────────────────────────────────────────────────
  if (shape === 'circle') {
    const size = 110;
    return (
      <div
        className="group relative flex items-center justify-center transition-all duration-200"
        style={{
          width: size, height: size,
          borderRadius: '50%',
          background: 'rgba(5,7,10,0.88)',
          border: `1.5px solid ${selected ? color : `${color}40`}`,
          boxShadow: selected ? `0 0 0 1px ${color}30, 0 0 24px ${color}18` : '0 2px 8px rgba(0,0,0,0.3)',
          padding: '12px',
        }}
      >
        {toolbar}
        <NodeContent {...contentProps} center />
        <Handles color={color} />
      </div>
    );
  }

  // ── Action (pill) ──────────────────────────────────────────────────────────
  if (shape === 'action') {
    return (
      <div
        className="group relative flex items-center justify-center min-w-[160px] px-6 py-2.5 transition-all duration-200"
        style={{
          borderRadius: 40,
          background: `linear-gradient(135deg, rgba(5,7,10,0.92) 0%, ${color}08 100%)`,
          border: `1.5px solid ${selected ? color : `${color}40`}`,
          boxShadow: selected ? `0 0 0 1px ${color}30, 0 0 20px ${color}18` : '0 2px 8px rgba(0,0,0,0.3)',
        }}
      >
        {toolbar}
        <NodeContent {...contentProps} center />
        <Handles color={color} />
      </div>
    );
  }

  // ── Milestone (hexagon badge) ──────────────────────────────────────────────
  if (shape === 'milestone') {
    return (
      <div
        className="group relative px-5 py-3 min-w-[140px] max-w-[240px] transition-all duration-200"
        style={{
          background: 'rgba(5,7,10,0.90)',
          border: `1.5px solid ${selected ? color : `${color}50`}`,
          clipPath: 'polygon(12px 0%, calc(100% - 12px) 0%, 100% 50%, calc(100% - 12px) 100%, 12px 100%, 0% 50%)',
          paddingLeft: '20px', paddingRight: '20px',
          boxShadow: selected ? `0 0 24px ${color}22` : '0 2px 8px rgba(0,0,0,0.3)',
        }}
      >
        {toolbar}
        <div className="flex items-center gap-2">
          <Star className="w-3 h-3 shrink-0" style={{ color }} />
          <NodeContent {...contentProps} />
        </div>
        <Handles color={color} />
      </div>
    );
  }

  return null;
}

export const VigilNode = memo(VigilNodeComponent);
