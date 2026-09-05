"""The isolation guard — the test that has to pass before a second organisme exists.

This is not only a regression test. When a prospect asks "can another organisme see my
data?", a passing run of this file is the answer; a paragraph is not. Keep it runnable
against a real database and keep its output presentable.

Run:  LEARN_DATABASE_URL=postgres://... pytest learn/tests/test_isolation.py -v
Skips cleanly when LEARN_DATABASE_URL is unset, so CI without a database stays green.
"""

from __future__ import annotations

import os
import uuid

import pytest

pytest.importorskip("asyncpg")
import asyncpg  # noqa: E402

DSN = os.environ.get("LEARN_DATABASE_URL")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not DSN, reason="LEARN_DATABASE_URL not set"),
]


async def _ctx(conn, *, role, tenant=None, company=None, principal="human", user=None):
    await conn.execute(
        """
        select set_config('learn.user_id',    $1, true),
               set_config('learn.role',       $2, true),
               set_config('learn.tenant_id',  $3, true),
               set_config('learn.company_id', $4, true),
               set_config('learn.principal',  $5, true)
        """,
        str(user or uuid.uuid4()), role, str(tenant or ""), str(company or ""), principal,
    )


@pytest.fixture
async def conn():
    c = await asyncpg.connect(DSN)
    try:
        yield c
    finally:
        await c.close()


@pytest.fixture
async def two_tenants(conn):
    """Two organismes with one admin each, created through the bootstrap path."""
    tr = conn.transaction()
    await tr.start()
    await conn.execute("select set_config('learn.bootstrap','on',true)")
    a = await conn.fetchval(
        "insert into learn_tenants(slug,name) values($1,$2) returning id",
        f"t-a-{uuid.uuid4().hex[:8]}", "Organisme A")
    b = await conn.fetchval(
        "insert into learn_tenants(slug,name) values($1,$2) returning id",
        f"t-b-{uuid.uuid4().hex[:8]}", "Organisme B")
    ua, ub = uuid.uuid4(), uuid.uuid4()
    for uid, tid, mail in ((ua, a, "admin@a.test"), (ub, b, "admin@b.test")):
        await conn.execute(
            "insert into learn_profiles(id,tenant_id,role,email) values($1,$2,'admin',$3)",
            uid, tid, mail)
    yield {"a": a, "b": b, "ua": ua, "ub": ub}
    await tr.rollback()


# --------------------------------------------------------------- the catalogue

async def test_seven_roles_seeded(conn):
    """Six people plus `prospect` — the visitor in the public tunnel (0016).

    `prospect` is a role rather than a special case inside a policy so that "what may an
    unauthenticated visitor do?" is answered by `learn_capabilities`, where every other
    role's answer already lives.
    """
    rows = await conn.fetch("select role, level, is_read_only from learn_roles order by level")
    assert [r["role"] for r in rows] == [
        "super_admin", "admin", "formateur", "entreprise", "auditeur", "apprenant",
        "prospect"]
    assert [r["role"] for r in rows if r["is_read_only"]] == ["auditeur"]


async def test_a_prospect_holds_exactly_three_capabilities(conn):
    """The public surface is the whole reason to check this one by name."""
    rows = await conn.fetch(
        "select resource, action from learn_capabilities where role='prospect' "
        "order by resource, action")
    assert [(r["resource"], r["action"]) for r in rows] == [
        ("lead", "create"), ("positionnement", "create"), ("program", "read")]


async def test_only_two_roles_may_sign(conn):
    rows = await conn.fetch(
        "select role from learn_capabilities where resource='attendance' and action='sign' order by role")
    assert [r["role"] for r in rows] == ["apprenant", "formateur"], (
        "only the person present and the person teaching may attest presence")


# --------------------------------------------------------------- the tenant floor

async def test_admin_of_a_cannot_see_tenant_b(conn, two_tenants):
    t = two_tenants
    await _ctx(conn, role="admin", tenant=t["a"], user=t["ua"])
    seen = await conn.fetch("select tenant_id from learn_profiles")
    assert seen, "admin A must see its own tenant"
    assert all(r["tenant_id"] == t["a"] for r in seen)
    assert not any(r["tenant_id"] == t["b"] for r in seen)


async def test_admin_of_a_cannot_write_into_tenant_b(conn, two_tenants):
    t = two_tenants
    await _ctx(conn, role="admin", tenant=t["a"], user=t["ua"])
    with pytest.raises(asyncpg.PostgresError):
        await conn.execute(
            "insert into learn_profiles(id,tenant_id,role,email) values($1,$2,'apprenant',$3)",
            uuid.uuid4(), t["b"], "intruder@b.test")


async def test_no_session_context_sees_nothing(conn, two_tenants):
    await _ctx(conn, role="anonymous")
    rows = await conn.fetch("select 1 from learn_profiles")
    assert rows == [], "an unset context must match no tenant"


# --------------------------------------------------------------- the read-only floor

async def test_auditeur_cannot_write(conn, two_tenants):
    t = two_tenants
    await _ctx(conn, role="auditeur", tenant=t["a"])
    with pytest.raises(asyncpg.PostgresError):
        await conn.execute(
            "insert into learn_profiles(id,tenant_id,role,email) values($1,$2,'apprenant',$3)",
            uuid.uuid4(), t["a"], "x@a.test")


# --------------------------------------------------------------- the hierarchy

async def test_auditeur_cannot_create_a_learner_despite_higher_level(conn, two_tenants):
    """The bug a level-only rule would have shipped: auditeur (4) outranks apprenant (5)."""
    t = two_tenants
    await _ctx(conn, role="auditeur", tenant=t["a"])
    with pytest.raises(asyncpg.PostgresError):
        await conn.execute(
            "insert into learn_profiles(id,tenant_id,role,email) values($1,$2,'apprenant',$3)",
            uuid.uuid4(), t["a"], "learner@a.test")


async def test_admin_cannot_mint_a_super_admin(conn, two_tenants):
    t = two_tenants
    await _ctx(conn, role="admin", tenant=t["a"], user=t["ua"])
    with pytest.raises(asyncpg.PostgresError):
        await conn.execute(
            "insert into learn_profiles(id,tenant_id,role,email) values($1,null,'super_admin',$2)",
            uuid.uuid4(), "escalation@a.test")


# --------------------------------------------------------------- the CI guard

async def test_every_learn_table_is_protected(conn):
    """Fails the build if any learn_% table has RLS off or carries no policy.

    This is the mitigation for hand-rolled multi-tenancy: a table created without going
    through learn_tenant_table() shows up here rather than in a customer's data.
    """
    exempt = {"learn_roles", "learn_capabilities"}  # reference data, readable by all
    rows = await conn.fetch(
        """
        select c.relname            as table_name,
               c.relrowsecurity     as rls_on,
               c.relforcerowsecurity as rls_forced,
               (select count(*) from pg_policies p
                 where p.schemaname='public' and p.tablename=c.relname) as policies
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname='public' and c.relkind='r' and c.relname like 'learn\\_%'
         order by c.relname
        """
    )
    assert rows, "no learn_ tables found — has the migration run?"
    offenders = [
        dict(r) for r in rows
        if r["table_name"] not in exempt
        and (not r["rls_on"] or not r["rls_forced"] or r["policies"] == 0)
    ]
    assert not offenders, f"tables without an enforced tenant policy: {offenders}"
