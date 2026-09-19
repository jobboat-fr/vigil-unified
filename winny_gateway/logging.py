"""Structured logging for the WinnyWoo gateway.

Two modes controlled by ``WW_LOG_FORMAT``:
  - ``json``   — one JSON object per line (production / log aggregators)
  - ``pretty`` — coloured human-readable output (development, default)

Log level is controlled by ``WW_LOG_LEVEL`` (default: INFO).

Usage::

    from winny_gateway.logging import setup_logging, get_logger
    setup_logging()                         # call once at startup
    logger = get_logger(__name__)           # per-module loggers
    logger.info("order submitted", extra={"symbol": "BTC/USD", "qty": 0.5})
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import Any

# ── Colours for pretty mode ──────────────────────────────────────────────────
_RESET  = "\033[0m"
_GREY   = "\033[90m"
_CYAN   = "\033[96m"
_GREEN  = "\033[92m"
_YELLOW = "\033[93m"
_RED    = "\033[91m"
_BOLD   = "\033[1m"
_MAGENTA = "\033[95m"

_LEVEL_COLOURS: dict[int, str] = {
    logging.DEBUG:    _GREY,
    logging.INFO:     _GREEN,
    logging.WARNING:  _YELLOW,
    logging.ERROR:    _RED,
    logging.CRITICAL: f"{_BOLD}{_RED}",
}

_LEVEL_TAGS: dict[int, str] = {
    logging.DEBUG:    "DBG",
    logging.INFO:     "INF",
    logging.WARNING:  "WRN",
    logging.ERROR:    "ERR",
    logging.CRITICAL: "CRT",
}


# ── JSON Formatter ───────────────────────────────────────────────────────────

class JsonFormatter(logging.Formatter):
    """Une ligne JSON au schéma commun de l'écosystème VTLVS (identique à LEARN) :
    ts, niveau, service, env, journal, message, evenement, puis les champs fournis par l'appelant.
    L'adresse IP n'est jamais écrite en clair."""

    _STANDARD = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}
    _RENOMMES = {"status_code": "statut", "duration_ms": "duree_ms", "path": "route", "method": "methode",
                 "request_id": "requete_id", "user_id": "acteur", "action": "evenement"}

    def format(self, record: logging.LogRecord) -> str:
        import hashlib

        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "niveau": record.levelname.lower(),
            "service": "passerelle",
            "env": os.getenv("RAILWAY_ENVIRONMENT_NAME") or "production",
            "journal": record.name,
            "message": record.getMessage(),
        }
        for key, val in vars(record).items():
            if key in self._STANDARD or key.startswith("_") or val is None:
                continue
            if key == "ip":
                val = hashlib.sha256(f"{os.getenv('LOG_IP_SALT', 'vtlvs')}:{val}".encode()).hexdigest()[:12]
            payload[self._RENOMMES.get(key, key)] = val
        if record.exc_info and record.exc_info[1]:
            payload["exception"] = self.formatException(record.exc_info)[-2000:]
        return json.dumps(payload, default=str, ensure_ascii=False)


# ── Pretty Formatter ─────────────────────────────────────────────────────────

class PrettyFormatter(logging.Formatter):
    """Coloured single-line output for local development."""

    def format(self, record: logging.LogRecord) -> str:
        colour = _LEVEL_COLOURS.get(record.levelno, "")
        tag = _LEVEL_TAGS.get(record.levelno, "???")
        ts = datetime.fromtimestamp(record.created, tz=UTC).strftime("%H:%M:%S.%f")[:-3]
        name = record.name.replace("gateway.", "gw.").replace("winny.", "wn.")
        msg = record.getMessage()

        # Append extra structured fields inline
        extras: list[str] = []
        for key in ("symbol", "broker", "user_id", "action", "duration_ms",
                     "status_code", "method", "path", "request_id", "component"):
            val = getattr(record, key, None)
            if val is not None:
                extras.append(f"{_GREY}{key}={_RESET}{_CYAN}{val}{_RESET}")

        extra_str = f"  {' '.join(extras)}" if extras else ""

        line = (
            f"{_GREY}{ts}{_RESET} "
            f"{colour}{tag}{_RESET} "
            f"{_MAGENTA}{name:<28}{_RESET} "
            f"{msg}"
            f"{extra_str}"
        )

        if record.exc_info and record.exc_info[1]:
            line += f"\n{self.formatException(record.exc_info)}"

        return line


# ── Setup ────────────────────────────────────────────────────────────────────

def setup_logging() -> None:
    """Configure root logger. Call once from ``gateway.__main__``."""

    log_format = os.getenv("WW_LOG_FORMAT", "pretty").lower()
    log_level = os.getenv("WW_LOG_LEVEL", "INFO").upper()

    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level, logging.INFO))

    # Remove any pre-existing handlers (uvicorn adds its own)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, log_level, logging.INFO))

    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(PrettyFormatter())

    root.addHandler(handler)

    # Puits central (Loki sur OVH), si configuré : même ligne JSON, envoyée par lots.
    from winny_gateway.journal_loki import installer as installer_loki
    installer_loki(root, "passerelle", JsonFormatter())

    # Quiet noisy libraries
    for noisy in ("uvicorn.access", "httpcore", "httpx", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger("uvicorn.error").setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger — thin wrapper for discoverability."""
    return logging.getLogger(name)


# ── Request logging middleware helper ────────────────────────────────────────

_req_logger = logging.getLogger("gateway.http")


async def log_request(request: Any, call_next: Any) -> Any:
    """Une ligne par requête (événement http.requete) — niveau selon le statut."""
    if request.url.path == "/health":
        return await call_next(request)
    start = time.perf_counter()
    # La référence voyage du navigateur au journal : si le client en a posé une, on la
    # garde — sinon on en fabrique une. Elle repart dans la réponse pour que l'écran
    # d'erreur puisse l'afficher, et c'est la même chaîne qu'on cherche dans Loki.
    recue = request.headers.get("x-request-id") or ""
    requete_id = recue if 8 <= len(recue) <= 64 and recue.replace("-", "").isalnum() else uuid.uuid4().hex
    response = await call_next(request)
    response.headers["x-request-id"] = requete_id
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    statut = response.status_code
    niveau = logging.ERROR if statut >= 500 else logging.WARNING if statut in (401, 403, 429) else logging.INFO
    _req_logger.log(
        niveau,
        "%s %s → %d (%.1f ms)",
        request.method, request.url.path, statut, duration_ms,
        extra={
            "evenement": "http.requete",
            "method": request.method,
            "path": request.url.path,
            "status_code": statut,
            "duration_ms": duration_ms,
            "request_id": requete_id,
            "ip": request.headers.get("cf-connecting-ip") or (request.client.host if request.client else None),
        },
    )
    return response
