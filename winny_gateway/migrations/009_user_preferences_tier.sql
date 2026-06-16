-- Add billing tier to user preferences for Pro-gated features.

ALTER TABLE public.user_preferences
    ADD COLUMN IF NOT EXISTS tier TEXT NOT NULL DEFAULT 'lite';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'user_preferences_tier_check'
    ) THEN
        ALTER TABLE public.user_preferences
            ADD CONSTRAINT user_preferences_tier_check
            CHECK (tier IN ('lite', 'pro'));
    END IF;
END $$;
