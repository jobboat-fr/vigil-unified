-- Phase 4 — the post-meeting artifact canvas.
-- Stores the canvas-ready structure (decision-flow nodes/edges + action table)
-- and the tldraw document the user edits, alongside the existing text artifact.
ALTER TABLE public.artifacts
  ADD COLUMN IF NOT EXISTS canvas   jsonb,   -- {nodes, edges, table} from the structurer
  ADD COLUMN IF NOT EXISTS tldraw   jsonb;   -- the tldraw editor document, once the user edits
