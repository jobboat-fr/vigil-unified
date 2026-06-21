-- Integration platform keys, editable from the UI.
-- Stores provider platform credentials (e.g. PLAID_CLIENT_ID/PLAID_SECRET) ENCRYPTED
-- at rest (Fernet, shared WINNY_CRED_KEY). The connector resolves keys per-request:
-- a stored value wins, else the gateway env var of the same name (platform default).
-- Owner-operator scoped; values are never returned by any API (set/unset + source only).

CREATE TABLE IF NOT EXISTS public.integration_secrets (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL,
    provider    text NOT NULL,           -- plaid|quickbooks|xero
    name        text NOT NULL,           -- env-style key name, e.g. PLAID_CLIENT_ID
    value_enc   text NOT NULL,           -- Fernet-encrypted value
    updated_at  timestamptz NOT NULL DEFAULT now(),
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT integration_secrets_unique UNIQUE (user_id, provider, name)
);

CREATE INDEX IF NOT EXISTS integration_secrets_user_idx ON public.integration_secrets (user_id, provider);

ALTER TABLE public.integration_secrets ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own integration secrets" ON public.integration_secrets
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Service role full access integration secrets" ON public.integration_secrets
    FOR ALL USING (auth.role() = 'service_role');

CREATE OR REPLACE FUNCTION public.integration_secrets_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS integration_secrets_updated_at ON public.integration_secrets;
CREATE TRIGGER integration_secrets_updated_at BEFORE UPDATE ON public.integration_secrets
    FOR EACH ROW EXECUTE FUNCTION public.integration_secrets_touch_updated_at();
