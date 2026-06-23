-- Legal precedent board (Phase 3, adapted from lavern's cross-engagement learning).
-- Each Legal review stores its key finding + the documents it cited; subsequent
-- reviews are given recent precedents as context, so the department gets sharper over
-- time instead of starting cold every run. Per-tenant, RLS-on.

CREATE TABLE IF NOT EXISTS public.legal_precedents (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL,
    title       text NOT NULL DEFAULT '',
    summary     text NOT NULL DEFAULT '',
    doc_ids     jsonb NOT NULL DEFAULT '[]'::jsonb,   -- the real vault docs it grounded in
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS legal_precedents_user_idx ON public.legal_precedents (user_id, created_at DESC);

ALTER TABLE public.legal_precedents ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own legal precedents" ON public.legal_precedents
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Service role full access legal precedents" ON public.legal_precedents
    FOR ALL USING (auth.role() = 'service_role');
