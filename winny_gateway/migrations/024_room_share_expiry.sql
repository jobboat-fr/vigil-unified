-- 024 — Un lien d'invitation expire, et meurt avec la réunion.
--
-- Jusqu'ici le jeton de partage d'une salle valait pour toujours : un lien transféré, ou
-- resté dans une boîte mail, ouvrait encore la salle des mois après la séance.
-- share_expires_at borne sa durée (ROOM_SHARE_TTL_HOURS côté passerelle, 72 h par défaut) ;
-- une salle close refuse aussi l'entrée, quelle que soit l'échéance.

alter table public.rooms add column if not exists share_expires_at timestamptz;
