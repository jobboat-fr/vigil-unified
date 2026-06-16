"""Fee models — SPECS.md §3.3.6.

Strategies and backtests use FeeModel to estimate the fees an order would
incur. The DefaultFeeModel hardcodes the conservative per-asset-class defaults
from the spec; broker-specific implementations override.

Fees are made of two components:
  - proportional: basis-points of notional value (maker/taker rates)
  - fixed:        flat per-contract or per-share charge (options, futures)

Conservative defaults intentionally over-estimate; a strategy that survives
backtest with default fees has margin to spare under real fee schedules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from winny.common.errors import WinnyValidationError
from winny.common.symbols import AssetClass, Symbol
from winny.common.types import Side

Liquidity = Literal["maker", "taker"]

# Fixed-precision rounding for fee currency amounts.
_FEE_QUANTIZE = Decimal("0.0001")
_BPS_DIVISOR = Decimal("10000")


@dataclass(frozen=True, slots=True)
class FeeQuote:
    """Pre-computed fee estimate for one hypothetical trade.

    `total` is the sum a strategy should add to its cost estimate. Stored
    separately so callers can see how fixed vs proportional contributed.
    """

    proportional_bps: int  # rate applied
    proportional_amount: Decimal  # bps * notional / 10000
    fixed_amount: Decimal  # per-unit fixed fee * qty
    total: Decimal  # proportional + fixed
    liquidity: Liquidity  # which side of the book


class FeeModel(ABC):
    """Abstract fee model. Implementations cover one or more asset classes."""

    @abstractmethod
    def maker_fee_bps(self, symbol: Symbol, side: Side) -> int:
        """Basis points charged when the order ADDS liquidity (limit, posted)."""

    @abstractmethod
    def taker_fee_bps(self, symbol: Symbol, side: Side) -> int:
        """Basis points charged when the order REMOVES liquidity (market, IOC)."""

    @abstractmethod
    def fixed_fee(self, symbol: Symbol, side: Side, qty: Decimal) -> Decimal:
        """Flat fee per unit (e.g. $0.65 / option contract). Returned for `qty` units."""

    def quote(
        self,
        symbol: Symbol,
        side: Side,
        qty: Decimal,
        notional: Decimal,
        *,
        liquidity: Liquidity = "taker",
    ) -> FeeQuote:
        """Combine maker/taker bps and fixed fee into a single FeeQuote.

        Conservative default: callers should assume `taker` rates unless they
        explicitly post a limit order (rare in our flow — most signals fire
        on the close of a bar and get marketable-limit execution).
        """
        if qty <= 0:
            raise WinnyValidationError(f"qty must be positive, got {qty}")
        if notional <= 0:
            raise WinnyValidationError(f"notional must be positive, got {notional}")

        bps = (
            self.maker_fee_bps(symbol, side)
            if liquidity == "maker"
            else self.taker_fee_bps(symbol, side)
        )
        proportional = (notional * Decimal(bps) / _BPS_DIVISOR).quantize(_FEE_QUANTIZE)
        fixed = self.fixed_fee(symbol, side, qty).quantize(_FEE_QUANTIZE)
        return FeeQuote(
            proportional_bps=bps,
            proportional_amount=proportional,
            fixed_amount=fixed,
            total=(proportional + fixed).quantize(_FEE_QUANTIZE),
            liquidity=liquidity,
        )


# ---------- defaults per §3.3.6 ----------

# Maker rates (limit orders that post to the book).
_DEFAULT_MAKER_BPS: dict[AssetClass, int] = {
    AssetClass.CRYPTO: 4,  # Binance retail
    AssetClass.EQUITY: 0,  # IBKR Pro Tier baseline
    AssetClass.FOREX: 0,
    AssetClass.FUTURE: 0,
    AssetClass.OPTION: 0,
}

# Taker rates (market/IOC orders that cross the spread).
_DEFAULT_TAKER_BPS: dict[AssetClass, int] = {
    AssetClass.CRYPTO: 10,  # Binance retail taker
    AssetClass.EQUITY: 0,
    AssetClass.FOREX: 0,
    AssetClass.FUTURE: 0,
    AssetClass.OPTION: 0,
}

# Fixed per-unit fees.
#   OPTION: $0.65 / contract (IBKR US options retail)
#   FUTURE: $2.50 / contract (IBKR retail; varies by exchange)
#   EQUITY / FX / CRYPTO: $0 (commission-free or built into bps)
_DEFAULT_FIXED: dict[AssetClass, Decimal] = {
    AssetClass.CRYPTO: Decimal("0"),
    AssetClass.EQUITY: Decimal("0"),
    AssetClass.FOREX: Decimal("0"),
    AssetClass.FUTURE: Decimal("2.50"),
    AssetClass.OPTION: Decimal("0.65"),
}


class DefaultFeeModel(FeeModel):
    """The conservative per-asset-class defaults from SPECS.md §3.3.6.

    Side is ignored at this layer (the same rate applies to BUY and SELL on
    every venue we currently care about). Subclasses MAY override for venues
    that have side-differentiated fee schedules.
    """

    def maker_fee_bps(self, symbol: Symbol, side: Side) -> int:
        return _DEFAULT_MAKER_BPS[symbol.asset_class]

    def taker_fee_bps(self, symbol: Symbol, side: Side) -> int:
        return _DEFAULT_TAKER_BPS[symbol.asset_class]

    def fixed_fee(self, symbol: Symbol, side: Side, qty: Decimal) -> Decimal:
        per_unit = _DEFAULT_FIXED[symbol.asset_class]
        return per_unit * qty
