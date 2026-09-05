"""Postgres access for LEARN — isolation enforced by the database, not by this file.

Deliberate departure from `winny_gateway.db`, which talks PostgREST with the service_role
key. That key *bypasses* RLS, so isolation there lives entirely in application code and
`_scope_ok` is the compensating control. For a product sold to competing organisations,
"can another organisme see my data?" has to be answerable with a passing test rather than
a paragraph — so LEARN connects as an unprivileged role and lets Postgres enforce it.

Every request runs in one transaction that opens by SET LOCAL-ing the session context the
RLS policies read. SET LOCAL is transaction-scoped, so context cannot leak to the next
request that borrows the same pooled connection.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import HTTPException

from .roles import Actor

# asyncpg is imported lazily inside pool(). This module is imported by the gateway at
# boot; a missing driver or an unset DSN must degrade LEARN, never stop VIGIL starting.
asyncpg = None  # type: ignore[assignment]

_pool = None


async def pool():
    global _pool, asyncpg
    if asyncpg is None:
        import asyncpg as _pg  # noqa: PLC0415
        asyncpg = _pg
    if _pool is None:
        dsn = os.environ.get("LEARN_DATABASE_URL")
        if not dsn:
            raise RuntimeError("LEARN_DATABASE_URL is not set")
        _pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=int(os.getenv("LEARN_DB_POOL_MIN", "1")),
            max_size=int(os.getenv("LEARN_DB_POOL_MAX", "10")),
            command_timeout=float(os.getenv("LEARN_DB_TIMEOUT", "20")),
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def scoped(actor: Actor) -> AsyncIterator[Any]:
    """Open a transaction with this actor's context applied.

    `set_config(..., is_local => true)` is the parameterised form of SET LOCAL. SET LOCAL
    itself takes no bind parameters, and interpolating a tenant id into SQL is precisely
    the injection this is meant to make impossible.
    """
    p = await pool()
    async with p.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                select set_config('learn.user_id',    $1, true),
                       set_config('learn.role',       $2, true),
                       set_config('learn.tenant_id',  $3, true),
                       set_config('learn.company_id', $4, true),
                       set_config('learn.principal',  $5, true)
                """,
                actor.user_id,
                actor.role,
                actor.tenant_id or "",
                actor.company_id or "",
                actor.principal,
            )
            # EVERY request drops out of the connecting role before touching data.
            # Supabase connects as `postgres`, a SUPERUSER — and superusers bypass RLS
            # entirely, `force row level security` notwithstanding. Without this line the
            # policies are inert and a cross-tenant read succeeds. Found the hard way in
            # Phase 0: the read returned another tenant's rows while the equivalent write
            # was caught only because triggers still fire for superusers.
            #
            # Read-only actors additionally land in a role holding no write grant, so a
            # future table that forgets its WITH CHECK still cannot be written by an
            # auditeur.
            await conn.execute(
                "set local role learn_readonly" if actor.read_only else "set local role learn_app"
            )
            yield conn


@asynccontextmanager
async def bootstrap() -> AsyncIterator[Any]:
    """Migrations and tenant provisioning only — opts past the hierarchy trigger.

    Never reachable from a request path: nothing under `learn/routes/` imports this.
    """
    p = await pool()
    async with p.acquire() as conn:
        async with conn.transaction():
            await conn.execute("select set_config('learn.bootstrap', 'on', true)")
            yield conn


# --------------------------------------------------------------------------- guard

# Ported from `winny_gateway.db._scope_ok_*`, re-keyed from user_id to tenant_id. RLS
# already blocks a cross-tenant read; this catches the *other* failure — a query that
# forgot to filter and would hand a formateur the whole tenant — and turns a silent bug
# into a loud one.

TENANT_SCOPED = frozenset({
    "learn_companies", "learn_profiles", "learn_programs", "learn_sessions",
    "learn_session_slots", "learn_enrollments", "learn_resources",
    "learn_attendance_signatures", "learn_absences", "learn_courses", "learn_modules",
    "learn_lessons", "learn_lesson_progress", "learn_documents", "learn_doc_templates",
    "learn_vault_objects", "learn_access_log", "learn_evaluations", "learn_reclamations",
})


class UnscopedQuery(RuntimeError):
    """A query on a tenant-scoped table carried no scope filter."""


def assert_scoped(table: str, filters: dict[str, Any] | None) -> None:
    if table not in TENANT_SCOPED:
        return
    if filters and any(k in filters for k in ("tenant_id", "id")):
        return
    raise UnscopedQuery(
        f"query on {table!r} has no tenant_id or id filter. RLS still holds the tenant "
        "boundary, but this query is a bug and would over-fetch inside the tenant."
    )


def available() -> bool:
    """True when LEARN can reach a database. The router checks this before serving."""
    if not os.environ.get("LEARN_DATABASE_URL"):
        return False
    try:
        import asyncpg  # noqa: F401,PLC0415
    except ImportError:
        return False
    return True


def translate(exc: Exception) -> HTTPException:
    """Turn a Postgres error into the HTTP answer the client should get.

    The database is the authority on these rules, so its refusals are translated rather
    than re-checked: an exclusion violation is a real 409 naming a real conflict, and a
    42501 is the policy layer saying no.
    """
    sqlstate = getattr(exc, "sqlstate", None)
    detail = str(getattr(exc, "detail", "") or exc)
    if sqlstate == "23P01":  # exclusion_violation — double booking
        return HTTPException(409, {"error": "slot_conflict", "detail": detail})
    if sqlstate == "42501":  # insufficient_privilege — trigger or policy refused
        return HTTPException(403, {"error": "not_permitted", "detail": detail})
    if sqlstate == "23505":
        return HTTPException(409, {"error": "already_exists", "detail": detail})
    if sqlstate == "23503":
        return HTTPException(422, {"error": "unknown_reference", "detail": detail})
    if sqlstate == "23514":
        return HTTPException(422, {"error": "invalid_value", "detail": detail})
    return HTTPException(500, {"error": "database_error"})
