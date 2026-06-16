-- Mail backend — the triage store the mail-triage skill routes into, fed by the
-- himalaya transport (IMAP/SMTP CLI) when configured, or by manual ingest.
-- Per-user, RLS-on, app conventions.

CREATE TABLE IF NOT EXISTS public.mail_messages (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid NOT NULL,
    external_id  text,                 -- himalaya/IMAP id; NULL for manual
    thread_id    text,
    folder       text NOT NULL DEFAULT 'INBOX',
    from_addr    text,
    from_name    text,
    to_addrs     text[] NOT NULL DEFAULT '{}',
    subject      text,
    snippet      text,
    body         text,
    received_at  timestamptz,
    category     text,                 -- triage bucket: urgent|respond|fyi|newsletter|spam|archive
    priority     text NOT NULL DEFAULT 'normal',  -- high|normal|low
    triage_score numeric(5,2),         -- classifier confidence 0..1
    status       text NOT NULL DEFAULT 'unread',  -- unread|read|archived
    tags         text[] NOT NULL DEFAULT '{}',
    triaged      boolean NOT NULL DEFAULT false,
    metadata     jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    -- idempotent ingest: re-syncing the same envelope upserts (NULLs are
    -- distinct, so manual messages never collide)
    CONSTRAINT mail_messages_user_external_unique UNIQUE (user_id, external_id)
);

-- Outbound drafts — review-then-send (never auto-sent; persona hard rule).
CREATE TABLE IF NOT EXISTS public.mail_drafts (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL,
    in_reply_to text,                  -- external_id of the message being answered
    to_addrs    text[] NOT NULL DEFAULT '{}',
    subject     text,
    body        text NOT NULL DEFAULT '',
    status      text NOT NULL DEFAULT 'draft',  -- draft|approved|sent
    metadata    jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS mail_messages_user_status_idx ON public.mail_messages (user_id, status);
CREATE INDEX IF NOT EXISTS mail_messages_user_category_idx ON public.mail_messages (user_id, category);
CREATE INDEX IF NOT EXISTS mail_messages_user_received_idx ON public.mail_messages (user_id, received_at DESC);
CREATE INDEX IF NOT EXISTS mail_drafts_user_status_idx ON public.mail_drafts (user_id, status);

ALTER TABLE public.mail_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mail_drafts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own mail messages" ON public.mail_messages
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Service role full access mail messages" ON public.mail_messages
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Users manage own mail drafts" ON public.mail_drafts
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Service role full access mail drafts" ON public.mail_drafts
    FOR ALL USING (auth.role() = 'service_role');

CREATE OR REPLACE FUNCTION public.mail_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS mail_messages_updated_at ON public.mail_messages;
CREATE TRIGGER mail_messages_updated_at BEFORE UPDATE ON public.mail_messages
    FOR EACH ROW EXECUTE FUNCTION public.mail_touch_updated_at();

DROP TRIGGER IF EXISTS mail_drafts_updated_at ON public.mail_drafts;
CREATE TRIGGER mail_drafts_updated_at BEFORE UPDATE ON public.mail_drafts
    FOR EACH ROW EXECUTE FUNCTION public.mail_touch_updated_at();
