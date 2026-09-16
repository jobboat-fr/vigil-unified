-- 007 — Les tables de base de la passerelle, recréées dans le projet LEARN.
--
-- Elles avaient été créées à la main dans l'ancien projet Supabase VIGIL
-- (pqikzrcykdynxhtnjgeh), aujourd'hui supprimé : aucun fichier ne les décrivait.
-- Les colonnes sont reprises exactement de ce que le code lit et écrit
-- (routes/vigil/rooms.py, routes/vigil/studio.py, routes/vault.py, routes/billing.py,
-- routes/account.py, ops/*.py, integrations/notion.py) — le code ne change pas.
--
-- Doit passer avant 008-022 : 009 modifie user_preferences, 010/014/015 modifient
-- rooms et artifacts, 016 remplace le déclencheur de versions d'artefact.
-- Les tables de trading (broker_credentials, portfolio_snapshots, trade_history,
-- trading_signals) ne sont pas recréées : aucune des pages métier ne les utilise.

begin;

create table if not exists public.user_preferences (
    id                    uuid primary key default gen_random_uuid(),
    user_id               uuid not null references auth.users(id) on delete cascade,
    broker_cr             text not null default 'binance',
    tier                  text not null default 'lite',
    theme                 text not null default 'dark',
    notifications_enabled boolean not null default true,
    risk_level            text not null default 'moderate',
    max_position_pct      numeric(5,2) not null default 5.00,
    auto_approval_enabled boolean not null default false,
    created_at            timestamptz not null default now(),
    updated_at            timestamptz not null default now(),
    unique (user_id)
);

create table if not exists public.onboarding_state (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null references auth.users(id) on delete cascade,
    completed       boolean not null default false,
    experience      text,
    broker_cr       text,
    has_api_keys    boolean not null default false,
    coinbase_wallet jsonb,
    completed_at    timestamptz,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    unique (user_id)
);

-- db.audit_log écrit user_id/event_type/action/component/details/symbol/broker.
create table if not exists public.audit_events (
    id         bigint generated always as identity primary key,
    user_id    uuid references auth.users(id) on delete set null,
    event_type text not null,
    action     text not null,
    component  text not null default 'system',
    details    jsonb not null default '{}'::jsonb,
    symbol     text,
    broker     text,
    created_at timestamptz not null default now()
);
create index if not exists audit_events_user_time_idx on public.audit_events (user_id, created_at desc);

-- ── Organisation et abonnement ──────────────────────────────────────────────
create table if not exists public.organizations (
    id                 uuid primary key default gen_random_uuid(),
    name               text not null,
    slug               text unique,
    owner_id           uuid references auth.users(id) on delete set null,
    stripe_customer_id text,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now()
);

create table if not exists public.org_members (
    id         uuid primary key default gen_random_uuid(),
    org_id     uuid not null references public.organizations(id) on delete cascade,
    user_id    uuid not null references auth.users(id) on delete cascade,
    email      text,
    role       text not null default 'member',
    created_at timestamptz not null default now(),
    unique (org_id, user_id)
);
create index if not exists org_members_user_idx on public.org_members (user_id);

create table if not exists public.subscriptions (
    id                   uuid primary key default gen_random_uuid(),
    org_id               uuid not null references public.organizations(id) on delete cascade,
    provider             text not null,
    external_id          text,
    external_customer_id text,
    product_code         text,
    plan_tier            text,
    status               text,
    seats_purchased      integer not null default 1,
    unit_price_cents     integer not null default 0,
    currency             text not null default 'EUR',
    current_period_start timestamptz,
    current_period_end   timestamptz,
    cancelled_at         timestamptz,
    metadata             jsonb not null default '{}'::jsonb,
    created_at           timestamptz not null default now(),
    updated_at           timestamptz not null default now(),
    unique (provider, external_id)
);
create index if not exists subscriptions_org_idx on public.subscriptions (org_id, updated_at desc);

-- ── Support ─────────────────────────────────────────────────────────────────
create table if not exists public.support_tickets (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid references auth.users(id) on delete set null,
    email      text,
    subject    text,
    status     text not null default 'open',
    source     text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists support_tickets_user_idx on public.support_tickets (user_id, created_at desc);

create table if not exists public.support_messages (
    id           uuid primary key default gen_random_uuid(),
    ticket_id    uuid not null references public.support_tickets(id) on delete cascade,
    author_id    uuid,
    author_email text,
    author_type  text not null default 'user',
    body         text not null,
    created_at   timestamptz not null default now()
);
create index if not exists support_messages_ticket_idx on public.support_messages (ticket_id, created_at);

-- ── Studio : artefacts et versions ──────────────────────────────────────────
-- brief/approach/stub (010) et canvas/tldraw (015) sont ajoutés par leurs migrations.
create table if not exists public.artifacts (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid not null references auth.users(id) on delete cascade,
    title      text not null default 'Untitled artifact',
    kind       text not null default 'proposal',
    text_dump  text not null default '',
    status     text not null default 'draft',
    version    integer not null default 1,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists artifacts_user_idx on public.artifacts (user_id, updated_at desc);

create table if not exists public.artifact_versions (
    id          uuid primary key default gen_random_uuid(),
    artifact_id uuid not null references public.artifacts(id) on delete cascade,
    version     integer not null,
    canvas      jsonb,
    authored_by uuid,
    created_at  timestamptz not null default now()
);
create index if not exists artifact_versions_artifact_idx on public.artifact_versions (artifact_id, version desc);

-- ── Salle de réunion ────────────────────────────────────────────────────────
-- members/default_lens (010) et live_url/live_provider/live_persona (014) sont ajoutés
-- par leurs migrations ; share_token est ici parce que 014 l'indexe.
create table if not exists public.rooms (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references auth.users(id) on delete cascade,
    title        text not null default 'Advisory Session',
    transcript   jsonb not null default '[]'::jsonb,
    status       text not null default 'active',
    summary      text,
    concluded_at timestamptz,
    artifact_id  uuid references public.artifacts(id) on delete set null,
    share_token  text unique,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);
create index if not exists rooms_user_idx on public.rooms (user_id, created_at desc);

-- Le journal de l'algorithme d'intervention (rooms.py:321).
create table if not exists public.ai_interventions (
    id                  uuid primary key default gen_random_uuid(),
    room_id             uuid references public.rooms(id) on delete cascade,
    user_id             uuid not null,
    proposed_text       text not null default '',
    urgency             text not null default 'normal',
    reason              text not null default '',
    touched_specialties jsonb not null default '[]'::jsonb,
    cost_usd            numeric(12,6) not null default 0,
    decision            text not null check (decision in ('speak','silent')),
    feedback_score      smallint,
    created_at          timestamptz not null default now()
);
create index if not exists ai_interventions_room_idx on public.ai_interventions (room_id, created_at desc);

-- Poids comportementaux par organisme : cooldown_turns, min_specialist_signals, silence_bias.
create table if not exists public.pattern_weights (
    id         uuid primary key default gen_random_uuid(),
    org_id     uuid not null,
    pattern_id text not null,
    weight     numeric not null,
    updated_at timestamptz not null default now(),
    unique (org_id, pattern_id)
);

create table if not exists public.commitments (
    id           uuid primary key default gen_random_uuid(),
    org_id       uuid not null,
    room_id      uuid references public.rooms(id) on delete set null,
    speaker_name text,
    text         text not null,
    kind         text not null default 'action',
    status       text not null default 'open',
    source       text not null default 'meeting',
    external_id  text,
    due_at       timestamptz,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);
create index if not exists commitments_org_idx on public.commitments (org_id, status);

create table if not exists public.guest_leads (
    id                   uuid primary key default gen_random_uuid(),
    org_id               uuid not null,
    room_id              uuid references public.rooms(id) on delete set null,
    name                 text not null default 'Guest',
    email                text,
    consent_to_follow_up boolean not null default false,
    status               text not null default 'new',
    source               text,
    metadata             jsonb not null default '{}'::jsonb,
    created_at           timestamptz not null default now(),
    updated_at           timestamptz not null default now()
);
create index if not exists guest_leads_org_idx on public.guest_leads (org_id, status);

-- ── Coffre documentaire ─────────────────────────────────────────────────────
create table if not exists public.vault_documents (
    id             uuid primary key default gen_random_uuid(),
    user_id        uuid not null references auth.users(id) on delete cascade,
    filename       text not null,
    mime_type      text,
    size_bytes     bigint,
    storage_path   text,
    status         text not null default 'processing',
    extracted_text text,
    category       text,
    title          text,
    parties        jsonb not null default '[]'::jsonb,
    key_dates      jsonb not null default '[]'::jsonb,
    amounts        jsonb not null default '[]'::jsonb,
    risk_flags     jsonb not null default '[]'::jsonb,
    summary        text,
    classify_error text,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);
create index if not exists vault_documents_user_idx on public.vault_documents (user_id, created_at desc);

-- Le fichier brut va dans un bucket privé `vault` (routes/vault.py:257).
insert into storage.buckets (id, name, public)
values ('vault', 'vault', false)
on conflict (id) do nothing;

-- Déclencheur de versions d'artefact : 016 remplace la fonction, il faut qu'elle existe
-- et soit attachée.
create or replace function public.snapshot_artifact_version()
returns trigger language plpgsql security definer as $fn$
begin
  if old.canvas is distinct from new.canvas and old.canvas is not null then
    insert into artifact_versions (artifact_id, version, canvas, authored_by)
    values (old.id, old.version, old.canvas, auth.uid());
    new.version = old.version + 1;
  end if;
  return new;
end;
$fn$;

commit;
