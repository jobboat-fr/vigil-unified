"""MCP tool handlers for mcp-tradingagents per §3.2.3.

Tools:
    analyze_symbol     — Full multi-agent analysis
    debate_position    — Follow-up debate on a prior decision
    get_decision_history — Read past decisions (stub for now)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from winny.common.errors import WinnyValidationError
from winny.common.ids import DecisionId
from winny.common.signals_store import fetch_decisions
from winny.common.symbols import Symbol

from .config import TradingAgentsConfig, load_config
from .wrapper import TradingAgentsWrapper

# Module-level singleton (lazy-initialized on first tool call)
_wrapper: TradingAgentsWrapper | None = None
_config: TradingAgentsConfig | None = None


def _get_wrapper() -> TradingAgentsWrapper:
    """Get or create the singleton wrapper."""
    global _wrapper, _config
    if _wrapper is None:
        _config = load_config()
        _wrapper = TradingAgentsWrapper(_config)
    return _wrapper


def reset_wrapper() -> None:
    """Reset the singleton (for testing)."""
    global _wrapper, _config
    _wrapper = None
    _config = None


async def analyze_symbol(
    symbol: str,
    asof: str | None = None,
    *,
    forecast: dict[str, Any] | None = None,
    config_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full multi-agent analysis per §3.2.3 analyze_symbol.

    Args:
        symbol: Canonical Winny symbol (e.g. "EQ:NVDA", "CR:BTC-USDT@binance").
        asof: ISO datetime string. Defaults to now. Must be <= now.
        forecast: Optional ForecastResult dict from mcp-timesfm.
        config_overrides: Runtime overrides for this analysis.

    Returns:
        DecisionDraft serialized as dict.

    Raises:
        WinnyValidationError: invalid symbol or lookahead.
        ReasoningError: analysis graph failure.
    """
    # Parse symbol
    try:
        sym = Symbol.parse(symbol)
    except (ValueError, KeyError, WinnyValidationError) as e:
        raise WinnyValidationError(f"Invalid symbol: {symbol!r} - {e}") from e

    # Parse asof
    if asof is None:
        asof_dt = datetime.now(UTC)
    else:
        try:
            asof_dt = datetime.fromisoformat(asof)
            if asof_dt.tzinfo is None:
                asof_dt = asof_dt.replace(tzinfo=UTC)
        except ValueError as e:
            raise WinnyValidationError(f"Invalid asof datetime: {asof!r} - {e}") from e

    wrapper = _get_wrapper()
    decision = await wrapper.analyze(
        sym, asof_dt, forecast=forecast, config_overrides=config_overrides
    )

    # Serialize for JSON-RPC transport
    return decision.model_dump(mode="json")


async def debate_position(
    decision_id: str,
    user_question: str,
    perspective: str = "bull",
) -> dict[str, Any]:
    """Follow-up debate on a prior decision per §3.2.3.

    Args:
        decision_id: The DecisionId from a prior analyze_symbol call.
        user_question: The user's question or challenge.
        perspective: One of "bull", "bear", "risk", "trader".

    Returns:
        DebateResponse dict with focused rerun.

    Raises:
        WinnyValidationError: invalid inputs.
        ReasoningError: debate graph failure.
    """
    if not decision_id.startswith("dec_"):
        raise WinnyValidationError(
            f"Invalid decision_id format: {decision_id!r}. Expected 'dec_' prefix."
        )

    if not user_question.strip():
        raise WinnyValidationError("user_question must not be empty.")

    valid_perspectives = ("bull", "bear", "risk", "trader")
    if perspective not in valid_perspectives:
        raise WinnyValidationError(
            f"perspective must be one of {valid_perspectives}, got {perspective!r}"
        )

    wrapper = _get_wrapper()
    return await wrapper.debate(
        decision_id=DecisionId(decision_id),
        user_question=user_question,
        perspective=perspective,
    )


async def get_decision_history(
    symbol: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Read past decisions from memory per §3.2.3.

    Args:
        symbol: Filter by symbol (optional).
        limit: Max number of decisions to return.

    Returns:
        Dict with "decisions" key containing list of historical decisions.
    """
    if limit < 1 or limit > 100:
        raise WinnyValidationError(f"limit must be 1-100, got {limit}")

    # Read analyst rows the gateway's signal_runner_loop wrote to Supabase
    # (`source='analyst'`). Each row already carries side, confidence,
    # entry/stop/target and a thesis blurb, so the MCP caller (Hermes,
    # dashboard, debate_position) gets a usable history without us
    # standing up a separate reasoning-memory store.
    rows = fetch_decisions(symbol=symbol, limit=int(limit))
    return {
        "decisions": rows,
        "total": len(rows),
        "filter_symbol": symbol,
    }
