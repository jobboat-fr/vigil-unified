"""BacktestReport → JSON-safe dict serializer for the MCP wire.

MCP messages are JSON. Our domain types contain Decimal (money), datetime
(time), timedelta (durations), Symbol (frozen Pydantic), and dataclasses
(report nodes). This module flattens all of them into JSON-safe primitives:

    Decimal      → str        (preserves precision)
    datetime     → ISO 8601
    date         → ISO 8601
    timedelta    → float (total seconds)
    Symbol       → canonical()  ("EQ:NVDA", "CR:BTC-USDT@binance", ...)
    dataclass    → dict via dataclasses.fields()
    Pydantic     → dict via model_dump(mode='json')
    list/tuple   → list[jsonable]
    dict         → dict[str, jsonable]
    everything else → str(value)

Stable under round-trip: serializing the same BacktestReport twice yields
byte-identical JSON when sort_keys=True is applied on the receiving end.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from winny.common.symbols import Symbol
from winny.engine.results import BacktestReport


def to_jsonable(value: Any) -> Any:
    """Recursively convert a value to a JSON-serializable form."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, Symbol):
        return value.canonical()
    if isinstance(value, BaseModel):
        # Pydantic models — use model_dump in 'json' mode then post-process
        # to catch any Decimal/datetime/Symbol that survived as objects.
        return to_jsonable(value.model_dump(mode="python"))
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    # Last-resort: stringify enums and anything else.
    return str(value)


def report_to_dict(report: BacktestReport) -> dict[str, Any]:
    """Convert a BacktestReport to a JSON-safe dict for the MCP wire."""
    out = to_jsonable(report)
    assert isinstance(out, dict)  # BacktestReport is a dataclass → dict
    return out
