-- 025 — Une salle de réunion par créneau de formation LEARN.
--
-- Un créneau distanciel ou mixte (learn_session_slots) a sa salle LiveKit, créée à la
-- première entrée. Le formateur du créneau en est le propriétaire et l'animateur ; les
-- apprenants inscrits à la session la rejoignent. Une salle ordinaire (réunion interne)
-- garde learn_slot_id nul.

alter table public.rooms add column if not exists kind text not null default 'meeting';
alter table public.rooms add column if not exists learn_session_id uuid;
alter table public.rooms add column if not exists learn_slot_id uuid;
create unique index if not exists rooms_learn_slot_uidx on public.rooms (learn_slot_id) where learn_slot_id is not null;
create index if not exists rooms_learn_session_idx on public.rooms (learn_session_id) where learn_session_id is not null;
