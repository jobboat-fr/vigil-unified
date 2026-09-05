-- LEARN — 0008 — make append-only a privilege, not only a policy.
--
-- `learn_append_only()` revoked UPDATE and DELETE from `public`. That misses the roles the
-- application actually connects as: 0003's `alter default privileges` grants the full set
-- on every new table to `learn_app`, so the evidence table was created holding UPDATE and
-- DELETE for the app role.
--
-- The restrictive policies did hold — an update touched zero rows and the chain verified
-- intact afterwards. But it was a silent no-op rather than a refusal, which is the wrong
-- shape twice over: an application cannot tell the user the attempt was rejected, and the
-- table's protection rested on one layer instead of two.
--
-- Revoking from the named roles makes the attempt a hard `permission denied`, with the
-- policies still underneath it.

begin;

create or replace function learn_append_only(p_table regclass) returns void
language plpgsql as $fn$
declare t text := p_table::text;
begin
  -- Policies: nothing is visible to update or delete, for anyone, including super_admin.
  if not exists (select 1 from pg_policies
                  where schemaname='public' and tablename=p_table::text
                    and policyname='learn_no_update') then
    execute format($p$create policy learn_no_update on %s as restrictive for update using (false)$p$, t);
  end if;
  if not exists (select 1 from pg_policies
                  where schemaname='public' and tablename=p_table::text
                    and policyname='learn_no_delete') then
    execute format($p$create policy learn_no_delete on %s as restrictive for delete using (false)$p$, t);
  end if;

  -- Privileges: the second layer, and the one that produces a clear error.
  execute format('revoke update, delete on %s from public', t);
  execute format('revoke update, delete on %s from learn_app', t);
  execute format('revoke update, delete on %s from learn_readonly', t);
end
$fn$;

-- Re-apply to the table already created under the old definition.
select learn_append_only('learn_attendance_signatures');

commit;
