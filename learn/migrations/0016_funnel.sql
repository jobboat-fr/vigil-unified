-- LEARN — 0016 — le tunnel : vitrine → demande → positionnement → inscription.
--
-- This replaces the first sketch of the public funnel, which stored an inscription request
-- as a row in `learn_reclamations`. That was wrong in a way that matters: the réclamations
-- register is the artefact an auditor reads for indicator 30 — the single most-failed
-- indicator nationally. Filing every prospect there inflates the complaint count with
-- non-complaints and buries the real ones. A demande is not a réclamation, so it gets its
-- own table.
--
-- The public endpoints are the only unauthenticated writes in the product, so they are
-- confined on four axes at once:
--
--   role     `prospect` — a 7th role, holding exactly two capabilities
--   tenant   resolved from the URL slug, then SET LOCAL: the floor from 0001 applies
--   grants   DB role `learn_public` can INSERT one table and SELECT three; nothing else
--   rate     a SECURITY DEFINER counter the caller cannot read, reset or race
--
-- Why `prospect` is a real role rather than a special case in a policy: the question "what
-- may an unauthenticated visitor do?" is then answered by `learn_capabilities`, the same
-- place every other role's answer lives, instead of by a hand-written predicate that the
-- next person has to find.

begin;

-- ----------------------------------------------------------------- the 7th role

-- level 6 — below apprenant. Not read-only: the one thing it does is write a demande.
-- `creatable_roles` empty: a prospect never mints anyone, least of all itself.
insert into learn_roles (role, level, creatable_roles, data_scope, is_read_only, tenant_bound, label_fr)
values ('prospect', 6, array[]::text[], 'self', false, true, 'Visiteur (tunnel public)')
on conflict (role) do nothing;

insert into learn_capabilities (role, resource, action, note) values
  ('prospect','program','read','catalogue publié uniquement'),
  ('prospect','lead','create','sa propre demande'),
  ('prospect','positionnement','create','test de positionnement — indicateur 8')
on conflict (role, resource, action) do nothing;

-- A prospect sees the published catalogue and nothing else. Restrictive, so it holds
-- whatever `learn_programs_read using (true)` permits.
drop policy if exists learn_programs_prospect on learn_programs;
create policy learn_programs_prospect on learn_programs as restrictive for select
  using (learn_current_role() <> 'prospect' or published);

drop policy if exists learn_sessions_prospect on learn_sessions;
create policy learn_sessions_prospect on learn_sessions as restrictive for select
  using (learn_current_role() <> 'prospect' or status = 'planned');

-- ----------------------------------------------------------------- résoudre l'organisme

-- The chicken-and-egg of an unauthenticated request: the tenant floor needs a tenant id,
-- and all the visitor gave us is a slug from the URL. Definer, and it returns an id and a
-- display name — nothing that is not already on the organisme's own public pages.
create or replace function learn_tenant_by_slug(p_slug text)
returns table (id uuid, name text, slug text)
language sql security definer set search_path = public as $$
  select t.id, t.name, t.slug from learn_tenants t where t.slug = p_slug
$$;

-- ----------------------------------------------------------------- la demande

create table if not exists learn_leads (
  id             uuid primary key default gen_random_uuid(),
  program_id     uuid references learn_programs(id) on delete set null,
  session_id     uuid references learn_sessions(id) on delete set null,

  full_name      text not null check (length(btrim(full_name)) between 2 and 200),
  email          text not null check (position('@' in email) > 1),
  phone          text,
  company_name   text,
  message        text check (message is null or length(message) <= 2000),

  -- Attribution. `source` is where the visitor crossed over, `campaign` how they arrived.
  source         text not null default 'vitrine'
                   check (source in ('vitrine','salon','partenaire','opco','import','autre')),
  campaign       text,
  referer        text,

  status         text not null default 'recue'
                   check (status in ('recue','positionnement_envoye','positionnement_fait',
                                     'convertie','refusee','expiree')),

  -- Positioning outcome (indicator 8). Null until the test is taken.
  level          text check (level is null or level in ('debutant','intermediaire','avance')),
  score          numeric(5,2),

  -- RGPD. A demande is personal data collected on a consent basis, so the consent is
  -- recorded with the wording that was actually shown — not a boolean that proves nothing.
  consent_at     timestamptz not null default now(),
  consent_text   text not null,

  -- The raw IP is deliberately NOT stored. A prospect is a named individual and we have no
  -- purpose that needs their address; the salted digest still supports abuse detection and
  -- de-duplication. Salted per tenant, so the same visitor is not correlatable across
  -- organismes — which is the point of being a processor for several of them.
  ip_digest      bytea,

  converted_profile_id    uuid references learn_profiles(id) on delete set null,
  converted_enrollment_id uuid references learn_enrollments(id) on delete set null,
  refused_reason text,

  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
select learn_tenant_table('learn_leads');

create index if not exists learn_leads_status_idx on learn_leads (tenant_id, status, created_at desc);
create index if not exists learn_leads_email_idx  on learn_leads (tenant_id, lower(email));

-- A prospect may insert its own demande and read nothing at all — enforced by grants below
-- as well as here, because a policy that is the only control is one bug from being none.
drop policy if exists learn_leads_read on learn_leads;
create policy learn_leads_read on learn_leads for select
  using (learn_current_role() in ('super_admin','admin','auditeur'));

drop policy if exists learn_leads_insert on learn_leads;
create policy learn_leads_insert on learn_leads for insert
  with check (learn_can('lead','create') or learn_can('enrollment','create'));

drop policy if exists learn_leads_update on learn_leads;
create policy learn_leads_update on learn_leads for update
  using (learn_current_role() in ('super_admin','admin'))
  with check (learn_current_role() in ('super_admin','admin'));

-- A prospect must never be able to widen its own demande after the fact — e.g. flip
-- `status` to 'convertie'. It holds no UPDATE grant, and no policy would permit it either.

-- ----------------------------------------------------------------- le journal de la demande

-- Append-only: how a demande moved through the tunnel is the evidence behind "we analysed
-- the need before enrolling" (indicator 4). Editable history is not evidence.
create table if not exists learn_lead_events (
  id         uuid primary key default gen_random_uuid(),
  lead_id    uuid not null references learn_leads(id) on delete cascade,
  event      text not null check (event in ('recue','positionnement_envoye','positionnement_fait',
                                            'relance','convertie','refusee','expiree')),
  detail     jsonb not null default '{}'::jsonb,
  actor_id   uuid references learn_profiles(id) on delete set null,
  actor_role text,
  at         timestamptz not null default now()
);
select learn_tenant_table('learn_lead_events');
select learn_append_only('learn_lead_events');

create index if not exists learn_lead_events_lead_idx on learn_lead_events (lead_id, at);

drop policy if exists learn_lead_events_read on learn_lead_events;
create policy learn_lead_events_read on learn_lead_events for select
  using (learn_current_role() in ('super_admin','admin','auditeur'));

drop policy if exists learn_lead_events_insert on learn_lead_events;
create policy learn_lead_events_insert on learn_lead_events for insert
  with check (true);   -- the tenant floor and the grants are the control here

-- ----------------------------------------------------------------- les jetons de positionnement

-- The link a prospect follows to take the positioning test. Only the digest is stored: a
-- leaked backup of this table must not hand anyone a working link. Single use, expiring.
create table if not exists learn_lead_tokens (
  id         uuid primary key default gen_random_uuid(),
  lead_id    uuid not null references learn_leads(id) on delete cascade,
  purpose    text not null default 'positionnement'
               check (purpose in ('positionnement','confirmation')),
  token_sha  bytea not null unique,
  expires_at timestamptz not null,
  used_at    timestamptz,
  created_at timestamptz not null default now()
);
select learn_tenant_table('learn_lead_tokens');

drop policy if exists learn_lead_tokens_admin on learn_lead_tokens;
create policy learn_lead_tokens_admin on learn_lead_tokens for all
  using (learn_current_role() in ('super_admin','admin'))
  with check (learn_current_role() in ('super_admin','admin'));

-- ----------------------------------------------------------------- l'étranglement

-- An unauthenticated POST that writes to the database is a spam surface, and the vitrine's
-- own limiter does not protect the API from anything that skips the vitrine.
--
-- No grants at all: the counter is reachable only through the SECURITY DEFINER function
-- below, so a caller cannot read it, reset it, or race two requests past it. RLS is on with
-- a deny-all policy so it satisfies the same CI guard as every other learn_ table rather
-- than being an exception someone has to remember.
create table if not exists learn_public_hits (
  bucket     text primary key,
  window_at  timestamptz not null,
  hits       int not null default 0
);
alter table learn_public_hits enable row level security;
alter table learn_public_hits force row level security;
drop policy if exists learn_public_hits_none on learn_public_hits;
create policy learn_public_hits_none on learn_public_hits for all using (false);
revoke all on learn_public_hits from public;

create or replace function learn_public_throttle(
  p_bucket  text,
  p_window  int default 3600,
  p_limit   int default 5
) returns boolean
language plpgsql security definer set search_path = public as $fn$
declare v_now timestamptz := now(); v_hits int;
begin
  insert into learn_public_hits (bucket, window_at, hits)
  values (p_bucket, v_now, 1)
  on conflict (bucket) do update
     set window_at = case when learn_public_hits.window_at < v_now - make_interval(secs => p_window)
                          then v_now else learn_public_hits.window_at end,
         hits      = case when learn_public_hits.window_at < v_now - make_interval(secs => p_window)
                          then 1 else learn_public_hits.hits + 1 end
  returning hits into v_hits;
  return v_hits <= p_limit;
end
$fn$;

-- ----------------------------------------------------------------- issuing and reading a token

-- SECURITY DEFINER for the same reason as 0007: `digest()` lives in `extensions`, and the
-- application roles must not hold access to a crypto schema just to hash one string.
create or replace function learn_lead_token_issue(
  p_lead    uuid,
  p_purpose text default 'positionnement',
  p_hours   int  default 168          -- seven days: long enough to be useful by email
) returns text
language plpgsql security definer set search_path = public, extensions as $fn$
declare v_token text; v_tenant uuid;
begin
  select tenant_id into v_tenant from learn_leads where id = p_lead;
  if v_tenant is null then
    raise exception 'lead_not_found' using errcode = 'P0002';
  end if;
  v_token := encode(gen_random_bytes(32), 'hex');
  insert into learn_lead_tokens (tenant_id, lead_id, purpose, token_sha, expires_at)
  values (v_tenant, p_lead, p_purpose,
          digest(v_token, 'sha256'), now() + make_interval(hours => p_hours));
  -- Returned once and never again: nothing stores the clear value.
  return v_token;
end
$fn$;

create or replace function learn_lead_by_token(p_token text)
returns table (lead_id uuid, tenant_id uuid, purpose text, full_name text,
               email text, program_id uuid, session_id uuid, status text)
language plpgsql security definer set search_path = public, extensions as $fn$
begin
  return query
    select l.id, l.tenant_id, t.purpose, l.full_name, l.email,
           l.program_id, l.session_id, l.status
      from learn_lead_tokens t
      join learn_leads l on l.id = t.lead_id
     where t.token_sha = digest(p_token, 'sha256')
       and t.used_at is null
       and t.expires_at > now();
end
$fn$;

create or replace function learn_lead_token_burn(p_token text) returns boolean
language plpgsql security definer set search_path = public, extensions as $fn$
declare v_id uuid;
begin
  update learn_lead_tokens set used_at = now()
   where token_sha = digest(p_token, 'sha256') and used_at is null
   returning id into v_id;
  return v_id is not null;
end
$fn$;

-- Hash an address with the tenant as salt — see the column comment above.
create or replace function learn_ip_digest(p_ip text, p_tenant uuid) returns bytea
language sql security definer set search_path = public, extensions as $$
  select case when p_ip is null or p_ip = '' then null
              else digest(p_ip || ':' || p_tenant::text, 'sha256') end
$$;

-- ----------------------------------------------------------------- submitting a demande

-- One function so the throttle, the consent record and the journal entry cannot be
-- forgotten by a second caller. Runs as the invoker: the tenant floor and the `prospect`
-- capability still decide whether the insert happens.
create or replace function learn_submit_lead(
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
) returns uuid
language plpgsql as $fn$
declare v_id uuid;
begin
  if not learn_public_throttle('lead:' || p_tenant::text || ':' || coalesce(p_ip, 'unknown'),
                               3600, 5) then
    raise exception 'rate_limited' using errcode = '53400';
  end if;
  -- A second demande from the same address for the same programme is the same demande.
  -- Returning the existing id keeps a double-submitted form from creating two prospects
  -- an admin then has to reconcile.
  select id into v_id from learn_leads
   where tenant_id = p_tenant and lower(email) = lower(p_email)
     and program_id is not distinct from p_program
     and status in ('recue','positionnement_envoye','positionnement_fait')
   limit 1;
  if v_id is not null then
    return v_id;
  end if;

  insert into learn_leads (tenant_id, program_id, session_id, full_name, email, phone,
                           company_name, message, campaign, referer, consent_text, ip_digest)
  values (p_tenant, p_program, p_session, btrim(p_name), lower(btrim(p_email)), p_phone,
          p_company, p_message, p_campaign, p_referer, p_consent,
          learn_ip_digest(p_ip, p_tenant))
  returning id into v_id;

  insert into learn_lead_events (tenant_id, lead_id, event, detail, actor_role)
  values (p_tenant, v_id, 'recue',
          jsonb_build_object('campaign', p_campaign, 'program_id', p_program),
          learn_current_role());
  return v_id;
end
$fn$;

-- ----------------------------------------------------------------- recording the positioning

create or replace function learn_lead_positioned(
  p_token text,
  p_score numeric,
  p_level text
) returns uuid
language plpgsql security definer set search_path = public, extensions as $fn$
declare v_lead uuid; v_tenant uuid;
begin
  select lead_id, tenant_id into v_lead, v_tenant from learn_lead_by_token(p_token);
  if v_lead is null then
    raise exception 'invalid_or_expired_token' using errcode = 'P0002';
  end if;
  perform learn_lead_token_burn(p_token);
  update learn_leads
     set score = p_score, level = p_level,
         status = 'positionnement_fait', updated_at = now()
   where id = v_lead;
  insert into learn_lead_events (tenant_id, lead_id, event, detail, actor_role)
  values (v_tenant, v_lead, 'positionnement_fait',
          jsonb_build_object('score', p_score, 'level', p_level), 'prospect');
  return v_lead;
end
$fn$;

-- ----------------------------------------------------------------- the landing: lead → learner

-- Where the tunnel ends. Invoker rights on purpose: this must be refused for anyone whose
-- role cannot create a profile and an enrolment, and the hierarchy trigger from 0001 is the
-- one that decides — not a check written again here.
--
-- `p_user_id` is the **auth user id**, and it is required. `learn_profiles.id` *is* the
-- Supabase auth id — that identity is what every `self`-scope policy compares against — so
-- a profile cannot be minted with an invented key and reconciled later without breaking
-- the FK from `learn_enrollments` and every attendance row hanging off it. The invite that
-- produces that id therefore happens before this call, not inside it (see `learn/invite.py`).
create or replace function learn_convert_lead(
  p_lead     uuid,
  p_session  uuid,
  p_user_id  uuid,
  p_company  uuid default null
) returns table (profile_id uuid, enrollment_id uuid)
language plpgsql as $fn$
declare
  v_lead     learn_leads%rowtype;
  v_profile  uuid;
  v_enroll   uuid;
  v_session_tenant uuid;
begin
  if p_user_id is null then
    raise exception 'auth_user_required' using errcode = '22023';
  end if;
  select * into v_lead from learn_leads where id = p_lead for update;
  if not found then
    raise exception 'lead_not_found' using errcode = 'P0002';
  end if;
  if v_lead.status = 'convertie' then
    -- Idempotent: a double click must not enrol the same person twice.
    return query select v_lead.converted_profile_id, v_lead.converted_enrollment_id;
    return;
  end if;
  if v_lead.status = 'refusee' then
    raise exception 'lead_refused' using errcode = '22023';
  end if;

  select tenant_id into v_session_tenant from learn_sessions where id = p_session;
  if v_session_tenant is null or v_session_tenant <> v_lead.tenant_id then
    raise exception 'cross_tenant_violation' using errcode = '42501';
  end if;

  -- Reuse the person if they already exist in this organisme. Enrolling the same human
  -- twice under two profiles breaks every per-learner count downstream — attendance
  -- hours, certificates, the audit manifest.
  select id into v_profile from learn_profiles
   where tenant_id = v_lead.tenant_id and lower(email) = lower(v_lead.email) limit 1;

  if v_profile is null then
    insert into learn_profiles (id, tenant_id, company_id, role, full_name, email,
                                created_by)
    values (p_user_id, v_lead.tenant_id, p_company, 'apprenant', v_lead.full_name,
            v_lead.email, learn_current_user_id())
    returning id into v_profile;
  end if;

  insert into learn_enrollments (tenant_id, session_id, apprenant_id, company_id,
                                 status, level)
  values (v_lead.tenant_id, p_session, v_profile, p_company, 'inscrit', v_lead.level)
  returning id into v_enroll;

  update learn_leads
     set status = 'convertie', converted_profile_id = v_profile,
         converted_enrollment_id = v_enroll, session_id = p_session, updated_at = now()
   where id = p_lead;

  insert into learn_lead_events (tenant_id, lead_id, event, detail, actor_id, actor_role)
  values (v_lead.tenant_id, p_lead, 'convertie',
          jsonb_build_object('session_id', p_session, 'profile_id', v_profile),
          learn_current_user_id(), learn_current_role());

  return query select v_profile, v_enroll;
end
$fn$;

-- ----------------------------------------------------------------- le test de positionnement

-- Indicator 8 asks the organisme to establish the candidate's level *before* enrolling
-- them, which means the test has to be takeable by someone who does not yet have an
-- account. The attempt machinery in 0010 cannot serve that: `learn_attempts.profile_id`
-- references `learn_profiles`, and a prospect has no profile.
--
-- So the prospect path is deliberately narrower — no attempt row, no retakes, one shot
-- against a single-use token — and it never touches `learn_questions` directly. Both
-- functions are SECURITY DEFINER because the correct answers must stay unreachable from
-- the public role: what leaves is a prompt and its options, and what comes back is a level.

create or replace function learn_positioning_for_lead(p_token text)
returns table (assessment_id uuid, title text, duration_minutes int, questions jsonb)
language plpgsql security definer set search_path = public, extensions as $fn$
declare v_tenant uuid; v_program uuid; v_asmt learn_assessments%rowtype;
begin
  select l.tenant_id, l.program_id into v_tenant, v_program
    from learn_lead_by_token(p_token) l;
  if v_tenant is null then
    raise exception 'invalid_or_expired_token' using errcode = 'P0002';
  end if;

  -- The programme's own positioning test when it has one, the organisme's default when it
  -- does not. An organisme with neither gets a clear error rather than an empty quiz.
  select * into v_asmt from learn_assessments
   where tenant_id = v_tenant and kind = 'positionnement' and active
     and program_id is not distinct from v_program
   limit 1;
  if not found then
    select * into v_asmt from learn_assessments
     where tenant_id = v_tenant and kind = 'positionnement' and active
       and program_id is null
     limit 1;
  end if;
  if not found then
    raise exception 'no_positioning_assessment' using errcode = 'P0002';
  end if;

  return query
    select v_asmt.id, v_asmt.title, v_asmt.duration_minutes,
           coalesce(jsonb_agg(jsonb_build_object(
             'id', q.id, 'kind', q.kind, 'prompt', q.prompt,
             'options', q.options, 'points', q.points)
             order by array_position(v_asmt.question_ids, q.id)), '[]'::jsonb)
      from learn_questions q
     where q.id = any(v_asmt.question_ids) and q.active;
end
$fn$;

-- `p_answers` is [{"question_id": "...", "given": ["a"]}]. Graded with the same expression
-- `learn_grade_attempt()` uses — set equality, not containment — so a prospect and an
-- enrolled learner are marked identically. Two rules that are supposed to agree should be
-- one rule, but these run over different tables; keeping the expression textually identical
-- is the next best thing, and a divergence here would show up as two learners with the same
-- answers and different levels.
create or replace function learn_grade_positioning(p_token text, p_answers jsonb)
returns table (lead_id uuid, score numeric, max_score numeric, percent numeric, level text)
language plpgsql security definer set search_path = public, extensions as $fn$
declare
  v_tenant uuid; v_lead uuid; v_asmt_id uuid; v_asmt learn_assessments%rowtype;
  v_score numeric := 0; v_max numeric := 0; v_pct numeric; v_level text; k text;
begin
  select l.lead_id, l.tenant_id into v_lead, v_tenant from learn_lead_by_token(p_token) l;
  if v_lead is null then
    raise exception 'invalid_or_expired_token' using errcode = 'P0002';
  end if;

  -- Resolved through the same function the candidate was served from, so the paper they
  -- answered and the paper they are marked against cannot drift apart.
  select a.assessment_id into v_asmt_id from learn_positioning_for_lead(p_token) a;
  select * into v_asmt from learn_assessments where id = v_asmt_id;

  select coalesce(sum(case when q.kind = 'open' then 0
                           when (ans.given @> q.correct and q.correct @> ans.given)
                             then q.points else 0 end), 0),
         coalesce(sum(q.points), 0)
    into v_score, v_max
    from learn_questions q
    left join lateral (
      select coalesce(e -> 'given', '[]'::jsonb) as given
        from jsonb_array_elements(p_answers) e
       where (e ->> 'question_id')::uuid = q.id
       limit 1
    ) ans on true
   where q.id = any(v_asmt.question_ids) and q.active;

  v_pct := case when v_max > 0 then round(100 * v_score / v_max, 2) else null end;

  for k in select key from jsonb_each_text(v_asmt.level_thresholds)
            order by (value)::numeric desc
  loop
    if v_score >= (v_asmt.level_thresholds ->> k)::numeric then
      v_level := k;
      exit;
    end if;
  end loop;

  perform learn_lead_positioned(p_token, v_score, v_level);
  return query select v_lead, v_score, v_max, v_pct, v_level;
end
$fn$;

-- ----------------------------------------------------------------- the published figures

-- Indicator 1 obliges an organisme to publish its results, so these numbers are meant to be
-- read by strangers. They still do not travel through `learn_quality_indicators`: that view
-- is `security_invoker = true`, so serving it to the funnel would mean granting the public
-- role SELECT on `learn_reclamations` and `learn_evaluations` — the raw complaints and the
-- individual survey answers — to publish four aggregates.
--
-- A definer function returns the aggregates and nothing else, and takes the tenant as an
-- argument so one organisme's figures can never be served under another's name.
create or replace function learn_published_indicators(p_tenant uuid)
returns table (satisfaction numeric, responses bigint, response_rate numeric,
               learners bigint, year int)
language sql security definer set search_path = public as $$
  select i.satisfaction, i.responses, i.response_rate, i.learners, i.year
    from learn_quality_indicators i
   where i.tenant_id = p_tenant
   order by i.year desc
   limit 1
$$;

-- ----------------------------------------------------------------- the public database role

-- Same discipline as 0003: the funnel does not run as the application role, because the
-- application role can write every table in the product. `learn_public` can write one.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'learn_public') then
    create role learn_public nologin noinherit;
  end if;
end
$$;

grant usage on schema public to learn_public;

grant select on learn_tenants, learn_programs, learn_sessions to learn_public;
grant insert on learn_leads, learn_lead_events to learn_public;
grant execute on function learn_submit_lead(uuid, text, text, text, text, text, text,
                                            uuid, uuid, text, text, text) to learn_public;
grant execute on function learn_tenant_by_slug(text)         to learn_public, learn_app, learn_readonly;
grant execute on function learn_lead_by_token(text)          to learn_public;
grant execute on function learn_lead_positioned(text, numeric, text) to learn_public;
grant execute on function learn_public_throttle(text, int, int)      to learn_public;
grant execute on function learn_published_indicators(uuid) to learn_public, learn_app, learn_readonly;
grant execute on function learn_positioning_for_lead(text)        to learn_public, learn_app;
grant execute on function learn_grade_positioning(text, jsonb)    to learn_public, learn_app;

-- Explicitly NOT granted, and each absence is a decision:
--   select on learn_leads          — a prospect must not read other people's demandes
--   update/delete on learn_leads   — nor edit its own after submitting
--   anything on learn_profiles     — the funnel creates a demande, never an account
--   learn_lead_token_issue         — only the server side may mint a link

grant select, insert, update, delete on learn_leads, learn_lead_events, learn_lead_tokens
  to learn_app;
grant select on learn_leads, learn_lead_events, learn_lead_tokens to learn_readonly;
grant execute on function learn_convert_lead(uuid, uuid, uuid, uuid)  to learn_app;
grant execute on function learn_lead_token_issue(uuid, text, int)     to learn_app;
grant execute on function learn_lead_token_burn(text)                 to learn_app, learn_public;
grant execute on function learn_ip_digest(text, uuid)                 to learn_app, learn_public;
grant execute on function learn_submit_lead(uuid, text, text, text, text, text, text,
                                            uuid, uuid, text, text, text) to learn_app;

-- 0008's lesson: `learn_append_only()` revokes from `public`, which misses named roles.
revoke update, delete on learn_lead_events from learn_app, learn_public, learn_readonly;

-- ----------------------------------------------------------------- what an admin sees

create or replace view learn_funnel as
  select l.tenant_id,
         l.id, l.full_name, l.email, l.company_name, l.status, l.level, l.score,
         l.campaign, l.created_at, l.updated_at,
         p.title  as program_title,
         s.code   as session_code,
         s.starts_on,
         (select count(*) from learn_lead_events e where e.lead_id = l.id) as steps
    from learn_leads l
    left join learn_programs p on p.id = l.program_id
    left join learn_sessions s on s.id = l.session_id;

grant select on learn_funnel to learn_app, learn_readonly;

commit;
