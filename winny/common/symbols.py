"""Symbol — canonical cross-asset identifier per SPECS.md §4.1 + §6.1.

Canonical forms:
    EQ:NVDA                          US equity (venue = consolidated tape)
    EQ:0700.HK                       non-US equity (Yahoo suffix retained)
    CR:BTC-USDT@binance              crypto spot (venue is mandatory — price varies)
    CR:BTC-USDT-PERP@binance         crypto perp
    FX:EURUSD                        FX major
    FU:ES@CME-20260619               futures contract (venue + expiry)
    OP:NVDA-20260620-C-200@CBOE      option (underlying-expiry-CP-strike@venue)

`Symbol.parse(s).canonical() == s` MUST hold for every valid canonical string.
This invariant is asserted by hypothesis tests.

Validators enforce per-class invariants — e.g. CR symbols MUST have a quote,
FU MUST have an expiry, OP MUST have expiry + option_type + strike.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import WinnyValidationError


class AssetClass(StrEnum):
    """The five asset classes Winny covers. Order MUST NOT change (audit replay)."""

    CRYPTO = "CR"
    EQUITY = "EQ"
    FOREX = "FX"
    FUTURE = "FU"
    OPTION = "OP"


OptionType = Literal["C", "P"]


# Base may contain hyphens (CR perps like "BTC-USDT" + quote "PERP" canonicalize
# to "CR:BTC-USDT-PERP@binance"). The parser uses rsplit('-', 1) so it always
# picks the rightmost hyphen as the base/quote boundary — quote MUST therefore
# be hyphen-free or round-trip breaks.
_BASE_RE = re.compile(r"^[A-Z0-9._/-]+$")
_QUOTE_RE = re.compile(r"^[A-Z0-9.]+$")  # NO hyphens — protects round-trip invariant
_VENUE_RE = re.compile(r"^[A-Za-z0-9_]+$")


class Symbol(BaseModel):
    """Canonical cross-asset symbol.

    Frozen, hashable, comparable. Construct via `Symbol(asset_class=..., base=...)`
    or `Symbol.parse("EQ:NVDA")`. Always emit via `.canonical()` — never assemble
    the string by hand.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    asset_class: AssetClass
    base: str = Field(min_length=1, max_length=32)
    quote: str | None = Field(default=None, max_length=16)
    venue: str | None = Field(default=None, max_length=24)
    expiry: date | None = None
    option_type: OptionType | None = None
    strike: Decimal | None = None

    # ---------- validators ----------

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        ac = self.asset_class

        if not _BASE_RE.match(self.base):
            raise WinnyValidationError(f"invalid base for {ac}: {self.base!r}")
        if self.venue is not None and not _VENUE_RE.match(self.venue):
            raise WinnyValidationError(f"invalid venue: {self.venue!r}")
        if self.quote is not None and not _QUOTE_RE.match(self.quote):
            raise WinnyValidationError(
                f"invalid quote {self.quote!r} (hyphens not allowed — breaks round-trip)"
            )

        if ac is AssetClass.CRYPTO:
            if self.quote is None:
                raise WinnyValidationError("CR symbols require a quote (e.g. USDT)")
            if self.venue is None:
                raise WinnyValidationError(
                    "CR symbols require a venue (prices differ across exchanges)"
                )
            if self.expiry or self.option_type or self.strike:
                raise WinnyValidationError("CR symbols cannot carry expiry/option_type/strike")

        elif ac is AssetClass.EQUITY:
            if self.quote or self.expiry or self.option_type or self.strike:
                raise WinnyValidationError(
                    "EQ symbols only carry base (e.g. NVDA, 0700.HK); other fields forbidden"
                )

        elif ac is AssetClass.FOREX:
            if self.quote or self.expiry or self.option_type or self.strike:
                raise WinnyValidationError(
                    "FX symbols only carry base (e.g. EURUSD); other fields forbidden"
                )

        elif ac is AssetClass.FUTURE:
            if self.expiry is None:
                raise WinnyValidationError("FU symbols require an expiry date")
            if self.venue is None:
                raise WinnyValidationError("FU symbols require a venue (e.g. CME)")
            if self.option_type or self.strike:
                raise WinnyValidationError("FU symbols cannot carry option_type/strike")

        elif ac is AssetClass.OPTION:
            if self.expiry is None or self.option_type is None or self.strike is None:
                raise WinnyValidationError("OP symbols require expiry + option_type + strike")
            if self.venue is None:
                raise WinnyValidationError("OP symbols require a venue (e.g. CBOE)")
            if self.strike <= 0:
                raise WinnyValidationError(f"OP strike must be > 0, got {self.strike}")

        return self

    # ---------- canonical form ----------

    def canonical(self) -> str:
        """Return the canonical-form string per §6.1.

        The output is the SOLE wire/storage representation. Round-trips via
        `Symbol.parse(s.canonical()) == s`.
        """
        ac = self.asset_class
        if ac is AssetClass.EQUITY or ac is AssetClass.FOREX:
            return f"{ac.value}:{self.base}"
        if ac is AssetClass.CRYPTO:
            return f"{ac.value}:{self.base}-{self.quote}@{self.venue}"
        if ac is AssetClass.FUTURE:
            assert self.expiry is not None and self.venue is not None
            return f"{ac.value}:{self.base}@{self.venue}-{self.expiry.strftime('%Y%m%d')}"
        # OPTION
        assert (
            self.expiry is not None
            and self.option_type is not None
            and self.strike is not None
            and self.venue is not None
        )
        # Strike: strip trailing zeros if integer-valued, else preserve decimal
        strike_str = (
            str(int(self.strike))
            if self.strike == self.strike.to_integral_value()
            else str(self.strike)
        )
        return (
            f"{ac.value}:{self.base}-{self.expiry.strftime('%Y%m%d')}"
            f"-{self.option_type}-{strike_str}@{self.venue}"
        )

    # Mirror Python conventions
    def __str__(self) -> str:
        return self.canonical()

    # ---------- parser ----------

    @classmethod
    def parse(cls, s: str) -> Symbol:
        """Parse a canonical-form string into a Symbol.

        Raises WinnyValidationError on malformed input.
        """
        if ":" not in s:
            raise WinnyValidationError(f"missing asset_class prefix: {s!r}")
        prefix, rest = s.split(":", 1)
        try:
            ac = AssetClass(prefix)
        except ValueError as e:
            raise WinnyValidationError(f"unknown asset_class: {prefix!r}") from e

        if ac is AssetClass.EQUITY or ac is AssetClass.FOREX:
            return cls(asset_class=ac, base=rest)

        if ac is AssetClass.CRYPTO:
            # CR:BASE-QUOTE@VENUE   (BASE may have hyphens e.g. BTC-USDT-PERP)
            if "@" not in rest:
                raise WinnyValidationError(f"CR symbol missing @venue: {s!r}")
            pair, venue = rest.rsplit("@", 1)
            if "-" not in pair:
                raise WinnyValidationError(f"CR symbol missing -quote: {s!r}")
            base, quote = pair.rsplit("-", 1)
            return cls(asset_class=ac, base=base, quote=quote, venue=venue)

        if ac is AssetClass.FUTURE:
            # FU:ROOT@VENUE-YYYYMMDD
            if "@" not in rest:
                raise WinnyValidationError(f"FU symbol missing @venue: {s!r}")
            base, venue_part = rest.split("@", 1)
            if "-" not in venue_part:
                raise WinnyValidationError(f"FU symbol missing -expiry: {s!r}")
            venue, expiry_str = venue_part.split("-", 1)
            expiry = _parse_date(expiry_str, context=s)
            return cls(asset_class=ac, base=base, venue=venue, expiry=expiry)

        # OPTION: OP:UNDERLYING-YYYYMMDD-C|P-STRIKE@VENUE
        if "@" not in rest:
            raise WinnyValidationError(f"OP symbol missing @venue: {s!r}")
        body, venue = rest.rsplit("@", 1)
        parts = body.split("-")
        if len(parts) != 4:
            raise WinnyValidationError(
                f"OP symbol must be UNDERLYING-YYYYMMDD-C|P-STRIKE@VENUE: {s!r}"
            )
        underlying, expiry_str, opt_type, strike_str = parts
        if opt_type not in {"C", "P"}:
            raise WinnyValidationError(f"OP option_type must be C or P, got {opt_type!r}")
        try:
            strike = Decimal(strike_str)
        except (ValueError, ArithmeticError) as e:
            raise WinnyValidationError(f"OP strike not a valid Decimal: {strike_str!r}") from e
        return cls(
            asset_class=ac,
            base=underlying,
            venue=venue,
            expiry=_parse_date(expiry_str, context=s),
            option_type=opt_type,  # type: ignore[arg-type]  # narrowed by membership check above
            strike=strike,
        )


def _parse_date(s: str, *, context: str) -> date:
    if len(s) != 8 or not s.isdigit():
        raise WinnyValidationError(f"date must be YYYYMMDD: {s!r} (in {context!r})")
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:]))
    except ValueError as e:
        raise WinnyValidationError(f"invalid date {s!r} in {context!r}: {e}") from e
