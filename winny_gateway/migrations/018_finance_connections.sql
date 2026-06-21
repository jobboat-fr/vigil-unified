-- Finance connections — links to external bank / accounting providers (Plaid for
-- bank accounts via API; QuickBooks/Xero accounting later). The per-user access
-- token is stored ENCRYPTED at rest (Fernet, same WINNY_CRED_KEY as broker creds);
-- the plaintext token is never returned by any API. Per-user, RLS-on.

CREATE TABLE IF NOT EXISTS public.finance_connections (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            uuid NOT NULL,
    provider           text NOT NULL,                       -- plaid|quickbooks|xero
    item_id            text,                                -- provider item/realm id
    access_token_enc   text NOT NULL,                       -- Fernet-encrypted access token
    institution        text,                                -- display name of the linked bank/org
    status             text NOT NULL DEFAULT 'active',      -- active|error|revoked
    cursor             text,                                -- transactions/sync incremental cursor
    accounts_count     integer NOT NULL DEFAULT 0,
    last_synced_at     timestamptz,
    error              text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS finance_connections_user_idx ON public.finance_connections (user_id);

ALTER TABLE public.finance_connections ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own finance connections" ON public.finance_connections
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Service role full access finance connections" ON public.finance_connections
    FOR ALL USING (auth.role() = 'service_role');

CREATE OR REPLACE FUNCTION public.finance_conn_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS finance_connections_updated_at ON public.finance_connections;
CREATE TRIGGER finance_connections_updated_at BEFORE UPDATE ON public.finance_connections
    FOR EACH ROW EXECUTE FUNCTION public.finance_conn_touch_updated_at();
