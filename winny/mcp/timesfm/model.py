"""TimesFM model wrapper — §3.1.2.

Encapsulates the google/timesfm-2.5-200m-pytorch model behind a clean interface
that the MCP tools call. Handles:
    - Lazy model loading (cold start ~8-15s)
    - Input validation (NaN/Inf rejection, context truncation)
    - Batch inference
    - OOM recovery (halve batch, retry once)
    - Device detection (CUDA > MPS > CPU)

Model configuration (from spec §3.1.2):
    max_context:               1024
    max_horizon:               256
    normalize_inputs:          True
    use_continuous_quantile_head: True
    fix_quantile_crossing:     True
    force_flip_invariance:     True
    infer_is_positive:         True
    quantiles emitted:         mean + deciles 0.1…0.9

This wrapper is intentionally stateless — no caching, no symbol awareness.
Caching is the caller's responsibility (§3.1.6).
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog

from winny.common.errors import WinnyError

logger = structlog.get_logger()

# Default quantile levels: 0.1, 0.2, ..., 0.9
DEFAULT_QUANTILE_LEVELS: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)

# Model constants from §3.1.2
MAX_CONTEXT = 1024
MAX_HORIZON = 256
# The loader uses the TimesFM 2.5 torch API (TimesFM_2p5_200M_torch +
# ForecastConfig), which is what the `timesfm` 2.x package on the host exposes.
# Override the checkpoint with WINNY_TIMESFM_MODEL_ID if needed.
MODEL_ID = os.environ.get("WINNY_TIMESFM_MODEL_ID", "google/timesfm-2.5-200m-pytorch")


class ForecastError(WinnyError):
    """Raised when the forecasting model encounters an unrecoverable error."""


class InvalidInputError(ForecastError):
    """Raised when input data contains NaN, Inf, or is otherwise invalid."""


class InvalidHorizonError(ForecastError):
    """Raised when the requested horizon exceeds model limits."""


@dataclass
class ModelConfig:
    """TimesFM model configuration. Matches §3.1.2 defaults."""

    model_id: str = MODEL_ID
    max_context: int = MAX_CONTEXT
    max_horizon: int = MAX_HORIZON
    quantile_levels: tuple[float, ...] = DEFAULT_QUANTILE_LEVELS
    device: str = "auto"  # "auto" | "cuda" | "cpu" | "mps"
    # TimesFM-specific flags
    normalize_inputs: bool = True
    use_continuous_quantile_head: bool = True
    fix_quantile_crossing: bool = True
    force_flip_invariance: bool = True
    infer_is_positive: bool = True


@dataclass
class PredictionResult:
    """Raw model output for a batch of series.

    Attributes:
        point:     Point forecast, shape (B, H)
        quantiles: Quantile forecasts, shape (B, H, Q)
        quantile_levels: The quantile levels used
        metadata:  Additional info (device, model_id, context_lengths, etc.)
    """

    point: np.ndarray  # (B, H)
    quantiles: np.ndarray  # (B, H, Q)
    quantile_levels: tuple[float, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


class TimesFMModel:
    """Wrapper around the TimesFM 2.5 model.

    Lazy-loads the model on first predict() call. Thread-safe via asyncio
    (single-threaded event loop). Not designed for multi-process sharing.

    Usage:
        model = TimesFMModel(config=ModelConfig())
        result = model.predict(inputs=[[1.0, 2.0, 3.0]], horizon=5)
    """

    def __init__(self, config: ModelConfig | None = None) -> None:
        self._config = config or ModelConfig()
        self._model: Any = None
        self._device: str = ""
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def device(self) -> str:
        return self._device

    @property
    def config(self) -> ModelConfig:
        return self._config

    def load(self) -> None:
        """Load the TimesFM model from HuggingFace. Blocks ~8-15s on first call.

        Raises:
            ForecastError: if the model cannot be loaded (missing files, no HF access).
        """
        if self._loaded:
            return

        logger.info("timesfm_model_loading", model_id=self._config.model_id)

        try:
            import timesfm
        except ImportError as e:
            raise ForecastError(
                "TimesFM is not installed in this image. It is an optional heavy "
                "extra (torch + model weights); the gateway's TA forecaster powers "
                "live signals without it. To enable on-demand TimesFM forecasts, "
                "install the extra (pip install -e '/app[forecast]') on the host "
                "that runs mcp-timesfm, then restart."
            ) from e

        # Authenticate with Hugging Face Hub so gated/private model weights
        # can be downloaded.  HF_TOKEN is loaded from .env by winny.common.config.
        hf_token = os.environ.get("HF_TOKEN", "")
        if hf_token:
            try:
                from huggingface_hub import login

                login(token=hf_token, add_to_git_credential=False)
                logger.info("huggingface_hub_authenticated")
            except Exception as e:
                logger.warning("huggingface_hub_login_failed", error=str(e))
        else:
            logger.warning(
                "HF_TOKEN not set — model download may fail for gated repos. "
                "Add HF_TOKEN to your .env file."
            )

        # Detect device
        self._device = self._detect_device()

        try:
            # TimesFM 2.5 torch API: load the pretrained checkpoint from HF,
            # then compile it with a ForecastConfig (horizon/context + the
            # quantile/normalisation flags from §3.1.2).
            self._model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
                self._config.model_id
            )
            self._model.compile(
                timesfm.ForecastConfig(
                    max_context=self._config.max_context,
                    max_horizon=self._config.max_horizon,
                    normalize_inputs=self._config.normalize_inputs,
                    use_continuous_quantile_head=self._config.use_continuous_quantile_head,
                    force_flip_invariance=self._config.force_flip_invariance,
                    infer_is_positive=self._config.infer_is_positive,
                    fix_quantile_crossing=self._config.fix_quantile_crossing,
                )
            )
            self._loaded = True
            logger.info(
                "timesfm_model_loaded",
                model_id=self._config.model_id,
                device=self._device,
            )
        except Exception as e:
            raise ForecastError(f"Failed to load TimesFM model: {e}") from e

    def predict(
        self,
        inputs: list[list[float]],
        horizon: int,
        quantile_levels: tuple[float, ...] | None = None,
    ) -> PredictionResult:
        """Run inference on a batch of time series.

        Args:
            inputs: List of B time series, each of variable length (≤ max_context).
            horizon: Forecast horizon (1 ≤ horizon ≤ max_horizon).
            quantile_levels: Override default quantiles.

        Returns:
            PredictionResult with point and quantile forecasts.

        Raises:
            InvalidInputError: if inputs contain NaN/Inf or are empty.
            InvalidHorizonError: if horizon is out of bounds.
            ForecastError: on OOM or other model errors.
        """
        if not self._loaded:
            self.load()

        # Validate horizon §3.1.5
        if horizon < 1 or horizon > self._config.max_horizon:
            raise InvalidHorizonError(
                f"Horizon must be 1-{self._config.max_horizon}, got {horizon}"
            )

        # Validate inputs §3.1.5
        if not inputs or all(len(s) == 0 for s in inputs):
            raise InvalidInputError("Input series must not be empty")

        processed_inputs: list[list[float]] = []
        context_lengths: list[int] = []

        for i, series in enumerate(inputs):
            if not series:
                raise InvalidInputError(f"Series {i} is empty")

            # Check for NaN/Inf §3.1.5
            for j, val in enumerate(series):
                if math.isnan(val) or math.isinf(val):
                    raise InvalidInputError(
                        f"Series {i}, position {j}: NaN/Inf not allowed. "
                        "Do not silently impute — fix upstream data."
                    )

            # Truncate from head if > max_context §3.1.5
            if len(series) > self._config.max_context:
                logger.warning(
                    "timesfm_context_truncated",
                    series_idx=i,
                    original_len=len(series),
                    truncated_to=self._config.max_context,
                )
                series = series[-self._config.max_context :]

            processed_inputs.append(series)
            context_lengths.append(len(series))

        q_levels = list(quantile_levels or self._config.quantile_levels)

        # Run model inference with OOM retry
        try:
            point, quantiles = self._run_inference(processed_inputs, horizon, q_levels)
        except RuntimeError as e:
            if "out of memory" in str(e).lower() or "CUDA" in str(e):
                # §3.1.5 OOM recovery: halve batch, retry once
                logger.warning("timesfm_oom_retry", batch_size=len(processed_inputs))
                half = len(processed_inputs) // 2
                if half == 0:
                    raise ForecastError(f"OOM even with single series: {e}") from e

                p1, q1 = self._run_inference(processed_inputs[:half], horizon, q_levels)
                p2, q2 = self._run_inference(processed_inputs[half:], horizon, q_levels)
                point = np.concatenate([p1, p2], axis=0)
                quantiles = np.concatenate([q1, q2], axis=0)
            else:
                raise ForecastError(f"Model inference error: {e}") from e

        return PredictionResult(
            point=point,
            quantiles=quantiles,
            quantile_levels=tuple(q_levels),
            metadata={
                "model_id": self._config.model_id,
                "device": self._device,
                "context_lengths": context_lengths,
                "horizon": horizon,
                "batch_size": len(processed_inputs),
            },
        )

    def _run_inference(
        self,
        inputs: list[list[float]],
        horizon: int,
        quantile_levels: list[float],
    ) -> tuple[np.ndarray, np.ndarray]:
        """Execute model forward pass.

        Returns:
            (point_forecast, quantile_forecast) as numpy arrays.
        """
        assert self._model is not None

        # TimesFM 2.5 torch API: forecast(horizon=, inputs=[arr, ...]).
        # Returns (point_forecast, quantile_forecast) as numpy arrays:
        #   point:     (B, H)
        #   quantiles: (B, H, Q)  — Q = 10 (mean + deciles 0.1…0.9)
        forecast_input = [np.asarray(s, dtype=np.float32) for s in inputs]

        point_raw, quantile_raw = self._model.forecast(
            horizon=horizon,
            inputs=forecast_input,
        )

        point = np.asarray(point_raw)[:, :horizon]  # (B, H)

        if quantile_raw is not None:
            q = np.asarray(quantile_raw)  # (B, H, Q)
            quantiles = q[:, :horizon, :]
        else:
            # Fallback: use the point forecast for every requested quantile.
            quantiles = np.stack([point] * len(quantile_levels), axis=-1)

        return point, quantiles

    def _detect_device(self) -> str:
        """Detect best available compute device."""
        if self._config.device != "auto":
            return self._config.device

        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
        except ImportError:
            pass

        return "cpu"
