-- Finance backend — the books/ledger store the cfo-* skills route into
-- (capture → classify → reconcile → close → tax → report). Per-user, RLS-on,
-- mirroring the existing app's table conventions (auth.uid()=user_id + a
-- service-role bypass for the gateway's admin client).

-- Chart of accounts.
CREATE TABLE IF NOT EXISTS public.finance_accounts (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid NOT NULL,
    name       text NOT NULL,
    type       text NOT NULL DEFAULT 'expense',  -- asset|liability|equity|income|expense
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT finance_accounts_user_name_unique UNIQUE (user_id, name)
);

-- The ledger: one row per transaction (capture). category/account fill in at
-- classify; status walks uncategorized → categorized → reconciled.
CREATE TABLE IF NOT EXISTS public.finance_transactions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL,
    txn_date    date NOT NULL DEFAULT current_date,
    description text NOT NULL DEFAULT '',
    amount      numeric(18,2) NOT NULL DEFAULT 0,  -- signed: income +, expense -
    currency    text NOT NULL DEFAULT 'USD',
    category    text,
    account_id  uuid REFERENCES public.finance_accounts(id) ON DELETE SET NULL,
    status      text NOT NULL DEFAULT 'uncategorized',  -- uncategorized|categorized|reconciled
    source      text NOT NULL DEFAULT 'manual',         -- manual|import|broker
    metadata    jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS finance_transactions_user_date_idx
    ON public.finance_transactions (user_id, txn_date DESC);
CREATE INDEX IF NOT EXISTS finance_transactions_user_status_idx
    ON public.finance_transactions (user_id, status);

-- RLS
ALTER TABLE public.finance_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.finance_transactions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own finance accounts" ON public.finance_accounts
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Service role full access finance accounts" ON public.finance_accounts
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Users manage own finance transactions" ON public.finance_transactions
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Service role full access finance transactions" ON public.finance_transactions
    FOR ALL USING (auth.role() = 'service_role');

-- keep updated_at fresh on transaction edits
CREATE OR REPLACE FUNCTION public.finance_txn_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS finance_transactions_updated_at ON public.finance_transactions;
CREATE TRIGGER finance_transactions_updated_at
    BEFORE UPDATE ON public.finance_transactions
    FOR EACH ROW EXECUTE FUNCTION public.finance_txn_touch_updated_at();
