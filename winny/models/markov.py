"""Markov Radiation Predictor -- spectral diffusion on discretised price states.

The model combines three ideas:

1. **Enriched state space**: price returns, realised volatility, and relative
   volume are jointly quantile-binned so that the Markov state encodes short-
   term memory that a return-only chain would miss.

2. **Spectral radiation**: instead of a single-step transition forecast, the
   transition matrix is eigen-decomposed. Each eigenmode decays at a rate set
   by its eigenvalue, and a horizon-adaptive weighting produces a *radiated*
   probability distribution whose shape changes with the prediction horizon.

3. **Entropy-gated confidence**: Shannon entropy of the radiated distribution
   is normalised to [0, 1] and inverted to produce a *confidence* score.
   Low-entropy peaks mean the model is certain; high entropy means "no edge".

Mathematical reference
----------------------
Let T be the N x N row-stochastic transition matrix estimated with
exponential weighting (half-life beta).  Its eigendecomposition is

    T = V diag(lambda) V^{-1}

The radiated distribution for initial state i and horizon parameter alpha is

    p_rad = sum_{k=1}^{K} alpha^k * T^k * e_i
          = V diag( alpha*lambda / (1 - alpha*lambda) ) V^{-1} * e_i

where e_i is the one-hot vector for state i.

The spectral gap (1 - |lambda_2|) measures mixing speed:
  - small gap  =>  persistent regimes  =>  momentum edge
  - large gap  =>  fast mean-reversion  =>  reversion edge
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray

# ===================================================================
# Value objects
# ===================================================================


class RegimeType(StrEnum):
    """Dominant market regime inferred from spectral gap."""

    TRENDING = "trending"
    REVERTING = "reverting"
    CHAOTIC = "chaotic"


class ReturnBucket(StrEnum):
    """Human-readable labels for discretised return bins."""

    STRONG_DOWN = "strong_down"
    DOWN = "down"
    FLAT = "flat"
    UP = "up"
    STRONG_UP = "strong_up"


@dataclass(frozen=True, slots=True)
class MarkovPrediction:
    """Output of RadiationPredictor.predict()."""

    expected_return: float
    confidence: float  # 0..1, higher = more concentrated distribution
    dominant_regime: RegimeType
    spectral_gap: float
    state_distribution: dict[int, float]  # state_index -> probability
    current_state: int
    current_state_label: str


# ===================================================================
# StateEncoder
# ===================================================================

_DEFAULT_RETURN_EDGES: tuple[float, ...] = (-0.02, -0.005, 0.005, 0.02)
_DEFAULT_VOL_QUANTILES: int = 3
_DEFAULT_VOLUME_QUANTILES: int = 3


@dataclass(slots=True)
class StateEncoder:
    """Map (return, volatility, volume) -> discrete state index.

    Uses fixed edges for returns (interpretable buckets) and adaptive
    quantile boundaries for volatility and volume (fitted from data).

    Total states = len(return_edges)+1  *  vol_bins  *  volume_bins
                 = 5 * 3 * 3 = 45  by default.
    """

    return_edges: tuple[float, ...] = _DEFAULT_RETURN_EDGES
    vol_bins: int = _DEFAULT_VOL_QUANTILES
    volume_bins: int = _DEFAULT_VOLUME_QUANTILES

    # Fitted quantile edges (set by fit())
    _vol_edges: NDArray[np.float64] = field(default_factory=lambda: np.array([], dtype=np.float64))
    _volume_edges: NDArray[np.float64] = field(
        default_factory=lambda: np.array([], dtype=np.float64)
    )

    @property
    def n_return_bins(self) -> int:
        return len(self.return_edges) + 1

    @property
    def n_states(self) -> int:
        return self.n_return_bins * self.vol_bins * self.volume_bins

    def fit(
        self,
        volatilities: NDArray[np.float64],
        volumes: NDArray[np.float64],
    ) -> None:
        """Compute quantile edges for volatility and volume from training data."""
        vol_quantiles = np.linspace(0, 100, self.vol_bins + 1)[1:-1]
        self._vol_edges = np.percentile(volatilities[np.isfinite(volatilities)], vol_quantiles)

        volume_quantiles = np.linspace(0, 100, self.volume_bins + 1)[1:-1]
        self._volume_edges = np.percentile(volumes[np.isfinite(volumes)], volume_quantiles)

    def encode(self, ret: float, vol: float, volume: float) -> int:
        """Encode a single observation into a state index."""
        r_bin = int(np.searchsorted(self.return_edges, ret))
        v_bin = int(np.searchsorted(self._vol_edges, vol)) if len(self._vol_edges) > 0 else 0
        vol_bin = (
            int(np.searchsorted(self._volume_edges, volume)) if len(self._volume_edges) > 0 else 0
        )

        # Clamp to valid range
        v_bin = min(v_bin, self.vol_bins - 1)
        vol_bin = min(vol_bin, self.volume_bins - 1)

        return r_bin * (self.vol_bins * self.volume_bins) + v_bin * self.volume_bins + vol_bin

    def decode_return_bucket(self, state: int) -> ReturnBucket:
        """Extract the return bucket label from a state index."""
        r_bin = state // (self.vol_bins * self.volume_bins)
        labels = list(ReturnBucket)
        r_bin = min(r_bin, len(labels) - 1)
        return labels[r_bin]

    def return_midpoints(self) -> NDArray[np.float64]:
        """Midpoint of each return bin, used to map states back to expected returns."""
        edges = list(self.return_edges)
        # Synthetic outer edges: mirror the outermost gap
        low = edges[0] - (edges[1] - edges[0]) if len(edges) > 1 else edges[0] * 2
        high = edges[-1] + (edges[-1] - edges[-2]) if len(edges) > 1 else edges[-1] * 2
        all_edges = [low, *edges, high]
        mids = [(all_edges[i] + all_edges[i + 1]) / 2 for i in range(len(all_edges) - 1)]
        return np.array(mids, dtype=np.float64)


# ===================================================================
# SpectralTransitionModel
# ===================================================================

_LAPLACE_ALPHA: float = 1.0  # Dirichlet prior strength


@dataclass(slots=True)
class SpectralTransitionModel:
    """Exponentially-weighted transition matrix with eigendecomposition.

    The matrix is updated online via rank-1 count increments. The eigen-
    decomposition is recomputed lazily (only when ``radiate`` is called
    after new data has been ingested).

    Parameters
    ----------
    n_states : int
        Dimensionality of the state space.
    beta : float
        Exponential decay factor in (0, 1].  beta=1 means no decay (all
        history weighted equally).  Lower values track regime changes faster.
    laplace_alpha : float
        Dirichlet prior pseudo-count for Bayesian smoothing.
    """

    n_states: int
    beta: float = 0.995
    laplace_alpha: float = _LAPLACE_ALPHA

    # Internal state
    _counts: NDArray[np.float64] = field(init=False)
    _dirty: bool = field(init=False, default=True)
    _eigenvalues: NDArray[np.complex128] = field(init=False)
    _eigenvectors: NDArray[np.complex128] = field(init=False)
    _eigenvectors_inv: NDArray[np.complex128] = field(init=False)
    _transition_matrix: NDArray[np.float64] = field(init=False)

    def __post_init__(self) -> None:
        n = self.n_states
        self._counts = np.full((n, n), self.laplace_alpha, dtype=np.float64)
        self._eigenvalues = np.zeros(n, dtype=np.complex128)
        self._eigenvectors = np.eye(n, dtype=np.complex128)
        self._eigenvectors_inv = np.eye(n, dtype=np.complex128)
        self._transition_matrix = np.full((n, n), 1.0 / n, dtype=np.float64)

    def update(self, old_state: int, new_state: int) -> None:
        """Record a state transition. Applies exponential decay to all counts."""
        # Decay existing counts
        self._counts *= self.beta
        # Increment the observed transition
        self._counts[old_state, new_state] += 1.0
        self._dirty = True

    def update_batch(self, states: Sequence[int]) -> None:
        """Ingest a sequence of states (e.g. from a warmup window)."""
        for i in range(len(states) - 1):
            self.update(states[i], states[i + 1])

    def _rebuild(self) -> None:
        """Recompute transition matrix and eigendecomposition."""
        # Row-normalise counts to get T
        row_sums = self._counts.sum(axis=1, keepdims=True)
        row_sums = np.where(row_sums > 0, row_sums, 1.0)  # avoid div-by-zero
        self._transition_matrix = self._counts / row_sums

        # Eigendecomposition (right eigenvectors: T = V diag(lam) V^-1)
        eigenvalues, eigenvectors = np.linalg.eig(self._transition_matrix.T)

        # Sort by descending magnitude
        order = np.argsort(-np.abs(eigenvalues))
        self._eigenvalues = eigenvalues[order]
        self._eigenvectors = eigenvectors[:, order]

        # Pseudo-inverse for numerical stability
        self._eigenvectors_inv = np.linalg.pinv(self._eigenvectors).astype(np.complex128)
        self._dirty = False

    @property
    def transition_matrix(self) -> NDArray[np.float64]:
        if self._dirty:
            self._rebuild()
        return self._transition_matrix

    def spectral_gap(self) -> float:
        """1 - |lambda_2|.  Measures how fast the chain mixes."""
        if self._dirty:
            self._rebuild()
        if len(self._eigenvalues) < 2:
            return 1.0
        return float(1.0 - abs(self._eigenvalues[1]))

    def radiate(
        self,
        current_state: int,
        alpha: float = 0.8,
        max_steps: int = 20,
    ) -> NDArray[np.float64]:
        """Compute the radiated probability distribution.

        Parameters
        ----------
        current_state : int
            Index of the current state (one-hot source).
        alpha : float
            Decay factor per step.  Higher = longer-range radiation.
        max_steps : int
            Truncation of the Neumann series (K in the formula).

        Returns
        -------
        NDArray of shape (n_states,) -- normalised probability distribution.
        """
        if self._dirty:
            self._rebuild()

        n = self.n_states
        p = np.zeros(n, dtype=np.float64)
        t_power = np.eye(n, dtype=np.float64)  # T^0 = I

        for k in range(1, max_steps + 1):
            t_power = t_power @ self._transition_matrix
            weight = alpha**k
            p += weight * t_power[current_state]

        # Normalise to a proper distribution
        total = p.sum()
        if total > 0:
            p /= total
        else:
            p = np.full(n, 1.0 / n)

        return p

    def regime(self) -> RegimeType:
        """Classify the current market regime from spectral gap."""
        gap = self.spectral_gap()
        if gap < 0.15:
            return RegimeType.TRENDING
        if gap > 0.5:
            return RegimeType.REVERTING
        return RegimeType.CHAOTIC


# ===================================================================
# RadiationPredictor
# ===================================================================


def _shannon_entropy(p: NDArray[np.float64]) -> float:
    """Shannon entropy in nats.  Filters out zero-probability states."""
    mask = p > 0
    return float(-np.sum(p[mask] * np.log(p[mask])))


@dataclass(slots=True)
class RadiationPredictor:
    """Combines StateEncoder + SpectralTransitionModel into a predictor.

    Usage
    -----
    1. ``fit(returns, volatilities, volumes)`` to initialise from history.
    2. ``update(ret, vol, volume)`` on each new bar.
    3. ``predict(alpha, horizon_steps)`` to get the next-bar forecast.
    """

    encoder: StateEncoder = field(default_factory=StateEncoder)
    model: SpectralTransitionModel = field(init=False)
    _prev_state: int | None = field(init=False, default=None)
    _fitted: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.model = SpectralTransitionModel(n_states=self.encoder.n_states)

    def fit(
        self,
        returns: NDArray[np.float64],
        volatilities: NDArray[np.float64],
        volumes: NDArray[np.float64],
        *,
        beta: float = 0.995,
    ) -> None:
        """Warm up from historical arrays (all same length).

        Parameters
        ----------
        returns : array of bar-over-bar log-returns
        volatilities : array of realised volatility estimates
        volumes : array of raw or relative volumes
        beta : exponential decay for transition counting
        """
        n = len(returns)
        if n < 2:
            return

        self.encoder.fit(volatilities, volumes)
        self.model = SpectralTransitionModel(
            n_states=self.encoder.n_states,
            beta=beta,
        )

        # Encode all bars to states
        states = [
            self.encoder.encode(float(returns[i]), float(volatilities[i]), float(volumes[i]))
            for i in range(n)
        ]

        # Bulk-load transitions
        self.model.update_batch(states)
        self._prev_state = states[-1]
        self._fitted = True

    def update(self, ret: float, vol: float, volume: float) -> None:
        """Ingest one new bar observation and update the transition model."""
        new_state = self.encoder.encode(ret, vol, volume)
        if self._prev_state is not None:
            self.model.update(self._prev_state, new_state)
        self._prev_state = new_state
        self._fitted = True

    def predict(
        self,
        alpha: float = 0.8,
        horizon_steps: int = 20,
    ) -> MarkovPrediction:
        """Produce a prediction from the current state.

        Parameters
        ----------
        alpha : float
            Radiation decay.  0.5 = short-range, 0.95 = long-range.
        horizon_steps : int
            Maximum diffusion steps in the Neumann series.

        Returns
        -------
        MarkovPrediction with expected return, confidence, regime, etc.
        """
        if self._prev_state is None or not self._fitted:
            return MarkovPrediction(
                expected_return=0.0,
                confidence=0.0,
                dominant_regime=RegimeType.CHAOTIC,
                spectral_gap=1.0,
                state_distribution={},
                current_state=-1,
                current_state_label="unknown",
            )

        # Radiate probability from current state
        dist = self.model.radiate(self._prev_state, alpha=alpha, max_steps=horizon_steps)

        # Map distribution to expected return
        midpoints = self.encoder.return_midpoints()
        n_ret = self.encoder.n_return_bins
        n_vol = self.encoder.vol_bins
        n_volm = self.encoder.volume_bins

        # Marginalise over vol and volume dimensions to get return distribution
        return_probs = np.zeros(n_ret, dtype=np.float64)
        for state_idx in range(self.encoder.n_states):
            r_bin = state_idx // (n_vol * n_volm)
            if r_bin < n_ret:
                return_probs[r_bin] += dist[state_idx]

        # Normalise return marginal
        rp_sum = return_probs.sum()
        if rp_sum > 0:
            return_probs /= rp_sum

        expected_return = float(np.dot(return_probs, midpoints))

        # Confidence from entropy
        max_entropy = math.log(self.encoder.n_states) if self.encoder.n_states > 1 else 1.0
        entropy = _shannon_entropy(dist)
        confidence = max(0.0, 1.0 - entropy / max_entropy) if max_entropy > 0 else 0.0

        # State distribution as dict (top states only for compactness)
        state_dist = {int(i): float(dist[i]) for i in range(len(dist)) if dist[i] > 0.001}

        return MarkovPrediction(
            expected_return=expected_return,
            confidence=confidence,
            dominant_regime=self.model.regime(),
            spectral_gap=self.model.spectral_gap(),
            state_distribution=state_dist,
            current_state=self._prev_state,
            current_state_label=self.encoder.decode_return_bucket(self._prev_state).value,
        )
