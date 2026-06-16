"""x402 — HTTP-native stablecoin payments.

DISABLED. Flip WW_FEATURE_X402=true to let the gateway charge external
callers (e.g. AI agents that consume our backtest API) via HTTP 402.

Use cases (future):
  • Charge per-backtest run when our infra is consumed by external agents
  • Pay external data providers per-call from a cluster's wallet
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from winny.common.features import features


def issue_402_challenge(
    *, resource: str, price_usd: Decimal, recipient_address: str
) -> dict[str, Any]:
    """Return the HTTP 402 challenge headers + body for the caller."""
    features().require("x402", "set WW_FEATURE_X402=true to enable")
    raise NotImplementedError


def verify_402_payment(*, settlement_proof: str) -> bool:
    features().require("x402")
    raise NotImplementedError
