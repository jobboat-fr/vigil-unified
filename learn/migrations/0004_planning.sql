-- LEARN — 0004 — programmes, sessions, créneaux, inscriptions.
--
-- Shaped by how a calendar actually reads. Three decisions follow from that:
--
--   1. The demi-journée is a REAL ROW, not a recurrence rule evaluated at render time.
--      A calendar paints rows; an émargement attaches to a row. A rule that can be edited
--      after the fact cannot carry a signature.
--   2. Every slot carries a `tstzrange`, generated and stored. The calendar's only real
--      query is "everything overlapping this week", and a range with a GiST index answers
--      it directly — the same index that powers the double-booking constraint.
--   3. The formateur sits on the SLOT, not the session. Co-animation and module splits are
--      normal; "the formateur of this formation" is a DISTINCT over its slots.
--
-- Timezone: stored as timestamptz, boundaries computed in the tenant's zone at generation
-- time, so the March and October changeovers produce correct half-days.

begin;

create extension if not exists btree_gist;

-- ----------------------------------------------------------------- programmes

create table if not exists learn_programs (
  id                uuid primary key default gen_random_uuid(),
  code              text,
  title             text not null,                       -- intitulé exact (mention obligatoire)
  nature            text not null default 'action_formation'
                      check (nature in ('action_formation','bilan_competences','vae','apprentissage')),
  objectives        text,                                -- objectifs opérationnels et évaluables
  prerequisites     text,
  duration_hours    numeric(6,2) not null default 0,
  modality          text not null default 'presentiel'
                      check (modality in ('presentiel','distanciel','mixte')),
  certifiante       boolean not null default false,
  rncp_code         text,                                -- e.g. RNCP37275
  version           int not null default 1,
  last_reviewed_at  date,
  next_review_due   date,                                -- #1 cause of surveillance suspension
  published         boolean not null default false,
  created_at        timestamptz not null default now()
);
select learn_tenant_table('learn_programs');

-- ----------------------------------------------------------------- rooms & resources

create table if not exists learn_rooms (
  id        uuid primary key default gen_random_uuid(),
  name      text not null,
  site      text,
  capacity  int,
  colour    text,                                        -- the calendar paints with this
  active    boolean not null default true
);
select learn_tenant_table('learn_rooms');

-- ----------------------------------------------------------------- sessions

create table if not exists learn_sessions (
  id           uuid primary key default gen_random_uuid(),
  program_id   uuid not null references learn_programs(id) on delete restrict,
  code         text,
  title        text,                                     -- overrides the programme title when set
  starts_on    date not null,
  ends_on      date not null,
  modality     text not null default 'presentiel'
                 check (modality in ('presentiel','distanciel','mixte')),
  place        text,
  capacity     int not null default 12,
  status       text not null default 'planned'
                 check (status in ('draft','planned','running','finished','cancelled')),
  cancelled_at timestamptz,
  cancel_reason text,
  created_by   uuid references learn_profiles(id),
  created_at   timestamptz not null default now(),
  constraint learn_sessions_dates check (ends_on >= starts_on)
);
select learn_tenant_table('learn_sessions');
create index if not exists learn_sessions_program_idx on learn_sessions (program_id);
create index if not exists learn_sessions_span_idx    on learn_sessions (tenant_id, starts_on, ends_on);

-- ----------------------------------------------------------------- créneaux (the demi-journée)

create table if not exists learn_session_slots (
  id            uuid primary key default gen_random_uuid(),
  session_id    uuid not null references learn_sessions(id) on delete cascade,
  on_date       date not null,
  half          text not null check (half in ('am','pm')),
  starts_at     timestamptz not null,
  ends_at       timestamptz not null,
  -- One generated range serves both the calendar's overlap query and the constraint below.
  span          tstzrange generated always as (tstzrange(starts_at, ends_at, '[)')) stored,
  formateur_id  uuid references learn_profiles(id) on delete restrict,
  room_id       uuid references learn_rooms(id) on delete set null,
  title         text,
  status        text not null default 'planned'
                  check (status in ('planned','confirmed','done','cancelled')),
  cancelled_at  timestamptz,
  cancel_reason text,
  created_at    timestamptz not null default now(),
  constraint learn_slot_times check (ends_at > starts_at),
  constraint learn_slot_unique unique (session_id, on_date, half)
);
select learn_tenant_table('learn_session_slots');

create index if not exists learn_slots_cal_idx   on learn_session_slots (tenant_id, starts_at);
create index if not exists learn_slots_form_idx  on learn_session_slots (formateur_id, starts_at);
create index if not exists learn_slots_room_idx  on learn_session_slots (room_id, starts_at);
create index if not exists learn_slots_sess_idx  on learn_session_slots (session_id);
create index if not exists learn_slots_span_idx  on learn_session_slots using gist (span);

-- Double-booking is refused by the database, not by the application. An application check
-- is one race away from two sessions on one trainer, and the repair afterwards is manual.
alter table learn_session_slots drop constraint if exists learn_slot_no_formateur_overlap;
alter table learn_session_slots add constraint learn_slot_no_formateur_overlap
  exclude using gist (formateur_id with =, span with &&)
  where (status <> 'cancelled' and formateur_id is not null);

alter table learn_session_slots drop constraint if exists learn_slot_no_room_overlap;
alter table learn_session_slots add constraint learn_slot_no_room_overlap
  exclude using gist (room_id with =, span with &&)
  where (status <> 'cancelled' and room_id is not null);

-- ----------------------------------------------------------------- inscriptions

create table if not exists learn_enrollments (
  id           uuid primary key default gen_random_uuid(),
  session_id   uuid not null references learn_sessions(id) on delete cascade,
  apprenant_id uuid not null references learn_profiles(id) on delete restrict,
  company_id   uuid references learn_companies(id) on delete set null,
  status       text not null default 'inscrit'
                 check (status in ('demande','inscrit','confirme','abandon','termine')),
  level        text,                                     -- from the positioning quiz
  enrolled_at  timestamptz not null default now(),
  constraint learn_enrollment_unique unique (session_id, apprenant_id)
);
select learn_tenant_table('learn_enrollments');
create index if not exists learn_enroll_appr_idx on learn_enrollments (apprenant_id);
create index if not exists learn_enroll_comp_idx on learn_enrollments (company_id);

-- ----------------------------------------------------------------- ICS feed tokens

create table if not exists learn_calendar_tokens (
  id           uuid primary key default gen_random_uuid(),
  profile_id   uuid not null references learn_profiles(id) on delete cascade,
  token        text not null unique default encode(gen_random_bytes(24), 'hex'),
  created_at   timestamptz not null default now(),
  revoked_at   timestamptz
);
select learn_tenant_table('learn_calendar_tokens');

-- ----------------------------------------------------------------- scope helpers
--
-- SECURITY DEFINER on purpose: a policy on learn_sessions that reads learn_enrollments,
-- whose own policy reads learn_sessions, recurses forever. These resolve the membership
-- question once, outside RLS, and are STABLE so the planner calls them per statement
-- rather than per row — which is the difference between a fast calendar and a slow one.

create or replace function learn_formateur_sessions() returns setof uuid
language sql stable security definer set search_path = public as $$
  select distinct s.session_id from learn_session_slots s
   where s.formateur_id = learn_current_user_id()
$$;

create or replace function learn_apprenant_sessions() returns setof uuid
language sql stable security definer set search_path = public as $$
  select e.session_id from learn_enrollments e
   where e.apprenant_id = learn_current_user_id()
$$;

create or replace function learn_company_sessions() returns setof uuid
language sql stable security definer set search_path = public as $$
  select distinct e.session_id from learn_enrollments e
   where e.company_id = learn_current_company()
$$;

-- Which sessions may the current actor see at all.
create or replace function learn_visible_sessions() returns setof uuid
language sql stable security definer set search_path = public as $$
  select s.id from learn_sessions s
   where learn_is_platform()
      or learn_current_role() in ('admin','auditeur')
      or s.id in (select learn_formateur_sessions())
      or s.id in (select learn_apprenant_sessions())
      or s.id in (select learn_company_sessions())
$$;

-- ----------------------------------------------------------------- role scope policies

create policy learn_programs_read on learn_programs for select using (true);
create policy learn_programs_write on learn_programs for all
  using (learn_can('program','update')) with check (learn_can('program','create'));

create policy learn_rooms_read on learn_rooms for select using (true);
create policy learn_rooms_write on learn_rooms for all
  using (learn_can('session','update')) with check (learn_can('session','create'));

create policy learn_sessions_read on learn_sessions for select
  using (id in (select learn_visible_sessions()));
create policy learn_sessions_write on learn_sessions for all
  using (learn_can('session','update')) with check (learn_can('session','create'));

create policy learn_slots_read on learn_session_slots for select
  using (session_id in (select learn_visible_sessions()));
create policy learn_slots_write on learn_session_slots for all
  using (
    learn_can('slot','update')
    and (learn_current_role() <> 'formateur' or formateur_id = learn_current_user_id())
  )
  with check (learn_can('slot','create'));

create policy learn_enroll_read on learn_enrollments for select
  using (
    learn_is_platform()
    or learn_current_role() in ('admin','auditeur')
    or session_id in (select learn_formateur_sessions())
    or apprenant_id = learn_current_user_id()
    or (learn_current_role() = 'entreprise' and company_id = learn_current_company())
  );
create policy learn_enroll_write on learn_enrollments for all
  using (
    learn_can('enrollment','update')
    or (learn_can('enrollment','delete') and learn_current_role() = 'entreprise'
        and company_id = learn_current_company())
  )
  with check (
    learn_can('enrollment','create')
    and (learn_current_role() <> 'entreprise' or company_id = learn_current_company())
  );

create policy learn_caltok_self on learn_calendar_tokens for all
  using (profile_id = learn_current_user_id())
  with check (profile_id = learn_current_user_id());

-- Now that enrolments exist, a formateur may see the learners of their own sessions —
-- the widening deliberately deferred in 0001.
drop policy if exists learn_profiles_scope on learn_profiles;
create policy learn_profiles_scope on learn_profiles for select
  using (
    learn_is_platform()
    or learn_current_role() in ('admin','auditeur')
    or id = learn_current_user_id()
    or (learn_current_role() = 'entreprise' and company_id = learn_current_company())
    or (learn_current_role() = 'formateur' and id in (
          select e.apprenant_id from learn_enrollments e
           where e.session_id in (select learn_formateur_sessions())))
  );

-- ----------------------------------------------------------------- slot generation
--
-- Recurrence expands to rows here, once, in the tenant's timezone. Callers pass the dates
-- they want; holidays and unavailability are simply dates they leave out.

create or replace function learn_generate_slots(
  p_session uuid,
  p_dates   date[],
  p_halves  text[] default array['am','pm'],
  p_am      time  default '09:00',
  p_am_end  time  default '12:30',
  p_pm      time  default '13:30',
  p_pm_end  time  default '17:00',
  p_formateur uuid default null,
  p_room      uuid default null
) returns setof learn_session_slots
language plpgsql as $fn$
declare
  v_tenant uuid;
  v_tz     text;
  d        date;
  h        text;
  s_at     timestamptz;
  e_at     timestamptz;
begin
  select s.tenant_id, coalesce(t.timezone, 'Europe/Paris')
    into v_tenant, v_tz
    from learn_sessions s join learn_tenants t on t.id = s.tenant_id
   where s.id = p_session;
  if v_tenant is null then
    raise exception 'unknown_session %', p_session using errcode = '22023';
  end if;

  foreach d in array p_dates loop
    foreach h in array p_halves loop
      -- Built in the tenant's zone, so a DST changeover lands on the right wall clock.
      if h = 'am' then
        s_at := (d + p_am)     at time zone v_tz;
        e_at := (d + p_am_end) at time zone v_tz;
      else
        s_at := (d + p_pm)     at time zone v_tz;
        e_at := (d + p_pm_end) at time zone v_tz;
      end if;

      return query
        insert into learn_session_slots
          (tenant_id, session_id, on_date, half, starts_at, ends_at, formateur_id, room_id)
        values (v_tenant, p_session, d, h, s_at, e_at, p_formateur, p_room)
        on conflict (session_id, on_date, half) do nothing
        returning *;
    end loop;
  end loop;
end
$fn$;

-- ----------------------------------------------------------------- the calendar read model
--
-- One query answers "the week", already carrying the labels a calendar needs, so the UI
-- does not fan out into N+1 lookups per cell. security_invoker keeps RLS applying to the
-- caller rather than to the view's owner.

create or replace view learn_calendar
  with (security_invoker = true) as
select
  sl.id,
  sl.tenant_id,
  sl.session_id,
  sl.on_date,
  sl.half,
  sl.starts_at,
  sl.ends_at,
  sl.status,
  coalesce(sl.title, se.title, pr.title)      as title,
  pr.id                                        as program_id,
  pr.modality,
  sl.formateur_id,
  f.full_name                                  as formateur_name,
  sl.room_id,
  r.name                                       as room_name,
  r.colour                                     as room_colour,
  se.capacity,
  (select count(*) from learn_enrollments e
    where e.session_id = sl.session_id and e.status in ('inscrit','confirme')) as enrolled
from learn_session_slots sl
join learn_sessions  se on se.id = sl.session_id
join learn_programs  pr on pr.id = se.program_id
left join learn_profiles f on f.id = sl.formateur_id
left join learn_rooms    r on r.id = sl.room_id;

grant select on learn_calendar to learn_app, learn_readonly;
grant select, insert, update, delete
  on learn_programs, learn_rooms, learn_sessions, learn_session_slots,
     learn_enrollments, learn_calendar_tokens to learn_app;
grant select
  on learn_programs, learn_rooms, learn_sessions, learn_session_slots,
     learn_enrollments, learn_calendar_tokens to learn_readonly;

commit;
