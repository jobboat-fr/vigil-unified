-- LEARN — 0001 — tenancy, the 6-role catalogue, capabilities, and the access floor.
--
-- Design notes (../../hbs-backend/PLAN_V2.md §3, §4, §12):
--   * Authorization has THREE axes, not one. `level` orders the hierarchy for display,
--     `creatable_roles` says who may mint whom, and `learn_capabilities` says what a role
--     may do to a resource. Level alone is not sufficient: auditeur (4) sits above
--     apprenant (5), so a pure level rule would let a read-only auditor create learners.
--   * Tenant isolation and read-only are RESTRICTIVE policies. Restrictive policies are
--     AND-ed, so they form a floor no later permissive policy can widen.
--   * Context comes from session GUCs set with SET LOCAL inside the request transaction,
--     never from request input.
--   * Everything fails CLOSED: an unset or unknown role is read-only, matches no tenant,
--     and holds no capability.

begin;

create extension if not exists pgcrypto;

-- ----------------------------------------------------------------- session context

create or replace function learn_current_tenant() returns uuid
language sql stable as $$ select nullif(current_setting('learn.tenant_id', true), '')::uuid $$;

create or replace function learn_current_user_id() returns uuid
language sql stable as $$ select nullif(current_setting('learn.user_id', true), '')::uuid $$;

create or replace function learn_current_company() returns uuid
language sql stable as $$ select nullif(current_setting('learn.company_id', true), '')::uuid $$;

create or replace function learn_current_role() returns text
language sql stable as $$
  select coalesce(nullif(current_setting('learn.role', true), ''), 'anonymous')
$$;

-- 'agent' when the caller is the assistant acting on behalf of a human, else 'human'.
create or replace function learn_current_principal() returns text
language sql stable as $$
  select coalesce(nullif(current_setting('learn.principal', true), ''), 'human')
$$;

-- ----------------------------------------------------------------- role catalogue

create table if not exists learn_roles (
  role            text primary key,
  level           int  not null unique,
  creatable_roles text[] not null default '{}',
  data_scope      text not null
                    check (data_scope in ('platform','tenant','own_sessions','own_company','self')),
  is_read_only    boolean not null default false,
  tenant_bound    boolean not null default true,
  label_fr        text not null
);

insert into learn_roles (role, level, creatable_roles, data_scope, is_read_only, tenant_bound, label_fr) values
  ('super_admin', 0, array['admin','formateur','entreprise','auditeur','apprenant'], 'platform',     false, false, 'Super administrateur'),
  ('admin',       1, array['formateur','entreprise','auditeur','apprenant'],         'tenant',       false, true,  'Administrateur'),
  ('formateur',   2, array[]::text[],                                                'own_sessions', false, true,  'Formateur'),
  ('entreprise',  3, array['apprenant'],                                             'own_company',  false, true,  'Entreprise cliente'),
  ('auditeur',    4, array[]::text[],                                                'tenant',       true,  true,  'Auditeur'),
  ('apprenant',   5, array[]::text[],                                                'self',         false, true,  'Apprenant')
on conflict (role) do nothing;

create or replace function learn_is_platform() returns boolean
language sql stable as $$ select learn_current_role() = 'super_admin' $$;

-- Unknown role => read-only. Fail closed.
create or replace function learn_is_read_only() returns boolean
language sql stable as $$
  select coalesce((select is_read_only from learn_roles where role = learn_current_role()), true)
$$;

-- ----------------------------------------------------------------- capabilities (3rd axis)

create table if not exists learn_capabilities (
  role     text not null references learn_roles(role) on delete cascade,
  resource text not null,
  action   text not null
             check (action in ('create','read','update','delete','cancel','sign','export')),
  note     text,
  primary key (role, resource, action)
);

-- Read the seed as a grant list: anything absent is denied.
-- 'sign' is deliberately held only by the two people who can attest presence.
insert into learn_capabilities (role, resource, action, note) values
  -- super_admin: platform-wide, but attests nothing
  ('super_admin','tenant','create',null),   ('super_admin','tenant','read',null),
  ('super_admin','tenant','update',null),   ('super_admin','profile','create',null),
  ('super_admin','profile','read',null),    ('super_admin','program','read',null),
  ('super_admin','session','read',null),    ('super_admin','attendance','read',null),
  ('super_admin','document','read',null),   ('super_admin','vault_object','read',null),
  ('super_admin','access_log','read',null), ('super_admin','vault_object','export','réversibilité client'),

  -- admin: everything inside one organisme, except attesting a presence
  ('admin','program','create',null),    ('admin','program','read',null),
  ('admin','program','update',null),    ('admin','program','delete',null),
  ('admin','session','create',null),    ('admin','session','read',null),
  ('admin','session','update',null),    ('admin','session','cancel',null),
  ('admin','slot','create',null),       ('admin','slot','read',null),
  ('admin','slot','update',null),       ('admin','slot','cancel',null),
  ('admin','enrollment','create',null), ('admin','enrollment','read',null),
  ('admin','enrollment','update',null), ('admin','enrollment','delete',null),
  ('admin','profile','create',null),    ('admin','profile','read',null),
  ('admin','profile','update',null),    ('admin','attendance','read',null),
  ('admin','document','create',null),   ('admin','document','read',null),
  ('admin','document','update',null),   ('admin','vault_object','read',null),
  ('admin','vault_object','export','export d''audit Qualiopi'),
  ('admin','evaluation','read',null),   ('admin','reclamation','read',null),
  ('admin','reclamation','update',null),('admin','access_log','read',null),

  -- formateur: writes presence and lesson material, deletes nothing
  ('formateur','program','read',null),      ('formateur','session','read',null),
  ('formateur','slot','read',null),         ('formateur','slot','update','ses créneaux'),
  ('formateur','enrollment','read',null),   ('formateur','profile','read','ses apprenants'),
  ('formateur','attendance','read',null),   ('formateur','attendance','sign','contre-signature'),
  ('formateur','document','create','supports pédagogiques'),
  ('formateur','document','read',null),     ('formateur','evaluation','read',null),

  -- entreprise: its own employees only
  ('entreprise','session','read',null),     ('entreprise','enrollment','create','ses salariés'),
  ('entreprise','enrollment','read',null),  ('entreprise','enrollment','delete','ses salariés'),
  ('entreprise','profile','create','ses salariés'),
  ('entreprise','profile','read',null),     ('entreprise','attendance','read',null),
  ('entreprise','document','read',null),

  -- auditeur: reads everything in the tenant, writes nothing
  ('auditeur','program','read',null),       ('auditeur','session','read',null),
  ('auditeur','slot','read',null),          ('auditeur','enrollment','read',null),
  ('auditeur','profile','read',null),       ('auditeur','attendance','read',null),
  ('auditeur','document','read',null),      ('auditeur','vault_object','read',null),
  ('auditeur','evaluation','read',null),    ('auditeur','reclamation','read',null),

  -- apprenant: self only; the one thing they write is their own presence
  ('apprenant','program','read',null),      ('apprenant','session','read',null),
  ('apprenant','slot','read',null),         ('apprenant','enrollment','read',null),
  ('apprenant','profile','read','soi-même'),('apprenant','profile','update','soi-même'),
  ('apprenant','attendance','read',null),   ('apprenant','attendance','sign','entrée et sortie'),
  ('apprenant','document','read',null),     ('apprenant','evaluation','create',null),
  ('apprenant','reclamation','create',null)
on conflict (role, resource, action) do nothing;

create or replace function learn_can(p_resource text, p_action text) returns boolean
language sql stable as $$
  select exists (
    select 1 from learn_capabilities
    where role = learn_current_role() and resource = p_resource and action = p_action
  )
$$;

-- ----------------------------------------------------------------- tenants

create table if not exists learn_tenants (
  id          uuid primary key default gen_random_uuid(),
  slug        text not null unique,
  name        text not null,
  siret       text,
  nda         text,                                -- déclaration d'activité
  qualiopi    boolean not null default false,
  certifiante boolean not null default false,      -- gates Qualiopi indicators 3, 7, 16
  timezone    text not null default 'Europe/Paris',
  created_at  timestamptz not null default now()
);

alter table learn_tenants enable row level security;
alter table learn_tenants force row level security;

create policy learn_tenants_read on learn_tenants for select
  using (learn_is_platform() or id = learn_current_tenant());
create policy learn_tenants_write on learn_tenants for all
  using (learn_is_platform() and learn_can('tenant','update'))
  with check (learn_is_platform() and learn_can('tenant','create'));

-- ----------------------------------------------------------------- companies

create table if not exists learn_companies (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,
  siret      text,
  created_at timestamptz not null default now()
);

-- ----------------------------------------------------------------- profiles

create table if not exists learn_profiles (
  id         uuid primary key,                     -- = the auth user id
  tenant_id  uuid references learn_tenants(id) on delete restrict,   -- NULL only for super_admin
  role       text not null references learn_roles(role),
  company_id uuid references learn_companies(id) on delete set null,
  email      text not null,
  full_name  text,
  expires_at timestamptz,                          -- auditeur: an audit is a window, not a seat
  created_by uuid references learn_profiles(id),
  created_at timestamptz not null default now(),
  constraint learn_profiles_tenant_required
    check (role = 'super_admin' or tenant_id is not null),
  constraint learn_profiles_company_required
    check (role <> 'entreprise' or company_id is not null)
);

create index if not exists learn_profiles_tenant_idx  on learn_profiles (tenant_id);
create index if not exists learn_profiles_company_idx on learn_profiles (company_id);
create index if not exists learn_profiles_email_idx   on learn_profiles (lower(email));

alter table learn_profiles enable row level security;
alter table learn_profiles force row level security;

create policy learn_profiles_floor on learn_profiles as restrictive for all
  using      (learn_is_platform() or tenant_id = learn_current_tenant())
  with check (learn_is_platform() or tenant_id = learn_current_tenant());

create policy learn_profiles_ro_insert on learn_profiles as restrictive for insert
  with check (not learn_is_read_only());
create policy learn_profiles_ro_update on learn_profiles as restrictive for update
  using (not learn_is_read_only()) with check (not learn_is_read_only());
create policy learn_profiles_ro_delete on learn_profiles as restrictive for delete
  using (not learn_is_read_only());

-- Role-specific visibility. NOTE: formateur is limited to self here; widening it to
-- "learners enrolled in my sessions" lands in 0002, which is where learn_enrollments exists.
create policy learn_profiles_scope on learn_profiles for select
  using (
    learn_is_platform()
    or learn_current_role() in ('admin','auditeur')
    or id = learn_current_user_id()
    or (learn_current_role() = 'entreprise' and company_id = learn_current_company())
  );

create policy learn_profiles_write on learn_profiles for all
  using (
    learn_is_platform()
    or (learn_can('profile','update') and learn_current_role() = 'admin')
    or id = learn_current_user_id()
  )
  with check (
    learn_is_platform()
    or (learn_can('profile','create') and learn_current_role() = 'admin')
    or (learn_can('profile','create') and learn_current_role() = 'entreprise'
        and company_id = learn_current_company())
  );

-- ----------------------------------------------------------------- hierarchy trigger
-- Second line of defence. The API runs the same three checks; this makes a bug there
-- non-exploitable rather than merely unlikely.

create or replace function learn_enforce_role_hierarchy() returns trigger
language plpgsql as $fn$
declare
  actor_role    text := learn_current_role();
  actor_tenant  uuid := learn_current_tenant();
  actor_company uuid := learn_current_company();
  allowed       text[];
begin
  -- Explicit, opt-in bootstrap for migrations and tenant provisioning. Never implicit:
  -- an absent session context must not be a way past this trigger.
  if coalesce(current_setting('learn.bootstrap', true), '') = 'on' then
    return new;
  end if;

  if actor_role = 'anonymous' then
    raise exception 'no_session_context' using errcode = '42501';
  end if;

  -- 1. may this role mint users at all, and this role in particular
  if not learn_can('profile','create') then
    raise exception 'capability_missing: % cannot create profiles', actor_role
      using errcode = '42501';
  end if;
  select creatable_roles into allowed from learn_roles where role = actor_role;
  if allowed is null or not (new.role = any(allowed)) then
    raise exception 'role_hierarchy_violation: % cannot assign %', actor_role, new.role
      using errcode = '42501';
  end if;

  -- 2. same tenant
  if not learn_is_platform() and new.tenant_id is distinct from actor_tenant then
    raise exception 'cross_tenant_violation' using errcode = '42501';
  end if;

  -- 3. an entreprise may only touch its own employees
  if actor_role = 'entreprise' and new.company_id is distinct from actor_company then
    raise exception 'cross_company_violation' using errcode = '42501';
  end if;

  return new;
end
$fn$;

drop trigger if exists learn_profiles_hierarchy on learn_profiles;
create trigger learn_profiles_hierarchy
  before insert or update of role, tenant_id, company_id on learn_profiles
  for each row execute function learn_enforce_role_hierarchy();

-- ----------------------------------------------------------------- helpers every later migration uses

-- Makes a table tenant-scoped in ONE call: column, index, RLS, and the restrictive floors.
-- A table created through this helper cannot exist without a tenant policy — that is the
-- entire mitigation for hand-rolled multi-tenancy.
create or replace function learn_tenant_table(p_table regclass) returns void
language plpgsql as $fn$
declare t text := p_table::text;
begin
  execute format(
    'alter table %s add column if not exists tenant_id uuid not null references learn_tenants(id) on delete restrict', t);
  execute format(
    'create index if not exists %I on %s (tenant_id)', replace(t, '.', '_') || '_tenant_idx', t);
  execute format('alter table %s enable row level security', t);
  execute format('alter table %s force row level security', t);

  execute format($p$
    create policy learn_tenant_floor on %s as restrictive for all
      using      (learn_is_platform() or tenant_id = learn_current_tenant())
      with check (learn_is_platform() or tenant_id = learn_current_tenant())$p$, t);

  execute format($p$create policy learn_ro_insert on %s as restrictive for insert
      with check (not learn_is_read_only())$p$, t);
  execute format($p$create policy learn_ro_update on %s as restrictive for update
      using (not learn_is_read_only()) with check (not learn_is_read_only())$p$, t);
  execute format($p$create policy learn_ro_delete on %s as restrictive for delete
      using (not learn_is_read_only())$p$, t);
end
$fn$;

-- Evidence tables must be append-only: an émargement that can be edited is not evidence.
-- Enforced by revoked grants plus restrictive policies, so it holds for every role
-- including super_admin.
create or replace function learn_append_only(p_table regclass) returns void
language plpgsql as $fn$
declare t text := p_table::text;
begin
  execute format($p$create policy learn_no_update on %s as restrictive for update using (false)$p$, t);
  execute format($p$create policy learn_no_delete on %s as restrictive for delete using (false)$p$, t);
  execute format('revoke update, delete on %s from public', t);
end
$fn$;

-- An agent may never author an attestation of a human act. Applied to signature tables.
create or replace function learn_no_agent_writes(p_table regclass) returns void
language plpgsql as $fn$
declare t text := p_table::text;
begin
  execute format($p$create policy learn_human_only on %s as restrictive for insert
      with check (learn_current_principal() <> 'agent')$p$, t);
end
$fn$;

select learn_tenant_table('learn_companies');

commit;
