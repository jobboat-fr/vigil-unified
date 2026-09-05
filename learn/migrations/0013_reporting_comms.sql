-- LEARN — 0013 — export d'audit, notifications, signalement (V10 ind. 12).
--
-- The audit export is the phase's real deliverable. An organisme should never assemble a
-- dossier the week before an inspection — the dossier should already exist, and asking for
-- it should be a query. `learn_audit_manifest()` lists every piece Qualiopi expects for one
-- session and says plainly which are missing, because a manifest that hides a gap is worse
-- than no manifest.
--
-- Two other things land here:
--
--   * **Notifications are rows, not side effects.** A convocation that was "sent" by a
--     function call leaves nothing to show an auditor. Scheduling, sending and failing are
--     all states of a row.
--   * **Signalement (violence, harcèlement, discrimination)** — new in V10 indicator 12,
--     required from 1 November 2026. It is deliberately the most restricted table here:
--     a report about a formateur must not be readable by that formateur, so visibility is
--     admin-only and does not follow the session scope everything else uses.

begin;

-- ----------------------------------------------------------------- notifications

create table if not exists learn_notifications (
  id            uuid primary key default gen_random_uuid(),
  profile_id    uuid references learn_profiles(id) on delete cascade,
  email         text,
  kind          text not null,                    -- convocation, rappel, relance…
  channel       text not null default 'email' check (channel in ('email','sms','in_app')),
  subject       text not null,
  body          text,
  related_kind  text,
  related_id    uuid,
  scheduled_for timestamptz not null default now(),
  status        text not null default 'brouillon'
                  check (status in ('brouillon','planifie','envoye','echec','annule')),
  -- Anything leaving in the organisme's name is approved by a human first. The agent
  -- drafts; it does not send.
  approved_by   uuid references learn_profiles(id) on delete set null,
  approved_at   timestamptz,
  sent_at       timestamptz,
  error         text,
  created_at    timestamptz not null default now(),
  constraint learn_notif_sent_needs_approval
    check (status <> 'envoye' or approved_at is not null)
);
select learn_tenant_table('learn_notifications');
create index if not exists learn_notif_sched_idx on learn_notifications (status, scheduled_for);

-- ----------------------------------------------------------------- signalement (V10 ind. 12)

create table if not exists learn_signalements (
  id           uuid primary key default gen_random_uuid(),
  session_id   uuid references learn_sessions(id) on delete set null,
  reported_by  uuid references learn_profiles(id) on delete set null,
  anonymous    boolean not null default false,
  category     text not null
                 check (category in ('violence','harcelement','discrimination','autre')),
  body         text not null,
  status       text not null default 'recu'
                 check (status in ('recu','en_cours','traite','classe')),
  handled_by   uuid references learn_profiles(id) on delete set null,
  handled_at   timestamptz,
  outcome      text,
  received_at  timestamptz not null default now(),
  constraint learn_signal_closed
    check (status not in ('traite','classe') or (handled_at is not null and outcome is not null))
);
select learn_tenant_table('learn_signalements');

-- ----------------------------------------------------------------- audit export
--
-- Every piece Qualiopi expects for one session, present or not. The `missing` rows are the
-- point: they are the finding an auditor would have made, surfaced early enough to fix.

create or replace function learn_audit_manifest(p_session uuid)
returns table (piece text, indicator text, present boolean, detail text)
language sql stable security definer set search_path = public as $$
  with s as (select * from learn_sessions where id = p_session)
  select 'Convention ou contrat', 'ind. 9', exists(
      select 1 from learn_documents d where d.session_id = p_session
        and d.kind in ('convention','contrat')),
    'personne morale : convention ; personne physique : contrat'
  union all
  select 'Programme de formation', 'ind. 5-6', exists(
      select 1 from learn_programs pr join s on s.program_id = pr.id),
    (select coalesce('version ' || pr.version || ', revu le ' ||
            coalesce(pr.last_reviewed_at::text, 'jamais'), 'absent')
       from learn_programs pr join s on s.program_id = pr.id)
  union all
  select 'Convocations', 'ind. 9', exists(
      select 1 from learn_notifications n where n.related_id = p_session and n.kind = 'convocation'),
    'informer des conditions de déroulement'
  union all
  select 'Règlement intérieur', 'ind. 9', exists(
      select 1 from learn_documents d where d.session_id = p_session
        and d.kind = 'reglement_interieur'), null
  union all
  select 'Feuilles d''émargement', 'ind. 10', (
      select count(*) > 0 from learn_attendance_signatures a
        join learn_session_slots sl on sl.id = a.slot_id where sl.session_id = p_session),
    (select count(*)::text || ' signature(s)' from learn_attendance_signatures a
       join learn_session_slots sl on sl.id = a.slot_id where sl.session_id = p_session)
  union all
  select 'Positionnement à l''entrée', 'ind. 8', exists(
      select 1 from learn_attempts at join learn_assessments asm on asm.id = at.assessment_id
       where at.session_id = p_session and asm.kind = 'positionnement'),
    'cause fréquente d''écart en audit'
  union all
  select 'Évaluation des acquis', 'ind. 11', exists(
      select 1 from learn_attempts at join learn_assessments asm on asm.id = at.assessment_id
       where at.session_id = p_session and asm.kind in ('acquis_entree','acquis_sortie')), null
  union all
  select 'Appréciations recueillies', 'ind. 30', exists(
      select 1 from learn_survey_responses r
        join learn_survey_campaigns c on c.id = r.campaign_id where c.session_id = p_session),
    'indicateur le plus fréquemment en écart'
  union all
  select 'Réclamations traitées', 'ind. 31', not exists(
      select 1 from learn_reclamations rc where rc.session_id = p_session
        and rc.status in ('ouverte','en_cours')),
    (select coalesce(count(*)::text || ' ouverte(s)', '0')
       from learn_reclamations rc where rc.session_id = p_session and rc.status in ('ouverte','en_cours'))
  union all
  select 'Certificats de réalisation', 'ind. 11', exists(
      select 1 from learn_documents d where d.session_id = p_session and d.kind = 'certificat'),
    'remis obligatoirement en fin d''action'
$$;

-- ----------------------------------------------------------------- dashboards

create or replace view learn_dashboard
  with (security_invoker = true) as
select
  t.id as tenant_id,
  (select count(*) from learn_sessions s
    where s.tenant_id = t.id and s.status in ('planned','running'))        as sessions_actives,
  (select count(*) from learn_session_slots sl
    where sl.tenant_id = t.id and sl.starts_at >= current_date
      and sl.starts_at < current_date + 7)                                 as creneaux_semaine,
  (select count(*) from learn_enrollments e
    where e.tenant_id = t.id and e.status in ('inscrit','confirme'))       as inscrits,
  (select count(*) from learn_reclamations rc
    where rc.tenant_id = t.id and rc.status in ('ouverte','en_cours'))     as reclamations_ouvertes,
  (select count(*) from learn_improvement_actions a
    where a.tenant_id = t.id and a.status in ('ouverte','en_cours'))       as actions_ouvertes,
  (select count(*) from learn_attempts at
    where at.tenant_id = t.id and at.review_status = 'pending')            as copies_a_corriger,
  (select count(*) from learn_at_risk ar
    where ar.tenant_id = t.id and ar.reason <> 'actif')                    as apprenants_a_risque,
  (select count(*) from learn_programs pr
    where pr.tenant_id = t.id and pr.next_review_due < current_date)       as programmes_a_reviser,
  (select count(*) from learn_vault_retention v
    where v.tenant_id = t.id and v.purgeable)                              as pieces_purgeables
from learn_tenants t;

-- ----------------------------------------------------------------- policies

create policy learn_notif_read on learn_notifications for select
  using (profile_id = learn_current_user_id()
         or learn_current_role() in ('admin','auditeur') or learn_is_platform());
create policy learn_notif_write on learn_notifications for all
  using (learn_current_role() = 'admin' or learn_is_platform())
  with check (learn_current_role() = 'admin' or learn_is_platform());

-- Deliberately narrower than everything else: a report about a formateur must not be
-- visible to that formateur, so this does not follow the session scope.
create policy learn_signal_read on learn_signalements for select
  using (learn_current_role() = 'admin' or learn_is_platform()
         or (reported_by = learn_current_user_id() and not anonymous));
create policy learn_signal_insert on learn_signalements for insert with check (true);
create policy learn_signal_update on learn_signalements for update
  using (learn_current_role() = 'admin' or learn_is_platform())
  with check (learn_current_role() = 'admin' or learn_is_platform());

grant select on learn_dashboard to learn_app, learn_readonly;
grant select, insert, update, delete on learn_notifications, learn_signalements to learn_app;
grant select on learn_notifications, learn_signalements to learn_readonly;

commit;
