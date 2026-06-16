"""Liquidity Microstructure API — standalone FastAPI service.

Endpoints:
    GET  /health                      — service + engine health
    GET  /liquidity                   — analytics for all watched symbols
    GET  /liquidity/{symbol}          — analytics for one symbol (e.g. BTC-USDT)
    GET  /liquidity/{symbol}/signal   — condensed directional signal for agents
    GET  /sweeps                      — recent sweep events across all symbols

Auth: optional shared key via `X-Liquidity-Key` header (set LIQ_API_KEY).

Run standalone:
    uvicorn services.liquidity_api.app:app --port 8600

Integration with WinnyWoo gateway: set LIQUIDITY_API_URL=http://127.0.0.1:8600
and proxy or consume from mcp-algo / analytics as a covariate source.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request

from .config import Settings
from .engine import LiquidityEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("liquidity_api")

settings = Settings()
engine = LiquidityEngine(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await engine.start()
    try:
        yield
    finally:
        await engine.stop()


app = FastAPI(
    title="WinnyWoo Liquidity Microstructure API",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------


async def require_key(request: Request) -> None:
    if not settings.api_key:
        return
    if request.headers.get("X-Liquidity-Key") != settings.api_key:
        raise HTTPException(status_code=401, detail="invalid or missing X-Liquidity-Key")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _resolve_symbol(symbol: str) -> str:
    """Accept BTC-USDT or BTC/USDT; ccxt uses the slash form."""
    candidate = symbol.replace("-", "/").upper()
    if candidate in engine.state:
        return candidate
    raise HTTPException(
        status_code=404,
        detail=f"symbol {symbol!r} not watched; watching: {sorted(engine.state)}",
    )


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok" if engine.healthy else "degraded",
        "exchange": settings.exchange_id,
        "watchlist": settings.watchlist,
        "poll_interval": settings.poll_interval,
        "ts": time.time(),
    }


@app.get("/liquidity", dependencies=[Depends(require_key)])
async def all_liquidity() -> dict:
    return engine.all_snapshots()


@app.get("/liquidity/{symbol}", dependencies=[Depends(require_key)])
async def symbol_liquidity(symbol: str) -> dict:
    resolved = _resolve_symbol(symbol)
    snap = engine.snapshot(resolved)
    if snap is None or snap.ts <= 0:
        raise HTTPException(status_code=503, detail="no data yet for symbol")
    return snap.to_dict()


@app.get("/liquidity/{symbol}/signal", dependencies=[Depends(require_key)])
async def symbol_signal(symbol: str) -> dict:
    """Condensed directional signal — what mcp-algo / TradingAgents consume.

    direction: "bullish" | "bearish" | "neutral"
    strength:  0.0 - 1.0 composite confidence
    """
    resolved = _resolve_symbol(symbol)
    snap = engine.snapshot(resolved)
    if snap is None or snap.imbalance is None or snap.ts <= 0:
        raise HTTPException(status_code=503, detail="no data yet for symbol")

    imb = snap.imbalance
    score = abs(imb.imbalance)

    # sweep confirmation boosts confidence in the imbalance direction
    sweep_boost = 0.0
    for ev in snap.recent_sweeps:
        if imb.bias == "bullish" and ev.direction == "buy_sweep":
            sweep_boost = 0.25
        elif imb.bias == "bearish" and ev.direction == "sell_sweep":
            sweep_boost = 0.25

    # nearest opposing wall caps the move — reduces confidence
    wall_penalty = 0.0
    for w in snap.walls:
        opposing = (imb.bias == "bullish" and w.side == "ask") or (
            imb.bias == "bearish" and w.side == "bid"
        )
        if opposing and w.distance_pct < 1.0:
            wall_penalty = 0.2
            break

    strength = max(0.0, min(1.0, score + sweep_boost - wall_penalty))
    return {
        "symbol": resolved,
        "ts": snap.ts,
        "direction": imb.bias,
        "strength": round(strength, 4),
        "components": {
            "imbalance": round(imb.imbalance, 4),
            "sweep_boost": sweep_boost,
            "wall_penalty": wall_penalty,
            "spread_assessment": (
                snap.spread_estimate.assessment if snap.spread_estimate else None
            ),
            "liquidity_label": snap.liquidity.label if snap.liquidity else None,
        },
    }


@app.get("/sweeps", dependencies=[Depends(require_key)])
async def recent_sweeps() -> dict:
    events = [e.__dict__ for e in engine.sweep_detector.events]
    return {"count": len(events), "events": events[-50:]}
