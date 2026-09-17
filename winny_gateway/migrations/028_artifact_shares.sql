-- 028 — Partager un artefact du studio.
--
-- Deux façons, une seule table :
--   * à une personne de son organisme (grantee_id), en lecture (`view`) ou en modification (`edit`) ;
--   * par lien public (token_hash), toujours en lecture seule, avec une échéance.
-- Le jeton du lien n'est jamais stocké : seulement son empreinte SHA-256. Un partage n'est
-- jamais effacé, il est révoqué (revoked_at) — on garde la trace de qui a vu quoi.

begin;

create table if not exists public.artifact_shares (
    id             uuid primary key default gen_random_uuid(),
    artifact_id    uuid not null references public.artifacts(id) on delete cascade,
    owner_id       uuid not null references auth.users(id) on delete cascade,
    tenant_id      uuid,
    grantee_id     uuid references auth.users(id) on delete cascade,
    access         text not null default 'view' check (access in ('view', 'edit')),
    token_hash     text unique,
    expires_at     timestamptz,
    revoked_at     timestamptz,
    last_opened_at timestamptz,
    created_at     timestamptz not null default now(),
    constraint artifact_shares_one_target check ((grantee_id is null) <> (token_hash is null)),
    constraint artifact_shares_link_read_only check (token_hash is null or access = 'view'),
    constraint artifact_shares_link_expires check (token_hash is null or expires_at is not null)
);

create unique index if not exists artifact_shares_person_active
    on public.artifact_shares (artifact_id, grantee_id)
    where grantee_id is not null and revoked_at is null;
create index if not exists artifact_shares_grantee_idx
    on public.artifact_shares (grantee_id) where revoked_at is null;
create index if not exists artifact_shares_artifact_idx on public.artifact_shares (artifact_id);

-- L'organisme vient du propriétaire, comme pour toutes les tables de la passerelle (023).
drop trigger if exists vigil_stamp_tenant on public.artifact_shares;
create trigger vigil_stamp_tenant before insert on public.artifact_shares
    for each row execute function public.vigil_stamp_tenant();

alter table public.artifact_shares enable row level security;
revoke all on table public.artifact_shares from anon, authenticated;

commit;
