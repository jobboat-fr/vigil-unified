"""Helpers for translating gateway agent requests into MCP tool arguments."""

from __future__ import annotations

import json
import re
from typing import Any

from winny.common.errors import WinnyValidationError
from winny.common.symbols import Symbol

_FRIENDLY_PAIR_RE = re.compile(
    r"^\s*([A-Z0-9._-]+)\s*[/\-]\s*([A-Z0-9.]+)(?:@([A-Z0-9_]+))?\s*$",
    re.IGNORECASE,
)
_EQUITY_RE = re.compile(r"^[A-Z]{1,6}(?:\.[A-Z]{1,4})?$", re.IGNORECASE)
_COMMON_CRYPTO_BASES = {
    "ADA",
    "AVAX",
    "BTC",
    "DOGE",
    "DOT",
    "ETH",
    "LINK",
    "MATIC",
    "SOL",
    "XRP",
}


def canonicalise_agent_symbol(raw: str, *, default_crypto_venue: str = "binance") -> str:
    """Accept UI-friendly symbols and return Winny's canonical wire format."""
    value = raw.strip()
    if not value:
        raise WinnyValidationError("symbol must not be empty")

    try:
        return Symbol.parse(value).canonical()
    except Exception:
        pass

    pair = _FRIENDLY_PAIR_RE.match(value)
    if pair:
        base = pair.group(1).upper()
        quote = pair.group(2).upper()
        venue = (pair.group(3) or default_crypto_venue).lower()
        return Symbol.parse(f"CR:{base}-{quote}@{venue}").canonical()

    ticker = value.upper()
    if ticker in _COMMON_CRYPTO_BASES:
        return Symbol.parse(f"CR:{ticker}-USDT@{default_crypto_venue}").canonical()

    if _EQUITY_RE.match(ticker):
        return Symbol.parse(f"EQ:{ticker}").canonical()

    raise WinnyValidationError(
        f"Invalid symbol: {raw!r}. Use canonical form or a pair like BTC/USDT."
    )


def decode_mcp_text_payload(result: Any) -> dict[str, Any] | None:
    """Decode the JSON text payload from this repo's MCP content envelope."""
    if not isinstance(result, dict):
        return None

    if isinstance(result.get("decision_id"), str):
        return result

    content = result.get("content")
    if not isinstance(content, list):
        return None

    for part in content:
        if not isinstance(part, dict) or part.get("type") != "text":
            continue
        text = part.get("text")
        if not isinstance(text, str):
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
        return {"value": payload}

    return None


def extract_decision_id(result: Any) -> str | None:
    payload = decode_mcp_text_payload(result)
    decision_id = payload.get("decision_id") if payload else None
    return decision_id if isinstance(decision_id, str) else None
