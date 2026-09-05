-- Drive the whole tunnel against the real database, then roll it back.
--
-- Everything the API tests can only assert about the *shape* of a call is decided here: the
-- policies, the grants, the throttle, the definer boundary. Ends in ROLLBACK, so it can be
-- run against a live project without leaving a row behind.

begin;

create temp table r (step text, result text) on commit drop;
-- The scratch pad has to be writable from inside `learn_public`, or the failure we record
-- would be the recording itself.
grant all on r to public;

-- ---------------------------------------------------------------- fixtures
set local learn.bootstrap = 'on';
set local learn.role = 'super_admin';

do $$
declare
  t_a uuid; t_b uuid; adm uuid := gen_random_uuid(); prog uuid; sess uuid;
  asmt uuid; q1 uuid; q2 uuid;
begin
  insert into learn_tenants(slug, name) values ('vf-a', 'Organisme A') returning id into t_a;
  insert into learn_tenants(slug, name) values ('vf-b', 'Organisme B') returning id into t_b;
  insert into learn_profiles(id, tenant_id, role, email, full_name)
    values (adm, t_a, 'admin', 'admin@vf-a.test', 'Admin A');

  insert into learn_programs(tenant_id, title, duration_hours, published)
    values (t_a, 'Bureautique — socle', 21, true) returning id into prog;
  insert into learn_sessions(tenant_id, program_id, code, starts_on, ends_on, status)
    values (t_a, prog, 'VF-2026-01', current_date + 30, current_date + 32, 'planned')
    returning id into sess;

  insert into learn_questions(tenant_id, program_id, kind, prompt, options, correct, points)
    values (t_a, prog, 'qcm', 'Un tableur sert à…',
            '[{"key":"a","label":"calculer"},{"key":"b","label":"dessiner"}]'::jsonb,
            '["a"]'::jsonb, 10) returning id into q1;
  insert into learn_questions(tenant_id, program_id, kind, prompt, options, correct, points)
    values (t_a, prog, 'qcm', 'Une formule commence par…',
            '[{"key":"a","label":"#"},{"key":"b","label":"="}]'::jsonb,
            '["b"]'::jsonb, 10) returning id into q2;

  insert into learn_assessments(tenant_id, program_id, title, kind, question_ids,
                                level_thresholds, active)
    values (t_a, prog, 'Positionnement bureautique', 'positionnement',
            array[q1, q2],
            '{"debutant":0,"intermediaire":10,"avance":20}'::jsonb, true)
    returning id into asmt;

  insert into r values ('fixtures', 'tenant A=' || t_a || ' session=' || sess);
  perform set_config('vf.t_a', t_a::text, true);
  perform set_config('vf.t_b', t_b::text, true);
  perform set_config('vf.adm', adm::text, true);
  perform set_config('vf.sess', sess::text, true);
  perform set_config('vf.prog', prog::text, true);
end $$;

reset learn.bootstrap;

-- ---------------------------------------------------------------- 1. the prospect submits
set local learn.role = 'prospect';
set local learn.user_id = '';
select set_config('learn.tenant_id', current_setting('vf.t_a'), true);
set local role learn_public;

do $$
declare made boolean;
begin
  made := learn_submit_lead(
    current_setting('vf.t_a')::uuid, 'Nadia Cherif', 'n@delta-log.fr',
    'consentement affiché', null, 'Delta Logistique', 'Je souhaite une place',
    current_setting('vf.prog')::uuid, null, 'linkedin-2026', 'https://hbs-formation.fr',
    '203.0.113.9');
  insert into r values ('1 submit as learn_public',
    case when made then 'demande créée, id non divulgué ✓' else 'aucune création' end);
end $$;

-- ---------------------------------------------------------------- 2. what it may NOT do
do $$
declare n int;
begin
  begin
    select count(*) into n from learn_leads;
    insert into r values ('2a select learn_leads', 'LEAK — ' || n || ' rows readable');
  exception when insufficient_privilege then
    insert into r values ('2a select learn_leads', 'refusé (permission denied) ✓');
  end;

  begin
    update learn_leads set status = 'convertie';
    insert into r values ('2b self-promote to convertie', 'LEAK — update succeeded');
  exception when insufficient_privilege then
    insert into r values ('2b self-promote to convertie', 'refusé (permission denied) ✓');
  end;

  begin
    insert into learn_profiles(id, tenant_id, role, email)
      values (gen_random_uuid(), current_setting('vf.t_a')::uuid, 'admin', 'me@evil.test');
    insert into r values ('2c mint an account', 'LEAK — profile created');
  exception when insufficient_privilege then
    insert into r values ('2c mint an account', 'refusé (permission denied) ✓');
  end;

  begin
    insert into learn_leads(tenant_id, full_name, email, consent_text)
      values (current_setting('vf.t_b')::uuid, 'X', 'x@b.test', 'c');
    insert into r values ('2d write into tenant B', 'LEAK — cross-tenant insert succeeded');
  exception
    when insufficient_privilege then
      insert into r values ('2d write into tenant B', 'refusé (permission denied) ✓');
    when others then
      insert into r values ('2d write into tenant B', 'refusé (' || sqlstate || ') ✓');
  end;

  -- Nested, not handled at the block level: a plpgsql exception handler rolls back to the
  -- start of its own block, which would discard every row recorded above it.
  begin
    select count(*) into n from learn_reclamations;
    insert into r values ('2e réclamations untouched',
                          n || ' réclamation(s) — une demande n''en est pas une');
  exception when insufficient_privilege then
    insert into r values ('2e réclamations untouched', 'illisible pour un prospect ✓');
  end;
end $$;

-- ---------------------------------------------------------------- 3. dedupe + throttle
do $$
declare b boolean; ok boolean; i int;
begin
  -- Same address, same programme, different capitalisation. Must not create a second row,
  -- and must not tell an unauthenticated caller the id of the first.
  b := learn_submit_lead(current_setting('vf.t_a')::uuid, 'Nadia Cherif', 'N@Delta-Log.fr',
                         'consentement affiché', null, null, null,
                         current_setting('vf.prog')::uuid, null, null, null, '203.0.113.9');
  insert into r values ('3a double submit',
    case when b then 'DOUBLON créé' else 'aucune seconde demande ✓' end);

  for i in 1..6 loop
    ok := learn_public_throttle('vf-test-bucket', 3600, 5);
  end loop;
  insert into r values ('3b throttle after 6 hits',
    case when ok then 'PASSÉ — la limite ne tient pas' else 'bloqué ✓' end);
end $$;

-- ---------------------------------------------------------------- 4. the positioning test
reset role;
set local learn.role = 'admin';
select set_config('learn.user_id', current_setting('vf.adm'), true);
set local role learn_app;

do $$
declare tok text; v_lead uuid;
begin
  select id into v_lead from learn_leads
   where tenant_id = current_setting('vf.t_a')::uuid and lower(email) = 'n@delta-log.fr';
  perform set_config('vf.lead', v_lead::text, true);
  insert into r values ('4a0 id resolved by admin', 'demande ' || v_lead);
  tok := learn_lead_token_issue(v_lead);
  perform set_config('vf.tok', tok, true);
  insert into r values ('4a token issued', 'longueur ' || length(tok) ||
    ', stocké en clair: ' ||
    (select count(*)::text from learn_lead_tokens where token_sha::text like '%' || tok || '%'));
end $$;

reset role;
set local learn.role = 'prospect';
set local learn.user_id = '';
set local role learn_public;

do $$
declare paper record; graded record; leaked int;
begin
  select * into paper from learn_positioning_for_lead(current_setting('vf.tok'));
  insert into r values ('4b paper served',
    paper.title || ' — ' || jsonb_array_length(paper.questions) || ' questions');

  select count(*) into leaked
    from jsonb_array_elements(paper.questions) q
   where q ? 'correct' or q ? 'why_correct';
  insert into r values ('4c answers withheld',
    case when leaked = 0 then 'aucune réponse servie ✓' else 'FUITE — ' || leaked end);

  begin
    perform 1 from learn_questions limit 1;
    insert into r values ('4d read learn_questions directly', 'LEAK — readable');
  exception when insufficient_privilege then
    insert into r values ('4d read learn_questions directly', 'refusé ✓');
  end;

  select * into graded from learn_grade_positioning(
    current_setting('vf.tok'),
    ('[{"question_id":"' || (paper.questions -> 0 ->> 'id') ||
      '","given":["a"]},{"question_id":"' || (paper.questions -> 1 ->> 'id') ||
      '","given":["b"]}]')::jsonb);
  insert into r values ('4e graded',
    graded.score || '/' || graded.max_score || ' → ' || coalesce(graded.level, 'null'));

  begin
    perform learn_grade_positioning(current_setting('vf.tok'), '[]'::jsonb);
    insert into r values ('4f reuse the same link', 'LEAK — token rejouable');
  exception when others then
    insert into r values ('4f reuse the same link', 'refusé (' || sqlstate || ') ✓');
  end;
end $$;

-- ---------------------------------------------------------------- 5. the conversion
reset role;
set local learn.role = 'admin';
select set_config('learn.user_id', current_setting('vf.adm'), true);
select set_config('learn.tenant_id', current_setting('vf.t_a'), true);
set local role learn_app;

do $$
declare got record; again record; uid uuid := gen_random_uuid();
begin
  select * into got from learn_convert_lead(
    current_setting('vf.lead')::uuid, current_setting('vf.sess')::uuid, uid, null);
  insert into r values ('5a converted',
    'profil ' || got.profile_id || ' · inscription ' || got.enrollment_id);

  select * into again from learn_convert_lead(
    current_setting('vf.lead')::uuid, current_setting('vf.sess')::uuid, uid, null);
  insert into r values ('5b converted twice',
    case when again.enrollment_id = got.enrollment_id
         then 'idempotent — même inscription ✓'
         else 'DOUBLON: ' || again.enrollment_id end);

  insert into r
    select '5c niveau reporté', 'inscription.level = ' || coalesce(e.level, 'null')
      from learn_enrollments e where e.id = got.enrollment_id;

  insert into r
    select '5d journal', count(*) || ' étapes: ' || string_agg(event, ' → ' order by at)
      from learn_lead_events where lead_id = current_setting('vf.lead')::uuid;

  begin
    update learn_lead_events set event = 'recue'
     where lead_id = current_setting('vf.lead')::uuid;
    insert into r values ('5e rewrite the journal', 'LEAK — update succeeded');
  exception when insufficient_privilege then
    insert into r values ('5e rewrite the journal', 'refusé (append-only) ✓');
  end;
end $$;

-- ---------------------------------------------------------------- 6. cross-tenant read
reset role;
set local learn.role = 'prospect';
select set_config('learn.tenant_id', current_setting('vf.t_b'), true);
set local role learn_public;

do $$
declare n int;
begin
  select count(*) into n from learn_programs;
  insert into r values ('6 tenant B sees A''s catalogue',
    n || ' programme(s) visible(s) — attendu 0');
end $$;

reset role;
select * from r order by step;

rollback;
