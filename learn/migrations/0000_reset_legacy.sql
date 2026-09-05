-- LEARN — 0000 — clear the abandoned scaffold on project nncciltayjtwdwkfupox.
--
-- Verified before writing this (2026-09-05, via PostgREST with the service key):
--   public.users                0 rows
--   public.predictions          0 rows
--   public.outcomes             0 rows
--   public.subscription_events  0 rows
-- Four empty tables from a previous predictions/subscriptions project. Nothing is lost.
--
-- Deliberately narrow. This drops FOUR NAMED TABLES and nothing else — no
-- `drop schema public cascade`, no touching auth/storage/extensions, no blind wildcard.
-- If some other object exists that this misses, that is the correct failure mode: it
-- survives and can be looked at, rather than being destroyed by a script nobody read.

begin;

drop table if exists public.subscription_events cascade;
drop table if exists public.predictions        cascade;
drop table if exists public.outcomes           cascade;
drop table if exists public.users              cascade;

commit;

-- Sanity check — should return zero rows.
-- select tablename from pg_tables
--  where schemaname = 'public'
--    and tablename in ('users','predictions','outcomes','subscription_events');
