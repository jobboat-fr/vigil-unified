-- 030 — Les projets du Studio : un canevas façon Railway qui relie salles, artefacts, agents et coffre.
--
-- Trois tables :
--   * studio_projects       — un projet, ses six étapes classiques rangées dans `etapes` (jsonb) :
--                             nom_objectif, perimetre_livrables, equipe, jalons, ressources,
--                             validation. La forme de chaque étape est contrôlée par la passerelle
--                             (routes/vigil/projets.py) ; la base garde seulement que c'est un objet.
--   * studio_project_cards  — les cartes posées sur le canevas (salle, artefact, agent, coffre),
--                             avec leur position. Une carte ne copie rien : elle pointe (ref_id).
--   * studio_agent_runs     — chaque travail demandé à un agent depuis un projet, avec sa sortie
--                             COMPLÈTE. Ce qui est montré à la personne (aperçu ou texte entier)
--                             se décide à la lecture, selon l'abonnement du moment ; la trace, elle,
--                             reste entière. Supprimer le projet ne l'efface pas (project_id → null).
--
-- Même posture que 028 : l'organisme est posé par déclencheur, RLS activée, et `anon` comme
-- `authenticated` n'ont aucun droit — seule la passerelle (clé de service) lit et écrit.
--
-- Source d'un artefact : aucune colonne ajoutée. Le lien salle → artefact existe déjà
-- (`rooms.artifact_id`, posé par le résumé de fin de séance) ; la passerelle le lit à l'envers.

begin;

create table if not exists public.studio_projects (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid not null references auth.users(id) on delete cascade,
    tenant_id  uuid,
    title      text not null default 'Projet sans titre' check (char_length(title) between 1 and 200),
    etapes     jsonb not null default '{}'::jsonb check (jsonb_typeof(etapes) = 'object'),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists studio_projects_user_idx on public.studio_projects (user_id, updated_at desc);
create index if not exists studio_projects_tenant_idx on public.studio_projects (tenant_id);

create table if not exists public.studio_project_cards (
    id         uuid primary key default gen_random_uuid(),
    project_id uuid not null references public.studio_projects(id) on delete cascade,
    tenant_id  uuid,
    kind       text not null check (kind in ('salle', 'artefact', 'agent', 'coffre')),
    ref_id     text not null check (char_length(ref_id) between 1 and 200),
    -- Pour une carte `coffre` seulement : ce qu'elle désigne et comment l'afficher.
    sous_type  text check (sous_type is null or sous_type in ('document', 'session', 'personne')),
    libelle    text check (libelle is null or char_length(libelle) <= 200),
    x          double precision not null default 0,
    y          double precision not null default 0,
    created_at timestamptz not null default now(),
    constraint studio_project_cards_coffre_type check ((kind = 'coffre') = (sous_type is not null))
);
create index if not exists studio_project_cards_project_idx on public.studio_project_cards (project_id);
create index if not exists studio_project_cards_tenant_idx on public.studio_project_cards (tenant_id);

create table if not exists public.studio_agent_runs (
    id              uuid primary key default gen_random_uuid(),
    project_id      uuid references public.studio_projects(id) on delete set null,
    user_id         uuid not null references auth.users(id) on delete cascade,
    tenant_id       uuid,
    agent           text not null check (agent in ('azzmin', 'azzco', 'azzcom')),
    brief           text not null,
    sortie_complete text not null,
    stub            boolean not null default false,
    -- La personne était-elle abonnée à l'agent au moment du travail ? (trace, pas un droit)
    abonne          boolean not null default false,
    created_at      timestamptz not null default now()
);
create index if not exists studio_agent_runs_project_idx on public.studio_agent_runs (project_id, created_at desc);
create index if not exists studio_agent_runs_user_idx on public.studio_agent_runs (user_id, created_at desc);
create index if not exists studio_agent_runs_tenant_idx on public.studio_agent_runs (tenant_id);

-- L'organisme vient du propriétaire (023) pour les projets et les travaux d'agent…
drop trigger if exists vigil_stamp_tenant on public.studio_projects;
create trigger vigil_stamp_tenant before insert on public.studio_projects
    for each row execute function public.vigil_stamp_tenant();
drop trigger if exists vigil_stamp_tenant on public.studio_agent_runs;
create trigger vigil_stamp_tenant before insert on public.studio_agent_runs
    for each row execute function public.vigil_stamp_tenant();

-- …et du projet pour les cartes, qui n'ont pas de propriétaire direct. Fonction à part plutôt
-- que de réécrire vigil_stamp_tenant_from_parent (023), qui sert déjà deux autres tables.
create or replace function public.studio_stamp_tenant_from_project()
returns trigger language plpgsql security definer set search_path = public as $fn$
begin
  if new.tenant_id is null then
    select tenant_id into new.tenant_id from studio_projects where id = new.project_id;
  end if;
  return new;
end;
$fn$;

drop trigger if exists vigil_stamp_tenant on public.studio_project_cards;
create trigger vigil_stamp_tenant before insert on public.studio_project_cards
    for each row execute function public.studio_stamp_tenant_from_project();

alter table public.studio_projects enable row level security;
alter table public.studio_project_cards enable row level security;
alter table public.studio_agent_runs enable row level security;
revoke all on table public.studio_projects from anon, authenticated;
revoke all on table public.studio_project_cards from anon, authenticated;
revoke all on table public.studio_agent_runs from anon, authenticated;
revoke execute on function public.studio_stamp_tenant_from_project() from public, anon, authenticated;

commit;
