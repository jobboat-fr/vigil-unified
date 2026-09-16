-- 027 — Sous-salles : la répartition en groupes d'une salle (voir winny_gateway/breakouts.py).
-- [{id, name, members: [identité LiveKit = id utilisateur], open}] ; vide = pas de sous-salles.

alter table public.rooms add column if not exists breakouts jsonb not null default '[]'::jsonb;
