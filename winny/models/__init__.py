"""winny.models — predictive model implementations.

Models are the pure-Python, stateless (or carefully-stateful) building blocks
that strategies in `winny.strategies.*` consume. They live OUTSIDE the
engine loop and have no dependency on Brokerage / AuditStore / IntentBuilder.

Conventions:
  - Each model exposes a fit(...) and a predict(...) (or radiate / forecast).
  - Models are deterministic given their inputs + a seed.
  - Models return typed value objects (dataclasses), not raw arrays.

See:
  - winny.models.markov — Markov Radiation Predictor (spectral diffusion)
"""
