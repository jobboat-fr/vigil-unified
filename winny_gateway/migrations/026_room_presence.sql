-- 026 — Qui était dans la salle, et quand (webhook LiveKit).
--
-- Une ligne par entrée et par sortie. Sert à rapprocher la présence réelle en visio de
-- l'émargement LEARN : la passerelle SIGNALE les écarts, elle ne signe ni ne corrige
-- jamais une feuille. Les preuves d'émargement restent celles de LEARN.

create table if not exists public.room_presence (
    id          bigint generated always as identity primary key,
    room_id     uuid not null references public.rooms(id) on delete cascade,
    identity    text not null,
    name        text,
    event       text not null check (event in ('joined', 'left')),
    at          timestamptz not null,
    livekit_event_id text unique,
    tenant_id   uuid,
    created_at  timestamptz not null default now()
);
create index if not exists room_presence_room_idx on public.room_presence (room_id, identity, at);

alter table public.room_presence enable row level security;
revoke all on table public.room_presence from anon, authenticated;

drop trigger if exists vigil_stamp_tenant on public.room_presence;
create or replace function public.vigil_stamp_tenant_from_room()
returns trigger language plpgsql security definer set search_path = public as $fn$
begin
  if new.tenant_id is null then
    select tenant_id into new.tenant_id from rooms where id = new.room_id;
  end if;
  return new;
end;
$fn$;
create trigger vigil_stamp_tenant before insert on public.room_presence
  for each row execute function public.vigil_stamp_tenant_from_room();
revoke execute on function public.vigil_stamp_tenant_from_room() from public, anon, authenticated;
