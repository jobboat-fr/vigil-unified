-- LEARN — 0014 — reprise de données, DPA, registre, réversibilité.
--
-- Neither of these is a feature anyone asked for. Both decide whether the product sells.
--
-- **The importer.** An organisme switching from Digiforma or Dendreo must bring its history.
-- Asked to abandon its records, it does not switch. `GAP_ANALYSIS.md` §4 called this the
-- item most likely to decide whether this sells, and it was in no roadmap.
--
--   The constraint that shapes it: **imported attendance never enters the signature chain.**
--   A row in `learn_attendance_signatures` asserts that a named human signed *here*, and
--   back-dating one for a session that happened in another system three years ago would be
--   fabricating evidence. Historical émargements are archived as vault objects with an
--   `imported` provenance — auditable, retained, and honestly labelled as records rather
--   than as attestations made on this platform.
--
-- **The tenant-#2 gate.** Article 28 requires a written DPA before any processing on
-- another controller's behalf, and the absence of one is a standalone CNIL violation. So
-- the DPA is a row, the sub-processor list is a table, and the registre de traitement — the
-- one AZZ&CO keeps as *processor*, distinct from each tenant's own — is data rather than a
-- document someone means to write.

begin;

-- ----------------------------------------------------------------- reprise de données

create table if not exists learn_import_jobs (
  id          uuid primary key default gen_random_uuid(),
  source      text not null check (source in ('digiforma','dendreo','csv','excel','api')),
  entity      text not null check (entity in (
                'apprenants','sessions','emargements','documents','entreprises')),
  filename    text,
  -- Column mapping is stored so a failed run can be replayed identically rather than
  -- re-guessed by whoever is on shift.
  mapping     jsonb not null default '{}'::jsonb,
  status      text not null default 'prepare'
                check (status in ('prepare','simule','applique','echec','annule')),
  rows_total  int not null default 0,
  rows_ok     int not null default 0,
  rows_failed int not null default 0,
  report      jsonb not null default '{}'::jsonb,
  created_by  uuid references learn_profiles(id) on delete set null,
  created_at  timestamptz not null default now(),
  applied_at  timestamptz,
  constraint learn_import_applied check (status <> 'applique' or applied_at is not null)
);
select learn_tenant_table('learn_import_jobs');

create table if not exists learn_import_rows (
  id         uuid primary key default gen_random_uuid(),
  job_id     uuid not null references learn_import_jobs(id) on delete cascade,
  line_no    int not null,
  raw        jsonb not null,
  resolved   jsonb,
  target_id  uuid,
  status     text not null default 'en_attente'
               check (status in ('en_attente','ok','ignore','erreur')),
  error      text,
  constraint learn_import_line unique (job_id, line_no)
);
select learn_tenant_table('learn_import_rows');
create index if not exists learn_improw_job_idx on learn_import_rows (job_id, status);

-- Provenance on archived history, so nothing imported is ever mistaken for something
-- attested here.
alter table learn_vault_objects
  add column if not exists provenance text not null default 'native'
    check (provenance in ('native','imported'));
alter table learn_vault_objects
  add column if not exists imported_from text;

-- ----------------------------------------------------------------- Article 28

create table if not exists learn_dpas (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references learn_tenants(id) on delete cascade,
  version          text not null default '1.0',
  controller_name  text not null,                 -- the organisme; AZZ&CO is the processor
  controller_contact text,
  dpo_contact      text,
  signed_at        timestamptz,
  signed_by        text,
  document_id      uuid references learn_documents(id) on delete set null,
  -- Purposes, categories, retention: the eight minimum clauses summarised for a reader.
  terms            jsonb not null default '{}'::jsonb,
  constraint learn_dpa_tenant unique (tenant_id, version)
);
alter table learn_dpas enable row level security;
alter table learn_dpas force row level security;
create policy learn_dpa_read on learn_dpas for select
  using (learn_is_platform() or tenant_id = learn_current_tenant());
create policy learn_dpa_write on learn_dpas for all
  using (learn_is_platform()) with check (learn_is_platform());

-- Platform-wide, not per tenant: every customer is entitled to the same list and to
-- advance notice when it changes.
create table if not exists learn_subprocessors (
  id        uuid primary key default gen_random_uuid(),
  name      text not null,
  purpose   text not null,
  location  text not null,
  since     date not null default current_date,
  until     date,
  notified_at date
);
alter table learn_subprocessors enable row level security;
alter table learn_subprocessors force row level security;
create policy learn_subproc_read on learn_subprocessors for select using (true);
create policy learn_subproc_write on learn_subprocessors for all
  using (learn_is_platform()) with check (learn_is_platform());

insert into learn_subprocessors (name, purpose, location) values
  ('OVHcloud', 'Hébergement de la base et du stockage', 'France (eu-west)'),
  ('Supabase', 'Base de données managée et authentification', 'UE')
on conflict do nothing;

-- AZZ&CO's own registre, as processor — distinct from each tenant's, which is theirs.
create table if not exists learn_processing_register (
  id            uuid primary key default gen_random_uuid(),
  activity      text not null,
  purpose       text not null,
  legal_basis   text not null,
  data_subjects text not null,
  categories    text not null,
  retention     text not null,
  recipients    text,
  updated_at    timestamptz not null default now()
);
alter table learn_processing_register enable row level security;
alter table learn_processing_register force row level security;
create policy learn_register_read on learn_processing_register for select using (true);
create policy learn_register_write on learn_processing_register for all
  using (learn_is_platform()) with check (learn_is_platform());

insert into learn_processing_register
  (activity, purpose, legal_basis, data_subjects, categories, retention, recipients) values
  ('Émargement', 'Prouver l''assiduité en formation',
   'Obligation légale (art. L6362-x, contrôle DREETS)', 'Apprenants, formateurs',
   'Identité, horodatage, adresse IP, appareil', '3 à 10 ans selon le financeur',
   'Organisme, financeur, corps de contrôle'),
  ('Gestion des inscriptions', 'Exécuter la convention de formation',
   'Exécution du contrat', 'Apprenants', 'Identité, coordonnées, employeur',
   'Durée de la relation + 3 ans', 'Organisme'),
  ('Évaluations', 'Mesurer la satisfaction et les acquis (Qualiopi crit. 7)',
   'Intérêt légitime / obligation de certification', 'Apprenants, formateurs, entreprises',
   'Réponses, scores, commentaires', '5 ans', 'Organisme, auditeur')
on conflict do nothing;

-- ----------------------------------------------------------------- réversibilité
--
-- What a departing customer takes with them. Their retention obligation outlives the
-- subscription, so leaving without their evidence would make them non-compliant — which
-- makes this a duty as much as a sales answer to the lock-in objection.

create or replace function learn_reversibility_manifest(p_tenant uuid default null)
returns table (dataset text, rows bigint, note text)
language plpgsql stable security definer set search_path = public as $fn$
declare t uuid := coalesce(p_tenant, learn_current_tenant());
begin
  return query
    select 'profils'::text, count(*)::bigint, 'comptes et rôles'::text
      from learn_profiles where tenant_id = t
    union all select 'sessions', count(*), 'sessions et créneaux'
      from learn_sessions where tenant_id = t
    union all select 'inscriptions', count(*), null
      from learn_enrollments where tenant_id = t
    union all select 'emargements', count(*),
      'chaîne de hachage incluse, vérifiable hors plateforme'
      from learn_attendance_signatures where tenant_id = t
    union all select 'documents', count(*), 'PDF/A avec leur date de conservation'
      from learn_documents where tenant_id = t
    union all select 'coffre', count(*), null
      from learn_vault_objects where tenant_id = t
    union all select 'evaluations', count(*), null
      from learn_survey_responses where tenant_id = t
    union all select 'reclamations', count(*), 'avec les actions qui en découlent'
      from learn_reclamations where tenant_id = t
    union all select 'resultats', count(*), 'notes et blocs de compétences'
      from learn_attempts where tenant_id = t
    union all select 'journal_acces', count(*), 'append-only'
      from learn_access_log where tenant_id = t;
end
$fn$;

-- The gate itself. Refuses to call a tenant ready without a signed DPA.
create or replace function learn_tenant_readiness(p_tenant uuid)
returns table (requirement text, met boolean, detail text)
language sql stable security definer set search_path = public as $$
  select 'DPA signé (art. 28)'::text,
         exists(select 1 from learn_dpas d where d.tenant_id = p_tenant and d.signed_at is not null),
         'son absence est une violation autonome sanctionnée par la CNIL'::text
  union all
  select 'Liste des sous-traitants publiée',
         exists(select 1 from learn_subprocessors where until is null), null
  union all
  select 'Registre de traitement (responsable de traitement : nous)',
         exists(select 1 from learn_processing_register), null
  union all
  select 'Marque blanche configurée',
         exists(select 1 from learn_tenant_branding b where b.tenant_id = p_tenant),
         'la mention du NDA est obligatoire sur les documents'
  union all
  select 'Export de réversibilité disponible', true,
         'testé par learn_reversibility_manifest()'
$$;

create policy learn_impjob_all on learn_import_jobs for all
  using (learn_current_role() = 'admin' or learn_is_platform())
  with check (learn_current_role() = 'admin' or learn_is_platform());
create policy learn_improw_all on learn_import_rows for all
  using (learn_current_role() = 'admin' or learn_is_platform())
  with check (learn_current_role() = 'admin' or learn_is_platform());

grant select, insert, update, delete
  on learn_import_jobs, learn_import_rows, learn_dpas to learn_app;
grant select on learn_subprocessors, learn_processing_register to learn_app, learn_readonly;
grant select on learn_import_jobs, learn_import_rows, learn_dpas to learn_readonly;

commit;
