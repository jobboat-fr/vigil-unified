"""Markov Radiation Strategy -- spectral diffusion signals for entry/exit.

Uses the RadiationPredictor from winny.models.markov to generate trading
signals based on:
  - Expected return from the radiated probability distribution
  - Confidence (inverse normalised entropy) as a conviction filter
  - Spectral gap for adaptive regime awareness

Entry logic:
  - LONG  when expected_return > threshold AND confidence > min_confidence
  - SHORT when expected_return < -threshold AND confidence > min_confidence
Exit logic:
  - Exit LONG  when expected_return < 0 OR confidence drops below exit_confidence
  - Exit SHORT when expected_return > 0 OR confidence drops below exit_confidence
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import polars as pl

from winny.engine.strategy import BarMeta, WinnyStrategy
from winny.models.markov import RadiationPredictor, StateEncoder


class MarkovRadiationStrategy(WinnyStrategy):
    """Trading strategy driven by Markov radiation probability diffusion."""

    INTERFACE_VERSION: int = 1
    timeframe: str = "1h"
    startup_candle_count: int = 100
    stoploss: Decimal = Decimal("-0.05")
    minimal_roi: dict[int, Decimal] | None = {  # noqa: RUF012
        0: Decimal("0.04"),
        120: Decimal("0.02"),
        360: Decimal("0.01"),
    }
    can_short: bool = True

    # --- Strategy parameters ---
    entry_return_threshold: float = 0.003  # 0.3% expected return to enter
    min_confidence: float = 0.35
    exit_confidence: float = 0.20
    radiation_alpha: float = 0.80
    radiation_steps: int = 15
    vol_lookback: int = 20  # bars for realised vol estimate
    beta: float = 0.995  # exponential decay for transition matrix

    # Internal state (not serialised)
    _predictor: RadiationPredictor | None = None
    _warmup_done: bool = False
    _last_processed_idx: int = -1  # tracks how far we've fed the model

    def populate_indicators(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        """Compute returns, volatility, relative volume, and Markov predictions."""
        n = len(df)

        # Compute bar-over-bar returns
        close = df["close"].to_numpy().astype(np.float64)
        returns = np.zeros(n, dtype=np.float64)
        returns[1:] = np.diff(close) / np.where(close[:-1] != 0, close[:-1], 1.0)

        # Realised volatility (rolling std of returns)
        vol = np.zeros(n, dtype=np.float64)
        lb = self.vol_lookback
        for i in range(lb, n):
            vol[i] = float(np.std(returns[i - lb + 1 : i + 1]))
        # Fill early bars with first valid vol
        if n > lb:
            vol[:lb] = vol[lb]

        # Relative volume (ratio to rolling mean)
        raw_vol_col = df["volume"].to_numpy().astype(np.float64)
        rel_volume = np.ones(n, dtype=np.float64)
        for i in range(lb, n):
            mean_v = float(np.mean(raw_vol_col[i - lb + 1 : i + 1]))
            if mean_v > 0:
                rel_volume[i] = raw_vol_col[i] / mean_v
        if n > lb:
            rel_volume[:lb] = 1.0

        # Fit or update the predictor
        expected_returns = np.zeros(n, dtype=np.float64)
        confidences = np.zeros(n, dtype=np.float64)
        spectral_gaps = np.zeros(n, dtype=np.float64)

        warmup = max(self.startup_candle_count, lb + 2)

        if n >= warmup:
            if self._predictor is None or not self._warmup_done:
                # Full fit from scratch on the warmup window
                self._predictor = RadiationPredictor(encoder=StateEncoder())
                self._predictor.fit(
                    returns[:warmup],
                    vol[:warmup],
                    rel_volume[:warmup],
                    beta=self.beta,
                )
                self._warmup_done = True
                self._last_processed_idx = warmup - 1

                # Predict for warmup bars (retrospective, not used for signals)
                for i in range(warmup):
                    pred = self._predictor.predict(
                        alpha=self.radiation_alpha,
                        horizon_steps=self.radiation_steps,
                    )
                    expected_returns[i] = pred.expected_return
                    confidences[i] = pred.confidence
                    spectral_gaps[i] = pred.spectral_gap

            # Only process bars we haven't seen yet
            start_idx = max(warmup, self._last_processed_idx + 1)
            for i in range(start_idx, n):
                self._predictor.update(
                    float(returns[i]),
                    float(vol[i]),
                    float(rel_volume[i]),
                )
                pred = self._predictor.predict(
                    alpha=self.radiation_alpha,
                    horizon_steps=self.radiation_steps,
                )
                expected_returns[i] = pred.expected_return
                confidences[i] = pred.confidence
                spectral_gaps[i] = pred.spectral_gap

            self._last_processed_idx = n - 1

            # Fill earlier bars with last-known predictions for indicator continuity
            if start_idx > 0 and start_idx < n:
                last_pred = self._predictor.predict(
                    alpha=self.radiation_alpha,
                    horizon_steps=self.radiation_steps,
                )
                for i in range(min(start_idx, warmup)):
                    expected_returns[i] = last_pred.expected_return
                    confidences[i] = last_pred.confidence
                    spectral_gaps[i] = last_pred.spectral_gap

        return df.with_columns(
            pl.Series("bar_return", returns),
            pl.Series("realised_vol", vol),
            pl.Series("rel_volume", rel_volume),
            pl.Series("markov_expected_return", expected_returns),
            pl.Series("markov_confidence", confidences),
            pl.Series("markov_spectral_gap", spectral_gaps),
        )

    def populate_entry_trend(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        enter_long = (
            (
                (pl.col("markov_expected_return") > self.entry_return_threshold)
                & (pl.col("markov_confidence") > self.min_confidence)
            )
            .cast(pl.Int8)
            .alias("enter_long")
        )

        enter_short = (
            (
                (pl.col("markov_expected_return") < -self.entry_return_threshold)
                & (pl.col("markov_confidence") > self.min_confidence)
            )
            .cast(pl.Int8)
            .alias("enter_short")
        )

        return df.with_columns(enter_long, enter_short)

    def populate_exit_trend(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        exit_long = (
            (
                (pl.col("markov_expected_return") < 0)
                | (pl.col("markov_confidence") < self.exit_confidence)
            )
            .cast(pl.Int8)
            .alias("exit_long")
        )

        exit_short = (
            (
                (pl.col("markov_expected_return") > 0)
                | (pl.col("markov_confidence") < self.exit_confidence)
            )
            .cast(pl.Int8)
            .alias("exit_short")
        )

        return df.with_columns(exit_long, exit_short)
