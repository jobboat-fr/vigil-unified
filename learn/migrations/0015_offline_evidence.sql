-- LEARN — 0015 — évidence d'un émargement différé (hors ligne).
--
-- A signature made in a basement and stored twenty minutes later is honest only if both
-- times are visible. `signed_at` stays the server's clock — a phone's clock belongs to the
-- person holding it, and trusting it would let anyone sign for yesterday. The device's own
-- reading arrives inside the evidence bundle as `offline_at`, so a feuille can say
-- "signé sur l'appareil à 09:02, enregistré à 11:40 à la reconnexion" instead of a single
-- timestamp that quietly misrepresents the room.

begin;

create or replace view learn_attendance_deferred
  with (security_invoker = true) as
select
  a.id, a.tenant_id, a.slot_id, a.profile_id, a.kind,
  a.signed_at                                   as recorded_at,
  (a.evidence ->> 'offline_at')::timestamptz    as device_at,
  round(extract(epoch from (
        a.signed_at - (a.evidence ->> 'offline_at')::timestamptz)) / 60)::int
                                                as minutes_deferred
from learn_attendance_signatures a
where a.evidence ? 'offline_at';

grant select on learn_attendance_deferred to learn_app, learn_readonly;

commit;
