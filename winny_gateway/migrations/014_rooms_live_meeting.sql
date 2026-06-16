-- Live meeting: persist the active room URL + provider/persona on the room so an
-- external guest can resolve a share token to the SAME room (the one the AI
-- avatar + host are in) via the public /v1/rooms/meeting/{share_token} route.
-- Additive only. (share_token already exists on public.rooms.)

ALTER TABLE public.rooms
  ADD COLUMN IF NOT EXISTS live_url      text,
  ADD COLUMN IF NOT EXISTS live_provider text,
  ADD COLUMN IF NOT EXISTS live_persona  text;

CREATE INDEX IF NOT EXISTS rooms_share_token_idx
  ON public.rooms (share_token) WHERE share_token IS NOT NULL;
