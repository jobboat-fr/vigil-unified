"""Supabase JWT authentication for the gateway.

Supports two verification methods (tried in order):
  1. **JWKS / ES256** — preferred. Uses the project's JWKS endpoint to fetch
     the public key and verify ES256-signed user tokens.
  2. **HS256 secret** — legacy fallback if SUPABASE_JWT_SECRET is set.
  3. **Dev mock user** — ONLY returned when ``WW_ALLOW_DEV_AUTH=true`` is
     set explicitly. Production must NEVER silently fall back to a mock
     user; that's how owner-email gates silently fail against
     ``dev@winnywoo.local``.

If JWKS is configured and verification fails, and neither an HS256 secret
nor the dev-auth escape hatch is set, this raises 401. The frontend will
log the user out and force a re-auth — which is the only correct response
to a token we can't trust.
"""

from __future__ import annotations

import contextlib
import os
from typing import Any

import jwt  # PyJWT
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from winny_gateway.logging import get_logger

logger = get_logger(__name__)
_bearer = HTTPBearer(auto_error=False)


def _dev_auth_allowed() -> bool:
    """Production safety: only true if WW_ALLOW_DEV_AUTH is explicitly opt-in."""
    return os.getenv("WW_ALLOW_DEV_AUTH", "").lower() in ("1", "true", "yes")


def _expected_issuer(supabase_url: str) -> str | None:
    """Supabase token issuer to pin (F16): ``<SUPABASE_URL>/auth/v1``.

    Returns None when SUPABASE_URL is unset so verification still works in
    setups that only configure a JWKS URL or HS256 secret.
    """
    url = (supabase_url or "").rstrip("/")
    return f"{url}/auth/v1" if url else None


def _owner_emails() -> set[str]:
    """Allow-listed owner email addresses (lower-cased).

    Sourced from WW_OWNER_EMAILS (comma-separated), falling back to the
    single-owner env vars the brokerage layer already uses.
    """
    raw = (
        os.getenv("WW_OWNER_EMAILS", "")
        or os.getenv("KRAKEN_KEY_OWNER_EMAIL", "")
        or os.getenv("WW_SERVICE_TOKEN_OWNER_EMAIL", "")
    )
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_owner(user: dict[str, Any]) -> bool:
    """True when the principal is the trading owner (VIGIL spec §8).

    Owner = the internal service token, an explicit ``owner``/``service`` role
    claim, or an email on the WW_OWNER_EMAILS allow-list.
    """
    if not isinstance(user, dict):
        return False
    if user.get("service_token") or str(user.get("role", "")).lower() in ("service", "owner"):
        return True
    app_md = user.get("app_metadata")
    if isinstance(app_md, dict) and str(app_md.get("role", "")).lower() == "owner":
        return True
    owners = _owner_emails()
    if owners:
        return str(user.get("email", "")).lower() in owners
    return False


_DEV_USER = {
    "sub": "00000000-0000-0000-0000-000000000000",
    "email": "dev@winnywoo.local",
    "role": "authenticated",
}


def _check_service_token(token: str) -> dict[str, Any] | None:
    """Validate a service-token bearer for trusted internal callers.

    Used by mcp-winnywoo (running on the OVH Hermes host) to call the
    gateway as the operator without holding a Supabase JWT. The token is
    a constant-time-compared shared secret set on Railway as
    ``WW_SERVICE_TOKEN``; the resulting identity is pinned to the owner
    email so all owner-gated env-var brokerage credentials resolve
    cleanly (KRAKEN_KEY_OWNER_EMAIL match).

    Returns the operator user dict on match, ``None`` otherwise. NEVER
    raises so the caller can fall through to other auth methods.
    """
    expected = os.getenv("WW_SERVICE_TOKEN", "").strip()
    if not expected or not token:
        return None
    # Constant-time compare — avoid timing oracle on token contents.
    import hmac as _hmac
    if not _hmac.compare_digest(expected.encode(), token.encode()):
        return None
    owner_email = os.getenv(
        "WW_SERVICE_TOKEN_OWNER_EMAIL",
        os.getenv("KRAKEN_KEY_OWNER_EMAIL", "operator@winnywoo.local"),
    ).strip().lower()
    return {
        # Use a deterministic UUID5 for the operator so audit logs and
        # the credential_store key stay stable across restarts.
        "sub": "00000000-0000-0000-0000-00000000ffff",
        "email": owner_email,
        "role": "service",
        "service_token": True,
    }

# Cache the JWKS client so we don't fetch keys on every request.
# PyJWKClient has its own internal cache with a 5-minute TTL.
_jwks_client: PyJWKClient | None = None


def _get_jwks_client(jwks_url: str) -> PyJWKClient:
    """Return (and lazily create) a cached JWKS client."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=300)
    return _jwks_client


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    """Validate Supabase JWT and return user claims.

    Priority: JWKS (ES256) → HS256 secret → dev-mode mock user.
    """
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization header")

    token = credentials.credentials
    config = request.app.state.config

    # ── 0. Service-token short-circuit ──────────────────────────────────
    # mcp-winnywoo on the OVH Hermes host calls Railway as the operator
    # using a shared secret. Validating it first keeps tool latency low
    # and avoids spinning up a JWKS round-trip for every Hermes tool call.
    svc_user = _check_service_token(token)
    if svc_user is not None:
        logger.debug(
            "auth via service token",
            extra={"action": "auth.service_token_ok", "component": "auth"},
        )
        return svc_user

    jwks_err: Exception | None = None
    issuer = _expected_issuer(config.supabase_url)

    # ── 1. Try JWKS / ES256 ──────────────────────────────────────────────
    if config.supabase_jwks_url:
        try:
            client = _get_jwks_client(config.supabase_jwks_url)
            signing_key = client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256"],
                audience="authenticated",
                issuer=issuer,
                options={"verify_iss": issuer is not None},
            )
            logger.debug(
                "JWT verified via JWKS (ES256)",
                extra={"action": "auth.jwks_ok", "sub": payload.get("sub"), "component": "auth"},
            )
            return payload
        except Exception as exc:
            jwks_err = exc
            logger.warning(
                "JWKS verification failed: %s", exc,
                extra={"action": "auth.jwks_fail", "error": str(exc), "component": "auth"},
            )

    # ── 2. Try HS256 secret ──────────────────────────────────────────────
    if config.supabase_jwt_secret:
        try:
            payload = jwt.decode(
                token,
                config.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
                issuer=issuer,
                options={"verify_iss": issuer is not None},
            )
            logger.debug(
                "JWT verified via HS256 secret",
                extra={"action": "auth.hs256_ok", "sub": payload.get("sub"), "component": "auth"},
            )
            return payload
        except Exception as exc:
            logger.warning(
                "HS256 JWT validation failed: %s", exc,
                extra={"action": "auth.hs256_fail", "error": str(exc), "component": "auth"},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
            ) from exc

    # ── 3. Dev escape hatch — only if WW_ALLOW_DEV_AUTH=true ────────────
    if _dev_auth_allowed():
        logger.warning(
            "WW_ALLOW_DEV_AUTH=true — returning dev user (DO NOT USE IN PROD)",
            extra={"action": "auth.dev_fallback", "component": "auth"},
        )
        return dict(_DEV_USER)

    # ── 4. Fail closed ──────────────────────────────────────────────────
    if jwks_err is not None:
        # We tried, the token failed verification → 401.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    # No auth method configured at all → server is misconfigured.
    logger.error(
        "No JWT verification method configured. Set SUPABASE_JWKS_URL or "
        "SUPABASE_JWT_SECRET (or WW_ALLOW_DEV_AUTH=true for local).",
        extra={"action": "auth.unconfigured", "component": "auth"},
    )
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Authentication not configured",
    )


def effective_user(request: Request, user: dict[str, Any]) -> dict[str, Any]:
    """The end-user a request acts for (multi-tenant scoping).

    Trusted backends — the WinnyWoo dashboard proxy and mcp-winnywoo —
    authenticate with the service token but act ON BEHALF OF a logged-in
    user, asserted via the ``X-WinnyWoo-User-Id`` / ``X-WinnyWoo-User-Email``
    headers. Per-user operations (broker credentials, portfolio, prefs) must
    resolve against THAT user, so one operator token never stores or reads
    another user's data.

    A service-token call with no scope header is the operator acting as
    itself (e.g. the signal runner). Direct Supabase-JWT callers are
    always themselves.
    """
    if not isinstance(user, dict) or not user.get("service_token"):
        return user
    uid = request.headers.get("X-WinnyWoo-User-Id")
    if not uid:
        return user
    return {
        "sub": uid,
        "email": (request.headers.get("X-WinnyWoo-User-Email") or "").strip(),
        "role": "authenticated",
        "scoped": True,
    }


async def scoped_user(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """FastAPI dependency: the effective end-user (multi-tenant scoping).

    Use in place of ``get_current_user`` on per-user read routes (portfolio,
    balances, positions, orders) so a trusted backend acting via the service
    token resolves the *logged-in* user (X-WinnyWoo-User-Id), not the operator.
    """
    return effective_user(request, user)


async def require_owner(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Gate money-moving routes on the owner role (VIGIL spec §8, finding F8).

    Allows the request when the principal is the owner (service token, owner
    role claim, or WW_OWNER_EMAILS match). When no owner allow-list is
    configured at all, enforcement is impossible — we then allow the request
    but log loudly, so single-user/dev deployments keep working. Configure
    WW_OWNER_EMAILS to turn this into hard enforcement.
    """
    if is_owner(user):
        return user
    if not _owner_emails():
        logger.warning(
            "require_owner: WW_OWNER_EMAILS unset — cannot enforce owner role; "
            "allowing %s. Set WW_OWNER_EMAILS to enforce.",
            (user.get("email") if isinstance(user, dict) else None),
            extra={"action": "auth.owner_unenforced", "component": "auth"},
        )
        return user
    logger.warning(
        "require_owner: rejected non-owner %s",
        (user.get("email") if isinstance(user, dict) else None),
        extra={"action": "auth.owner_denied", "component": "auth"},
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="owner_role_required",
    )


async def ws_authenticate(token: str | None, request: Request) -> dict[str, Any] | None:
    """Authenticate a WebSocket connection from a query-param token.

    Returns the user payload on success, or None if auth fails.
    In dev mode (no JWT secret configured), returns mock user.
    """
    from winny_gateway.config import GatewayConfig

    config = GatewayConfig.from_env()

    if not token:
        # No token — only allow if dev escape hatch is on.
        if _dev_auth_allowed():
            logger.warning(
                "WS: no token, WW_ALLOW_DEV_AUTH=true → dev user",
                extra={"action": "auth.ws_dev_fallback", "component": "auth"},
            )
            return dict(_DEV_USER)
        return None

    # Service-token short-circuit — same path as the REST handler. Lets the
    # Hermes /api/winnywoo/ws/feed proxy open an upstream WS without
    # synthesising a Supabase JWT.
    svc_user = _check_service_token(token)
    if svc_user is not None:
        logger.info(
            "WS: authenticated via service token",
            extra={"action": "auth.ws_service_token_ok", "component": "auth"},
        )
        return svc_user

    # Try JWKS first
    if config.supabase_jwks_url:
        with contextlib.suppress(Exception):
            jwks = _get_jwks_client(config.supabase_jwks_url)
            key = jwks.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                key.key,
                algorithms=["ES256"],
                audience="authenticated",
                options={"verify_exp": True},
            )
            return dict(payload)

    # Try HS256
    if config.supabase_jwt_secret:
        with contextlib.suppress(Exception):
            payload = jwt.decode(
                token,
                config.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
                options={"verify_exp": True},
            )
            return dict(payload)

    # Dev escape hatch
    if _dev_auth_allowed():
        logger.warning(
            "WS: WW_ALLOW_DEV_AUTH=true → dev user",
            extra={"action": "auth.ws_dev_fallback", "component": "auth"},
        )
        return dict(_DEV_USER)

    return None
