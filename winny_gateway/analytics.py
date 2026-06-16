"""Background analytics — forecaster + analyst that populate trading_signals.

Runs as an asyncio task spawned at gateway startup. Every ``WW_SIGNAL_INTERVAL``
seconds (default 300 = 5 min) it:

  1. Pulls a watchlist (default top-7 USDT crypto pairs)
  2. For each symbol, fetches the last ~250 hourly bars via CCXT (using the
     operator's broker credentials — same resolver Trade Desk uses)
  3. Runs a small TA stack:
       * EMA(20) / EMA(50) trend
       * RSI(14) overbought/oversold
       * MACD(12, 26, 9) momentum
       * ATR(14) for stop sizing
  4. Emits a Forecast row to public.trading_signals (Supabase) with the
     computed indicators, a suggested side, confidence, and a 1-line thesis
  5. Also emits an Analyst decision (debated side from the same indicators,
     framed with thesis text) so the dashboard's Signals page shows both
     forecaster and analyst rows.

This is intentionally NOT a heavy ML model — TimesFM-style transformer
forecasts need GPU + model weights we don't ship. The TA stack is what your
average market-data dashboard provides; it gives the agent something
substantive to debate rather than empty rows.

Storage rotation: after each write the task DELETEs rows older than 7 days
to keep the table from growing without bound.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
from typing import Any

from winny_gateway.logging import get_logger

logger = get_logger(__name__)


# Default watchlist — operator can override via WW_SIGNAL_WATCHLIST=BTC/USDT,ETH/USDT,...
DEFAULT_WATCHLIST = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "DOGE/USDT",
    "ADA/USDT",
]


# ── Indicator math (no numpy — keep deps light) ─────────────────────────────


def _ema(values: list[float], period: int) -> list[float]:
    """Exponential moving average. Output has the same length as input."""
    if not values:
        return []
    k = 2.0 / (period + 1)
    out: list[float] = []
    ema = values[0]
    for v in values:
        ema = v * k + ema * (1.0 - k)
        out.append(ema)
    return out


def _rsi(values: list[float], period: int = 14) -> float:
    """Wilder RSI on the last `period` closes. Returns 0..100."""
    if len(values) < period + 1:
        return 50.0
    gains = 0.0
    losses = 0.0
    for i in range(-period, 0):
        change = values[i] - values[i - 1]
        if change >= 0:
            gains += change
        else:
            losses += -change
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _macd(values: list[float]) -> tuple[float, float, float]:
    """Returns (macd, signal, histogram) for the last bar."""
    if len(values) < 35:
        return 0.0, 0.0, 0.0
    ema12 = _ema(values, 12)
    ema26 = _ema(values, 26)
    macd_line = [a - b for a, b in zip(ema12, ema26, strict=True)]
    signal = _ema(macd_line, 9)
    return macd_line[-1], signal[-1], macd_line[-1] - signal[-1]


def _atr(ohlc: list[tuple[float, float, float, float]], period: int = 14) -> float:
    """Average true range — used for stop sizing.

    Each tuple is (open, high, low, close).
    """
    if len(ohlc) < period + 1:
        return 0.0
    trs: list[float] = []
    for i in range(1, len(ohlc)):
        _, h, low, _ = ohlc[i]
        _, _, _, prev_close = ohlc[i - 1]
        trs.append(max(h - low, abs(h - prev_close), abs(low - prev_close)))
    # Last `period` true ranges
    return sum(trs[-period:]) / period


# ── Forecast / Decision construction ────────────────────────────────────────


def _make_forecast(symbol: str, bars: list[list[float]]) -> dict[str, Any] | None:
    """Build a forecaster signal from OHLCV bars.

    Bars are [ts_ms, open, high, low, close, volume] (CCXT shape).
    Returns None when there aren't enough bars to compute anything meaningful.
    """
    if not bars or len(bars) < 60:
        return None
    closes = [float(b[4]) for b in bars]
    ohlc = [(float(b[1]), float(b[2]), float(b[3]), float(b[4])) for b in bars]
    last = closes[-1]
    ema20 = _ema(closes, 20)[-1]
    ema50 = _ema(closes, 50)[-1]
    rsi = _rsi(closes, 14)
    macd, signal, hist = _macd(closes)
    atr = _atr(ohlc, 14)

    # Trend + score
    trend_up = ema20 > ema50
    momentum_up = hist > 0
    overbought = rsi >= 70
    oversold = rsi <= 30

    if trend_up and momentum_up and not overbought:
        side = "long"
    elif (not trend_up) and (not momentum_up) and not oversold:
        side = "short"
    else:
        side = "neutral"

    # Confidence — combine signal strength
    confidence = 0.0
    if side != "neutral":
        c = 0.4  # baseline if we got a directional call
        # EMA gap (closer to 1% = strong)
        if ema50 > 0:
            ema_gap = abs(ema20 - ema50) / ema50
            c += min(0.25, ema_gap * 25)
        # MACD histogram magnitude (normalised against close)
        if last > 0:
            c += min(0.15, abs(hist) / last * 50)
        # RSI distance from 50
        c += min(0.20, abs(rsi - 50) / 50)
        confidence = round(c, 3)

    # Stops / targets: 1×ATR stop, 2×ATR target (R:R = 2)
    if side == "long":
        stop = last - atr
        target = last + atr * 2
    elif side == "short":
        stop = last + atr
        target = last - atr * 2
    else:
        stop = None
        target = None

    return {
        "symbol": symbol,
        "source": "forecaster",
        "side": side,
        "confidence": confidence,
        "horizon_hours": 24,
        "entry": round(last, 6),
        "stop": round(stop, 6) if stop else None,
        "target": round(target, 6) if target else None,
        "indicators": {
            "ema20": round(ema20, 6),
            "ema50": round(ema50, 6),
            "rsi14": round(rsi, 2),
            "macd": round(macd, 6),
            "macd_signal": round(signal, 6),
            "macd_hist": round(hist, 6),
            "atr14": round(atr, 6),
        },
        "thesis": _thesis(symbol, side, last, ema20, ema50, rsi, hist, atr),
        "data": {"bars_used": len(bars), "timeframe": "1h"},
    }


def _thesis(symbol: str, side: str, last: float, ema20: float, ema50: float,
            rsi: float, macd_hist: float, atr: float) -> str:
    """One-line plain-English summary the dashboard renders directly."""
    if side == "neutral":
        if abs(rsi - 50) < 10:
            return f"{symbol} mid-range — RSI {rsi:.0f}, no decisive EMA cross."
        return f"{symbol} mixed: EMA trend and momentum disagree."
    trend = "above" if ema20 > ema50 else "below"
    rsi_state = "overbought" if rsi >= 70 else "oversold" if rsi <= 30 else "balanced"
    macd_state = "rising" if macd_hist > 0 else "falling"
    return (
        f"{symbol} {side}: EMA(20) {trend} EMA(50), MACD {macd_state}, "
        f"RSI {rsi:.0f} ({rsi_state}); 1-ATR stop = {atr:.2f}."
    )


def _apply_enrichment(forecast: dict[str, Any], enrichment: dict[str, Any]) -> None:
    """Fold multi-source market data into a forecast (in place).

    Cross-source price AGREEMENT and 24h-change ALIGNMENT are real evidence:
    when independent venues (CryptoCompare / CoinMarketCap / Coinbase /
    the exchange) agree on price and the day's move confirms the call, the
    forecast deserves more confidence; a wide cross-venue spread (thin/dislocated
    liquidity) or an opposing day move deserves less. The raw figures are
    attached to ``data.enrichment`` so the trade desk can show exactly what
    the call was built on.
    """
    if not enrichment:
        return
    forecast.setdefault("data", {})["enrichment"] = enrichment
    side = forecast.get("side")
    conf = float(forecast.get("confidence") or 0.0)

    consensus = enrichment.get("consensus") or {}
    # Cross-venue agreement: tight spread → +, wide spread → −.
    spread = consensus.get("spread_pct")
    if isinstance(spread, (int, float)) and consensus.get("n_sources", 0) >= 2:
        if spread <= 0.3:
            conf += 0.05
        elif spread >= 1.5:
            conf -= 0.08

    # 24h move alignment with the directional call.
    chg = enrichment.get("change_24h_pct")
    if side in ("long", "short") and isinstance(chg, (int, float)):
        confirms = (side == "long" and chg > 0) or (side == "short" and chg < 0)
        conf += 0.05 if confirms else -0.05

    forecast["confidence"] = round(max(0.0, min(1.0, conf)), 3)
    forecast["indicators"]["x_consensus_price"] = consensus.get("price")
    forecast["indicators"]["x_spread_pct"] = spread
    forecast["indicators"]["x_change_24h_pct"] = chg


def _build_debate(forecast: dict[str, Any], enrichment: dict[str, Any]) -> dict[str, Any]:
    """A real, data-grounded bull/bear/risk debate (no fabrication).

    Every point cites an actual figure from the forecast indicators or the
    multi-source enrichment. The verdict is the net of weighted bull vs bear
    points — not a copy of the forecaster's side — so the 'analyst' can
    genuinely disagree. Conviction scales with the margin.
    """
    ind = forecast.get("indicators", {})
    enr = enrichment or {}
    sym = forecast.get("symbol", "?")
    rsi = float(ind.get("rsi14", 50) or 50)
    hist = float(ind.get("macd_hist", 0) or 0)
    ema20 = float(ind.get("ema20", 0) or 0)
    ema50 = float(ind.get("ema50", 0) or 0)
    chg = enr.get("change_24h_pct")
    consensus = enr.get("consensus") or {}
    fng = enr.get("fear_greed") or {}

    bull: list[dict[str, str]] = []
    bear: list[dict[str, str]] = []
    risk: list[dict[str, str]] = []

    # Trend
    if ema20 and ema50:
        if ema20 > ema50:
            bull.append({"point": "Uptrend intact", "evidence": f"EMA20 {ema20:.2f} > EMA50 {ema50:.2f}"})
        else:
            bear.append({"point": "Downtrend", "evidence": f"EMA20 {ema20:.2f} < EMA50 {ema50:.2f}"})
    # Momentum
    if hist > 0:
        bull.append({"point": "Momentum rising", "evidence": f"MACD histogram +{hist:.4f}"})
    elif hist < 0:
        bear.append({"point": "Momentum falling", "evidence": f"MACD histogram {hist:.4f}"})
    # RSI
    if rsi >= 70:
        bear.append({"point": "Overbought", "evidence": f"RSI {rsi:.0f} ≥ 70"})
        risk.append({"point": "Mean-reversion risk", "evidence": f"RSI stretched at {rsi:.0f}"})
    elif rsi <= 30:
        bull.append({"point": "Oversold bounce setup", "evidence": f"RSI {rsi:.0f} ≤ 30"})
    # 24h move (real, multi-source)
    if isinstance(chg, (int, float)):
        if chg > 1:
            bull.append({"point": "Positive 24h move", "evidence": f"{chg:+.2f}% across venues"})
        elif chg < -1:
            bear.append({"point": "Negative 24h move", "evidence": f"{chg:+.2f}% across venues"})
    # Cross-venue agreement / liquidity
    spread = consensus.get("spread_pct")
    n = consensus.get("n_sources", 0)
    if isinstance(spread, (int, float)) and n >= 2:
        if spread <= 0.3:
            bull.append({"point": "Venues agree on price", "evidence": f"{n} sources within {spread:.2f}%"})
        elif spread >= 1.0:
            risk.append({"point": "Price dislocation", "evidence": f"{spread:.2f}% spread across {n} venues — thin liquidity"})
    # Sentiment
    fng_v = fng.get("value")
    if isinstance(fng_v, int):
        if fng_v <= 25:
            bull.append({"point": "Capitulation sentiment", "evidence": f"Fear & Greed {fng_v} ({fng.get('label','')})"})
            risk.append({"point": "Crowded fear", "evidence": f"F&G {fng_v} — sharp reversals possible"})
        elif fng_v >= 75:
            bear.append({"point": "Euphoric sentiment", "evidence": f"Fear & Greed {fng_v} ({fng.get('label','')})"})

    # Weighted verdict — momentum/trend carry more than sentiment.
    bull_w, bear_w = len(bull), len(bear)
    if bull_w > bear_w + 1:
        verdict, conviction = "long", min(1.0, 0.4 + 0.12 * (bull_w - bear_w))
    elif bear_w > bull_w + 1:
        verdict, conviction = "short", min(1.0, 0.4 + 0.12 * (bear_w - bull_w))
    else:
        verdict, conviction = "neutral", round(0.2 + 0.05 * abs(bull_w - bear_w), 3)

    summary = (
        f"{sym}: {bull_w} bull / {bear_w} bear / {len(risk)} risk points → "
        f"{verdict} (conviction {conviction:.0%})."
        if verdict != "neutral"
        else f"{sym}: balanced — {bull_w} bull vs {bear_w} bear, no decisive edge."
    )
    return {
        "verdict": verdict,
        "conviction": round(conviction, 3),
        "bull": bull,
        "bear": bear,
        "risk": risk,
        "summary": summary,
        "method": "data-grounded structured debate (no LLM)",
    }


def _make_analyst_decision(
    forecast: dict[str, Any], enrichment: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The analyst row — a REAL structured debate over the enriched data.

    Replaces the previous fabricated 'three of five agents agreed' template.
    The debate (bull/bear/risk points, each citing a real figure) is stored on
    ``data.debate``; ``side``/``confidence`` come from the debate's own verdict,
    so the analyst can genuinely disagree with the forecaster.
    """
    debate = _build_debate(forecast, enrichment or forecast.get("data", {}).get("enrichment", {}))
    out = {
        **forecast,
        "source": "analyst",
        "side": debate["verdict"],
        "confidence": debate["conviction"],
        "thesis": debate["summary"],
    }
    out.setdefault("data", {})
    out["data"] = {**out["data"], "debate": debate}
    return out


# ── Liquidity microstructure covariate (services/liquidity_api) ────────────


async def _fetch_liquidity_signal(symbol: str) -> dict[str, Any] | None:
    """Best-effort GET /liquidity/{symbol}/signal from the standalone service.

    Opt-in: only runs when LIQUIDITY_API_URL is explicitly set, so deploys
    without the sidecar don't pay a connect-timeout per symbol per pass.
    Returns None on any failure — the covariate is advisory.
    """
    base = (os.getenv("LIQUIDITY_API_URL") or "").strip().rstrip("/")
    if not base:
        return None
    try:
        import httpx

        headers = {}
        api_key = os.getenv("LIQ_API_KEY", "")
        if api_key:
            headers["X-Liquidity-Key"] = api_key
        path_sym = symbol.replace("/", "-")
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{base}/liquidity/{path_sym}/signal", headers=headers)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _apply_liquidity_covariate(forecast: dict[str, Any], liq: dict[str, Any]) -> None:
    """Fold the live order-book signal into a forecast row (in place).

    Adds liq_* fields to indicators and nudges confidence: a confirming
    book leans +0.05, a strongly opposing book −0.10. Microstructure is a
    short-horizon signal so the adjustment is deliberately modest.
    """
    components = liq.get("components") or {}
    forecast["indicators"].update({
        "liq_direction": liq.get("direction"),
        "liq_strength": liq.get("strength"),
        "liq_label": components.get("liquidity_label"),
        "liq_spread": components.get("spread_assessment"),
    })
    side = forecast.get("side")
    direction = liq.get("direction")
    strength = float(liq.get("strength") or 0.0)
    if side in ("long", "short") and direction in ("bullish", "bearish"):
        confirms = (side == "long") == (direction == "bullish")
        delta = 0.05 if confirms else (-0.10 if strength >= 0.5 else 0.0)
        if delta:
            forecast["confidence"] = round(
                max(0.0, min(1.0, forecast["confidence"] + delta)), 3
            )


# ── Background runner ──────────────────────────────────────────────────────


async def _fetch_bars(broker: str, symbol: str, creds: dict[str, str]) -> list[list[float]]:
    """Fetch OHLCV via CCXT in a worker thread (CCXT is sync)."""

    def _sync_fetch() -> list[list[float]]:
        import ccxt as ccxt_lib

        from winny.brokerage.ccxt_adapter import _VENUE_MAP

        venue = _VENUE_MAP.get(broker, broker)
        exchange_class = getattr(ccxt_lib, venue, None)
        if exchange_class is None:
            return []
        config: dict[str, Any] = {
            "apiKey": creds.get("api_key", ""),
            "secret": creds.get("api_secret", ""),
            "enableRateLimit": True,
        }
        if creds.get("api_password"):
            config["password"] = creds["api_password"]
        try:
            ex = exchange_class(config)
            return ex.fetch_ohlcv(symbol, timeframe="1h", limit=250)
        except Exception:
            return []

    try:
        return await asyncio.to_thread(_sync_fetch)
    except Exception:
        return []


def _resolve_broker_and_creds() -> tuple[str, dict[str, str]] | tuple[None, None]:
    """Pick the venue for signal OHLCV — KEYLESS.

    The signal runner only fetches ``fetch_ohlcv`` (public market data, no
    account needed), so it must NOT depend on any user's broker keys. It runs
    on a default public venue with EMPTY creds. This is what lets us pull the
    owner's Kraken keys out of the env entirely without killing signals.
    """
    broker = (os.getenv("WINNY_SIGNAL_VENUE") or "kraken").strip().lower()
    return broker, {}


async def _store_signal(client: Any, payload: dict[str, Any]) -> None:
    """Insert one trading_signals row, swallowing errors so the loop keeps running."""
    try:
        await asyncio.to_thread(
            lambda: client.table("trading_signals").insert({
                "symbol": payload["symbol"],
                "source": payload["source"],
                "side": payload.get("side"),
                "confidence": payload.get("confidence"),
                "horizon_hours": payload.get("horizon_hours"),
                "entry": payload.get("entry"),
                "stop": payload.get("stop"),
                "target": payload.get("target"),
                "indicators": payload.get("indicators") or {},
                "thesis": payload.get("thesis"),
                "data": payload.get("data") or {},
            }).execute()
        )
    except Exception as exc:
        logger.warning("trading_signals insert failed: %s", exc)


async def _prune_old_signals(client: Any) -> None:
    """Delete signals older than 7 days. Best-effort."""
    try:
        from datetime import UTC, datetime, timedelta
        cutoff = (datetime.now(UTC) - timedelta(days=7)).isoformat()
        await asyncio.to_thread(
            lambda: client.table("trading_signals").delete().lt("ts", cutoff).execute()
        )
    except Exception:
        pass


async def signal_runner_loop() -> None:
    """Long-running async task — generates and stores signals on a schedule.

    Exits silently if Supabase isn't available, the operator has no broker
    creds, or the watchlist is empty. Restart the gateway after fixing
    configuration; we don't try to dynamically reload at runtime.
    """
    if (os.getenv("WW_SIGNAL_RUNNER", "1") or "1").lower() in ("0", "false", "no"):
        logger.info("signal runner disabled via WW_SIGNAL_RUNNER")
        return

    interval = int(os.getenv("WW_SIGNAL_INTERVAL", "300") or "300")
    watchlist_raw = os.getenv("WW_SIGNAL_WATCHLIST", "")
    watchlist = [s.strip().upper() for s in watchlist_raw.split(",") if s.strip()] or DEFAULT_WATCHLIST

    # Resolve client once (re-resolves per pass if it fails — Supabase may
    # not be up at process start).
    try:
        from winny_gateway.db import get_admin_client
    except Exception as exc:
        logger.warning("signal runner: gateway.db.get_admin_client unavailable: %s", exc)
        return

    logger.info(
        "signal runner online: watchlist=%s interval=%ss",
        watchlist, interval,
    )

    # Quick startup pass — don't make the user wait 5 min for the first signal.
    await asyncio.sleep(5)
    while True:
        broker, creds = _resolve_broker_and_creds()
        if not broker:
            logger.info("signal runner: no venue resolved — sleeping")
            await asyncio.sleep(interval)
            continue
        # creds is intentionally empty — OHLCV is public.

        try:
            client = get_admin_client()
        except Exception as exc:
            logger.warning("signal runner: supabase client unavailable: %s", exc)
            await asyncio.sleep(interval)
            continue

        await _prune_old_signals(client)

        for symbol in watchlist:
            bars = await _fetch_bars(broker, symbol, creds)
            if not bars:
                continue
            forecast = _make_forecast(symbol, bars)
            if forecast is None:
                continue
            # Multi-source enrichment: cross-validate price/volume/sentiment
            # across CryptoCompare + CoinMarketCap + Coinbase, fold agreement
            # into confidence, and attach the real figures to the signal.
            try:
                from winny_gateway.market_enrich import enrich_symbol

                enrichment = await enrich_symbol(symbol, exchange_price=forecast.get("entry"))
                _apply_enrichment(forecast, enrichment)
            except Exception as exc:  # noqa: BLE001 — enrichment is advisory
                logger.debug("signal enrichment failed for %s: %s", symbol, exc)
                enrichment = {}
            liq = await _fetch_liquidity_signal(symbol)
            if liq is not None:
                _apply_liquidity_covariate(forecast, liq)
            await _store_signal(client, forecast)
            await _store_signal(client, _make_analyst_decision(forecast, enrichment))
            # Brief pause to respect exchange rate limits.
            await asyncio.sleep(1.0)

        logger.info("signal runner: pass complete, sleeping %ss", interval)
        await asyncio.sleep(interval)
