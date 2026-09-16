-- 023 — Rattacher les tables de la passerelle au modèle LEARN.
--
-- 1. Chaque ligne porte le `tenant_id` LEARN de son propriétaire. Le code de la passerelle
--    n'écrit que user_id (ou org_id / owner_id) : un déclencheur retrouve l'organisme dans
--    auth.users.raw_app_meta_data->>'tenant_id', là où LEARN le range (voir 0037).
--    Rien à modifier côté Python, et une ligne ne peut pas naître sans organisme connu
--    si son propriétaire en a un.
-- 2. La passerelle passe exclusivement par la clé de service. Les rôles `anon` et
--    `authenticated` n'ont donc rien à faire sur ces tables : on retire leurs droits,
--    comme LEARN le fait pour ses propres tables. Les politiques « auth.uid() = user_id »
--    des migrations 011-022 restent en place mais ne peuvent plus servir.
-- 3. Le déclencheur de versions d'artefact (016) est attaché, maintenant que `canvas` existe.

begin;

create or replace function public.vigil_stamp_tenant()
returns trigger language plpgsql security definer set search_path = public, auth as $fn$
declare
  j     jsonb := to_jsonb(new);
  owner uuid;
begin
  if new.tenant_id is not null then
    return new;
  end if;
  owner := coalesce(
    nullif(j->>'user_id', '')::uuid,
    nullif(j->>'owner_id', '')::uuid,
    nullif(j->>'org_id', '')::uuid
  );
  if owner is not null then
    select nullif(u.raw_app_meta_data->>'tenant_id', '')::uuid
      into new.tenant_id
      from auth.users u
     where u.id = owner;
  end if;
  return new;
end;
$fn$;

do $$
declare
  t text;
begin
  foreach t in array array[
    'user_preferences','onboarding_state','audit_events',
    'organizations','org_members','subscriptions',
    'support_tickets','support_messages',
    'artifacts','artifact_versions',
    'rooms','ai_interventions','pattern_weights','commitments','guest_leads',
    'vault_documents','legal_precedents',
    'finance_accounts','finance_transactions','finance_connections',
    'crm_contacts','crm_deals',
    'mail_messages','mail_drafts',
    'departments','ops_jobs','ops_tasks','ops_events',
    'integration_secrets','connections','outbound_actions'
  ] loop
    execute format('alter table public.%I add column if not exists tenant_id uuid', t);
    execute format('create index if not exists %I on public.%I (tenant_id)', t || '_tenant_idx', t);
    execute format('drop trigger if exists vigil_stamp_tenant on public.%I', t);
    execute format(
      'create trigger vigil_stamp_tenant before insert on public.%I '
      'for each row execute function public.vigil_stamp_tenant()', t);
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on table public.%I from anon, authenticated', t);
  end loop;
end $$;

-- support_messages et artifact_versions n'ont pas de propriétaire direct : ils héritent
-- de leur parent.
create or replace function public.vigil_stamp_tenant_from_parent()
returns trigger language plpgsql security definer set search_path = public as $fn$
begin
  if new.tenant_id is null then
    if tg_table_name = 'support_messages' then
      select tenant_id into new.tenant_id from support_tickets where id = new.ticket_id;
    elsif tg_table_name = 'artifact_versions' then
      select tenant_id into new.tenant_id from artifacts where id = new.artifact_id;
    end if;
  end if;
  return new;
end;
$fn$;

drop trigger if exists vigil_stamp_tenant on public.support_messages;
create trigger vigil_stamp_tenant before insert on public.support_messages
  for each row execute function public.vigil_stamp_tenant_from_parent();
drop trigger if exists vigil_stamp_tenant on public.artifact_versions;
create trigger vigil_stamp_tenant before insert on public.artifact_versions
  for each row execute function public.vigil_stamp_tenant_from_parent();

drop trigger if exists artifacts_snapshot_version on public.artifacts;
create trigger artifacts_snapshot_version before update on public.artifacts
  for each row execute function public.snapshot_artifact_version();

revoke execute on function public.vigil_stamp_tenant() from public, anon, authenticated;
revoke execute on function public.vigil_stamp_tenant_from_parent() from public, anon, authenticated;
revoke execute on function public.snapshot_artifact_version() from public, anon, authenticated;

commit;
