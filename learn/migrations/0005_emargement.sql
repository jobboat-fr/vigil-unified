-- LEARN — 0005 — émargement: the evidence layer.
--
-- Four legal facts shape every line below (../../hbs-backend/PLAN_V2.md §1):
--
--   1. The unit is the DEMI-JOURNÉE, signed by the apprenant AND the formateur. Entry and
--      exit are two rows, not two columns, so a missing exit is visibly missing.
--   2. A simple electronic signature is admissible, but the burden of proving integrity
--      falls on the organisme. So the *evidence bundle* carries the weight: identity,
--      server timestamp, IP, device, and a hash chained to the previous signature.
--   3. Retention runs 3 to 10 years. Rows must survive; only cancellation is available.
--   4. Presence attests that a NAMED HUMAN was there. An agent signing one fabricates a
--      human act — refused in the database, not by a setting.
--
-- The chain is computed by a trigger, not by the application. Two learners signing in the
-- same second must not read the same predecessor, so the tail row is locked FOR UPDATE
-- and the chain is serialised at the point of write.

begin;

-- ----------------------------------------------------------------- signatures

create table if not exists learn_attendance_signatures (
  id           uuid primary key default gen_random_uuid(),
  seq_no       bigint not null,                       -- per tenant, assigned by the trigger
  slot_id      uuid not null references learn_session_slots(id) on delete restrict,
  profile_id   uuid not null references learn_profiles(id)      on delete restrict,
  signer_role  text not null check (signer_role in ('apprenant','formateur')),
  kind         text not null check (kind in ('in','out','countersign')),

  -- Server clock only. A phone's clock is the signer's to set.
  signed_at    timestamptz not null default now(),

  -- The evidence bundle. Opaque to the schema, meaningful to an auditor.
  evidence     jsonb not null default '{}'::jsonb,     -- ip, user_agent, device, geo…

  prev_hash    char(64) not null,
  this_hash    char(64) not null,

  constraint learn_sig_once unique (slot_id, profile_id, kind)
);
select learn_tenant_table('learn_attendance_signatures');

create unique index if not exists learn_sig_seq_idx
  on learn_attendance_signatures (tenant_id, seq_no);
create index if not exists learn_sig_slot_idx on learn_attendance_signatures (slot_id);
create index if not exists learn_sig_prof_idx on learn_attendance_signatures (profile_id);

-- ----------------------------------------------------------------- the chain

create or replace function learn_chain_attendance() returns trigger
language plpgsql as $fn$
declare
  v_prev  char(64);
  v_seq   bigint;
  v_body  text;
begin
  -- FOR UPDATE on the tail serialises concurrent signers. Without it two inserts in the
  -- same instant read the same prev_hash and the chain forks silently.
  select s.this_hash, s.seq_no into v_prev, v_seq
    from learn_attendance_signatures s
   where s.tenant_id = new.tenant_id
   order by s.seq_no desc
   limit 1
     for update;

  new.seq_no    := coalesce(v_seq, 0) + 1;
  new.prev_hash := coalesce(v_prev, repeat('0', 64));   -- genesis

  -- jsonb orders its keys, so this serialisation is stable across rebuilds. seq_no is
  -- deliberately excluded: prev_hash already proves ordering, and leaving the number out
  -- keeps a hash verifiable after a dump and restore.
  v_body := (jsonb_build_object(
      'slot',      new.slot_id,
      'profile',   new.profile_id,
      'role',      new.signer_role,
      'kind',      new.kind,
      'signed_at', to_char(new.signed_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.USZ'),
      'evidence',  new.evidence,
      'prev',      new.prev_hash
  ))::text;

  new.this_hash := encode(extensions.digest(v_body, 'sha256'), 'hex');
  return new;
end
$fn$;

drop trigger if exists learn_sig_chain on learn_attendance_signatures;
create trigger learn_sig_chain
  before insert on learn_attendance_signatures
  for each row execute function learn_chain_attendance();

-- ----------------------------------------------------------------- who may sign what

create or replace function learn_may_sign(p_slot uuid, p_kind text)
returns boolean
language sql stable security definer set search_path = public, extensions as $$
  select case
    -- An apprenant signs their own entry and exit, only on a slot they are enrolled in.
    when learn_current_role() = 'apprenant' and p_kind in ('in','out') then exists (
      select 1 from learn_session_slots sl
        join learn_enrollments e on e.session_id = sl.session_id
       where sl.id = p_slot
         and e.apprenant_id = learn_current_user_id()
         and e.status in ('inscrit','confirme')
         and sl.status <> 'cancelled')
    -- A formateur counter-signs only the slots they actually teach.
    when learn_current_role() = 'formateur' and p_kind = 'countersign' then exists (
      select 1 from learn_session_slots sl
       where sl.id = p_slot
         and sl.formateur_id = learn_current_user_id()
         and sl.status <> 'cancelled')
    else false
  end
$$;

-- ----------------------------------------------------------------- policies
--
-- Read follows the session scope already established in 0004. Write is narrow: the
-- capability, the identity, and the enrolment must all agree.

create policy learn_sig_read on learn_attendance_signatures for select
  using (slot_id in (select id from learn_session_slots
                      where session_id in (select learn_visible_sessions())));

create policy learn_sig_insert on learn_attendance_signatures for insert
  with check (
    learn_can('attendance','sign')
    and profile_id = learn_current_user_id()          -- nobody signs for anyone else
    and learn_may_sign(slot_id, kind)
  );

-- Append-only, and never by an agent. Applied after the policies above so the restrictive
-- floors sit on top of them.
select learn_append_only('learn_attendance_signatures');
select learn_no_agent_writes('learn_attendance_signatures');

-- ----------------------------------------------------------------- absences

create table if not exists learn_absences (
  id            uuid primary key default gen_random_uuid(),
  slot_id       uuid not null references learn_session_slots(id) on delete restrict,
  apprenant_id  uuid not null references learn_profiles(id)      on delete restrict,
  reason        text,
  justified     boolean not null default false,
  justification_ref text,                              -- vault object, once P5 exists
  declared_by   uuid references learn_profiles(id),
  declared_at   timestamptz not null default now(),
  constraint learn_absence_once unique (slot_id, apprenant_id)
);
select learn_tenant_table('learn_absences');
create index if not exists learn_absence_slot_idx on learn_absences (slot_id);

create policy learn_absence_read on learn_absences for select
  using (slot_id in (select id from learn_session_slots
                      where session_id in (select learn_visible_sessions())));
create policy learn_absence_write on learn_absences for all
  using (learn_can('attendance','read') and not learn_is_read_only())
  with check (learn_can('attendance','read') and not learn_is_read_only());

-- ----------------------------------------------------------------- verification
--
-- Recomputes the chain and reports the first break. This is what an auditor is shown, and
-- what the reversibility export ships alongside the PDFs so a departing customer can
-- prove integrity without this platform.

create or replace function learn_verify_attendance_chain(p_tenant uuid default null)
returns table (checked bigint, valid boolean, first_broken_seq bigint, reason text)
language plpgsql stable security definer set search_path = public, extensions as $fn$
declare
  r        record;
  v_prev   char(64) := repeat('0', 64);
  v_body   text;
  v_calc   char(64);
  v_count  bigint := 0;
  v_tenant uuid := coalesce(p_tenant, learn_current_tenant());
begin
  for r in
    select * from learn_attendance_signatures
     where tenant_id = v_tenant order by seq_no
  loop
    v_count := v_count + 1;
    if r.prev_hash <> v_prev then
      return query select v_count, false, r.seq_no, 'prev_hash_mismatch'::text;
      return;
    end if;
    v_body := (jsonb_build_object(
        'slot', r.slot_id, 'profile', r.profile_id, 'role', r.signer_role,
        'kind', r.kind,
        'signed_at', to_char(r.signed_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.USZ'),
        'evidence', r.evidence, 'prev', r.prev_hash))::text;
    v_calc := encode(extensions.digest(v_body, 'sha256'), 'hex');
    if v_calc <> r.this_hash then
      return query select v_count, false, r.seq_no, 'content_altered'::text;
      return;
    end if;
    v_prev := r.this_hash;
  end loop;
  return query select v_count, true, null::bigint, 'intact'::text;
end
$fn$;

-- ----------------------------------------------------------------- the sheet
--
-- One row per learner per slot, with both signatures and the absence beside them — the
-- shape a feuille d'émargement is printed from, and the shape an auditor reads.

create or replace view learn_attendance_sheet
  with (security_invoker = true) as
select
  sl.id            as slot_id,
  sl.tenant_id,
  sl.session_id,
  sl.on_date,
  sl.half,
  sl.starts_at,
  sl.ends_at,
  p.id             as apprenant_id,
  p.full_name      as apprenant_name,
  si.signed_at     as signed_in_at,
  so.signed_at     as signed_out_at,
  ab.justified     as absence_justified,
  ab.reason        as absence_reason,
  cs.signed_at     as countersigned_at,
  cf.full_name     as countersigned_by,
  case
    when ab.id is not null           then 'absent'
    when si.id is not null and so.id is not null then 'complet'
    when si.id is not null           then 'entree_seule'
    else 'non_signe'
  end as state
from learn_session_slots sl
join learn_enrollments e  on e.session_id = sl.session_id
                         and e.status in ('inscrit','confirme')
join learn_profiles    p  on p.id = e.apprenant_id
left join learn_attendance_signatures si
       on si.slot_id = sl.id and si.profile_id = p.id and si.kind = 'in'
left join learn_attendance_signatures so
       on so.slot_id = sl.id and so.profile_id = p.id and so.kind = 'out'
left join learn_absences ab on ab.slot_id = sl.id and ab.apprenant_id = p.id
left join learn_attendance_signatures cs
       on cs.slot_id = sl.id and cs.kind = 'countersign'
left join learn_profiles cf on cf.id = cs.profile_id;

grant select on learn_attendance_sheet to learn_app, learn_readonly;
grant select, insert on learn_attendance_signatures to learn_app;
grant select                on learn_attendance_signatures to learn_readonly;
grant select, insert, update, delete on learn_absences to learn_app;
grant select                         on learn_absences to learn_readonly;

commit;
