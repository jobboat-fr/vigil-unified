-- LEARN — 0010 — positionnement, évaluation des acquis, examens, gradebook.
--
-- Indicator 8 (positionnement et évaluation à l'entrée) is a top-five non-conformité at
-- roughly 15 %, and indicator 11 requires evaluating what was actually acquired. Both are
-- served by the same machinery, distinguished only by `kind`.
--
-- Three decisions carry the weight:
--
--   1. **Correct answers never leave the database until an attempt is submitted.** The
--      classic failure is shipping the whole quiz, answers included, to a browser that can
--      read it. `learn_questions_public` exists so the take-path has nothing else to serve.
--   2. **The clock is the server's.** `expires_at` is computed at start from the server's
--      own time; a client cannot extend its own exam by adjusting a phone.
--   3. **Grading happens in Postgres.** A score computed client-side is a score the client
--      chose.
--
-- Questions carry a `bloc`, which maps onto RNCP blocs de compétences. That is what makes
-- indicator 3 (taux d'obtention par bloc) answerable for a certifiante organisme — and it
-- is the one thing here the generic LMS market does not model.

begin;

-- ----------------------------------------------------------------- questions

create table if not exists learn_questions (
  id          uuid primary key default gen_random_uuid(),
  program_id  uuid references learn_programs(id) on delete set null,
  bank        text,                                   -- free grouping label
  kind        text not null default 'qcm'
                check (kind in ('qcm','multi','scale','open')),
  prompt      text not null,
  options     jsonb not null default '[]'::jsonb,     -- [{key,label}]
  correct     jsonb not null default '[]'::jsonb,     -- ["a"] or ["a","c"]; empty for open
  points      numeric(5,2) not null default 1,
  why_correct text,                                   -- shown after submission, not before
  bloc        text,                                   -- RNCP bloc de compétences
  active      boolean not null default true,
  created_at  timestamptz not null default now()
);
select learn_tenant_table('learn_questions');
create index if not exists learn_q_program_idx on learn_questions (program_id);
create index if not exists learn_q_bloc_idx    on learn_questions (bloc);

-- The only shape a candidate may ever receive. `correct` and `why_correct` are absent by
-- construction rather than by a handler remembering to strip them.
create or replace view learn_questions_public
  with (security_invoker = true) as
select id, tenant_id, program_id, bank, kind, prompt, options, points, bloc
  from learn_questions where active;

-- ----------------------------------------------------------------- assessments

create table if not exists learn_assessments (
  id               uuid primary key default gen_random_uuid(),
  program_id       uuid references learn_programs(id) on delete set null,
  code             text,
  title            text not null,
  kind             text not null default 'positionnement'
                     check (kind in ('positionnement','acquis_entree','acquis_sortie','examen')),
  duration_minutes int not null default 20 check (duration_minutes between 1 and 480),
  pass_mark        numeric(5,2),                      -- null when there is nothing to pass
  question_ids     uuid[] not null default '{}',
  -- {"debutant":0,"intermediaire":10,"avance":15} — the score bands that decide a level.
  level_thresholds jsonb not null default '{}'::jsonb,
  retakes_allowed  int not null default 0,
  active           boolean not null default true,
  created_at       timestamptz not null default now()
);
select learn_tenant_table('learn_assessments');

-- ----------------------------------------------------------------- attempts

create table if not exists learn_attempts (
  id            uuid primary key default gen_random_uuid(),
  assessment_id uuid not null references learn_assessments(id) on delete restrict,
  profile_id    uuid not null references learn_profiles(id)    on delete restrict,
  session_id    uuid references learn_sessions(id) on delete set null,
  attempt_no    int not null default 1,
  started_at    timestamptz not null default now(),
  expires_at    timestamptz not null,                 -- server-computed at start
  submitted_at  timestamptz,
  score         numeric(6,2),
  max_score     numeric(6,2),
  percent       numeric(5,2),
  level         text,
  passed        boolean,
  status        text not null default 'en_cours'
                  check (status in ('en_cours','soumis','corrige','expire')),
  review_status text not null default 'none'
                  check (review_status in ('none','pending','reviewed')),
  constraint learn_attempt_once unique (assessment_id, profile_id, attempt_no)
);
select learn_tenant_table('learn_attempts');
create index if not exists learn_att_prof_idx on learn_attempts (profile_id);
create index if not exists learn_att_sess_idx on learn_attempts (session_id);

create table if not exists learn_attempt_answers (
  id          uuid primary key default gen_random_uuid(),
  attempt_id  uuid not null references learn_attempts(id) on delete cascade,
  question_id uuid not null references learn_questions(id) on delete restrict,
  given       jsonb not null default '[]'::jsonb,
  is_correct  boolean,
  points      numeric(5,2),
  constraint learn_answer_once unique (attempt_id, question_id)
);
select learn_tenant_table('learn_attempt_answers');

-- An answer may only be written while its attempt is still open. Without this a candidate
-- could keep editing after submitting, and the grade would mean nothing.
create or replace function learn_answer_window() returns trigger
language plpgsql security definer set search_path = public as $fn$
declare st text; exp timestamptz;
begin
  select status, expires_at into st, exp from learn_attempts where id = new.attempt_id;
  if st is null then
    raise exception 'unknown_attempt' using errcode = '22023';
  end if;
  if st <> 'en_cours' then
    raise exception 'attempt_closed' using errcode = '42501';
  end if;
  if now() > exp then
    raise exception 'attempt_expired' using errcode = '42501';
  end if;
  return new;
end
$fn$;

drop trigger if exists learn_answer_window_t on learn_attempt_answers;
create trigger learn_answer_window_t
  before insert or update on learn_attempt_answers
  for each row execute function learn_answer_window();

-- ----------------------------------------------------------------- grading

create or replace function learn_grade_attempt(p_attempt uuid)
returns learn_attempts
language plpgsql security definer set search_path = public as $fn$
declare
  a        learn_attempts;
  asmt     learn_assessments;
  v_score  numeric(6,2) := 0;
  v_max    numeric(6,2) := 0;
  v_pct    numeric(5,2);
  v_level  text;
  k        text;
  v_open   boolean := false;
begin
  select * into a from learn_attempts where id = p_attempt;
  if a.id is null then
    raise exception 'unknown_attempt' using errcode = '22023';
  end if;
  select * into asmt from learn_assessments where id = a.assessment_id;

  -- Score each answer against the question. An open question scores nothing automatically
  -- and flags the attempt for human review — a machine marking free text against a
  -- syllabus is a claim we are not going to make.
  update learn_attempt_answers ans
     set is_correct = case when q.kind = 'open' then null
                           else (ans.given @> q.correct and q.correct @> ans.given) end,
         points     = case when q.kind = 'open' then 0
                           when (ans.given @> q.correct and q.correct @> ans.given)
                             then q.points else 0 end
    from learn_questions q
   where q.id = ans.question_id and ans.attempt_id = p_attempt;

  select coalesce(sum(ans.points), 0),
         coalesce(sum(q.points), 0),
         bool_or(q.kind = 'open')
    into v_score, v_max, v_open
    from learn_attempt_answers ans
    join learn_questions q on q.id = ans.question_id
   where ans.attempt_id = p_attempt;

  v_pct := case when v_max > 0 then round(100 * v_score / v_max, 2) else null end;

  -- Highest threshold the score reaches.
  for k in select key from jsonb_each_text(asmt.level_thresholds)
            order by (value)::numeric desc
  loop
    if v_score >= (asmt.level_thresholds ->> k)::numeric then
      v_level := k;
      exit;
    end if;
  end loop;

  update learn_attempts
     set submitted_at  = coalesce(submitted_at, now()),
         score = v_score, max_score = v_max, percent = v_pct, level = v_level,
         passed = case when asmt.pass_mark is null then null else v_score >= asmt.pass_mark end,
         status = 'corrige',
         review_status = case when coalesce(v_open, false) then 'pending' else 'none' end
   where id = p_attempt
  returning * into a;

  return a;
end
$fn$;

-- ----------------------------------------------------------------- policies

create policy learn_q_read on learn_questions for select
  using (learn_current_role() in ('admin','formateur','auditeur') or learn_is_platform());
create policy learn_q_write on learn_questions for all
  using (learn_current_role() in ('admin','formateur') or learn_is_platform())
  with check (learn_current_role() in ('admin','formateur') or learn_is_platform());

create policy learn_asmt_read on learn_assessments for select using (true);
create policy learn_asmt_write on learn_assessments for all
  using (learn_current_role() = 'admin' or learn_is_platform())
  with check (learn_current_role() = 'admin' or learn_is_platform());

-- A candidate sees their own attempts; staff see the tenant's.
create policy learn_att_read on learn_attempts for select
  using (profile_id = learn_current_user_id()
         or learn_current_role() in ('admin','auditeur')
         or learn_is_platform()
         or session_id in (select learn_formateur_sessions()));
create policy learn_att_write on learn_attempts for all
  using (profile_id = learn_current_user_id()
         or learn_current_role() in ('admin','formateur') or learn_is_platform())
  with check (profile_id = learn_current_user_id()
              or learn_current_role() in ('admin','formateur') or learn_is_platform());

create policy learn_ans_read on learn_attempt_answers for select
  using (attempt_id in (select id from learn_attempts));
create policy learn_ans_write on learn_attempt_answers for all
  using (attempt_id in (select id from learn_attempts where profile_id = learn_current_user_id())
         or learn_current_role() in ('admin','formateur') or learn_is_platform())
  with check (attempt_id in (select id from learn_attempts where profile_id = learn_current_user_id())
              or learn_current_role() in ('admin','formateur') or learn_is_platform());

-- ----------------------------------------------------------------- gradebook

create or replace view learn_gradebook
  with (security_invoker = true) as
select
  a.tenant_id,
  a.session_id,
  se.code            as session_code,
  a.profile_id,
  p.full_name        as apprenant_name,
  asm.kind           as assessment_kind,
  asm.title          as assessment_title,
  a.attempt_no,
  a.score, a.max_score, a.percent, a.level, a.passed,
  a.status, a.review_status,
  a.submitted_at
from learn_attempts a
join learn_assessments asm on asm.id = a.assessment_id
join learn_profiles    p   on p.id  = a.profile_id
left join learn_sessions se on se.id = a.session_id;

-- Per-bloc results — indicator 3 for a certifiante organisme, and the thing a generic LMS
-- has no column for.
create or replace view learn_bloc_results
  with (security_invoker = true) as
select
  a.tenant_id,
  a.profile_id,
  p.full_name       as apprenant_name,
  a.session_id,
  q.bloc,
  count(*)                                        as questions,
  sum(coalesce(ans.points, 0))                    as score,
  sum(q.points)                                   as max_score,
  round(100 * sum(coalesce(ans.points, 0)) / nullif(sum(q.points), 0), 1) as percent
from learn_attempt_answers ans
join learn_attempts  a on a.id = ans.attempt_id
join learn_questions q on q.id = ans.question_id
join learn_profiles  p on p.id = a.profile_id
where q.bloc is not null
group by a.tenant_id, a.profile_id, p.full_name, a.session_id, q.bloc;

grant select on learn_questions_public, learn_gradebook, learn_bloc_results
  to learn_app, learn_readonly;
grant select, insert, update, delete
  on learn_questions, learn_assessments, learn_attempts, learn_attempt_answers to learn_app;
grant select
  on learn_questions, learn_assessments, learn_attempts, learn_attempt_answers to learn_readonly;

commit;
