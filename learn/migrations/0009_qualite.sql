-- LEARN — 0009 — the qualité loop (Qualiopi criterion 7, indicators 30/31/32).
--
-- Indicator 30 is the most-failed indicator in France, around 44 % of non-conformités.
-- Organismes rarely fail it for want of a survey — they fail it because nothing shows the
-- feedback was *exploited*. An auditor asks "you collected this, so what changed?" and the
-- answer is a shrug.
--
-- So the load-bearing decision here is one NOT NULL: an improvement action must name the
-- thing that caused it. `source_kind` and `source_id` are required, which makes the
-- unanswerable question structurally unaskable — you cannot record an action floating free
-- of its cause.
--
-- Four audiences, because indicator 30 says *parties prenantes*, not "learners":
-- apprenants, formateurs, entreprises clientes, financeurs.

begin;

-- ----------------------------------------------------------------- questionnaires

create table if not exists learn_surveys (
  id         uuid primary key default gen_random_uuid(),
  code       text,
  title      text not null,
  audience   text not null
               check (audience in ('apprenant','formateur','entreprise','financeur')),
  timing     text not null default 'chaud'
               check (timing in ('chaud','froid','positionnement','ponctuel')),
  -- Questions live as jsonb: a questionnaire is edited as a whole, versioned as a whole,
  -- and never joined against. A table of rows would buy nothing and cost a migration
  -- every time someone adds a question type.
  questions  jsonb not null default '[]'::jsonb,
  active     boolean not null default true,
  created_at timestamptz not null default now()
);
select learn_tenant_table('learn_surveys');

-- ----------------------------------------------------------------- campaigns

create table if not exists learn_survey_campaigns (
  id         uuid primary key default gen_random_uuid(),
  survey_id  uuid not null references learn_surveys(id) on delete restrict,
  session_id uuid references learn_sessions(id) on delete cascade,
  audience   text not null
               check (audience in ('apprenant','formateur','entreprise','financeur')),
  -- Scheduling is data, not a cron entry: "à chaud at session end, à froid at J+90" is
  -- expressed by these two timestamps so a missed run is visible rather than lost.
  opens_at   timestamptz not null default now(),
  due_at     timestamptz,
  anonymous  boolean not null default true,
  status     text not null default 'open'
               check (status in ('scheduled','open','closed')),
  created_at timestamptz not null default now()
);
select learn_tenant_table('learn_survey_campaigns');
create index if not exists learn_camp_session_idx on learn_survey_campaigns (session_id);

create table if not exists learn_survey_invitations (
  id           uuid primary key default gen_random_uuid(),
  campaign_id  uuid not null references learn_survey_campaigns(id) on delete cascade,
  profile_id   uuid references learn_profiles(id) on delete set null,
  email        text,
  token        text not null unique default encode(gen_random_bytes(18), 'hex'),
  sent_at      timestamptz,
  responded_at timestamptz,
  constraint learn_invite_target check (profile_id is not null or email is not null)
);
select learn_tenant_table('learn_survey_invitations');
create index if not exists learn_invite_camp_idx on learn_survey_invitations (campaign_id);

create table if not exists learn_survey_responses (
  id            uuid primary key default gen_random_uuid(),
  campaign_id   uuid not null references learn_survey_campaigns(id) on delete cascade,
  invitation_id uuid references learn_survey_invitations(id) on delete set null,
  -- Kept null when the campaign is anonymous. Response rate still counts through the
  -- invitation; the answers just cannot be traced back to a person.
  profile_id    uuid references learn_profiles(id) on delete set null,
  answers       jsonb not null default '{}'::jsonb,
  score         numeric(4,2),                  -- normalised 0–5 where the survey has one
  comment       text,
  submitted_at  timestamptz not null default now()
);
select learn_tenant_table('learn_survey_responses');
create index if not exists learn_resp_camp_idx on learn_survey_responses (campaign_id);

-- ----------------------------------------------------------------- réclamations (ind. 31)

create table if not exists learn_reclamations (
  id           uuid primary key default gen_random_uuid(),
  session_id   uuid references learn_sessions(id) on delete set null,
  raised_by    uuid references learn_profiles(id) on delete set null,
  raised_by_kind text not null default 'apprenant'
                   check (raised_by_kind in ('apprenant','formateur','entreprise','financeur','autre')),
  raised_by_name text,                          -- when the complainant has no account
  subject      text not null,
  body         text,
  severity     text not null default 'normale'
                 check (severity in ('faible','normale','haute','critique')),
  status       text not null default 'ouverte'
                 check (status in ('ouverte','en_cours','resolue','classee')),
  received_at  timestamptz not null default now(),
  resolved_at  timestamptz,
  resolution   text,
  constraint learn_reclam_resolved check (
    status not in ('resolue','classee') or (resolved_at is not null and resolution is not null))
);
select learn_tenant_table('learn_reclamations');
create index if not exists learn_reclam_status_idx on learn_reclamations (tenant_id, status);

-- ----------------------------------------------------------------- risks (ind. 32, V10)

create table if not exists learn_risks (
  id          uuid primary key default gen_random_uuid(),
  title       text not null,
  description text,
  likelihood  int not null default 2 check (likelihood between 1 and 4),
  impact      int not null default 2 check (impact between 1 and 4),
  mitigation  text,
  owner_id    uuid references learn_profiles(id) on delete set null,
  reviewed_at date,
  next_review date,
  created_at  timestamptz not null default now()
);
select learn_tenant_table('learn_risks');

-- ----------------------------------------------------------------- the loop closes here

create table if not exists learn_improvement_actions (
  id          uuid primary key default gen_random_uuid(),
  title       text not null,
  description text,
  -- The whole point of this table. An action with no cause is what fails an audit, so the
  -- schema refuses to record one.
  source_kind text not null
                check (source_kind in ('evaluation','reclamation','risque','veille','audit')),
  source_id   uuid not null,
  owner_id    uuid references learn_profiles(id) on delete set null,
  due_on      date,
  status      text not null default 'ouverte'
                check (status in ('ouverte','en_cours','faite','abandonnee')),
  outcome     text,
  closed_at   timestamptz,
  created_at  timestamptz not null default now(),
  constraint learn_action_closed check (
    status not in ('faite','abandonnee') or (closed_at is not null and outcome is not null))
);
select learn_tenant_table('learn_improvement_actions');
create index if not exists learn_action_src_idx on learn_improvement_actions (source_kind, source_id);

-- ----------------------------------------------------------------- policies
--
-- Responses are the sensitive part: an anonymous campaign must stay anonymous even to the
-- admin, so nothing here grants a route back from a response to a person beyond what the
-- row itself carries.

create policy learn_survey_read on learn_surveys for select using (true);
create policy learn_survey_write on learn_surveys for all
  using (learn_can('evaluation','read') and not learn_is_read_only())
  with check (learn_can('evaluation','read') and not learn_is_read_only());

create policy learn_camp_read on learn_survey_campaigns for select
  using (session_id is null or session_id in (select learn_visible_sessions()));
create policy learn_camp_write on learn_survey_campaigns for all
  using (learn_can('evaluation','read') and not learn_is_read_only())
  with check (learn_can('evaluation','read') and not learn_is_read_only());

-- An invitation is visible to its own recipient and to whoever runs the campaign.
create policy learn_invite_read on learn_survey_invitations for select
  using (profile_id = learn_current_user_id()
         or learn_current_role() in ('admin','auditeur') or learn_is_platform());
create policy learn_invite_write on learn_survey_invitations for all
  using (learn_current_role() = 'admin' or learn_is_platform())
  with check (learn_current_role() = 'admin' or learn_is_platform());

create policy learn_resp_read on learn_survey_responses for select
  using (learn_current_role() in ('admin','auditeur','formateur') or learn_is_platform()
         or profile_id = learn_current_user_id());
create policy learn_resp_insert on learn_survey_responses for insert
  with check (learn_can('evaluation','create') or learn_current_role() = 'admin');

create policy learn_reclam_read on learn_reclamations for select
  using (learn_current_role() in ('admin','auditeur') or learn_is_platform()
         or raised_by = learn_current_user_id());
create policy learn_reclam_insert on learn_reclamations for insert
  with check (learn_can('reclamation','create') or learn_current_role() = 'admin');
create policy learn_reclam_update on learn_reclamations for update
  using (learn_can('reclamation','update')) with check (learn_can('reclamation','update'));

create policy learn_risk_all on learn_risks for all
  using (learn_current_role() in ('admin','auditeur') or learn_is_platform())
  with check (learn_current_role() = 'admin' or learn_is_platform());

create policy learn_action_read on learn_improvement_actions for select
  using (learn_current_role() in ('admin','auditeur','formateur') or learn_is_platform());
create policy learn_action_write on learn_improvement_actions for all
  using (learn_current_role() = 'admin' or learn_is_platform())
  with check (learn_current_role() = 'admin' or learn_is_platform());

-- ----------------------------------------------------------------- what the auditor reads
--
-- Two views. The first is the number an organisme publishes; the second is the proof that
-- the number came from somewhere — V10 indicator 1 requires every published figure to be
-- justifiable, so the counts travel with the rate.

create or replace view learn_quality_by_session
  with (security_invoker = true) as
select
  se.id                as session_id,
  se.tenant_id,
  se.code,
  pr.title             as program_title,
  se.starts_on,
  se.ends_on,
  count(distinct i.id)                                        as invited,
  count(distinct r.id)                                        as responded,
  round(100.0 * count(distinct r.id)
        / nullif(count(distinct i.id), 0), 1)                 as response_rate,
  round(avg(r.score), 2)                                      as avg_score,
  (select count(*) from learn_reclamations rc where rc.session_id = se.id) as reclamations,
  (select count(*) from learn_improvement_actions a
     where a.source_kind = 'reclamation'
       and a.source_id in (select rc.id from learn_reclamations rc
                            where rc.session_id = se.id))     as actions_from_reclamations
from learn_sessions se
join learn_programs pr on pr.id = se.program_id
left join learn_survey_campaigns  c on c.session_id = se.id
left join learn_survey_invitations i on i.campaign_id = c.id
left join learn_survey_responses  r on r.campaign_id = c.id
group by se.id, se.tenant_id, se.code, pr.title, se.starts_on, se.ends_on;

-- The headline figures a vitrine publishes, each with the population it was computed from.
create or replace view learn_quality_indicators
  with (security_invoker = true) as
with recl as (
  select tenant_id, date_part('year', received_at)::int as year, count(*)::bigint as n
    from learn_reclamations group by 1, 2
)
select
  t.id                                            as tenant_id,
  date_part('year', se.starts_on)::int            as year,
  count(distinct se.id)                           as sessions,
  count(distinct e.apprenant_id)                  as learners,
  count(distinct r.id)                            as responses,
  round(avg(r.score), 2)                          as satisfaction,
  round(100.0 * count(distinct r.id)
        / nullif(count(distinct i.id), 0), 1)     as response_rate,
  coalesce(max(rc.n), 0)                          as reclamations
from learn_tenants t
join learn_sessions se on se.tenant_id = t.id
left join learn_enrollments e on e.session_id = se.id
left join learn_survey_campaigns  c on c.session_id = se.id
left join learn_survey_invitations i on i.campaign_id = c.id
left join learn_survey_responses  r on r.campaign_id = c.id
left join recl rc on rc.tenant_id = t.id
                 and rc.year = date_part('year', se.starts_on)::int
group by t.id, date_part('year', se.starts_on);

grant select on learn_quality_by_session, learn_quality_indicators
  to learn_app, learn_readonly;
grant select, insert, update, delete
  on learn_surveys, learn_survey_campaigns, learn_survey_invitations,
     learn_survey_responses, learn_reclamations, learn_risks, learn_improvement_actions
  to learn_app;
grant select
  on learn_surveys, learn_survey_campaigns, learn_survey_invitations,
     learn_survey_responses, learn_reclamations, learn_risks, learn_improvement_actions
  to learn_readonly;

commit;
