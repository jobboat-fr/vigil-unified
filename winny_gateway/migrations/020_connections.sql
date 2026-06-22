-- Connector kit — a generic, per-tenant connection store (Phase 0).
-- One row per tenant↔provider link. Holds ONLY the tenant's tokens (encrypted at
-- rest, Fernet); platform app-credentials live in env/secrets-manager, never here.
-- Provider-agnostic: GitHub, Gmail, HubSpot, etc. each reuse this table + the
-- Connector base. (Finance/Plaid keeps its existing finance_connections table.)

CREATE TABLE IF NOT EXISTS public.connections (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            uuid NOT NULL,
    provider           text NOT NULL,                       -- github|gmail|hubspot|...
    kind               text NOT NULL DEFAULT 'generic',     -- engineering|email|crm|...
    external_account   text,                                -- e.g. the github login
    access_token_enc   text NOT NULL,                       -- Fernet-encrypted tenant token
    refresh_token_enc  text,                                -- Fernet-encrypted (OAuth providers)
    status             text NOT NULL DEFAULT 'active',      -- active|error|revoked
    cursor             text,                                -- incremental sync cursor
    metadata           jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_synced_at     timestamptz,
    error              text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS connections_user_provider_idx ON public.connections (user_id, provider);

ALTER TABLE public.connections ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own connections" ON public.connections
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Service role full access connections" ON public.connections
    FOR ALL USING (auth.role() = 'service_role');

CREATE OR REPLACE FUNCTION public.connections_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS connections_updated_at ON public.connections;
CREATE TRIGGER connections_updated_at BEFORE UPDATE ON public.connections
    FOR EACH ROW EXECUTE FUNCTION public.connections_touch_updated_at();
