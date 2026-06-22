"""WinnyWoo API Gateway — FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

# Load .env into os.environ BEFORE anything else — MCP subprocesses inherit
# the parent's environment, so HF_TOKEN, API keys, etc. must be present
# before McpPool.start_all() forks the child processes.
import winny.common.config  # noqa: F401  — side-effect: _load_dotenv()
from winny_gateway.config import GatewayConfig
from winny_gateway.events import EventBus, approvals_poller, portfolio_poller
from winny_gateway.logging import get_logger, log_request
from winny_gateway.mcp_bridge import McpPool
from winny_gateway.routes import (
    account,
    agents,
    approvals,
    assistant,
    audit,
    auto_trade,
    backtest,
    billing,
    broker_connect,
    chat,
    chat_proxy,
    events,
    features,
    integrations,
    market,
    onboarding,
    orders,
    portfolio,
    settings,
    signals,
    vault,
    webhooks,
    ws,
)
from winny_gateway.routes.vigil import council as vigil_council
from winny_gateway.routes.vigil import rooms as vigil_rooms
from winny_gateway.routes.vigil import studio as vigil_studio
from winny_gateway.routes.vigil import finance as vigil_finance
from winny_gateway.routes.vigil import crm as vigil_crm
from winny_gateway.routes.vigil import mail as vigil_mail
from winny_gateway.routes.vigil import ops as vigil_ops
from winny_gateway.routes.vigil import finance_connect as vigil_finance_connect
from winny_gateway.routes.vigil import connect as vigil_connect
from winny_gateway.security import SecurityMiddleware

logger = get_logger(__name__)

_MCP_DEFAULT_NAMES = {"mcp-algo", "mcp-approval", "mcp-timesfm", "mcp-tradingagents"}


def _mcp_command(configured: str, module: str, *, autoroute: bool = True) -> str | list[str]:
    """Resolve how to spawn an MCP server.

    - An explicit operator override (env set to anything other than the bare
      default name) wins verbatim — it is shlex-split by the bridge.
    - Otherwise, when ``autoroute`` is set, run the vendored server via the
      current interpreter so it works without the venv Scripts dir on PATH.
    - When ``autoroute`` is off (heavy servers), keep the bare name so a missing
      binary degrades to stub mode instead of crashing on a heavy import.
    """
    if configured not in _MCP_DEFAULT_NAMES:
        return configured
    if autoroute:
        return [sys.executable, "-m", module]
    return configured


def create_app(config: GatewayConfig | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if config is None:
        config = GatewayConfig.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # Startup: MCP pool + event bus + pollers.
        #
        # Native port: the winny MCP servers are vendored in-tree, so we spawn
        # the light ones (algo, approval) via the CURRENT interpreter
        # (`sys.executable -m winny.mcp.<name>.server`) — no dependency on the
        # venv Scripts dir being on PATH. The heavy ones (timesfm needs torch,
        # tradingagents needs langgraph) keep their bare-name default so they
        # degrade to stub mode unless the operator installs the extras and
        # overrides WW_MCP_*_CMD. An explicit env override always wins.
        pool = McpPool()
        pool.register("algo", _mcp_command(config.mcp_algo_cmd, "winny.mcp.algo.server"))
        pool.register("approval", _mcp_command(config.mcp_approval_cmd, "winny.mcp.approval.server"))
        pool.register("timesfm", _mcp_command(config.mcp_timesfm_cmd, "winny.mcp.timesfm.server", autoroute=False))
        pool.register(
            "tradingagents",
            _mcp_command(config.mcp_tradingagents_cmd, "winny.mcp.tradingagents.server", autoroute=False),
        )
        await pool.start_all()
        app.state.mcp_pool = pool

        bus = EventBus()
        await bus.start()
        app.state.event_bus = bus

        # Background pollers — auto-publish portfolio + new pending approvals.
        poller_tasks: list[asyncio.Task[None]] = [
            asyncio.create_task(portfolio_poller(bus, pool), name="portfolio-poller"),
            asyncio.create_task(approvals_poller(bus, pool), name="approvals-poller"),
        ]

        # Signal runner — periodic forecaster + analyst writing to Supabase.
        # Quiet exit if Supabase isn't configured (logs and returns).
        try:
            from winny_gateway.analytics import signal_runner_loop
            poller_tasks.append(
                asyncio.create_task(signal_runner_loop(), name="signal-runner")
            )
        except Exception as exc:
            logger.warning("signal runner failed to start: %s", exc)

        app.state.poller_tasks = poller_tasks

        logger.info("WinnyWoo Gateway started on %s:%d", config.host, config.port)
        yield

        # Shutdown — stop pollers, drain bus, kill MCP pool
        for t in poller_tasks:
            t.cancel()
        for t in poller_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t

        await bus.stop()
        await pool.stop_all()
        logger.info("WinnyWoo Gateway stopped")

    app = FastAPI(
        title="WinnyWoo Gateway",
        description="REST + WebSocket bridge between VIGIL frontend and WinnyWoo MCP servers",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.config = config

    # CORS — never combine credentialed requests with a reflected wildcard (F9).
    # If "*" is configured, browsers forbid credentials anyway; we make that
    # explicit and log it so a misconfig doesn't silently disable isolation.
    cors_wildcard = "*" in config.cors_origins
    if cors_wildcard:
        logger.warning(
            "CORS configured with '*' — disabling allow_credentials. Pin explicit "
            "origins via WW_CORS_ORIGINS to use credentialed requests."
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        # Also accept any vigil-ai.xyz subdomain (dev./demo./apex) + Vercel
        # previews via regex, so a new frontend host works without editing
        # WW_CORS_ORIGINS. Skipped under a "*" config (credentials already off).
        allow_origin_regex=None if cors_wildcard else (config.cors_origin_regex or None),
        allow_credentials=not cors_wildcard,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Security middleware (rate-limit, body-size cap, security headers)
    app.add_middleware(SecurityMiddleware)

    # Request logging middleware
    app.add_middleware(BaseHTTPMiddleware, dispatch=log_request)

    # Register routers
    app.include_router(portfolio.router)
    app.include_router(orders.router)
    app.include_router(approvals.router)
    app.include_router(agents.router)

    # Hermes-on-OVH proxy takes precedence over the in-process chat
    # orchestrator whenever HERMES_URL is set. Both share the prefix
    # /api/v1/chat but FastAPI route resolution gives priority to the
    # router included first.
    if config.hermes_url:
        logger.info("Chat: routing /api/v1/chat/* to Hermes at %s", config.hermes_url)
        app.include_router(chat_proxy.router)
    else:
        logger.info("Chat: HERMES_URL unset — using in-process orchestrator fallback")
        app.include_router(chat.router)
    app.include_router(backtest.router)
    app.include_router(audit.router)
    app.include_router(signals.router)
    app.include_router(settings.router)
    app.include_router(onboarding.router)
    app.include_router(broker_connect.router)
    app.include_router(webhooks.router)
    app.include_router(features.router)
    app.include_router(auto_trade.router)
    app.include_router(market.router)
    app.include_router(billing.router)
    app.include_router(account.router)
    app.include_router(ws.router)
    app.include_router(events.router)
    # VIGIL assistant — bridges the vigil-web AssistantWidget to Hermes.
    app.include_router(assistant.router)
    # VIGIL vault — user document store grounding the agent in real docs.
    app.include_router(vault.router)
    # VIGIL integrations — runtime MCP servers, single source of truth.
    app.include_router(integrations.router)
    # VIGIL meeting room + council — ported from VIGIL backendv2 (Node→Python).
    app.include_router(vigil_council.router)
    app.include_router(vigil_rooms.router)
    # Studio — artifact drafting behind the brainstorm-first gate.
    app.include_router(vigil_studio.router)
    # Finance — the books/ledger backend the cfo-* skills route into.
    app.include_router(vigil_finance.router)
    # Finance connector — bank (Plaid) / accounting platform sync into the ledger.
    app.include_router(vigil_finance_connect.router)
    # Connector kit — generic per-tenant system-of-record connectors (GitHub, …).
    app.include_router(vigil_connect.router)
    # CRM — contacts + deal pipeline the crm skill routes into.
    app.include_router(vigil_crm.router)
    # Mail — inbox triage store (himalaya transport) the mail-triage skill uses.
    app.include_router(vigil_mail.router)
    # Ops Team — agentic-company departments (on-demand runs + effectiveness gate).
    app.include_router(vigil_ops.router)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "data": {"status": "ok", "service": "winnywoo-gateway"}}

    return app
