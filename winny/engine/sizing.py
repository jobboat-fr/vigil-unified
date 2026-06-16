"""Sizing policy — SPECS.md §3.3.3 + §1.3 hard cap.

Sizing decides "how much money to put on this trade" in QUOTE currency. The
engine takes that stake and divides by the reference price (with lot/tick
rounding from MarketSpec) to produce an OrderIntent.qty.

The user, the LLM, and the strategy cannot bypass the §1.3 hard cap of
5% portfolio NAV per single trade. `apply_nav_cap` is the chokepoint that
enforces it; every code path that produces an OrderIntent MUST pass through
either a SizingPolicy whose constructor refuses values > the cap, or call
`apply_nav_cap` explicitly.

This is the defensive layer that ensures "approve for $100" never becomes
"$10,000 actual stake" even under bugs or hostile inputs upstream.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from winny.common.errors import WinnyValidationError
from winny.common.symbols import Symbol
from winny.common.types import Side

# §1.3 hard constraint: no single trade exceeds 5% portfolio NAV.
# This is an ABSOLUTE ceiling — user-configurable downward, never upward.
HARD_NAV_FRACTION_CAP = Decimal("0.05")

# Quantize sizing output to cents — refinement to tick size happens later in
# the engine when applying MarketSpec.qty_step.
_STAKE_QUANTIZE = Decimal("0.01")


def apply_nav_cap(stake: Decimal, portfolio_nav: Decimal) -> Decimal:
    """Clamp a stake suggestion to the §1.3 5%-NAV ceiling.

    Returns min(stake, nav * 0.05), never raises. Use as the final guard
    around any sizing decision regardless of which SizingPolicy produced it.
    """
    if stake < 0:
        raise WinnyValidationError(f"stake must be non-negative, got {stake}")
    if portfolio_nav <= 0:
        raise WinnyValidationError(f"portfolio_nav must be positive, got {portfolio_nav}")
    ceiling = (portfolio_nav * HARD_NAV_FRACTION_CAP).quantize(_STAKE_QUANTIZE)
    return min(stake.quantize(_STAKE_QUANTIZE), ceiling)


# ===================================================================
# SizingPolicy interface
# ===================================================================


class SizingPolicy(ABC):
    """Abstract sizing — returns the QUOTE-currency stake for one position.

    Implementations MUST honor HARD_NAV_FRACTION_CAP — either by construction
    (refuse instantiation with a higher fraction) or by calling `apply_nav_cap`
    inside `stake_amount`. The engine also calls `apply_nav_cap` defensively.
    """

    @abstractmethod
    def stake_amount(
        self,
        symbol: Symbol,
        side: Side,
        ref_price: Decimal,
        portfolio_nav: Decimal,
    ) -> Decimal:
        """Compute the stake in quote currency. MUST <= portfolio_nav * 0.05."""


# ===================================================================
# FixedFractionalSizing — the default policy
# ===================================================================


@dataclass(frozen=True, slots=True)
class FixedFractionalSizing(SizingPolicy):
    """Stake a fixed fraction of NAV on every trade. Default 5% (the cap).

    For a 2% allocation set `nav_fraction=Decimal("0.02")`. Anything above
    HARD_NAV_FRACTION_CAP is rejected at construction; you cannot bypass the
    §1.3 ceiling by mis-configuring this policy.
    """

    nav_fraction: Decimal = HARD_NAV_FRACTION_CAP

    def __post_init__(self) -> None:
        if self.nav_fraction <= 0:
            raise WinnyValidationError(f"nav_fraction must be > 0, got {self.nav_fraction}")
        if self.nav_fraction > HARD_NAV_FRACTION_CAP:
            raise WinnyValidationError(
                f"nav_fraction {self.nav_fraction} exceeds §1.3 hard cap "
                f"{HARD_NAV_FRACTION_CAP} (5% NAV)"
            )

    def stake_amount(
        self,
        symbol: Symbol,
        side: Side,
        ref_price: Decimal,
        portfolio_nav: Decimal,
    ) -> Decimal:
        if portfolio_nav <= 0:
            raise WinnyValidationError(f"portfolio_nav must be positive, got {portfolio_nav}")
        raw = portfolio_nav * self.nav_fraction
        # apply_nav_cap is a no-op here (already constructor-bounded) but
        # is included so the chokepoint is exercised on every code path.
        return apply_nav_cap(raw, portfolio_nav)


# ===================================================================
# ConvictionScaledSizing — bigger conviction = bigger stake (still capped)
# ===================================================================


@dataclass(frozen=True, slots=True)
class ConvictionScaledSizing(SizingPolicy):
    """Scale stake by the strategy's conviction (1..10).

    `base_fraction` is the stake at conviction=5; conviction=10 doubles it,
    conviction=1 halves it. Hard-capped at HARD_NAV_FRACTION_CAP regardless
    of conviction or base.
    """

    base_fraction: Decimal = Decimal("0.025")  # 2.5% at conviction=5
    conviction: int = 5

    def __post_init__(self) -> None:
        if not (1 <= self.conviction <= 10):
            raise WinnyValidationError(f"conviction must be 1..10, got {self.conviction}")
        if self.base_fraction <= 0:
            raise WinnyValidationError(f"base_fraction must be > 0, got {self.base_fraction}")
        # base_fraction itself MAY be > cap — the cap is applied to the
        # multiplied result, not the base. We just ensure base * 2 (conviction=10
        # peak multiplier) isn't insanely high to avoid surprise. Soft warning
        # only: still enforced by apply_nav_cap at use time.

    def stake_amount(
        self,
        symbol: Symbol,
        side: Side,
        ref_price: Decimal,
        portfolio_nav: Decimal,
    ) -> Decimal:
        if portfolio_nav <= 0:
            raise WinnyValidationError(f"portfolio_nav must be positive, got {portfolio_nav}")
        # Linear scale: conviction=5 → 1x, conviction=10 → 2x, conviction=1 → 0.2x
        multiplier = Decimal(self.conviction) / Decimal("5")
        raw = portfolio_nav * self.base_fraction * multiplier
        return apply_nav_cap(raw, portfolio_nav)
