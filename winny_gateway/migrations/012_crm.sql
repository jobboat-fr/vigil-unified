-- CRM backend — contacts + deals/pipeline the crm skill routes into.
-- (sales_leads is inbound-lead intake, not a contacts+pipeline model, so this
-- is a distinct, additive store.) Per-user, RLS-on, app conventions.

CREATE TABLE IF NOT EXISTS public.crm_contacts (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid NOT NULL,
    name       text NOT NULL,
    email      text,
    phone      text,
    company    text,
    title      text,
    tags       text[] NOT NULL DEFAULT '{}',
    notes      text,
    metadata   jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.crm_deals (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid NOT NULL,
    title          text NOT NULL,
    contact_id     uuid REFERENCES public.crm_contacts(id) ON DELETE SET NULL,
    stage          text NOT NULL DEFAULT 'lead',  -- lead|qualified|proposal|negotiation|won|lost
    value          numeric(18,2) NOT NULL DEFAULT 0,
    currency       text NOT NULL DEFAULT 'USD',
    probability    numeric(5,2) NOT NULL DEFAULT 0,  -- 0..100
    expected_close date,
    notes          text,
    metadata       jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS crm_contacts_user_idx ON public.crm_contacts (user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS crm_deals_user_stage_idx ON public.crm_deals (user_id, stage);

ALTER TABLE public.crm_contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.crm_deals ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own crm contacts" ON public.crm_contacts
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Service role full access crm contacts" ON public.crm_contacts
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Users manage own crm deals" ON public.crm_deals
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Service role full access crm deals" ON public.crm_deals
    FOR ALL USING (auth.role() = 'service_role');

CREATE OR REPLACE FUNCTION public.crm_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS crm_contacts_updated_at ON public.crm_contacts;
CREATE TRIGGER crm_contacts_updated_at BEFORE UPDATE ON public.crm_contacts
    FOR EACH ROW EXECUTE FUNCTION public.crm_touch_updated_at();

DROP TRIGGER IF EXISTS crm_deals_updated_at ON public.crm_deals;
CREATE TRIGGER crm_deals_updated_at BEFORE UPDATE ON public.crm_deals
    FOR EACH ROW EXECUTE FUNCTION public.crm_touch_updated_at();
