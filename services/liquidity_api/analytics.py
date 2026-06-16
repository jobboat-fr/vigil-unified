"""Liquidity microstructure analytics — pure functions, no I/O.

Algorithms extracted and re-implemented from market-making bot patterns:
  1. Order book imbalance       — directional pressure from bid/ask depth ratio
  2. Liquidity wall detection   — large resting orders acting as support/resistance
  3. Sweep detection            — aggressive consumption of book levels between snapshots
  4. Dynamic spread estimation  — volatility-adjusted fair spread
  5. Composite liquidity score  — 0-100 health score for a market

All functions operate on plain snapshots so they are trivially testable and
reusable inside WinnyWoo (mcp-algo covariates, TradingAgents context, signals).
"""

from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Core data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BookLevel:
    """One price level in the order book."""

    price: float
    qty: float

    @property
    def notional(self) -> float:
        return self.price * self.qty


@dataclass(frozen=True, slots=True)
class OrderBookSnapshot:
    """Immutable snapshot of an L2 order book at a point in time."""

    symbol: str
    ts: float  # unix epoch seconds (UTC)
    bids: tuple[BookLevel, ...]  # sorted descending by price
    asks: tuple[BookLevel, ...]  # sorted ascending by price

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 0.0

    @property
    def mid(self) -> float:
        if not self.bids or not self.asks:
            return 0.0
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread_pct(self) -> float:
        m = self.mid
        if m <= 0:
            return 0.0
        return (self.best_ask - self.best_bid) / m * 100.0

    @classmethod
    def from_ccxt(cls, symbol: str, raw: dict) -> "OrderBookSnapshot":
        """Build from a ccxt fetch_order_book() payload."""
        ts = (raw.get("timestamp") or time.time() * 1000) / 1000.0
        bids = tuple(BookLevel(price=float(p), qty=float(q)) for p, q, *_ in raw.get("bids", []))
        asks = tuple(BookLevel(price=float(p), qty=float(q)) for p, q, *_ in raw.get("asks", []))
        return cls(symbol=symbol, ts=ts, bids=bids, asks=asks)


# ---------------------------------------------------------------------------
# 1. Order book imbalance
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ImbalanceResult:
    """Bid/ask depth imbalance within a price band around mid.

    `imbalance` in [-1, +1]: +1 = all liquidity on the bid side (bullish
    pressure), -1 = all on the ask side (bearish pressure), 0 = balanced.
    """

    imbalance: float
    bid_notional: float
    ask_notional: float
    band_pct: float
    bias: str  # "bullish" | "bearish" | "neutral"


def compute_imbalance(
    book: OrderBookSnapshot,
    band_pct: float = 1.0,
    neutral_threshold: float = 0.15,
) -> ImbalanceResult:
    """Depth-weighted imbalance within +/- band_pct of mid price.

    Classic order-flow signal: persistent positive imbalance precedes upward
    micro-moves (and vice versa). The band restriction matters — far levels
    are often spoofed or stale, so only near-mid liquidity is meaningful.
    """
    mid = book.mid
    if mid <= 0:
        return ImbalanceResult(0.0, 0.0, 0.0, band_pct, "neutral")

    lo = mid * (1 - band_pct / 100.0)
    hi = mid * (1 + band_pct / 100.0)

    bid_notional = sum(l.notional for l in book.bids if l.price >= lo)
    ask_notional = sum(l.notional for l in book.asks if l.price <= hi)
    total = bid_notional + ask_notional
    if total <= 0:
        return ImbalanceResult(0.0, 0.0, 0.0, band_pct, "neutral")

    imb = (bid_notional - ask_notional) / total
    if imb > neutral_threshold:
        bias = "bullish"
    elif imb < -neutral_threshold:
        bias = "bearish"
    else:
        bias = "neutral"
    return ImbalanceResult(imb, bid_notional, ask_notional, band_pct, bias)


# ---------------------------------------------------------------------------
# 2. Liquidity wall detection
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Wall:
    """A large resting order (or cluster) that may act as support/resistance."""

    side: str  # "bid" | "ask"
    price: float
    qty: float
    notional: float
    sigma: float  # how many std-devs above mean level size
    distance_pct: float  # distance from mid, percent


def detect_walls(
    book: OrderBookSnapshot,
    sigma_threshold: float = 3.0,
    max_distance_pct: float = 5.0,
    top_n: int = 5,
) -> list[Wall]:
    """Find levels whose size is a statistical outlier vs the rest of the book.

    A 'wall' = level qty > mean + sigma_threshold * stddev of all level sizes
    on that side, within max_distance_pct of mid. Bid walls below price act
    as support; ask walls above act as resistance. Note: walls can be spoofed —
    treat as context, never as a sole entry trigger.
    """
    mid = book.mid
    if mid <= 0:
        return []

    walls: list[Wall] = []
    for side, levels in (("bid", book.bids), ("ask", book.asks)):
        near = [
            l for l in levels if abs(l.price - mid) / mid * 100.0 <= max_distance_pct
        ]
        if len(near) < 5:
            continue
        sizes = [l.qty for l in near]
        mean = statistics.fmean(sizes)
        stdev = statistics.pstdev(sizes)
        if stdev <= 0:
            continue
        for l in near:
            sigma = (l.qty - mean) / stdev
            if sigma >= sigma_threshold:
                walls.append(
                    Wall(
                        side=side,
                        price=l.price,
                        qty=l.qty,
                        notional=l.notional,
                        sigma=round(sigma, 2),
                        distance_pct=round(abs(l.price - mid) / mid * 100.0, 4),
                    )
                )
    walls.sort(key=lambda w: w.sigma, reverse=True)
    return walls[:top_n]


# ---------------------------------------------------------------------------
# 3. Sweep detection (stateful — compares consecutive snapshots)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SweepEvent:
    """Aggressive liquidity consumption detected between two snapshots."""

    symbol: str
    ts: float
    direction: str  # "buy_sweep" (asks consumed) | "sell_sweep" (bids consumed)
    levels_cleared: int
    notional_consumed: float
    price_move_pct: float


class SweepDetector:
    """Detects sweeps by diffing consecutive order book snapshots.

    A sweep = N or more price levels on one side disappearing between
    snapshots while the best price moves through them. Indicates aggressive
    market orders eating the book — a strong short-term momentum signal.
    """

    def __init__(
        self,
        min_levels_cleared: int = 3,
        min_notional: float = 10_000.0,
        history_limit: int = 200,
    ) -> None:
        self.min_levels_cleared = min_levels_cleared
        self.min_notional = min_notional
        self.history_limit = history_limit
        self._prev: dict[str, OrderBookSnapshot] = {}
        self.events: list[SweepEvent] = []

    def update(self, book: OrderBookSnapshot) -> SweepEvent | None:
        prev = self._prev.get(book.symbol)
        self._prev[book.symbol] = book
        if prev is None or prev.mid <= 0 or book.mid <= 0:
            return None

        event = self._check_side(prev, book, "buy_sweep") or self._check_side(
            prev, book, "sell_sweep"
        )
        if event is not None:
            self.events.append(event)
            if len(self.events) > self.history_limit:
                self.events = self.events[-self.history_limit :]
        return event

    def _check_side(
        self, prev: OrderBookSnapshot, curr: OrderBookSnapshot, direction: str
    ) -> SweepEvent | None:
        if direction == "buy_sweep":
            # asks consumed: levels with price < new best ask vanished
            old_levels = prev.asks
            boundary = curr.best_ask
            cleared = [l for l in old_levels if l.price < boundary]
            price_move = (curr.best_ask - prev.best_ask) / prev.best_ask * 100.0
            if price_move <= 0:
                return None
        else:
            old_levels = prev.bids
            boundary = curr.best_bid
            cleared = [l for l in old_levels if l.price > boundary]
            price_move = (curr.best_bid - prev.best_bid) / prev.best_bid * 100.0
            if price_move >= 0:
                return None

        notional = sum(l.notional for l in cleared)
        if len(cleared) >= self.min_levels_cleared and notional >= self.min_notional:
            return SweepEvent(
                symbol=curr.symbol,
                ts=curr.ts,
                direction=direction,
                levels_cleared=len(cleared),
                notional_consumed=round(notional, 2),
                price_move_pct=round(price_move, 4),
            )
        return None

    def recent(self, symbol: str, window_seconds: float = 300.0) -> list[SweepEvent]:
        cutoff = time.time() - window_seconds
        return [e for e in self.events if e.symbol == symbol and e.ts >= cutoff]


# ---------------------------------------------------------------------------
# 4. Dynamic spread estimation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SpreadEstimate:
    """Volatility-adjusted fair spread for a market."""

    observed_spread_pct: float
    fair_spread_pct: float
    volatility_pct: float
    assessment: str  # "tight" | "fair" | "wide"


class SpreadEstimator:
    """Tracks mid-price returns to derive a volatility-adjusted fair spread.

    Market-maker logic: fair spread ~ k * sigma(returns). When the observed
    spread is much wider than fair, liquidity is thin / makers are scared
    (risk-off context). When tighter, the market is highly competitive.
    """

    def __init__(self, k: float = 2.0, window: int = 120) -> None:
        self.k = k
        self.window = window
        self._mids: dict[str, list[float]] = {}

    def update(self, book: OrderBookSnapshot) -> SpreadEstimate | None:
        mids = self._mids.setdefault(book.symbol, [])
        if book.mid > 0:
            mids.append(book.mid)
            if len(mids) > self.window:
                del mids[: len(mids) - self.window]
        if len(mids) < 10:
            return None

        rets = [
            math.log(mids[i] / mids[i - 1])
            for i in range(1, len(mids))
            if mids[i - 1] > 0
        ]
        if not rets:
            return None
        vol_pct = statistics.pstdev(rets) * 100.0
        fair = self.k * vol_pct
        observed = book.spread_pct
        if fair <= 0:
            assessment = "fair"
        elif observed > fair * 1.5:
            assessment = "wide"
        elif observed < fair * 0.5:
            assessment = "tight"
        else:
            assessment = "fair"
        return SpreadEstimate(
            observed_spread_pct=round(observed, 6),
            fair_spread_pct=round(fair, 6),
            volatility_pct=round(vol_pct, 6),
            assessment=assessment,
        )


# ---------------------------------------------------------------------------
# 5. Composite liquidity score
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LiquidityScore:
    """0-100 composite market liquidity health score with sub-components."""

    score: float
    depth_score: float
    spread_score: float
    balance_score: float
    label: str  # "excellent" | "good" | "moderate" | "poor"


def compute_liquidity_score(
    book: OrderBookSnapshot,
    imbalance: ImbalanceResult,
    reference_depth_notional: float = 1_000_000.0,
) -> LiquidityScore:
    """Composite score: depth (50%), spread tightness (30%), balance (20%).

    `reference_depth_notional` is the notional within the band considered
    'deep' (100/100). Scale per market cap tier when integrating.
    """
    total_depth = imbalance.bid_notional + imbalance.ask_notional
    depth_score = min(100.0, total_depth / reference_depth_notional * 100.0)

    # spread: 0.01% -> ~100, 1% -> ~0 (log scale)
    sp = max(book.spread_pct, 1e-6)
    spread_score = max(0.0, min(100.0, 50.0 * -math.log10(sp)))

    balance_score = (1.0 - abs(imbalance.imbalance)) * 100.0

    score = depth_score * 0.5 + spread_score * 0.3 + balance_score * 0.2
    if score >= 80:
        label = "excellent"
    elif score >= 60:
        label = "good"
    elif score >= 40:
        label = "moderate"
    else:
        label = "poor"
    return LiquidityScore(
        score=round(score, 2),
        depth_score=round(depth_score, 2),
        spread_score=round(spread_score, 2),
        balance_score=round(balance_score, 2),
        label=label,
    )


# ---------------------------------------------------------------------------
# Aggregated per-symbol state (what the API serves)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SymbolAnalytics:
    """Latest computed analytics for one symbol — serialization-friendly."""

    symbol: str
    ts: float = 0.0
    mid: float = 0.0
    spread_pct: float = 0.0
    imbalance: ImbalanceResult | None = None
    walls: list[Wall] = field(default_factory=list)
    spread_estimate: SpreadEstimate | None = None
    liquidity: LiquidityScore | None = None
    recent_sweeps: list[SweepEvent] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "ts": self.ts,
            "mid": self.mid,
            "spread_pct": self.spread_pct,
            "imbalance": self.imbalance.__dict__ if self.imbalance else None,
            "walls": [w.__dict__ for w in self.walls],
            "spread_estimate": (
                self.spread_estimate.__dict__ if self.spread_estimate else None
            ),
            "liquidity": self.liquidity.__dict__ if self.liquidity else None,
            "recent_sweeps": [e.__dict__ for e in self.recent_sweeps],
        }
