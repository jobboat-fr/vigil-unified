-- Outbound write-actions queue (owner-gated, human-in-the-loop).
-- A department (or the UI) PROPOSES an outbound action via a connector (send an
-- email, open a GitHub issue, …). It lands here as `pending` and is NEVER executed
-- by the autonomous engine. Only a human (the tenant) approving it via the API
-- triggers execution through the connector. This is the consent/liability gate for
-- anything that leaves the system. Per-tenant, RLS-on.

CREATE TABLE IF NOT EXISTS public.outbound_actions (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid NOT NULL,
    provider       text NOT NULL,                       -- gmail|github|hubspot|...
    connection_id  uuid,                                -- the connection it runs through
    action         text NOT NULL,                       -- send|create_issue|...
    params         jsonb NOT NULL DEFAULT '{}'::jsonb,
    status         text NOT NULL DEFAULT 'pending',     -- pending|executed|rejected|failed
    result         jsonb,
    error          text,
    department_id  uuid,                                -- which department proposed it (if any)
    requested_by   text NOT NULL DEFAULT 'agent',       -- agent|user
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS outbound_actions_user_status_idx ON public.outbound_actions (user_id, status, created_at DESC);

ALTER TABLE public.outbound_actions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own outbound actions" ON public.outbound_actions
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Service role full access outbound actions" ON public.outbound_actions
    FOR ALL USING (auth.role() = 'service_role');

CREATE OR REPLACE FUNCTION public.outbound_actions_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS outbound_actions_updated_at ON public.outbound_actions;
CREATE TRIGGER outbound_actions_updated_at BEFORE UPDATE ON public.outbound_actions
    FOR EACH ROW EXECUTE FUNCTION public.outbound_actions_touch_updated_at();
