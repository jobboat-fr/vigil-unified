-- Stage 5 persistence — move the unified Studio + Meeting Room off in-memory
-- stores onto the EXISTING VIGIL tables (public.artifacts, public.rooms), which
-- already carry live data and RLS. This migration is purely ADDITIVE: it only
-- adds nullable/defaulted columns the unified brainstorm→draft + room flows need,
-- so existing rows and the prior app keep working untouched.

-- Studio: the brainstorm gate's brief + approved approach, and whether the draft
-- came from the keyless stub provider. (content → text_dump, brief short → summary
-- already exist; version already counts revisions.)
ALTER TABLE public.artifacts
  ADD COLUMN IF NOT EXISTS brief    text,
  ADD COLUMN IF NOT EXISTS approach text,
  ADD COLUMN IF NOT EXISTS stub     boolean NOT NULL DEFAULT false;

-- Meeting Room: the Deal Board members (full objects, including custom name/
-- title/voiceColor beyond the template lenses) and the room's default council
-- lens. Transcript reuses the existing rooms.transcript jsonb column.
ALTER TABLE public.rooms
  ADD COLUMN IF NOT EXISTS members      jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS default_lens text  NOT NULL DEFAULT 'cfo_review';
