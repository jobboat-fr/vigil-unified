-- LEARN — 0006 — schema-qualify digest().
--
-- pgcrypto lives in `extensions` on Supabase, not `public`. Our SECURITY DEFINER functions
-- pin search_path for safety, which correctly excluded it — so digest() resolved nowhere
-- and every signature insert failed. Qualifying the call is the fix; widening search_path
-- on a definer function would not be.

begin;

create or replace function learn_chain_attendance() returns trigger
language plpgsql as $fn$
declare
  v_prev  char(64);
  v_seq   bigint;
  v_body  text;
begin
  -- FOR UPDATE on the tail serialises concurrent signers. Without it two inserts in the
  -- same instant read the same prev_hash and the chain forks silently.
  select s.this_hash, s.seq_no into v_prev, v_seq
    from learn_attendance_signatures s
   where s.tenant_id = new.tenant_id
   order by s.seq_no desc
   limit 1
     for update;

  new.seq_no    := coalesce(v_seq, 0) + 1;
  new.prev_hash := coalesce(v_prev, repeat('0', 64));   -- genesis

  -- jsonb orders its keys, so this serialisation is stable across rebuilds. seq_no is
  -- deliberately excluded: prev_hash already proves ordering, and leaving the number out
  -- keeps a hash verifiable after a dump and restore.
  v_body := (jsonb_build_object(
      'slot',      new.slot_id,
      'profile',   new.profile_id,
      'role',      new.signer_role,
      'kind',      new.kind,
      'signed_at', to_char(new.signed_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.USZ'),
      'evidence',  new.evidence,
      'prev',      new.prev_hash
  ))::text;

  new.this_hash := encode(extensions.digest(v_body, 'sha256'), 'hex');
  return new;
end
$fn$;

create or replace function learn_verify_attendance_chain(p_tenant uuid default null)
returns table (checked bigint, valid boolean, first_broken_seq bigint, reason text)
language plpgsql stable security definer set search_path = public, extensions as $fn$
declare
  r        record;
  v_prev   char(64) := repeat('0', 64);
  v_body   text;
  v_calc   char(64);
  v_count  bigint := 0;
  v_tenant uuid := coalesce(p_tenant, learn_current_tenant());
begin
  for r in
    select * from learn_attendance_signatures
     where tenant_id = v_tenant order by seq_no
  loop
    v_count := v_count + 1;
    if r.prev_hash <> v_prev then
      return query select v_count, false, r.seq_no, 'prev_hash_mismatch'::text;
      return;
    end if;
    v_body := (jsonb_build_object(
        'slot', r.slot_id, 'profile', r.profile_id, 'role', r.signer_role,
        'kind', r.kind,
        'signed_at', to_char(r.signed_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.USZ'),
        'evidence', r.evidence, 'prev', r.prev_hash))::text;
    v_calc := encode(extensions.digest(v_body, 'sha256'), 'hex');
    if v_calc <> r.this_hash then
      return query select v_count, false, r.seq_no, 'content_altered'::text;
      return;
    end if;
    v_prev := r.this_hash;
  end loop;
  return query select v_count, true, null::bigint, 'intact'::text;
end
$fn$;

commit;
