"""Liquidity engine — polls exchange order books and runs analytics.

One asyncio task per symbol. Uses ccxt's async support (already a WinnyWoo
dependency). Stateless restart: no persistence, the book re-fills within
one poll cycle.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .analytics import (
    OrderBookSnapshot,
    SpreadEstimator,
    SweepDetector,
    SymbolAnalytics,
    compute_imbalance,
    compute_liquidity_score,
    detect_walls,
)
from .config import Settings

logger = logging.getLogger("liquidity_api.engine")


class LiquidityEngine:
    """Polls order books for a watchlist and maintains per-symbol analytics."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sweep_detector = SweepDetector(
            min_levels_cleared=settings.sweep_min_levels,
            min_notional=settings.sweep_min_notional,
        )
        self.spread_estimator = SpreadEstimator(
            k=settings.spread_k, window=settings.spread_window
        )
        self.state: dict[str, SymbolAnalytics] = {}
        self._exchange: Any = None
        self._tasks: list[asyncio.Task] = []
        self._running = False

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        import ccxt.async_support as ccxt_async

        exchange_cls = getattr(ccxt_async, self.settings.exchange_id, None)
        if exchange_cls is None:
            raise RuntimeError(f"unknown ccxt exchange: {self.settings.exchange_id}")
        self._exchange = exchange_cls({"enableRateLimit": True})
        self._running = True
        for symbol in self.settings.watchlist:
            self.state[symbol] = SymbolAnalytics(symbol=symbol)
            self._tasks.append(asyncio.create_task(self._poll_loop(symbol)))
        logger.info(
            "liquidity engine started: exchange=%s symbols=%s interval=%ss",
            self.settings.exchange_id,
            self.settings.watchlist,
            self.settings.poll_interval,
        )

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self._exchange is not None:
            await self._exchange.close()
        logger.info("liquidity engine stopped")

    # ------------------------------------------------------------------
    # polling
    # ------------------------------------------------------------------

    async def _poll_loop(self, symbol: str) -> None:
        backoff = 1.0
        while self._running:
            try:
                raw = await self._exchange.fetch_order_book(
                    symbol, limit=self.settings.book_depth
                )
                book = OrderBookSnapshot.from_ccxt(symbol, raw)
                self._process(book)
                backoff = 1.0
                await asyncio.sleep(self.settings.poll_interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — provider errors are diverse
                logger.warning("poll error for %s: %s (backoff %.0fs)", symbol, exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    def _process(self, book: OrderBookSnapshot) -> None:
        imbalance = compute_imbalance(
            book,
            band_pct=self.settings.imbalance_band_pct,
            neutral_threshold=self.settings.imbalance_neutral_threshold,
        )
        walls = detect_walls(
            book,
            sigma_threshold=self.settings.wall_sigma_threshold,
            max_distance_pct=self.settings.wall_max_distance_pct,
        )
        sweep = self.sweep_detector.update(book)
        if sweep is not None:
            logger.info(
                "SWEEP %s %s levels=%d notional=%.0f move=%.3f%%",
                sweep.symbol,
                sweep.direction,
                sweep.levels_cleared,
                sweep.notional_consumed,
                sweep.price_move_pct,
            )
        spread_est = self.spread_estimator.update(book)
        liquidity = compute_liquidity_score(
            book, imbalance, reference_depth_notional=self.settings.reference_depth_notional
        )

        analytics = self.state[book.symbol]
        analytics.ts = book.ts
        analytics.mid = book.mid
        analytics.spread_pct = round(book.spread_pct, 6)
        analytics.imbalance = imbalance
        analytics.walls = walls
        analytics.spread_estimate = spread_est
        analytics.liquidity = liquidity
        analytics.recent_sweeps = self.sweep_detector.recent(
            book.symbol, window_seconds=self.settings.sweep_window_seconds
        )

    # ------------------------------------------------------------------
    # accessors
    # ------------------------------------------------------------------

    def snapshot(self, symbol: str) -> SymbolAnalytics | None:
        return self.state.get(symbol)

    def all_snapshots(self) -> dict[str, dict]:
        return {s: a.to_dict() for s, a in self.state.items()}

    @property
    def healthy(self) -> bool:
        if not self.state:
            return False
        now = time.time()
        stale_after = max(self.settings.poll_interval * 5, 30)
        return any(now - a.ts < stale_after for a in self.state.values() if a.ts > 0)
