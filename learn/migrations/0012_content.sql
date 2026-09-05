-- LEARN — 0012 — cours, modules, leçons, parcours, progression, xAPI.
--
-- Two things here are structural, meaning they cannot be added later without touching
-- every row already written. `GAP_ANALYSIS.md` §3 named both:
--
--   1. **Versioning.** A programme revised mid-cohort must not change what earlier
--      learners were taught or assessed on. So a course version IS a row: `(code, version)`
--      is unique, a session points at one specific version, and revising means inserting
--      a new row rather than editing an old one. Nothing that has been delivered is ever
--      mutated.
--   2. **Prerequisites.** "Finish A before B" is a graph. Retrofitting ordering onto a flat
--      lesson table means rewriting every query that reads it, so the edge table exists
--      from the start even while most tenants leave it empty.
--
-- And one thing is regulatory: V10 indicator 19 no longer accepts connection logs as proof
-- of distance-learning follow-up — it wants evidence the follow-up *worked*. So progress
-- feeds `learn_at_risk`, which is a list of people someone has to do something about,
-- not a report nobody reads.

begin;

-- ----------------------------------------------------------------- courses

create table if not exists learn_courses (
  id         uuid primary key default gen_random_uuid(),
  program_id uuid references learn_programs(id) on delete set null,
  code       text not null,
  version    int  not null default 1,
  title      text not null,
  summary    text,
  language   text not null default 'fr',
  published  boolean not null default false,
  -- Set when a newer version supersedes this one. The old row stays readable forever.
  superseded_by uuid references learn_courses(id) on delete set null,
  created_at timestamptz not null default now(),
  constraint learn_course_version unique (code, version)
);
select learn_tenant_table('learn_courses');

create table if not exists learn_modules (
  id        uuid primary key default gen_random_uuid(),
  course_id uuid not null references learn_courses(id) on delete cascade,
  position  int  not null default 1,
  title     text not null,
  summary   text,
  required  boolean not null default true,
  constraint learn_module_order unique (course_id, position)
);
select learn_tenant_table('learn_modules');

create table if not exists learn_lessons (
  id            uuid primary key default gen_random_uuid(),
  module_id     uuid not null references learn_modules(id) on delete cascade,
  position      int  not null default 1,
  title         text not null,
  kind          text not null default 'text'
                  check (kind in ('text','video','pdf','scorm','xapi','quiz','link')),
  content       jsonb not null default '{}'::jsonb,
  -- Media lives in the coffre like everything else, so retention and access logging apply
  -- to a training video exactly as they do to a convention.
  vault_object_id uuid references learn_vault_objects(id) on delete set null,
  assessment_id uuid references learn_assessments(id) on delete set null,
  duration_minutes int,
  constraint learn_lesson_order unique (module_id, position)
);
select learn_tenant_table('learn_lessons');

-- The learning path. An edge, not a column, because a module can gate several others.
create table if not exists learn_prerequisites (
  module_id  uuid not null references learn_modules(id) on delete cascade,
  requires_id uuid not null references learn_modules(id) on delete cascade,
  primary key (module_id, requires_id),
  constraint learn_prereq_not_self check (module_id <> requires_id)
);
select learn_tenant_table('learn_prerequisites');

-- ----------------------------------------------------------------- progression

create table if not exists learn_lesson_progress (
  id           uuid primary key default gen_random_uuid(),
  lesson_id    uuid not null references learn_lessons(id) on delete cascade,
  profile_id   uuid not null references learn_profiles(id) on delete cascade,
  session_id   uuid references learn_sessions(id) on delete set null,
  status       text not null default 'en_cours'
                 check (status in ('non_commence','en_cours','termine')),
  progress_pct numeric(5,2) not null default 0 check (progress_pct between 0 and 100),
  seconds_spent int not null default 0,
  first_at     timestamptz not null default now(),
  last_at      timestamptz not null default now(),
  completed_at timestamptz,
  constraint learn_progress_once unique (lesson_id, profile_id)
);
select learn_tenant_table('learn_lesson_progress');
create index if not exists learn_prog_prof_idx on learn_lesson_progress (profile_id);
create index if not exists learn_prog_last_idx on learn_lesson_progress (last_at);

-- xAPI in our own table. Learning Locker's open-source edition stopped moving in 2021, so
-- adopting it would mean depending on an abandoned service; the statements are simple and
-- a real LRS can be fed from here later if a customer ever demands one.
create table if not exists learn_xapi_statements (
  id          uuid primary key default gen_random_uuid(),
  actor_id    uuid references learn_profiles(id) on delete set null,
  verb        text not null,
  object_id   text not null,
  object_type text not null default 'Activity',
  result      jsonb not null default '{}'::jsonb,
  context     jsonb not null default '{}'::jsonb,
  at          timestamptz not null default now()
);
select learn_tenant_table('learn_xapi_statements');
select learn_append_only('learn_xapi_statements');
create index if not exists learn_xapi_actor_idx on learn_xapi_statements (actor_id, at);

-- ----------------------------------------------------------------- gating

create or replace function learn_module_unlocked(p_module uuid, p_profile uuid)
returns boolean
language sql stable security definer set search_path = public as $$
  select not exists (
    select 1
      from learn_prerequisites pre
     where pre.module_id = p_module
       and exists (                         -- the required module has an unfinished lesson
         select 1 from learn_lessons l
          where l.module_id = pre.requires_id
            and not exists (
              select 1 from learn_lesson_progress pr
               where pr.lesson_id = l.id and pr.profile_id = p_profile
                 and pr.status = 'termine')))
$$;

-- ----------------------------------------------------------------- views

create or replace view learn_course_progress
  with (security_invoker = true) as
select
  co.tenant_id,
  co.id                 as course_id,
  co.code, co.version, co.title,
  pr.profile_id,
  p.full_name,
  count(l.id)                                                as lessons,
  count(*) filter (where pr.status = 'termine')              as completed,
  round(100.0 * count(*) filter (where pr.status = 'termine')
        / nullif(count(l.id), 0), 1)                         as percent,
  sum(pr.seconds_spent)                                      as seconds_spent,
  max(pr.last_at)                                            as last_activity
from learn_courses co
join learn_modules m on m.course_id = co.id
join learn_lessons l on l.module_id = m.id
join learn_lesson_progress pr on pr.lesson_id = l.id
join learn_profiles p on p.id = pr.profile_id
group by co.tenant_id, co.id, co.code, co.version, co.title, pr.profile_id, p.full_name;

-- Indicator 19 in V10: showing that follow-up happened, not that logs exist. This is the
-- list a formateur is expected to act on, with the reason attached.
create or replace view learn_at_risk
  with (security_invoker = true) as
select
  e.tenant_id,
  e.session_id,
  e.apprenant_id,
  p.full_name,
  max(pr.last_at)                                    as last_activity,
  (current_date - max(pr.last_at)::date)             as days_since,
  coalesce(round(100.0 * count(*) filter (where pr.status = 'termine')
           / nullif(count(pr.id), 0), 1), 0)         as percent_complete,
  case
    when max(pr.last_at) is null                          then 'jamais_connecte'
    when (current_date - max(pr.last_at)::date) > 14      then 'inactif_14j'
    when (current_date - max(pr.last_at)::date) > 7       then 'inactif_7j'
    else 'actif'
  end as reason
from learn_enrollments e
join learn_profiles p on p.id = e.apprenant_id
left join learn_lesson_progress pr on pr.profile_id = e.apprenant_id
                                  and pr.session_id = e.session_id
where e.status in ('inscrit','confirme')
group by e.tenant_id, e.session_id, e.apprenant_id, p.full_name;

-- ----------------------------------------------------------------- policies

create policy learn_course_read on learn_courses for select using (true);
create policy learn_course_write on learn_courses for all
  using (learn_current_role() in ('admin','formateur') or learn_is_platform())
  with check (learn_current_role() in ('admin','formateur') or learn_is_platform());

create policy learn_module_read on learn_modules for select using (true);
create policy learn_module_write on learn_modules for all
  using (learn_current_role() in ('admin','formateur') or learn_is_platform())
  with check (learn_current_role() in ('admin','formateur') or learn_is_platform());

create policy learn_lesson_read on learn_lessons for select using (true);
create policy learn_lesson_write on learn_lessons for all
  using (learn_current_role() in ('admin','formateur') or learn_is_platform())
  with check (learn_current_role() in ('admin','formateur') or learn_is_platform());

create policy learn_prereq_read on learn_prerequisites for select using (true);
create policy learn_prereq_write on learn_prerequisites for all
  using (learn_current_role() in ('admin','formateur') or learn_is_platform())
  with check (learn_current_role() in ('admin','formateur') or learn_is_platform());

create policy learn_prog_read on learn_lesson_progress for select
  using (profile_id = learn_current_user_id()
         or learn_current_role() in ('admin','auditeur') or learn_is_platform()
         or session_id in (select learn_formateur_sessions()));
create policy learn_prog_write on learn_lesson_progress for all
  using (profile_id = learn_current_user_id() or learn_current_role() = 'admin'
         or learn_is_platform())
  with check (profile_id = learn_current_user_id() or learn_current_role() = 'admin'
              or learn_is_platform());

create policy learn_xapi_read on learn_xapi_statements for select
  using (actor_id = learn_current_user_id()
         or learn_current_role() in ('admin','auditeur') or learn_is_platform());
create policy learn_xapi_insert on learn_xapi_statements for insert with check (true);

grant select on learn_course_progress, learn_at_risk to learn_app, learn_readonly;
grant select, insert, update, delete
  on learn_courses, learn_modules, learn_lessons, learn_prerequisites, learn_lesson_progress
  to learn_app;
grant select, insert on learn_xapi_statements to learn_app;
grant select
  on learn_courses, learn_modules, learn_lessons, learn_prerequisites,
     learn_lesson_progress, learn_xapi_statements to learn_readonly;

commit;
