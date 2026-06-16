"""Entry point: python -m gateway."""

from __future__ import annotations

import uvicorn

from winny_gateway.app import create_app
from winny_gateway.config import GatewayConfig
from winny_gateway.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)

config = GatewayConfig.from_env()
app = create_app(config)

if __name__ == "__main__":
    logger.info(
        "Starting WinnyWoo Gateway",
        extra={"component": "main", "action": "startup"},
    )
    uvicorn.run(
        "winny_gateway.__main__:app",
        host=config.host,
        port=config.port,
        reload=config.debug,
        log_level="info",
    )
