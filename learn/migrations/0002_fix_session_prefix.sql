-- LEARN — 0002 — repair the session-variable prefix.
--
-- 0001 was written for a package called hbs_learn and renamed to learn when the product
-- became an AZZ&CO product rather than an HBS one. The rename replaced `hbs_` but not
-- `hbs.` — so the functions kept reading GUCs named hbs.role / hbs.tenant_id while the
-- application sets learn.*. Every policy therefore saw an empty context and denied
-- everything, which is the correct failure direction but not the intended one.
--
-- Re-creates only the functions that read a GUC. Tables, policies and seeds are untouched.

begin;

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

create or replace function learn_current_principal() returns text
language sql stable as $$
  select coalesce(nullif(current_setting('learn.principal', true), ''), 'human')
$$;

create or replace function learn_is_platform() returns boolean
language sql stable as $$ select learn_current_role() = 'super_admin' $$;

create or replace function learn_is_read_only() returns boolean
language sql stable as $$
  select coalesce((select is_read_only from learn_roles where role = learn_current_role()), true)
$$;

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

create or replace function learn_no_agent_writes(p_table regclass) returns void
language plpgsql as $fn$
declare t text := p_table::text;
begin
  execute format($p$create policy learn_human_only on %s as restrictive for insert
      with check (learn_current_principal() <> 'agent')$p$, t);
end
$fn$;

commit;
