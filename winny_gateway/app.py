"""WinnyWoo API Gateway — FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

# Load .env into os.environ BEFORE anything else — MCP subprocesses inherit
# the parent's environment, so HF_TOKEN, API keys, etc. must be present
# before McpPool.start_all() forks the child processes.
import winny.common.config  # noqa: F401  — side-effect: _load_dotenv()
from winny_gateway.config import GatewayConfig
from winny_gateway.logging import get_logger, log_request
from winny_gateway.routes import (
    account,
    assistant,
    audit,
    billing,
    features,
    integrations,
    vault,
)
from winny_gateway.routes.vigil import council as vigil_council
from winny_gateway.routes.vigil import rooms as vigil_rooms
from winny_gateway.routes.vigil import studio as vigil_studio
from winny_gateway.routes.vigil import projets as vigil_projets
from winny_gateway.routes.vigil import finance as vigil_finance
from winny_gateway.routes.vigil import crm as vigil_crm
from winny_gateway.routes.vigil import mail as vigil_mail
from winny_gateway.routes.vigil import ops as vigil_ops
from winny_gateway.routes.vigil import finance_connect as vigil_finance_connect
from winny_gateway.routes.vigil import connect as vigil_connect
from winny_gateway.routes.vigil import privacy as vigil_privacy
from winny_gateway import ai_guard, permissions
from winny_gateway.db import DatabaseError
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
        # vigil-ai.xyz est éteint (Azer, 29/09) : la passerelle ne lance plus les serveurs MCP de
        # trading (algo, approval, timesfm, tradingagents), ni le bus d'évènements du flux
        # WebSocket, ni les sondeurs de portefeuille et de validations, ni le moteur de signaux.
        # Rien de ce qui reste servi ne s'en servait.
        logger.info("WinnyWoo Gateway started on %s:%d", config.host, config.port)
        yield
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
        # Motif d'origines : vide par défaut (voir config.py) ; seulement s'il est posé
        # explicitement. Ignoré sous une configuration « * » (identifiants déjà coupés).
        allow_origin_regex=None if cors_wildcard else (config.cors_origin_regex or None),
        allow_credentials=not cors_wildcard,
        allow_methods=["*"],
        allow_headers=["*"],
        # Le navigateur ne lit un en-tête de réponse que s'il est exposé. Sans cette
        # ligne, l'application ne récupère pas la référence que la passerelle a
        # journalisée et affiche la sienne : deux identifiants pour une seule requête.
        expose_headers=["x-request-id"],
    )

    # Security middleware (rate-limit, body-size cap, security headers)
    app.add_middleware(SecurityMiddleware)
    # Limite de débit par personne (voir limite_debit.py), exécutée après le verrou d'origine.
    from winny_gateway.limite_debit import LimiteDebitMiddleware
    app.add_middleware(LimiteDebitMiddleware)

    # Verrou d'origine : refuse ce qui contourne la bordure Cloudflare (voir edge_lock.py).
    # Ajouté après, donc exécuté avant : une requête directe ne consomme rien d'autre.
    from winny_gateway.edge_lock import EdgeLockMiddleware
    app.add_middleware(EdgeLockMiddleware)

    # Request logging middleware
    app.add_middleware(BaseHTTPMiddleware, dispatch=log_request)

    # Register routers
    # Les routes WinnyWoo (portefeuille, ordres, validations d'ordres, prévisions, backtest,
    # signaux, clés de courtier, intégration courtier/Coinbase, trading automatique, marché,
    # chat d'origine, flux WebSocket, diffusion d'évènements, webhook Coinbase) sont RETIRÉES
    # le 29/09 : elles ne servaient que vigil-ai.xyz, éteint. Aucun écran VTLVS ne les appelait.
    # LEARN moved to jobboat-fr/hbs-backend- (app/learn/) on 2026-09-06 and is served
    # from Railway at api.vtlvs.com. It was mounted here while it was being built; keeping
    # a second copy in this repo meant two copies of the same authorization rules, and they
    # had started to diverge within a day. See learn/README.md.


    app.include_router(audit.router)
    app.include_router(features.router)
    app.include_router(billing.router)
    # Mon compte (RGPD) et support — avant l'ancien routeur, dont DELETE /api/v1/account est retiré.
    from winny_gateway.routes import compte_support
    app.include_router(compte_support.router)
    # Les alertes Grafana : reçues ici, remises par l'entonnoir de LEARN. Grafana tourne
    # sur l'hôte OVH, d'où le SMTP sortant est bloqué — un point de contact « email » y
    # resterait muet, et muet de la même façon silencieuse qu'aujourd'hui.
    from winny_gateway.routes import alertes
    app.include_router(alertes.router)
    app.include_router(account.router)
    # VIGIL assistant — bridges the vigil-web AssistantWidget to Hermes.
    app.include_router(assistant.router)
    # VIGIL vault — user document store grounding the agent in real docs.
    app.include_router(vault.router, dependencies=[Depends(permissions.guard("legal")), Depends(ai_guard.feature("vault"))])
    # VIGIL integrations — runtime MCP servers, single source of truth.
    app.include_router(integrations.router)
    # VIGIL meeting room + council — ported from VIGIL backendv2 (Node→Python).
    app.include_router(vigil_council.router, dependencies=[Depends(ai_guard.feature("council"))])
    app.include_router(vigil_rooms.router, dependencies=[Depends(permissions.guard("room")), Depends(ai_guard.feature("meeting"))])
    # Studio — artifact drafting behind the brainstorm-first gate.
    app.include_router(vigil_studio.router, dependencies=[Depends(permissions.guard("studio")), Depends(ai_guard.feature("studio"))])
    # Projets du Studio — le canevas qui relie salles, artefacts, agents et coffre ; mêmes droits que le Studio.
    app.include_router(vigil_projets.router, dependencies=[Depends(permissions.guard("studio")), Depends(ai_guard.feature("studio"))])
    # Finance — the books/ledger backend the cfo-* skills route into.
    app.include_router(vigil_finance.router, dependencies=[Depends(permissions.guard("finance"))])
    # Finance connector — bank (Plaid) / accounting platform sync into the ledger.
    app.include_router(vigil_finance_connect.router, dependencies=[Depends(permissions.guard("finance"))])
    # Connector kit — generic per-tenant system-of-record connectors (GitHub, …).
    app.include_router(vigil_connect.router)
    # Privacy / GDPR — tenant data export + erasure.
    app.include_router(vigil_privacy.router)
    # CRM — contacts + deal pipeline the crm skill routes into.
    app.include_router(vigil_crm.router, dependencies=[Depends(permissions.guard("crm"))])
    # Mail — inbox triage store (himalaya transport) the mail-triage skill uses.
    app.include_router(vigil_mail.router, dependencies=[Depends(permissions.guard("mail")), Depends(ai_guard.feature("mail"))])
    # Ops Team — agentic-company departments (on-demand runs + effectiveness gate).
    app.include_router(vigil_ops.router, dependencies=[Depends(permissions.guard("ops")), Depends(ai_guard.feature("ops"))])
    # Droits des pages métier, lus dans learn_capabilities — le menu de l'app s'en sert.
    app.include_router(permissions.router)
    # Délégations d'agent et contexte d'identité (qui, quel rôle, quels droits).
    from winny_gateway.routes import agents_identite
    app.include_router(agents_identite.router)
    # Coupe-circuit IA : état lu par l'app pour afficher « assistant indisponible ».
    app.include_router(ai_guard.router)

    # Une erreur de base devient une réponse lisible, jamais une liste vide.
    @app.exception_handler(DatabaseError)
    async def database_error(_request: Request, exc: DatabaseError) -> JSONResponse:
        scope = exc.reason == "cross_tenant_blocked"
        return JSONResponse(
            status_code=500 if scope else 503,
            content={
                "ok": False,
                "error": "internal_scope_error" if scope else "database_unavailable",
                "detail": {"table": exc.table, "operation": exc.operation,
                           **({} if scope else {"reason": exc.reason})},
            },
        )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "data": {"status": "ok", "service": "winnywoo-gateway"}}

    return app
