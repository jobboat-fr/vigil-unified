"""Market & News — public endpoints for market overview and news feed.

Endpoints:
  GET /api/v1/market/overview — BTC/ETH prices, Fear & Greed, trending
  GET /api/v1/market/news     — public news feed with sentiment
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query

from winny_gateway.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/market", tags=["market"])

# Cache to avoid hammering external APIs
_overview_cache: dict[str, Any] = {}
_overview_ts: float = 0
_CACHE_TTL = 60  # seconds


async def _fetch_market_overview() -> dict[str, Any]:
    """Real market overview — multi-source via gateway.market_enrich.

    BTC/ETH prices + 24h change come from the cross-source consensus
    (CryptoCompare / CoinMarketCap / Coinbase); Fear & Greed from
    alternative.me; dominance from CMC. Fail-soft: any down source is
    omitted rather than faked.
    """
    global _overview_cache, _overview_ts
    import time

    now = time.time()
    if _overview_cache and (now - _overview_ts) < _CACHE_TTL:
        return _overview_cache

    from winny_gateway.market_enrich import enrich_symbol, fear_greed

    btc = await enrich_symbol("BTC/USD")
    eth = await enrich_symbol("ETH/USD")
    fng = await fear_greed()

    def _price(e: dict[str, Any]) -> Any:
        c = (e.get("consensus") or {}).get("price")
        return f"{c:.2f}" if isinstance(c, (int, float)) else None

    def _chg(e: dict[str, Any]) -> Any:
        v = e.get("change_24h_pct")
        return f"{v:.2f}" if isinstance(v, (int, float)) else None

    _overview_cache = {
        "btc_price": _price(btc),
        "btc_24h_change": _chg(btc),
        "eth_price": _price(eth),
        "eth_24h_change": _chg(eth),
        "btc_dominance_pct": btc.get("btc_dominance_pct"),
        "btc_market_cap_usd": btc.get("market_cap_usd"),
        "fear_greed_index": (fng or {}).get("value"),
        "fear_greed_label": (fng or {}).get("label"),
        "btc_sources": list((btc.get("sources") or {}).keys()),
        "asof": datetime.now(timezone.utc).isoformat(),
    }
    _overview_ts = now
    return _overview_cache


async def _fetch_news(page: int = 1, symbol: str | None = None) -> list[dict[str, Any]]:
    """Real crypto news from CryptoCompare (keyless), newest first.

    Falls back to the static seed list only if the upstream is unreachable,
    so the panel never renders empty.
    """
    import httpx

    try:
        params = {"lang": "EN"}
        if symbol:
            params["categories"] = symbol.upper()
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(
                "https://min-api.cryptocompare.com/data/v2/news/", params=params
            )
            r.raise_for_status()
            items = (r.json().get("Data") or [])[:20]
        if items:
            out = []
            for n in items:
                cats = (n.get("categories") or "").upper()
                sym = next((s for s in ("BTC", "ETH", "SOL", "XRP", "ADA") if s in cats), None)
                out.append({
                    "id": str(n.get("id")),
                    "title": n.get("title"),
                    "summary": (n.get("body") or "")[:240],
                    "source": (n.get("source_info") or {}).get("name") or n.get("source"),
                    "url": n.get("url"),
                    "image": n.get("imageurl"),
                    "symbol": sym,
                    "published_at": datetime.fromtimestamp(
                        int(n.get("published_on", 0)), tz=timezone.utc
                    ).isoformat(),
                })
            return out
    except Exception as e:  # noqa: BLE001 — fall through to seed
        logger.debug("market news fetch failed, using seed: %s", e)

    now = datetime.now(timezone.utc).isoformat()
    base_news = [
        {
            "id": "news-1",
            "title": "Bitcoin Breaks $105K as Institutional Demand Surges",
            "summary": "Major financial institutions continue accumulating BTC with spot ETF inflows reaching $1.2B this week.",
            "source": "CoinDesk",
            "url": "https://coindesk.com",
            "symbol": "BTC",
            "sentiment": "bullish",
            "published_at": now,
        },
        {
            "id": "news-2",
            "title": "Ethereum Upgrades Drive Layer-2 Activity to Record Highs",
            "summary": "The Pectra upgrade has reduced L2 costs by 90%, driving unprecedented transaction volumes across Arbitrum and Optimism.",
            "source": "The Block",
            "url": "https://theblock.co",
            "symbol": "ETH",
            "sentiment": "bullish",
            "published_at": now,
        },
        {
            "id": "news-3",
            "title": "SEC Signals Shift on Crypto Regulation Framework",
            "summary": "New SEC guidance suggests a more accommodative stance toward digital asset classification, potentially opening the door for altcoin ETFs.",
            "source": "Reuters",
            "url": "https://reuters.com",
            "symbol": None,
            "sentiment": "neutral",
            "published_at": now,
        },
        {
            "id": "news-4",
            "title": "Solana DeFi TVL Hits New ATH Amid Memecoin Season",
            "summary": "Total value locked on Solana crosses $20B as Jupiter and Raydium see record volumes.",
            "source": "DeFi Llama",
            "url": "https://defillama.com",
            "symbol": "SOL",
            "sentiment": "bullish",
            "published_at": now,
        },
        {
            "id": "news-5",
            "title": "Macro Headwinds: Fed Minutes Show Hawkish Bias",
            "summary": "Federal Reserve minutes reveal concerns about persistent inflation, suggesting rates may stay higher for longer than markets expected.",
            "source": "Bloomberg",
            "url": "https://bloomberg.com",
            "symbol": None,
            "sentiment": "bearish",
            "published_at": now,
        },
    ]

    if symbol:
        base_news = [n for n in base_news if n.get("symbol") == symbol.upper()]

    return base_news


@router.get("/overview")
async def market_overview() -> dict[str, Any]:
    """Public endpoint — no auth required."""
    data = await _fetch_market_overview()
    return {"ok": True, "data": data}


@router.get("/news")
async def market_news(
    page: int = Query(default=1, ge=1),
    symbol: str | None = Query(default=None),
) -> dict[str, Any]:
    """Public endpoint — no auth required."""
    news = await _fetch_news(page=page, symbol=symbol)
    return {"ok": True, "data": news}


def _split_symbol(symbol: str) -> tuple[str, str]:
    """'BTC/USDT' | 'BTC-USD' | 'BTCUSDT' → (base, quote). CryptoCompare uses
    USD, so stablecoin quotes are normalised to USD."""
    s = symbol.upper().replace("-", "/")
    if "/" in s:
        base, quote = s.split("/", 1)
    else:
        for q in ("USDT", "USDC", "USD", "EUR", "BTC", "ETH"):
            if s.endswith(q) and len(s) > len(q):
                base, quote = s[: -len(q)], q
                break
        else:
            base, quote = s, "USD"
    if quote in ("USDT", "USDC", "BUSD"):
        quote = "USD"
    return base, quote


@router.get("/ohlcv/{symbol:path}")
async def market_ohlcv(
    symbol: str,
    timeframe: str = Query(default="hour", pattern="^(hour|minute|day)$"),
    limit: int = Query(default=168, ge=10, le=2000),
) -> dict[str, Any]:
    """Public OHLCV candles for the Trade Desk chart (CryptoCompare, keyless).

    Returns newest-last candles [{t, o, h, l, c, v}] where t is a UNIX seconds
    timestamp. No account data; safe to render on a public chart.
    """
    import httpx

    base, quote = _split_symbol(symbol)
    endpoint = {
        "minute": "histominute",
        "hour": "histohour",
        "day": "histoday",
    }[timeframe]
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                f"https://min-api.cryptocompare.com/data/v2/{endpoint}",
                params={"fsym": base, "tsym": quote, "limit": limit},
            )
            r.raise_for_status()
            body = r.json()
        rows = ((body.get("Data") or {}).get("Data")) or []
        candles = [
            {
                "t": int(c["time"]),
                "o": float(c["open"]),
                "h": float(c["high"]),
                "l": float(c["low"]),
                "c": float(c["close"]),
                "v": float(c.get("volumefrom", 0) or 0),
            }
            for c in rows
            if c.get("close")
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning("market ohlcv fetch failed for %s: %s", symbol, e)
        candles = []

    return {
        "ok": True,
        "data": {
            "symbol": f"{base}/{quote}",
            "timeframe": timeframe,
            "candles": candles,
        },
    }


@router.get("/enrich/{symbol:path}")
async def market_enrich(symbol: str) -> dict[str, Any]:
    """Live cross-source enrichment for one pair (trade-desk drill-down).

    Returns per-source prices (CryptoCompare/CoinMarketCap/Coinbase), the
    consensus + cross-venue spread, 24h volume/market-cap/change, BTC
    dominance, and Fear & Greed — the same figures folded into the signal
    confidence and the analyst debate. Public; no account data.
    """
    from winny_gateway.market_enrich import enrich_symbol

    data = await enrich_symbol(symbol)
    return {"ok": True, "data": data}
