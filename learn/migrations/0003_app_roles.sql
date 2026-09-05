-- LEARN — 0003 — the database roles the application actually connects as.
--
-- Why this exists: 0001 built the policies but nothing to enforce them against. Supabase's
-- SQL endpoint connects as `postgres`, a SUPERUSER, and **superusers bypass RLS entirely**
-- — `force row level security` does not change that. So every policy written in 0001 was
-- inert on that connection, and a cross-tenant read succeeded while the equivalent write
-- was caught only because triggers still fire for superusers.
--
-- That is the difference between "policies exist" and "policies are enforced". The
-- application must connect as a non-superuser, and there must be a read-only role for
-- `auditeur` so learn/db.py's `set local role learn_readonly` resolves.
--
-- These are NOLOGIN roles: the app connects as its Supabase user and does SET ROLE, so no
-- new password enters the system.

begin;

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'learn_app') then
    create role learn_app nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'learn_readonly') then
    create role learn_readonly nologin;
  end if;
end
$$;

grant usage on schema public to learn_app, learn_readonly;

-- Reference data both roles may read.
grant select on learn_roles, learn_capabilities to learn_app, learn_readonly;

-- Everything else: learn_app reads and writes (RLS decides which rows), learn_readonly
-- only reads. A read-only role holding no write grant means a future table that forgets
-- its WITH CHECK still cannot be written by an auditeur.
grant select, insert, update, delete on learn_tenants, learn_companies, learn_profiles to learn_app;
grant select                        on learn_tenants, learn_companies, learn_profiles to learn_readonly;

-- Later migrations create more tables; make the grant automatic rather than a thing to
-- remember. Applies to tables created by `postgres` from here on.
alter default privileges in schema public
  grant select, insert, update, delete on tables to learn_app;
alter default privileges in schema public
  grant select on tables to learn_readonly;
alter default privileges in schema public
  grant usage, select on sequences to learn_app;

-- Whoever the app authenticates as must be able to assume these.
do $$
declare r text;
begin
  foreach r in array array['authenticated','service_role','anon','postgres'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant learn_app, learn_readonly to %I', r);
    end if;
  end loop;
end
$$;

commit;
