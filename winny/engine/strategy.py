"""WinnyStrategy — bar-driven strategy interface (§3.3.2).

Vendored from Freqtrade's `IStrategy` pattern — the DataFrame-transformation
model, not the runtime. Strategies receive a Polars DataFrame of historical
bars and add signal columns; the engine loop (§3.3.4) consumes those signals.

Strategies NEVER submit orders. They emit intents; the engine + approval gate
handle execution (§1.3, D-008).

Key contract:
    1. Methods receive bars with timestamps up to and including `meta.ts`.
    2. The LAST row of the returned DataFrame is the current bar's signals.
    3. Lookahead is forbidden in entry/exit columns (caught by walk-forward
       backtest per §10.3 — no static check today).
    4. Decimal money, UTC times, Polars (not pandas).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import polars as pl

from winny.common.symbols import Symbol
from winny.common.types import Side

# ---------- value objects ----------


@dataclass(frozen=True, slots=True)
class BarMeta:
    """Context passed to every strategy method.

    `ts` is the END time of the current (most recent) bar — the strategy may
    use anything strictly before this time, may NOT condition entry/exit
    decisions on data after this time.
    """

    symbol: Symbol
    ts: datetime  # tz-aware UTC; end of current bar
    timeframe: str


@dataclass(frozen=True, slots=True)
class StoplossDecision:
    """Returned by `custom_stoploss`. None = leave existing stop in place."""

    new_stoploss_pct: Decimal  # e.g. Decimal("-0.05") for -5%
    reason: str


@dataclass(frozen=True, slots=True)
class TradePosition:
    """Passed to confirm_trade_exit / custom_stoploss. Read-only snapshot."""

    symbol: Symbol
    side: Side
    entry_price: Decimal
    qty: Decimal
    open_ts: datetime
    enter_tag: str | None


# ---------- the interface ----------


class WinnyStrategy(ABC):
    """Base class for all Winny trading strategies.

    Subclass overrides:
        - `populate_indicators` (REQUIRED): add TA / ML features.
        - `populate_entry_trend` (REQUIRED): set `enter_long` / `enter_short` columns.
        - `populate_exit_trend`  (REQUIRED): set `exit_long`  / `exit_short`  columns.
        - Optional confirmation/risk hooks (see below).
        - Optional FreqAI-style ML hooks (deferred to PR #12+).

    Class-level configuration mirrors Freqtrade's pattern so strategies port
    easily; defaults are conservative and explicit.
    """

    # ---------- bumped on any breaking change to the interface ----------
    INTERFACE_VERSION: int = 1

    # ---------- defaults (override in subclass) ----------
    timeframe: str = "1h"
    """Bar interval the strategy consumes. Must be in winny.data.providers.base.VALID_TIMEFRAMES."""

    startup_candle_count: int = 100
    """Minimum bars of warm-up required before the strategy may issue signals.
    Engine refuses to call populate_* with fewer rows."""

    stoploss: Decimal = Decimal("-0.10")
    """Default stop-loss as fractional return (Decimal('-0.10') = -10%).
    Engine enforces this unless `custom_stoploss` returns a tighter value."""

    minimal_roi: dict[int, Decimal] | None = None
    """Minutes -> ROI threshold. e.g. {0: Decimal('0.05'), 30: Decimal('0.02')}
    means: take profit at +5% immediately, drop the threshold to +2% after 30min.
    None disables; engine uses stoploss / signals only."""

    can_short: bool = False
    """If False, populate_entry_trend MAY still set enter_short but the engine
    will reject those signals. Subclass MUST opt in explicitly for shorts."""

    use_custom_stoploss: bool = False
    """If True, engine calls custom_stoploss on every bar for open positions."""

    # ===================================================================
    # MANDATORY methods — every subclass implements
    # ===================================================================

    @abstractmethod
    def populate_indicators(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        """Add technical indicators / features.

        Input columns: ts, open, high, low, close, volume (Decimal-as-Float64).
        Output: same DataFrame with added indicator columns.
        OHLCV columns MUST be preserved.

        You MAY look at any row when computing indicators (e.g. rolling means
        use past bars). You MUST NOT use information from rows after `meta.ts`
        — that's lookahead. The engine passes only bars up to meta.ts so you
        physically cannot in normal use; walk-forward testing catches the rest.
        """

    @abstractmethod
    def populate_entry_trend(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        """Define entry signals.

        Output requirements:
            - MUST set integer 0/1 column `enter_long`.
            - MAY set integer 0/1 column `enter_short` (requires can_short=True).
            - MAY set string column `enter_tag` naming the signal (for audit).
        The last row's `enter_long`/`enter_short` is what the engine acts on.
        """

    @abstractmethod
    def populate_exit_trend(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        """Define exit signals.

        Output requirements:
            - MUST set integer 0/1 column `exit_long`.
            - MAY set integer 0/1 column `exit_short`.
            - MAY set string column `exit_tag`.
        Same last-row semantics as populate_entry_trend.
        """

    # ===================================================================
    # OPTIONAL hooks — default to no-op / pass-through
    # ===================================================================

    def custom_stoploss(
        self,
        position: TradePosition,
        current_ts: datetime,
        current_rate: Decimal,
        current_profit_pct: Decimal,
        **kwargs: Any,
    ) -> StoplossDecision | None:
        """Override per-position stoploss based on live state.

        Returning None keeps the existing stop. Returning a StoplossDecision
        REPLACES the stop (the engine validates it's a tightening, not loosening,
        unless `use_custom_stoploss` is set to allow loosening).
        Only called if `use_custom_stoploss = True`.
        """
        return None

    def custom_stake_amount(
        self,
        symbol: Symbol,
        current_ts: datetime,
        current_rate: Decimal,
        proposed_stake: Decimal,
        **kwargs: Any,
    ) -> Decimal:
        """Override the engine's proposed position size for THIS specific trade.

        Default: accept the engine's proposal (which came from the sizing policy
        per §3.3.3, which itself derives from portfolio NAV * risk fraction).

        Returning a value > proposed_stake is allowed but the engine caps it at
        the §1.3 hard limit of 5% NAV per trade.
        """
        return proposed_stake

    def confirm_trade_entry(
        self,
        symbol: Symbol,
        side: Side,
        qty: Decimal,
        rate: Decimal,
        current_ts: datetime,
        enter_tag: str | None,
        **kwargs: Any,
    ) -> bool:
        """Final per-trade veto before an OrderIntent is constructed.

        Use for last-mile sanity checks that depend on live state (e.g. veto
        if the spread widened, if a news event just hit, etc.). Default: True.
        """
        return True

    def confirm_trade_exit(
        self,
        position: TradePosition,
        rate: Decimal,
        current_ts: datetime,
        exit_reason: str,
        **kwargs: Any,
    ) -> bool:
        """Final per-trade veto before an exit order is constructed. Default: True."""
        return True

    # ===================================================================
    # FREQAI-style ML hooks — formalized in PR #12+ (FreqAI port)
    # ===================================================================

    def feature_engineering_expand_all(
        self, df: pl.DataFrame, period: int, meta: BarMeta
    ) -> pl.DataFrame:
        """ML feature expansion across multiple periods. Default: pass-through."""
        return df

    def feature_engineering_expand_basic(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        """Single-period base features. Default: pass-through."""
        return df

    def feature_engineering_standard(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        """Common features (e.g. day-of-week, hour-of-day). Default: pass-through."""
        return df

    def set_freqai_targets(self, df: pl.DataFrame, meta: BarMeta) -> pl.DataFrame:
        """Add target columns (`&-target_*`) for FreqAI training. Default: pass-through."""
        return df

    # ===================================================================
    # Lifecycle hooks (rarely overridden)
    # ===================================================================

    def bot_start(self) -> None:  # noqa: B027 — optional hook, base is intentionally no-op
        """Called once when the engine starts. Use for warm-up, key checks, etc."""

    def bot_loop_start(  # noqa: B027 — optional hook, base is intentionally no-op
        self, current_ts: datetime
    ) -> None:
        """Called at the start of every engine tick, before per-symbol processing."""
