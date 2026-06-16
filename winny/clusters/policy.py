"""ClusterPolicy — the immutable contract for a single cluster.

Each cluster has its own:
  • NAV target (capital allocation in some quote currency)
  • risk profile (conservative / balanced / aggressive / experimental)
  • per-trade size cap (overrides the global §1.3 5% cap when stricter)
  • strategy filter (which signal tags this cluster accepts)
  • dedicated AgentKit wallet address

The allocator (winny.clusters.allocator) uses these to decide signal split.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from winny.common.ids import Currency

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class RiskProfile(StrEnum):
    """Cluster risk tier — drives default sizing + drawdown thresholds."""

    CONSERVATIVE = "conservative"   # max 2% / position, low-conviction filter
    BALANCED = "balanced"           # max 5% / position
    AGGRESSIVE = "aggressive"       # max 10% / position
    EXPERIMENTAL = "experimental"   # max 1% / position, accepts new-strategy signals


class ClusterPolicy(BaseModel):
    """Immutable cluster definition. Stored in winny.clusters.store."""

    model_config = _FROZEN

    cluster_id: str = Field(min_length=8)                  # ulid
    name: str = Field(min_length=1, max_length=64)         # human-readable
    nav_target: Decimal = Field(gt=0)                       # allocated capital
    nav_currency: Currency
    risk_profile: RiskProfile
    max_position_pct: Decimal = Field(gt=0, le=Decimal("100"))
    strategy_filter: tuple[str, ...] = ()                   # signal tags accepted; empty = all
    wallet_provider: Literal["paper", "agentkit", "ccxt"] = "paper"
    wallet_address: str = ""                                # populated when wallet_provider != "paper"
    active: bool = True
    created_at: str                                          # ISO 8601
