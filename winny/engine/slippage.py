"""Slippage models — SPECS.md §3.3.6.

Slippage is the price difference between the reference price (last close)
and the actual fill price. In a bar-driven backtest we don't know the real
fill — we model it with a basis-points haircut against the reference.

BUY orders fill at  ref_price * (1 + slip_bps / 10_000)
SELL orders fill at ref_price * (1 - slip_bps / 10_000)

This is the conservative direction: every trade is worse than the close.
A strategy that's profitable under this model has margin to spare against
real fills (which can sometimes be better than the close, sometimes worse).

The BpsSlippageModel below covers the §3.3.6 defaults. Future PRs may add
order-book-aware models that use depth-of-book to compute realistic impact.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal

from winny.common.errors import WinnyValidationError
from winny.common.symbols import AssetClass, Symbol
from winny.common.types import Side

_BPS_DIVISOR = Decimal("10000")
_PRICE_QUANTIZE = Decimal("0.00000001")  # tighter than crypto tick; engine re-rounds to symbol tick


class SlippageModel(ABC):
    """Abstract slippage model — maps (symbol, side, qty, ref_price) → fill_price."""

    @abstractmethod
    def slip_bps(
        self,
        symbol: Symbol,
        side: Side,
        qty: Decimal,
        ref_price: Decimal,
    ) -> int:
        """Return the slippage in basis points for this hypothetical trade."""

    def apply(
        self,
        symbol: Symbol,
        side: Side,
        qty: Decimal,
        ref_price: Decimal,
    ) -> Decimal:
        """Return the slipped fill price for the given trade.

        BUY shifts up, SELL shifts down — always worse than ref_price.
        """
        if ref_price <= 0:
            raise WinnyValidationError(f"ref_price must be positive, got {ref_price}")
        if qty <= 0:
            raise WinnyValidationError(f"qty must be positive, got {qty}")
        bps = Decimal(self.slip_bps(symbol, side, qty, ref_price))
        adj = ref_price * bps / _BPS_DIVISOR
        if side is Side.BUY:
            return (ref_price + adj).quantize(_PRICE_QUANTIZE)
        return (ref_price - adj).quantize(_PRICE_QUANTIZE)


# ---------- defaults per §3.3.6 ----------

# Equities: 5 bps (mid-tier institutional ~3, retail ~7; we pick 5)
# Crypto:   5 bps (BTC/ETH on a major venue at retail size)
# Forex:    1 bps (highly liquid majors)
# Futures:  3 bps (front-month ES, CL, etc.)
# Options:  50 bps (wide spreads; can be much worse on illiquid strikes)
_DEFAULT_SLIP_BPS: dict[AssetClass, int] = {
    AssetClass.CRYPTO: 5,
    AssetClass.EQUITY: 5,
    AssetClass.FOREX: 1,
    AssetClass.FUTURE: 3,
    AssetClass.OPTION: 50,
}


@dataclass(frozen=True, slots=True)
class BpsSlippageModel(SlippageModel):
    """Flat basis-points slippage by asset class.

    Use `overrides` to tune per asset class without subclassing:
        BpsSlippageModel(overrides={AssetClass.EQUITY: 10})
    """

    overrides: dict[AssetClass, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for ac, bps in self.overrides.items():
            if not isinstance(ac, AssetClass):
                raise WinnyValidationError(f"override key must be AssetClass, got {ac!r}")
            if bps < 0:
                raise WinnyValidationError(f"slippage bps must be >= 0, got {bps} for {ac}")

    def slip_bps(
        self,
        symbol: Symbol,
        side: Side,
        qty: Decimal,
        ref_price: Decimal,
    ) -> int:
        return self.overrides.get(symbol.asset_class, _DEFAULT_SLIP_BPS[symbol.asset_class])


@dataclass(frozen=True, slots=True)
class ZeroSlippageModel(SlippageModel):
    """Best-case model. Use ONLY in tests where you want exact arithmetic."""

    def slip_bps(
        self,
        symbol: Symbol,
        side: Side,
        qty: Decimal,
        ref_price: Decimal,
    ) -> int:
        return 0
