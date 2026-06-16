"""Multi-source market enrichment for signals + the trade desk.

The forecaster builds its call from ONE exchange's OHLCV. This module pulls
the same asset from several independent sources so a signal can be
cross-validated and grounded in real figures:

  * CryptoCompare  — price, 24h volume, 24h change, market cap   (key optional)
  * CoinMarketCap  — price, volume, market cap, rank, BTC dominance (key optional)
  * Coinbase       — spot price                                  (keyless)
  * Fear & Greed   — alternative.me index                        (keyless)

Every fetch is fail-soft: a down/unconfigured source is simply omitted, never
an exception. Results are cached per base asset (default 90s) so the 5-minute
signal pass and dashboard polling don't hammer the upstreams.

The output is consumed by ``gateway.analytics`` (folds cross-source agreement
into signal confidence and stores the figures on the signal row) and can be
served directly to the trade desk.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from statistics import median
from typing import Any

import httpx

from winny_gateway.logging import get_logger

logger = get_logger(__name__)

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL = float(os.getenv("WW_ENRICH_TTL", "90"))
_TIMEOUT = httpx.Timeout(6.0)

# alternative.me Fear & Greed is market-wide (not per-asset) — cache once.
_FNG_CACHE: tuple[float, dict[str, Any] | None] = (0.0, None)
_FNG_TTL = 300.0


def _cmc_key() -> str:
    return (os.getenv("WINNY_CMC_API_KEY") or os.getenv("CMC_API_KEY") or "").strip()


def _cc_key() -> str:
    return (
        os.getenv("WINNY_CRYPTOCOMPARE_API_KEY")
        or os.getenv("CRYPTOCOMPARE_API_KEY")
        or ""
    ).strip()


def _num(v: Any) -> float | None:
    try:
        f = float(v)
        return f if f == f else None  # drop NaN
    except (TypeError, ValueError):
        return None


async def _cryptocompare(client: httpx.AsyncClient, base: str, quote: str) -> dict[str, Any] | None:
    headers = {}
    key = _cc_key()
    if key:
        headers["authorization"] = f"Apikey {key}"
    try:
        r = await client.get(
            "https://min-api.cryptocompare.com/data/pricemultifull",
            params={"fsyms": base, "tsyms": quote},
            headers=headers,
        )
        r.raise_for_status()
        raw = (r.json().get("RAW") or {}).get(base, {}).get(quote)
        if not raw:
            return None
        return {
            "price": _num(raw.get("PRICE")),
            "vol24h_usd": _num(raw.get("TOTALVOLUME24HTO")),
            "change24h_pct": _num(raw.get("CHANGEPCT24HOUR")),
            "mktcap_usd": _num(raw.get("MKTCAP")),
        }
    except Exception as e:  # noqa: BLE001
        logger.debug("enrich.cryptocompare_fail base=%s: %s", base, e)
        return None


async def _coinmarketcap(client: httpx.AsyncClient, base: str, quote: str) -> dict[str, Any] | None:
    key = _cmc_key()
    if not key:
        return None
    try:
        r = await client.get(
            "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest",
            params={"symbol": base, "convert": quote},
            headers={"X-CMC_PRO_API_KEY": key},
        )
        r.raise_for_status()
        entry = (r.json().get("data") or {}).get(base)
        if isinstance(entry, list):
            entry = entry[0] if entry else None
        if not entry:
            return None
        q = (entry.get("quote") or {}).get(quote, {})
        return {
            "price": _num(q.get("price")),
            "vol24h_usd": _num(q.get("volume_24h")),
            "change24h_pct": _num(q.get("percent_change_24h")),
            "mktcap_usd": _num(q.get("market_cap")),
            "rank": entry.get("cmc_rank"),
        }
    except Exception as e:  # noqa: BLE001
        logger.debug("enrich.cmc_fail base=%s: %s", base, e)
        return None


async def _coinbase(client: httpx.AsyncClient, base: str, quote: str) -> dict[str, Any] | None:
    try:
        r = await client.get(f"https://api.coinbase.com/v2/prices/{base}-{quote}/spot")
        r.raise_for_status()
        amt = _num((r.json().get("data") or {}).get("amount"))
        return {"price": amt} if amt else None
    except Exception as e:  # noqa: BLE001
        logger.debug("enrich.coinbase_fail base=%s: %s", base, e)
        return None


async def _cmc_dominance(client: httpx.AsyncClient) -> float | None:
    key = _cmc_key()
    if not key:
        return None
    try:
        r = await client.get(
            "https://pro-api.coinmarketcap.com/v1/global-metrics/quotes/latest",
            headers={"X-CMC_PRO_API_KEY": key},
        )
        r.raise_for_status()
        return _num((r.json().get("data") or {}).get("btc_dominance"))
    except Exception:
        return None


async def fear_greed() -> dict[str, Any] | None:
    """Market-wide Fear & Greed index (alternative.me, keyless, cached 5m)."""
    global _FNG_CACHE
    ts, val = _FNG_CACHE
    if val is not None and (time.time() - ts) < _FNG_TTL:
        return val
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get("https://api.alternative.me/fng/?limit=1")
            r.raise_for_status()
            d = (r.json().get("data") or [{}])[0]
            out = {"value": int(d.get("value", 0)), "label": d.get("value_classification", "")}
            _FNG_CACHE = (time.time(), out)
            return out
    except Exception:
        return val  # stale is fine


async def enrich_symbol(symbol: str, *, exchange_price: float | None = None) -> dict[str, Any]:
    """Cross-source snapshot for a trading pair (e.g. ``BTC/USDT``).

    ``exchange_price`` is the last close the forecaster already has — folded
    in as a fourth price point for the consensus + spread.
    """
    base, _, quote_raw = symbol.replace("-", "/").partition("/")
    base = base.upper().strip() or "BTC"
    quote = (quote_raw or "USD").upper().strip()
    # CMC/Coinbase/CryptoCompare quote in fiat; map stablecoins → USD.
    fiat = "USD" if quote in ("USDT", "USDC", "BUSD", "DAI", "") else quote

    cache_key = f"{base}/{fiat}"
    hit = _CACHE.get(cache_key)
    if hit and (time.time() - hit[0]) < _CACHE_TTL:
        out = dict(hit[1])
        out["exchange_price"] = exchange_price
        return _finalize(out, exchange_price)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        cc, cmc, cb, dom, fng = await asyncio.gather(
            _cryptocompare(client, base, fiat),
            _coinmarketcap(client, base, fiat),
            _coinbase(client, base, fiat),
            _cmc_dominance(client),
            fear_greed(),
        )

    sources: dict[str, Any] = {}
    if cc:
        sources["cryptocompare"] = cc
    if cmc:
        sources["coinmarketcap"] = cmc
    if cb:
        sources["coinbase"] = cb

    enrichment = {
        "asof": datetime.now(UTC).isoformat(),
        "base": base,
        "quote": fiat,
        "sources": sources,
        "btc_dominance_pct": dom,
        "fear_greed": fng,
    }
    _CACHE[cache_key] = (time.time(), enrichment)
    return _finalize(dict(enrichment), exchange_price)


def _finalize(enrichment: dict[str, Any], exchange_price: float | None) -> dict[str, Any]:
    """Derive consensus price, cross-source spread, volume + market cap."""
    sources = enrichment.get("sources") or {}
    prices = [s["price"] for s in sources.values() if _num(s.get("price"))]
    if exchange_price and _num(exchange_price):
        prices.append(float(exchange_price))
        enrichment["exchange_price"] = float(exchange_price)

    if prices:
        mid = median(prices)
        lo, hi = min(prices), max(prices)
        spread_pct = round((hi - lo) / mid * 100, 4) if mid else None
        enrichment["consensus"] = {
            "price": round(mid, 8),
            "spread_pct": spread_pct,
            "n_sources": len(prices),
            "agree": spread_pct is not None and spread_pct <= 0.5,
        }

    vols = [s["vol24h_usd"] for s in sources.values() if _num(s.get("vol24h_usd"))]
    if vols:
        enrichment["volume_24h_usd"] = round(median(vols), 2)
    caps = [s["mktcap_usd"] for s in sources.values() if _num(s.get("mktcap_usd"))]
    if caps:
        enrichment["market_cap_usd"] = round(median(caps), 2)
    changes = [s["change24h_pct"] for s in sources.values() if _num(s.get("change24h_pct"))]
    if changes:
        enrichment["change_24h_pct"] = round(median(changes), 3)
    return enrichment
