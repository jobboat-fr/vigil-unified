"""Gateway configuration — loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GatewayConfig:
    """Configuration for the WinnyWoo API gateway."""

    # Server
    host: str = "0.0.0.0"
    port: int = 8400
    debug: bool = False

    # CORS
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"])
    # Regex allowlist (in addition to cors_origins) so any vigil-ai.xyz subdomain
    # (dev./demo./apex) and the project's Vercel preview URLs are accepted without
    # having to enumerate each in WW_CORS_ORIGINS. Specific, not a wildcard, so it
    # stays compatible with credentialed requests.
    cors_origin_regex: str = (
        r"https://([a-z0-9-]+\.)?vigil-ai\.xyz|https://vigil-unified-[a-z0-9-]+\.vercel\.app"
    )

    # Supabase
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwks_url: str = ""
    supabase_jwt_secret: str = ""

    # MCP server commands (stdio).
    # These match the [project.scripts] entries in pyproject.toml created by
    # `pip install -e .` — each resolves to `winny.mcp.<name>.server:main`.
    mcp_algo_cmd: str = "mcp-algo"
    mcp_approval_cmd: str = "mcp-approval"
    mcp_timesfm_cmd: str = "mcp-timesfm"
    mcp_tradingagents_cmd: str = "mcp-tradingagents"

    # Rate limits
    rate_limit_per_minute: int = 120

    # ── External Hermes runtime (OVH) ──────────────────────────────────
    # When set, /api/v1/chat/* forwards to this base URL instead of running
    # the in-process regex orchestrator. The legacy orchestrator stays as
    # a fallback when HERMES_URL is empty so we can flip back via env.
    hermes_url: str = ""
    hermes_proxy_secret: str = ""
    hermes_timeout_seconds: float = 120.0

    @classmethod
    def from_env(cls) -> GatewayConfig:
        return cls(
            host=os.getenv("WW_HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", os.getenv("WW_PORT", "8400"))),
            debug=os.getenv("WW_DEBUG", "").lower() in ("1", "true", "yes"),
            cors_origins=os.getenv("WW_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(","),
            cors_origin_regex=os.getenv(
                "WW_CORS_ORIGIN_REGEX",
                r"https://([a-z0-9-]+\.)?vigil-ai\.xyz|https://vigil-unified-[a-z0-9-]+\.vercel\.app",
            ),
            supabase_url=os.getenv("SUPABASE_URL", ""),
            supabase_anon_key=os.getenv("SUPABASE_ANON_KEY", ""),
            supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
            supabase_jwks_url=os.getenv("SUPABASE_JWKS_URL", ""),
            supabase_jwt_secret=os.getenv("SUPABASE_JWT_SECRET", ""),
            mcp_algo_cmd=os.getenv("WW_MCP_ALGO_CMD", "mcp-algo"),
            mcp_approval_cmd=os.getenv("WW_MCP_APPROVAL_CMD", "mcp-approval"),
            mcp_timesfm_cmd=os.getenv("WW_MCP_TIMESFM_CMD", "mcp-timesfm"),
            mcp_tradingagents_cmd=os.getenv("WW_MCP_TRADINGAGENTS_CMD", "mcp-tradingagents"),
            rate_limit_per_minute=int(os.getenv("WW_RATE_LIMIT", "120")),
            hermes_url=os.getenv("HERMES_URL", ""),
            hermes_proxy_secret=os.getenv("HERMES_PROXY_SECRET", ""),
            hermes_timeout_seconds=float(os.getenv("HERMES_TIMEOUT", "120")),
        )
