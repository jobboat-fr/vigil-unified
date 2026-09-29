-- Auto-trade configuration table
-- Stores per-user auto-trade settings (Pro tier feature)

CREATE TABLE IF NOT EXISTS public.auto_trade_config (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    strategy_id TEXT NOT NULL DEFAULT '',
    max_daily_trades INTEGER NOT NULL DEFAULT 5,
    max_position_pct NUMERIC(5,2) NOT NULL DEFAULT 5.0,
    stop_loss_pct NUMERIC(5,2) NOT NULL DEFAULT 5.0,
    take_profit_pct NUMERIC(5,2) NOT NULL DEFAULT 10.0,
    risk_level TEXT NOT NULL DEFAULT 'moderate',
    symbols TEXT[] NOT NULL DEFAULT ARRAY['BTC-USDT', 'ETH-USDT'],
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT auto_trade_config_user_unique UNIQUE (user_id)
);

-- RLS: users can only access their own config
ALTER TABLE public.auto_trade_config ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own auto-trade config"
    ON public.auto_trade_config
    FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Service role bypass for server writes
CREATE POLICY "Service role full access on auto_trade_config"
    ON public.auto_trade_config
    FOR ALL
    USING (auth.role() = 'service_role');

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_auto_trade_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER auto_trade_config_updated_at
    BEFORE UPDATE ON public.auto_trade_config
    FOR EACH ROW
    EXECUTE FUNCTION update_auto_trade_updated_at();
