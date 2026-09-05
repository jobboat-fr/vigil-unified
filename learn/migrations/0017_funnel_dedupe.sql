-- LEARN — 0017 — repair: submit a demande without reading one back.
--
-- Two failures found by executing 0016, not by reading it. They are the same mistake twice:
-- the public path was written as if it could see what it had just written, and the whole
-- point of that path is that it cannot.
--
--   1. `learn_submit_lead()` de-duplicated with a SELECT. `learn_public` holds no SELECT on
--      `learn_leads` — deliberately — so the first submission died with
--      `permission denied for table learn_leads`.
--
--   2. Replacing the SELECT with `insert … on conflict do nothing returning id` failed the
--      same way. `INSERT … RETURNING` needs the SELECT privilege *and* applies the SELECT
--      policy, so returning the new id is a read like any other.
--
-- Both tempting shortcuts are wrong. Granting SELECT hands an unauthenticated caller the
-- read the role exists to be denied, and the read policy would return nothing anyway, so
-- the duplicate is created regardless. Making the function SECURITY DEFINER does not help
-- either: `learn_tenant_table()` sets FORCE ROW LEVEL SECURITY and `postgres` is not a
-- superuser on this project, so RLS applies to the owner too.
--
-- So the public path stops reading entirely:
--
--   * a partial unique index makes the duplicate impossible at the storage layer;
--   * `ROW_COUNT` reports whether a row was created — a number, not a row;
--   * an AFTER INSERT trigger writes the journal entry, so the caller needs no grant on
--     `learn_lead_events` either;
--   * the id is resolved afterwards on the authenticated connection, by the actor that is
--     allowed to read it.
--
-- The result is stricter than what 0016 intended: a visitor can now cause exactly one row
-- to exist and can observe nothing about it.

begin;

-- One open demande per (organisme, address, programme). Closed ones — convertie, refusée,
-- expirée — are excluded, so somebody who trained last year can enrol again. The coalesce
-- is because NULL never conflicts with NULL, and "no programme chosen" must still collapse
-- to one demande.
create unique index if not exists learn_leads_open_uniq
  on learn_leads (tenant_id, lower(email),
                  coalesce(program_id, '00000000-0000-0000-0000-000000000000'::uuid))
  where status in ('recue', 'positionnement_envoye', 'positionnement_fait');

-- ----------------------------------------------------------------- the journal, by trigger

create or replace function learn_lead_recorded() returns trigger
language plpgsql security definer set search_path = public as $fn$
begin
  insert into learn_lead_events (tenant_id, lead_id, event, detail, actor_role)
  values (new.tenant_id, new.id, 'recue',
          jsonb_build_object('campaign', new.campaign, 'program_id', new.program_id),
          learn_current_role());
  return new;
end
$fn$;

drop trigger if exists learn_leads_recorded on learn_leads;
create trigger learn_leads_recorded after insert on learn_leads
  for each row execute function learn_lead_recorded();

-- ----------------------------------------------------------------- submitting, blind

-- Returns TRUE when a demande was created, FALSE when one was already on file. Not the id:
-- the caller is a stranger, and "your request is registered" is the whole of what a
-- stranger needs to know.
-- The return type changes from uuid to boolean, and CREATE OR REPLACE cannot do that.
drop function if exists learn_submit_lead(uuid, text, text, text, text, text, text,
                                          uuid, uuid, text, text, text);

create function learn_submit_lead(
  p_tenant   uuid,
  p_name     text,
  p_email    text,
  p_consent  text,
  p_phone    text default null,
  p_company  text default null,
  p_message  text default null,
  p_program  uuid default null,
  p_session  uuid default null,
  p_campaign text default null,
  p_referer  text default null,
  p_ip       text default null
) returns boolean
language plpgsql as $fn$
declare v_rows int;
begin
  if not learn_public_throttle('lead:' || p_tenant::text || ':' || coalesce(p_ip, 'unknown'),
                               3600, 5) then
    raise exception 'rate_limited' using errcode = '53400';
  end if;

  insert into learn_leads (tenant_id, program_id, session_id, full_name, email, phone,
                           company_name, message, campaign, referer, consent_text, ip_digest)
  values (p_tenant, p_program, p_session, btrim(p_name), lower(btrim(p_email)), p_phone,
          p_company, p_message, p_campaign, p_referer, p_consent,
          learn_ip_digest(p_ip, p_tenant))
  on conflict do nothing;

  get diagnostics v_rows = row_count;
  return v_rows > 0;
end
$fn$;

grant execute on function learn_submit_lead(uuid, text, text, text, text, text, text,
                                            uuid, uuid, text, text, text)
  to learn_public, learn_app;

-- The trigger writes the journal now, so the public role needs nothing on that table.
revoke all on learn_lead_events from learn_public;

-- Third instance of the same omission: the insert policy calls `learn_can()`, which reads
-- `learn_capabilities`, and the public role could not read it — so the policy that was
-- supposed to *permit* the insert raised `permission denied` instead. The two catalogue
-- tables are reference data (the CI guard in test_isolation.py exempts them for the same
-- reason); withholding them does not protect anything, it only makes every policy that
-- consults them fail closed for the wrong reason.
grant select on learn_roles, learn_capabilities to learn_public;

commit;
