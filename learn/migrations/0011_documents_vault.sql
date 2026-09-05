-- LEARN — 0011 — documents, coffre, rétention, marque blanche.
--
-- Retention is the fact that shapes this whole file. Émargements and conventions must
-- survive 3 to 10 years depending on who financed the action (3 minimum for the DREETS
-- control right, 5 to cover a Qualiopi cycle, 6 to prove the reality of the expenditure,
-- 10 for FSE+). So the coffre is not "a folder of files": it is storage with a clock and a
-- hold, and deletion is something the database refuses rather than something an
-- application remembers not to do.
--
-- Three decisions:
--
--   1. **`retention_until` is computed at write**, from the funding basis, never typed.
--      A date someone enters by hand is a date someone gets wrong.
--   2. **A BEFORE DELETE trigger refuses** anything still inside its window or under legal
--      hold — including an RGPD erasure. The lawful basis for keeping it is *legal
--      obligation*, and the code has to know that or a learner's "delete my data" button
--      destroys an organisme's audit trail.
--   3. **Branding is per tenant, and it lands now.** An OF will not send its learners a
--      convocation carrying someone else's name. Designed into the template engine it is
--      nearly free; bolted on afterwards it touches every document ever generated.

begin;

-- ----------------------------------------------------------------- marque blanche

create table if not exists learn_tenant_branding (
  tenant_id     uuid primary key references learn_tenants(id) on delete cascade,
  legal_name    text not null,
  logo_url      text,
  primary_colour text default '#1D3FAE',
  address       text,
  nda           text,                         -- déclaration d'activité, a mandatory mention
  siret         text,
  footer_mentions text,                       -- e.g. the L6352-12 wording
  updated_at    timestamptz not null default now()
);
alter table learn_tenant_branding enable row level security;
alter table learn_tenant_branding force row level security;
create policy learn_brand_read on learn_tenant_branding for select
  using (learn_is_platform() or tenant_id = learn_current_tenant());
create policy learn_brand_write on learn_tenant_branding for all
  using (learn_is_platform() or (tenant_id = learn_current_tenant() and learn_current_role() = 'admin'))
  with check (learn_is_platform() or (tenant_id = learn_current_tenant() and learn_current_role() = 'admin'));

-- ----------------------------------------------------------------- gabarits

create table if not exists learn_doc_templates (
  id          uuid primary key default gen_random_uuid(),
  code        text,
  kind        text not null check (kind in (
                'convention','contrat','convocation','attestation','certificat',
                'reglement_interieur','feuille_emargement','programme','devis','facture')),
  title       text not null,
  version     int not null default 1,
  body_html   text not null default '',
  -- Named so generation can refuse before producing a document with a hole in it.
  required_fields text[] not null default '{}',
  active      boolean not null default true,
  created_at  timestamptz not null default now(),
  constraint learn_tpl_version unique (id, version)
);
select learn_tenant_table('learn_doc_templates');

-- ----------------------------------------------------------------- le coffre

create table if not exists learn_vault_objects (
  id             uuid primary key default gen_random_uuid(),
  kind           text not null,
  filename       text not null,
  storage_path   text not null,               -- private bucket, served by signed URL only
  mime           text not null default 'application/pdf',
  bytes          bigint,
  sha256         char(64),
  -- Who paid decides how long it is kept.
  retention_basis text not null default 'direct'
                    check (retention_basis in ('direct','qualiopi','opco','fse','legal')),
  retention_until date not null,
  legal_hold     boolean not null default false,
  held_reason    text,
  held_at        timestamptz,
  visibility     text not null default 'tenant'
                   check (visibility in ('tenant','session','self')),
  session_id     uuid references learn_sessions(id) on delete set null,
  subject_id     uuid references learn_profiles(id) on delete set null,
  created_by     uuid references learn_profiles(id) on delete set null,
  created_at     timestamptz not null default now()
);
select learn_tenant_table('learn_vault_objects');
create index if not exists learn_vault_sess_idx on learn_vault_objects (session_id);
create index if not exists learn_vault_subj_idx on learn_vault_objects (subject_id);
create index if not exists learn_vault_ret_idx  on learn_vault_objects (retention_until);

-- End of the civil year in which it was produced, plus the years the basis requires.
create or replace function learn_retention_until(p_basis text, p_ref date default current_date)
returns date
language sql immutable as $$
  select (date_trunc('year', p_ref)::date + interval '1 year - 1 day')::date
       + (case p_basis
            when 'direct'   then interval '3 years'   -- DREETS control right, the floor
            when 'qualiopi' then interval '5 years'   -- covers a full certification cycle
            when 'opco'     then interval '6 years'   -- proving the reality of the spend
            when 'fse'      then interval '10 years'  -- European funding
            when 'legal'    then interval '10 years'
            else interval '3 years'
          end)
$$;

-- Deletion is refused, not merely discouraged.
create or replace function learn_vault_guard() returns trigger
language plpgsql as $fn$
begin
  if old.legal_hold then
    raise exception 'legal_hold: % is held (%)', old.filename,
      coalesce(old.held_reason, 'no reason recorded') using errcode = '42501';
  end if;
  if old.retention_until >= current_date then
    raise exception 'retention_active: % must be kept until %', old.filename,
      old.retention_until using errcode = '42501';
  end if;
  return old;
end
$fn$;

drop trigger if exists learn_vault_no_early_delete on learn_vault_objects;
create trigger learn_vault_no_early_delete
  before delete on learn_vault_objects
  for each row execute function learn_vault_guard();

-- ----------------------------------------------------------------- documents

create table if not exists learn_documents (
  id          uuid primary key default gen_random_uuid(),
  template_id uuid references learn_doc_templates(id) on delete set null,
  kind        text not null,
  title       text not null,
  session_id  uuid references learn_sessions(id) on delete set null,
  subject_id  uuid references learn_profiles(id) on delete set null,
  company_id  uuid references learn_companies(id) on delete set null,
  -- The data actually merged in. Keeping it means a document can be explained years later
  -- without reconstructing the state of the system at the time.
  merged      jsonb not null default '{}'::jsonb,
  status      text not null default 'brouillon'
                check (status in ('brouillon','genere','envoye','signe','annule')),
  vault_object_id uuid references learn_vault_objects(id) on delete set null,
  issued_at   timestamptz,
  issued_by   uuid references learn_profiles(id) on delete set null,
  created_at  timestamptz not null default now()
);
select learn_tenant_table('learn_documents');
create index if not exists learn_doc_sess_idx on learn_documents (session_id);
create index if not exists learn_doc_subj_idx on learn_documents (subject_id);

-- ----------------------------------------------------------------- journal d'accès

create table if not exists learn_access_log (
  id         uuid primary key default gen_random_uuid(),
  vault_object_id uuid references learn_vault_objects(id) on delete set null,
  document_id uuid references learn_documents(id) on delete set null,
  actor_id   uuid references learn_profiles(id) on delete set null,
  actor_role text,
  principal  text not null default 'human',
  action     text not null default 'read',
  purpose    text,
  at         timestamptz not null default now(),
  evidence   jsonb not null default '{}'::jsonb
);
select learn_tenant_table('learn_access_log');
select learn_append_only('learn_access_log');
create index if not exists learn_acclog_obj_idx on learn_access_log (vault_object_id);

-- ----------------------------------------------------------------- certificat de réalisation
--
-- Computed from signatures, never typed. Hours attended are what the émargements say, and
-- a certificate that disagrees with them is the finding an auditor is looking for.

create or replace function learn_certificate_data(p_session uuid, p_apprenant uuid)
returns table (
  apprenant_name text, program_title text, starts_on date, ends_on date,
  half_days_total bigint, half_days_attended bigint,
  hours_total numeric, hours_attended numeric, complete boolean
)
language sql stable security definer set search_path = public as $$
  with slots as (
    select sl.id, sl.starts_at, sl.ends_at
      from learn_session_slots sl
     where sl.session_id = p_session and sl.status <> 'cancelled'
  ),
  signed as (
    select s.id
      from slots s
     where exists (select 1 from learn_attendance_signatures a
                    where a.slot_id = s.id and a.profile_id = p_apprenant and a.kind = 'in')
       and exists (select 1 from learn_attendance_signatures a
                    where a.slot_id = s.id and a.profile_id = p_apprenant and a.kind = 'out')
  )
  select
    p.full_name,
    pr.title,
    se.starts_on,
    se.ends_on,
    (select count(*) from slots),
    (select count(*) from signed),
    round((select coalesce(sum(extract(epoch from (s.ends_at - s.starts_at)))/3600, 0) from slots s), 2),
    round((select coalesce(sum(extract(epoch from (s.ends_at - s.starts_at)))/3600, 0)
             from slots s where s.id in (select id from signed)), 2),
    (select count(*) from signed) = (select count(*) from slots)
  from learn_sessions se
  join learn_programs pr on pr.id = se.program_id
  join learn_profiles p  on p.id  = p_apprenant
  where se.id = p_session
$$;

-- ----------------------------------------------------------------- policies

create policy learn_tpl_read on learn_doc_templates for select using (true);
create policy learn_tpl_write on learn_doc_templates for all
  using (learn_can('document','update') or learn_current_role() = 'admin')
  with check (learn_can('document','create') or learn_current_role() = 'admin');

-- A vault object is visible by its own declared scope: the whole tenant, the people on a
-- session, or only its subject.
create policy learn_vault_read on learn_vault_objects for select
  using (
    learn_is_platform()
    or (visibility = 'tenant'  and learn_current_role() in ('admin','auditeur'))
    or (visibility = 'session' and session_id in (select learn_visible_sessions()))
    or (visibility = 'self'    and subject_id = learn_current_user_id())
    or subject_id = learn_current_user_id()
  );
create policy learn_vault_write on learn_vault_objects for all
  using (learn_can('document','update') or learn_current_role() = 'admin')
  with check (learn_can('document','create') or learn_current_role() = 'admin');

create policy learn_doc_read on learn_documents for select
  using (
    learn_is_platform()
    or learn_current_role() in ('admin','auditeur')
    or subject_id = learn_current_user_id()
    or session_id in (select learn_visible_sessions())
  );
create policy learn_doc_write on learn_documents for all
  using (learn_can('document','update') or learn_current_role() = 'admin')
  with check (learn_can('document','create') or learn_current_role() = 'admin');

create policy learn_acclog_read on learn_access_log for select
  using (learn_current_role() in ('admin','auditeur') or learn_is_platform());
create policy learn_acclog_insert on learn_access_log for insert with check (true);

-- ----------------------------------------------------------------- what is due for purge

create or replace view learn_vault_retention
  with (security_invoker = true) as
select
  v.id, v.tenant_id, v.kind, v.filename, v.retention_basis, v.retention_until,
  v.legal_hold, v.held_reason,
  (v.retention_until < current_date) as expired,
  (v.retention_until < current_date and not v.legal_hold) as purgeable,
  (v.retention_until - current_date) as days_remaining
from learn_vault_objects v;

grant select on learn_vault_retention to learn_app, learn_readonly;
grant select, insert, update, delete
  on learn_doc_templates, learn_documents, learn_vault_objects, learn_tenant_branding
  to learn_app;
grant select, insert on learn_access_log to learn_app;
grant select
  on learn_doc_templates, learn_documents, learn_vault_objects,
     learn_tenant_branding, learn_access_log to learn_readonly;

commit;
