"""Signal extraction — turns a populated DataFrame into typed Signal objects.

Per §3.3.4, the engine loop runs the strategy's `populate_*` methods then
inspects the LAST row of the returned DataFrame for entry/exit signals.
This module owns that translation step.

Why a separate module: keeps `WinnyStrategy` purely declarative (it just sets
columns) and gives the engine + tests one place to look for the contract
between "DataFrame columns" and "Signal objects".
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

import polars as pl

from winny.common.errors import WinnyValidationError
from winny.common.symbols import Symbol

# ---------- canonical column names ----------

# Entry/exit signal columns the strategy MAY set. Type: integer 0 or 1.
ENTER_LONG_COL = "enter_long"
ENTER_SHORT_COL = "enter_short"
EXIT_LONG_COL = "exit_long"
EXIT_SHORT_COL = "exit_short"

# Optional tag columns naming the signal (for audit + debugging).
ENTER_TAG_COL = "enter_tag"
EXIT_TAG_COL = "exit_tag"

SIGNAL_COLS = frozenset([ENTER_LONG_COL, ENTER_SHORT_COL, EXIT_LONG_COL, EXIT_SHORT_COL])


# ---------- types ----------


class SignalType(StrEnum):
    """The four signal kinds a strategy may emit."""

    ENTER_LONG = "ENTER_LONG"
    ENTER_SHORT = "ENTER_SHORT"
    EXIT_LONG = "EXIT_LONG"
    EXIT_SHORT = "EXIT_SHORT"


@dataclass(frozen=True, slots=True)
class Signal:
    """One emission from a strategy at a specific bar."""

    type: SignalType
    symbol: Symbol
    ts: datetime  # end of the bar that produced this signal
    bar_close: Decimal  # close price of that bar
    tag: str | None = None  # strategy-supplied label (enter_tag / exit_tag)


# ---------- extraction ----------


_TYPE_BY_COL: dict[str, SignalType] = {
    ENTER_LONG_COL: SignalType.ENTER_LONG,
    ENTER_SHORT_COL: SignalType.ENTER_SHORT,
    EXIT_LONG_COL: SignalType.EXIT_LONG,
    EXIT_SHORT_COL: SignalType.EXIT_SHORT,
}


def extract_signals(df: pl.DataFrame, symbol: Symbol, ts: datetime) -> list[Signal]:
    """Read signals from the last row of a populated DataFrame.

    Returns 0..4 Signal objects (one per signal column that's set to 1).
    Empty dataframes return [] silently — strategies during warm-up legitimately
    have no signals.

    The DataFrame MUST contain the OHLCV columns; signal columns are optional
    (strategies that only buy never set exit_* columns and vice versa).
    The last row's `close` is used as `bar_close` per §3.3.6 fee model defaults.
    """
    if df.is_empty():
        return []

    columns = set(df.columns)
    if "close" not in columns:
        raise WinnyValidationError(
            "DataFrame missing required 'close' column for signal extraction"
        )

    last = df.tail(1).to_dicts()[0]

    try:
        bar_close = Decimal(str(last["close"]))
    except (ArithmeticError, ValueError) as e:
        raise WinnyValidationError(f"last bar close is not a valid Decimal: {e}") from e

    enter_tag = last.get(ENTER_TAG_COL) if ENTER_TAG_COL in columns else None
    exit_tag = last.get(EXIT_TAG_COL) if EXIT_TAG_COL in columns else None

    signals: list[Signal] = []
    for col, sig_type in _TYPE_BY_COL.items():
        if col not in columns:
            continue
        value = last.get(col)
        if not _is_truthy_signal(value):
            continue
        tag = enter_tag if sig_type in (SignalType.ENTER_LONG, SignalType.ENTER_SHORT) else exit_tag
        signals.append(
            Signal(
                type=sig_type,
                symbol=symbol,
                ts=ts,
                bar_close=bar_close,
                tag=tag if isinstance(tag, str) and tag else None,
            )
        )
    return signals


def _is_truthy_signal(value: object) -> bool:
    """A signal cell is 'set' when it's a truthy int/float (1 / 1.0 / True).

    NaN / None / 0 / "" → not set. We're permissive about the column dtype
    because Polars may store the int 1 as Int64 or Float64 depending on how
    the strategy constructed it; both are valid.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        # Reject NaN and 0
        if isinstance(value, float) and math.isnan(value):
            return False
        return value != 0
    return False


# ---------- validation ----------


def validate_signal_columns(df: pl.DataFrame) -> None:
    """Raise WinnyValidationError if a strategy's DataFrame has malformed signals.

    Called by the engine loop after each populate_*_trend call (PR #11).
    Checks:
      - signal columns, if present, must be Int8/Int16/Int32/Int64/Float64
      - tag columns, if present, must be Utf8
    """
    schema = df.schema
    int_or_float = {
        pl.Boolean,
        pl.Int8,
        pl.Int16,
        pl.Int32,
        pl.Int64,
        pl.UInt8,
        pl.UInt16,
        pl.UInt32,
        pl.UInt64,
        pl.Float32,
        pl.Float64,
    }
    for col in SIGNAL_COLS:
        if col in schema and schema[col] not in int_or_float:
            raise WinnyValidationError(f"signal column {col!r} must be numeric, got {schema[col]}")
    for col in (ENTER_TAG_COL, EXIT_TAG_COL):
        if col in schema and schema[col] != pl.Utf8:
            raise WinnyValidationError(f"tag column {col!r} must be Utf8, got {schema[col]}")
