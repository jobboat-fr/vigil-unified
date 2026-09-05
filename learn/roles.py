"""Authorization for LEARN — three axes, checked in the API and again in Postgres.

The rule is deliberately *not* "a role may act on anything below its level". Level orders
the hierarchy for display and for minting users; it says nothing about what a role may do
to a resource. Applied naively it produces a real bug: auditeur (level 4) sits above
apprenant (5), so a level-only rule lets a read-only auditor create learners.

So every write is three checks:

  1. capability  — does this role hold (resource, action)?      learn_capabilities
  2. hierarchy   — for user creation, is the target role in     learn_roles.creatable_roles
                   the actor's allowlist?
  3. scope       — same tenant, and for `entreprise`, same company.

All three are mirrored by the `learn_enforce_role_hierarchy` trigger and the RESTRICTIVE
RLS policies in migrations/0001, so a bug here is not exploitable — it is merely a bug.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request, status

from winny_gateway.auth import effective_user, get_current_user

# Mirrors learn_roles. Kept here so the API can fail fast without a round trip; the
# database remains the authority and will reject anything this table would have allowed
# but the policies do not.
ROLES: dict[str, dict[str, Any]] = {
    "super_admin": {"level": 0, "scope": "platform", "read_only": False,
                    "creatable": {"admin", "formateur", "entreprise", "auditeur", "apprenant"}},
    "admin": {"level": 1, "scope": "tenant", "read_only": False,
              "creatable": {"formateur", "entreprise", "auditeur", "apprenant"}},
    "formateur": {"level": 2, "scope": "own_sessions", "read_only": False, "creatable": set()},
    "entreprise": {"level": 3, "scope": "own_company", "read_only": False,
                   "creatable": {"apprenant"}},
    "auditeur": {"level": 4, "scope": "tenant", "read_only": True, "creatable": set()},
    "apprenant": {"level": 5, "scope": "self", "read_only": False, "creatable": set()},
}

# The agent never exceeds the human who invoked it; the ceiling only caps.
AGENT_READ_CEILING = "super_admin"
AGENT_WRITE_CEILING = "admin"

# Actions an agent may never take, whatever its delegator holds. Enforced again by
# learn_no_agent_writes() on the signature tables.
AGENT_FORBIDDEN: set[tuple[str, str]] = {
    ("attendance", "sign"),
    ("profile", "create"),
    ("document", "issue"),
}


@dataclass(frozen=True)
class Actor:
    """Who this request acts as. Built from verified claims, never from request input."""

    user_id: str
    role: str
    tenant_id: str | None = None
    company_id: str | None = None
    principal: str = "human"          # "human" | "agent"
    on_behalf_of: str | None = None   # the delegating user, when principal == "agent"

    @property
    def level(self) -> int:
        return ROLES.get(self.role, {}).get("level", 99)

    @property
    def scope(self) -> str:
        return ROLES.get(self.role, {}).get("scope", "self")

    @property
    def read_only(self) -> bool:
        # Unknown role => read-only. Fail closed.
        return ROLES.get(self.role, {}).get("read_only", True)


class Capabilities:
    """(role, resource, action) grants, loaded from learn_capabilities.

    Anything absent is denied. Held in memory because it changes at deploy time, not at
    request time; `refresh()` reloads it without a restart.
    """

    def __init__(self) -> None:
        self._grants: set[tuple[str, str, str]] = set()
        self._loaded = False

    async def refresh(self, conn: Any) -> None:
        rows = await conn.fetch("select role, resource, action from learn_capabilities")
        self._grants = {(r["role"], r["resource"], r["action"]) for r in rows}
        self._loaded = True

    def allows(self, role: str, resource: str, action: str) -> bool:
        if not self._loaded:
            # Never guess a grant we have not read. Fail closed.
            return False
        return (role, resource, action) in self._grants

    def for_role(self, role: str) -> list[dict[str, str]]:
        return sorted(
            ({"resource": r, "action": a} for (ro, r, a) in self._grants if ro == role),
            key=lambda x: (x["resource"], x["action"]),
        )


CAPS = Capabilities()


def can(actor: Actor, resource: str, action: str) -> bool:
    """The single question every write route asks before touching the database."""
    if actor.read_only and action != "read":
        return False
    if actor.principal == "agent":
        if (resource, action) in AGENT_FORBIDDEN:
            return False
        # The write ceiling caps the agent at admin level; it never grants.
        if action != "read" and ROLES.get(AGENT_WRITE_CEILING, {}).get("level", 99) > actor.level:
            return False
    return CAPS.allows(actor.role, resource, action)


def can_assign_role(actor: Actor, target_role: str) -> bool:
    """User creation: capability, then the explicit allowlist. Level is not the rule."""
    if not can(actor, "profile", "create"):
        return False
    return target_role in ROLES.get(actor.role, {}).get("creatable", set())


def capabilities_for(actor: Actor, resource: str) -> dict[str, bool]:
    """The `_can` block returned alongside every row.

    The front end renders controls from this and never infers them from the role — so the
    rule lives in one place instead of being restated in TypeScript.
    """
    return {
        a: can(actor, resource, a)
        for a in ("create", "read", "update", "delete", "cancel", "sign", "export")
    }


def require(resource: str, action: str):
    """FastAPI dependency: `Depends(require("session", "create"))`."""

    async def _dep(actor: Actor = Depends(current_actor)) -> Actor:
        if not can(actor, resource, action):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=f"capability_missing:{resource}:{action}",
            )
        return actor

    return _dep


async def current_actor(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> Actor:
    """Resolve the request to an Actor.

    Delegation reuses `winny_gateway.auth.effective_user`: a trusted backend authenticating
    with the service token but acting on behalf of a named user. Here that is the agent —
    it borrows the delegator's role and scope, and the ceiling above caps what it may do
    with them.
    """
    eff = effective_user(request, user)
    claims = eff.get("app_metadata") or eff.get("user_metadata") or {}
    role = str(claims.get("learn_role") or eff.get("learn_role") or "").strip()
    if role not in ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="no_learn_role")

    is_agent = bool(request.headers.get("X-Learn-Principal") == "agent" and user.get("service_token"))

    return Actor(
        user_id=str(eff.get("sub") or ""),
        role=role,
        tenant_id=(claims.get("tenant_id") or None),
        company_id=(claims.get("company_id") or None),
        principal="agent" if is_agent else "human",
        on_behalf_of=str(user.get("sub")) if is_agent else None,
    )
