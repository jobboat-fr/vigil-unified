"""Droits des pages métier — la même règle que LEARN, lue dans la même table.

La salle de réunion, le mail, le CRM, l'équipe agentique, la finance et le juridique
sont servis par cette passerelle, mais leurs droits vivent dans ``learn_capabilities``
(migration LEARN 0039). Une seule source : ce que LEARN accorde, la passerelle l'accorde ;
ce qui n'y figure pas est refusé.

Qui agit :
  * un jeton Supabase d'app.vtlvs.com → le rôle est dans ``app_metadata.learn_role`` ;
  * le jeton de service avec un utilisateur délégant (``X-Learn-On-Behalf-Of`` ou
    ``X-WinnyWoo-User-Id``) → un agent agit pour cette personne : on relit son rôle dans
    auth.users, et l'agent ne dépasse jamais ``admin`` en écriture ;
  * le jeton de service seul → l'opérateur (tâches planifiées), plafonné de la même façon.

Tout échoue fermé : rôle inconnu, table illisible, route absente de la carte → refus.

Chaque routeur reçoit ``Depends(guard("<ressource>"))``. L'action se déduit de la méthode
HTTP (GET lire, POST créer, PATCH/PUT modifier, DELETE supprimer), sauf pour les routes
listées dans ``OVERRIDES`` — animer ou rejoindre une salle, lancer un pôle, trier un mail.
Une route marquée ``PUBLIC`` (invitation à une réunion) passe sans contrôle : le jeton de
partage est sa propre preuve.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from winny_gateway.auth import _bearer, get_current_user
from winny_gateway.db import get_admin_client
from winny_gateway.logging import get_logger

logger = get_logger(__name__)

PUBLIC = "public"

ROLE_LEVEL: dict[str, int] = {
    "super_admin": 0, "admin": 1, "formateur": 2, "entreprise": 3,
    "auditeur": 4, "apprenant": 5, "prospect": 6,
}
READ_ONLY_ROLES = {"auditeur"}
AGENT_WRITE_CEILING = "admin"

METHOD_ACTION = {"GET": "read", "HEAD": "read", "POST": "create", "PUT": "update",
                 "PATCH": "update", "DELETE": "delete"}

# (méthode, chemin complet) → action, quand la méthode ne dit pas la vérité.
OVERRIDES: dict[tuple[str, str], str] = {
    # Salle : animer (host) et participer (join).
    ("POST", "/v1/rooms/{room_id}/members"): "host",
    ("POST", "/v1/rooms/{room_id}/import-transcript"): "host",
    ("POST", "/v1/rooms/{room_id}/avatar-session"): "host",
    ("DELETE", "/v1/rooms/{room_id}/avatar-session"): "host",
    ("POST", "/v1/rooms/{room_id}/bring-agent"): "host",
    ("POST", "/v1/rooms/{room_id}/share"): "host",
    ("POST", "/v1/rooms/{room_id}/summarize"): "host",
    ("POST", "/v1/rooms/{room_id}/messages"): "join",
    ("POST", "/v1/rooms/{room_id}/intervention-check"): "join",
    ("POST", "/v1/rooms/{room_id}/livekit-token"): "join",
    ("POST", "/v1/rooms/learn/slots/{slot_id}/join"): "join",
    ("GET", "/v1/rooms/meeting/{share_token}"): PUBLIC,
    ("POST", "/v1/rooms/livekit/webhook"): PUBLIC,  # signé par LiveKit, vérifié dans la route
    ("GET", "/v1/rooms/{room_id}/attendance-check"): "host",
    ("POST", "/v1/rooms/{room_id}/breakouts"): "host",
    ("DELETE", "/v1/rooms/{room_id}/breakouts"): "host",
    ("POST", "/v1/rooms/{room_id}/breakouts/{gid}/join"): "join",
    ("POST", "/v1/rooms/guest/{share_token}/join"): PUBLIC,
    # Studio : le lien public porte sa propre preuve ; partager et affiner modifient l'artefact.
    ("GET", "/v1/artifacts/partage/{token}"): PUBLIC,
    ("POST", "/v1/artifacts/{artifact_id}/shares"): "update",
    ("DELETE", "/v1/artifacts/{artifact_id}/shares/{share_id}"): "update",
    ("POST", "/v1/artifacts/{artifact_id}/link"): "update",
    ("POST", "/v1/artifacts/{artifact_id}/refine"): "update",
    # Mail : synchroniser et trier modifient, ils ne créent rien de nouveau pour l'utilisateur.
    ("POST", "/v1/mail/sync"): "update",
    ("POST", "/v1/mail/messages/{message_id}/triage"): "update",
    # Équipe agentique : lancer, tester, suspendre.
    ("POST", "/v1/ops/departments/{dept_id}/run"): "update",
    ("POST", "/v1/ops/departments/{dept_id}/selftest"): "update",
    ("POST", "/v1/ops/pause-all"): "update",
    ("POST", "/v1/ops/resume-all"): "update",
    # Finance : synchroniser un compte relié.
    ("POST", "/v1/finance/connect/sync"): "update",
}


# ── Les droits, chargés depuis LEARN ─────────────────────────────────────────

class _Grants:
    """(rôle, ressource, action) lus dans learn_capabilities, rechargés toutes les 5 min."""

    TTL = 300.0

    def __init__(self) -> None:
        self._grants: set[tuple[str, str, str]] = set()
        self._loaded_at = 0.0
        self._lock = asyncio.Lock()

    def _fetch(self) -> set[tuple[str, str, str]]:
        rows = get_admin_client().table("learn_capabilities").select("role,resource,action").execute().data
        return {(r["role"], r["resource"], r["action"]) for r in rows or []}

    async def ensure(self) -> None:
        if self._loaded_at and time.monotonic() - self._loaded_at < self.TTL:
            return
        async with self._lock:
            if self._loaded_at and time.monotonic() - self._loaded_at < self.TTL:
                return
            try:
                self._grants = await asyncio.to_thread(self._fetch)
                self._loaded_at = time.monotonic()
            except Exception as exc:  # noqa: BLE001
                logger.error("permissions.load_failed: %s", exc, extra={"component": "permissions"})
                if not self._loaded_at:
                    # Jamais chargés : on ne devine pas un droit. La page affiche l'erreur.
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail={"error": "permissions_unavailable"},
                    ) from exc
                # Déjà chargés : on garde la dernière version connue plutôt que tout couper.

    def allows(self, role: str, resource: str, action: str) -> bool:
        return (role, resource, action) in self._grants

    def for_role(self, role: str) -> dict[str, list[str]]:
        out: dict[str, set[str]] = {}
        for ro, res, act in self._grants:
            if ro == role:
                out.setdefault(res, set()).add(act)
        return {k: sorted(v) for k, v in sorted(out.items())}


GRANTS = _Grants()


# ── Qui agit ─────────────────────────────────────────────────────────────────

_role_cache: dict[str, tuple[float, str | None]] = {}


def _lookup_role(user_id: str) -> str | None:
    res = get_admin_client().auth.admin.get_user_by_id(user_id)
    user = getattr(res, "user", None)
    meta = getattr(user, "app_metadata", None) or {}
    return meta.get("learn_role")


async def _role_of(user_id: str) -> str | None:
    hit = _role_cache.get(user_id)
    if hit and time.monotonic() - hit[0] < 60:
        return hit[1]
    try:
        role = await asyncio.to_thread(_lookup_role, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("permissions.role_lookup_failed: %s", exc, extra={"component": "permissions"})
        role = None
    _role_cache[user_id] = (time.monotonic(), role)
    return role


async def actor_for(request: Request, user: dict[str, Any]) -> dict[str, Any]:
    """{user_id, role, principal} pour cette requête. Jamais tiré du corps de la requête."""
    if user.get("agent_credential"):
        from winny_gateway.agent_identite import role_plafonne

        cred = user["agent_credential"]
        role = await _role_of(str(user.get("sub")))
        return {"user_id": user.get("sub"), "role": role_plafonne(role, cred.get("role_max")) if role else None,
                "principal": "agent", "agent": cred.get("agent"), "lecture_seule": cred.get("lecture_seule")}
    if user.get("service_token"):
        delegant = (
            request.headers.get("X-Learn-On-Behalf-Of")
            or request.headers.get("X-WinnyWoo-User-Id")
            or ""
        ).strip()
        if delegant:
            return {"user_id": delegant, "role": await _role_of(delegant), "principal": "agent"}
        return {"user_id": user.get("sub"), "role": "super_admin", "principal": "agent"}
    meta = user.get("app_metadata") or {}
    return {"user_id": user.get("sub"), "role": meta.get("learn_role"), "principal": "human"}


def can(actor: dict[str, Any], resource: str, action: str) -> bool:
    role = actor.get("role")
    if role not in ROLE_LEVEL:
        return False
    if actor.get("lecture_seule") and action != "read":
        return False
    if role in READ_ONLY_ROLES and action != "read":
        return False
    if actor.get("principal") == "agent" and action != "read":
        if ROLE_LEVEL[role] < ROLE_LEVEL[AGENT_WRITE_CEILING]:
            role = AGENT_WRITE_CEILING
    return GRANTS.allows(role, resource, action)


# ── La dépendance posée sur chaque routeur ───────────────────────────────────

def action_for(method: str, path: str) -> str | None:
    return OVERRIDES.get((method, path)) or METHOD_ACTION.get(method)


def guard(resource: str):
    async def _guard(request: Request) -> None:
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        action = action_for(request.method, path)
        if action == PUBLIC:
            return
        if action is None:
            raise HTTPException(status_code=status.HTTP_405_METHOD_NOT_ALLOWED)
        user = await get_current_user(request, await _bearer(request))
        await GRANTS.ensure()
        actor = await actor_for(request, user)
        if not can(actor, resource, action):
            logger.info(
                "permissions.denied",
                extra={"component": "permissions", "resource": resource, "action": action,
                       "role": actor.get("role"), "principal": actor.get("principal")},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "forbidden", "resource": resource, "action": action,
                        "role": actor.get("role")},
            )
        request.state.actor = actor

    return _guard


# ── Ce que l'app demande pour construire son menu ────────────────────────────

router = APIRouter(prefix="/v1/permissions", tags=["permissions"])


@router.get("/me")
async def my_permissions(request: Request, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Le rôle LEARN et les droits de la personne connectée, par ressource.

    Le menu et les boutons se construisent à partir de cette réponse — jamais à partir du
    nom du rôle — pour que la règle ne vive qu'à un seul endroit.
    """
    await GRANTS.ensure()
    actor = await actor_for(request, user)
    role = actor.get("role")
    grants = GRANTS.for_role(role) if role in ROLE_LEVEL else {}
    if role in READ_ONLY_ROLES:
        grants = {k: [a for a in v if a == "read"] for k, v in grants.items()}
    return {"ok": True, "data": {"role": role, "principal": actor.get("principal"), "grants": grants}}
