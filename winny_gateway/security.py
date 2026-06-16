"""Gateway security middleware & helpers — SECURITY HARDENING.

Centralised request-level protections applied to every incoming HTTP request:
  1. Request body size cap  — rejects payloads > MAX_BODY_SIZE early.
  2. Per-IP sliding-window rate limiter — prevents brute-force and DoS.
  3. Security response headers — HSTS, content-type sniffing, XSS, framing.
  4. WebSocket message size cap and per-connection rate limiter.

All limits are configurable via environment variables.
"""

from __future__ import annotations

import os
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from winny_gateway.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration (env-overridable)
# ---------------------------------------------------------------------------

MAX_BODY_BYTES = int(os.getenv("WW_MAX_BODY_BYTES", str(1 * 1024 * 1024)))  # 1 MB
RATE_LIMIT_RPM = int(os.getenv("WW_RATE_LIMIT_RPM", "120"))  # requests per minute
RATE_LIMIT_BURST = int(os.getenv("WW_RATE_LIMIT_BURST", "20"))  # burst allowance
WS_MAX_MSG_BYTES = int(os.getenv("WW_WS_MAX_MSG_BYTES", str(64 * 1024)))  # 64 KB
WS_MSG_PER_MIN = int(os.getenv("WW_WS_MSG_PER_MIN", "60"))  # WS messages per minute

# Number of trusted reverse-proxy hops in front of the gateway (F6). The client
# IP is taken from X-Forwarded-For counting this many entries from the RIGHT —
# i.e. the address the outermost trusted proxy observed. Anything the client
# prepends sits to the left and is ignored, so the limiter key can't be spoofed.
# 0 = don't trust XFF at all; use the direct socket peer.
# Default 1: this gateway runs behind exactly one edge proxy in production
# (Railway), so the real client IP is the rightmost XFF entry the proxy added.
# With a default of 0, every request collapsed onto the proxy's IP → one shared
# rate-limit bucket for all users (lockout risk). Local/dev requests carry no
# XFF header and fall through to the direct socket peer regardless, so 1 is
# safe there too. Override (e.g. 2) only if you stack more trusted proxies.
TRUST_PROXY_HOPS = int(os.getenv("WW_TRUST_PROXY_HOPS", "1"))

# Hard cap on distinct rate-limit buckets to bound memory (F6 DoS guard).
RATE_LIMIT_MAX_KEYS = int(os.getenv("WW_RATE_LIMIT_MAX_KEYS", "20000"))

# Paths exempt from rate limiting (health checks, static)
_RATE_LIMIT_EXEMPT = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})


# ---------------------------------------------------------------------------
# In-memory sliding-window rate limiter
# ---------------------------------------------------------------------------

class _SlidingWindow:
    """Per-key sliding-window rate limiter (in-memory, single-process).

    For production multi-instance deployments, replace with Redis-backed
    sliding window (e.g. via redis-py ``ZRANGEBYSCORE`` pattern).
    """

    __slots__ = ("_buckets", "_max_keys", "_max_requests", "_window_seconds")

    def __init__(
        self, max_requests: int, window_seconds: int = 60, max_keys: int = RATE_LIMIT_MAX_KEYS
    ) -> None:
        self._buckets: dict[str, list[float]] = {}
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._max_keys = max_keys

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self._window_seconds
        bucket = [t for t in self._buckets.get(key, []) if t > cutoff]
        if len(bucket) >= self._max_requests:
            self._buckets[key] = bucket
            return False
        bucket.append(now)
        self._buckets[key] = bucket
        # Bound memory: evict idle/expired buckets when the map grows too large.
        if len(self._buckets) > self._max_keys:
            self._evict(cutoff)
        return True

    def _evict(self, cutoff: float) -> None:
        """Drop buckets that are fully expired; if still over cap, drop oldest."""
        dead = [k for k, v in self._buckets.items() if not v or v[-1] <= cutoff]
        for k in dead:
            del self._buckets[k]
        overflow = len(self._buckets) - self._max_keys
        if overflow > 0:
            # Evict the least-recently-active buckets.
            stale = sorted(self._buckets.items(), key=lambda kv: kv[1][-1])[:overflow]
            for k, _ in stale:
                del self._buckets[k]

    def remaining(self, key: str) -> int:
        now = time.monotonic()
        cutoff = now - self._window_seconds
        bucket = [t for t in self._buckets.get(key, []) if t > cutoff]
        return max(0, self._max_requests - len(bucket))


_rate_limiter = _SlidingWindow(max_requests=RATE_LIMIT_RPM, window_seconds=60)


# ---------------------------------------------------------------------------
# HTTP security middleware
# ---------------------------------------------------------------------------

class SecurityMiddleware(BaseHTTPMiddleware):
    """Defence-in-depth HTTP middleware.

    Applied globally via ``app.add_middleware(SecurityMiddleware)`` in app.py.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        client_ip = _get_client_ip(request)
        path = request.url.path

        # 1. Body-size guard (before reading the body)
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_BODY_BYTES:
            logger.warning(
                "Request body too large",
                extra={
                    "action": "security.body_too_large",
                    "client_ip": client_ip,
                    "content_length": content_length,
                    "component": "security",
                },
            )
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large"},
            )

        # 2. Rate limiting (skip exempt paths)
        if path not in _RATE_LIMIT_EXEMPT and not _rate_limiter.is_allowed(client_ip):
            logger.warning(
                "Rate limit exceeded",
                extra={
                    "action": "security.rate_limited",
                    "client_ip": client_ip,
                    "path": path,
                    "component": "security",
                },
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={"Retry-After": "60"},
            )

        # 3. Process request
        response = await call_next(request)

        # 4. Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # HSTS only if served over TLS (don't break local dev)
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # 5. Rate-limit info headers
        remaining = _rate_limiter.remaining(client_ip)
        response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT_RPM)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        return response


# ---------------------------------------------------------------------------
# WebSocket rate limiter (per-connection)
# ---------------------------------------------------------------------------

class WebSocketRateLimiter:
    """Per-connection sliding-window rate limiter for WebSocket messages."""

    __slots__ = ("_max_per_minute", "_timestamps")

    def __init__(self, max_per_minute: int = WS_MSG_PER_MIN) -> None:
        self._timestamps: list[float] = []
        self._max_per_minute = max_per_minute

    def check(self) -> bool:
        """Return True if the message is allowed, False if rate-limited."""
        now = time.monotonic()
        cutoff = now - 60.0
        self._timestamps = [t for t in self._timestamps if t > cutoff]
        if len(self._timestamps) >= self._max_per_minute:
            return False
        self._timestamps.append(now)
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_client_ip(request: Request) -> str:
    """Extract the client IP for rate-limiting, resistant to XFF spoofing (F6).

    X-Forwarded-For is client-controllable on the left. We only trust it when
    ``WW_TRUST_PROXY_HOPS`` is set, and then read the entry that many hops from
    the RIGHT — the address inserted by the outermost trusted proxy. Spoofed
    entries the client prepends are to the left and ignored. With hops=0 we
    ignore XFF entirely and use the direct socket peer.
    """
    direct = request.client.host if request.client else "unknown"
    if TRUST_PROXY_HOPS <= 0:
        return direct
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return direct
    parts = [p.strip() for p in forwarded.split(",") if p.strip()]
    idx = len(parts) - TRUST_PROXY_HOPS
    if idx < 0 or idx >= len(parts):
        # Fewer entries than trusted hops — misconfigured/forged; fail safe.
        return direct
    return parts[idx]


def sanitise_error_detail(detail: Any) -> str:
    """Ensure error details don't leak internal paths or stack traces.

    Only allows short, printable strings through. Everything else becomes
    a generic message.
    """
    if not isinstance(detail, str):
        return "Internal server error"
    text: str = detail
    # Strip any potential path leaks
    if len(text) > 256:
        text = text[:256]
    # Never expose file paths
    if ("\\" in text or "/" in text) and ":" in text and ("Users" in text or "home" in text or "var" in text):
        return "Internal server error"
    return text
