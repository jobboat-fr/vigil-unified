"""Settings for the liquidity API — env-driven, sane defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _split_csv(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


@dataclass(slots=True)
class Settings:
    # exchange / watchlist
    exchange_id: str = field(
        default_factory=lambda: os.getenv("LIQ_EXCHANGE", "binance")
    )
    watchlist: list[str] = field(
        default_factory=lambda: _split_csv(
            os.getenv("LIQ_WATCHLIST", "BTC/USDT,ETH/USDT,SOL/USDT")
        )
    )
    poll_interval: float = field(
        default_factory=lambda: float(os.getenv("LIQ_POLL_INTERVAL", "5"))
    )
    book_depth: int = field(default_factory=lambda: int(os.getenv("LIQ_BOOK_DEPTH", "100")))

    # imbalance
    imbalance_band_pct: float = field(
        default_factory=lambda: float(os.getenv("LIQ_IMBALANCE_BAND_PCT", "1.0"))
    )
    imbalance_neutral_threshold: float = field(
        default_factory=lambda: float(os.getenv("LIQ_IMBALANCE_NEUTRAL", "0.15"))
    )

    # walls
    wall_sigma_threshold: float = field(
        default_factory=lambda: float(os.getenv("LIQ_WALL_SIGMA", "3.0"))
    )
    wall_max_distance_pct: float = field(
        default_factory=lambda: float(os.getenv("LIQ_WALL_MAX_DIST_PCT", "5.0"))
    )

    # sweeps
    sweep_min_levels: int = field(
        default_factory=lambda: int(os.getenv("LIQ_SWEEP_MIN_LEVELS", "3"))
    )
    sweep_min_notional: float = field(
        default_factory=lambda: float(os.getenv("LIQ_SWEEP_MIN_NOTIONAL", "10000"))
    )
    sweep_window_seconds: float = field(
        default_factory=lambda: float(os.getenv("LIQ_SWEEP_WINDOW_SECONDS", "300"))
    )

    # spread estimator
    spread_k: float = field(default_factory=lambda: float(os.getenv("LIQ_SPREAD_K", "2.0")))
    spread_window: int = field(
        default_factory=lambda: int(os.getenv("LIQ_SPREAD_WINDOW", "120"))
    )

    # liquidity score
    reference_depth_notional: float = field(
        default_factory=lambda: float(os.getenv("LIQ_REF_DEPTH_NOTIONAL", "1000000"))
    )

    # server
    host: str = field(default_factory=lambda: os.getenv("LIQ_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("LIQ_PORT", "8600")))
    api_key: str = field(default_factory=lambda: os.getenv("LIQ_API_KEY", ""))
