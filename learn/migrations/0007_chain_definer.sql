-- LEARN — 0007 — the chaining trigger runs as its owner.
--
-- 0006 qualified digest() as extensions.digest(), which resolved the name but not the
-- privilege: the trigger executes as the *caller*, and `learn_app` has no USAGE on the
-- `extensions` schema. So every signature still failed.
--
-- Two ways out. Granting `learn_app` usage on `extensions` would work and would also hand
-- the application role a crypto toolkit it has no other reason to hold. Making the trigger
-- SECURITY DEFINER is tighter: the hash is computed by the owner, and the app role can
-- neither reach digest() nor be tricked into calling it directly. search_path is pinned,
-- which is the precaution a definer function always needs.

begin;

create or replace function learn_chain_attendance() returns trigger
language plpgsql
security definer
set search_path = public, extensions
as $fn$
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

  new.this_hash := encode(digest(v_body, 'sha256'), 'hex');
  return new;
end
$fn$;

commit;
