"""Canonical value objects per SPECS.md §4.

All money is `Decimal`. All times are tz-aware UTC. All models are frozen.
Unknown fields are rejected (`extra='forbid'`) except where the underlying
schema is still evolving (ReasoningTrace sub-parts — see PR #6/#7).

These types form the contract between MCP servers. Every cross-process boundary
exchanges instances of these (serialized via `model_dump_json()` / parsed via
`model_validate_json()`).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .ids import ApprovalId, BrokerOrderId, DecisionId, IntentId
from .symbols import Symbol

# ===================================================================
# Enums (§5 state machines)
# ===================================================================


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class TimeInForce(StrEnum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    DAY = "DAY"


class OrderStatus(StrEnum):
    """§5.2 — order lifecycle."""

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class ApprovalStatus(StrEnum):
    """§5.3 — approval lifecycle."""

    PENDING = "PENDING"
    GRANTED = "GRANTED"
    CONSUMED = "CONSUMED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class DecisionAction(StrEnum):
    """§4.3 — what the reasoning produced."""

    LONG = "LONG"
    SHORT = "SHORT"
    HOLD = "HOLD"
    CLOSE = "CLOSE"


# ===================================================================
# Common base
# ===================================================================

_FROZEN = ConfigDict(frozen=True, extra="forbid")


# ===================================================================
# Forecasts (§4.2)
# ===================================================================


class ForecastResult(BaseModel):
    """Raw forecast output. Shape-validated arrays; metadata for caching/audit."""

    model_config = _FROZEN

    model_id: str
    asof: datetime
    horizon: int = Field(gt=0)
    quantile_levels: tuple[float, ...]
    point: tuple[tuple[float, ...], ...]  # shape (B, H)
    quantiles: tuple[tuple[tuple[float, ...], ...], ...]  # shape (B, H, len(quantile_levels))
    metadata: dict[str, Any] = Field(default_factory=dict)


class SymbolForecast(BaseModel):
    """Symbol-bound forecast bundle. Carries content-hash for cache invalidation."""

    model_config = _FROZEN

    symbol: Symbol
    timeframe: str  # "1m" | "5m" | "15m" | "1h" | "4h" | "1d"
    bars_used: int = Field(gt=0)
    forecast: ForecastResult
    history_hash: str = Field(min_length=64, max_length=64)  # sha256 of input bars


# ===================================================================
# Market data (§3.3.3, §6.3)
# ===================================================================


class Bar(BaseModel):
    """One OHLCV record at a single timeframe interval."""

    model_config = _FROZEN

    symbol: Symbol
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class MarketSpec(BaseModel):
    """Per-venue trading rules for a symbol."""

    model_config = _FROZEN

    symbol: Symbol
    min_qty: Decimal
    qty_step: Decimal  # lot size / tick size on the quantity axis
    price_tick: Decimal
    min_notional: Decimal | None = None
    maker_fee_bps: int
    taker_fee_bps: int
    is_active: bool = True


# ===================================================================
# Reasoning (§4.4)  —  placeholders, formalized in PR #6/#7
# ===================================================================


class LLMMessage(BaseModel):
    """One verbatim LLM exchange. Audit-grade — store raw."""

    model_config = ConfigDict(frozen=True, extra="allow")

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    model: str  # e.g. "gpt-5.4-mini@2026-05"
    ts: datetime


class ReasoningTrace(BaseModel):
    """Full reasoning artifact from TradingAgents. Sub-parts will be tightened in PR #6/#7."""

    model_config = ConfigDict(frozen=True, extra="allow")

    analyst_reports: dict[str, Any]  # role_name -> AnalystReport (PR #7)
    debate_rounds: list[Any]  # list[DebateRound] (PR #7)
    trader_recommendation: dict[str, Any]
    risk_assessment: dict[str, Any]
    portfolio_verdict: dict[str, Any]
    raw_messages: list[LLMMessage]


class RiskFlag(BaseModel):
    """A specific risk surfaced by the Risk Manager."""

    model_config = _FROZEN

    code: str  # short stable identifier, e.g. "earnings_within_5d"
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    detail: str


class DecisionInputs(BaseModel):
    """Provenance: what data + what models produced this decision."""

    model_config = _FROZEN

    forecast_id: str | None = None
    data_version_hash: str = Field(min_length=64, max_length=64)
    llm_versions: dict[str, str]  # role -> "provider/model@date"
    config_hash: str = Field(min_length=64, max_length=64)


# ===================================================================
# Decisions (§4.3)
# ===================================================================


class DecisionDraft(BaseModel):
    """A reasoned recommendation. NOT yet an order. Not yet approved."""

    model_config = _FROZEN

    decision_id: DecisionId
    symbol: Symbol
    asof: datetime
    action: DecisionAction
    conviction: int = Field(ge=1, le=10)
    target_horizon: timedelta
    reasoning_trace: ReasoningTrace
    risk_flags: tuple[RiskFlag, ...] = ()
    inputs_used: DecisionInputs


# ===================================================================
# Orders (§4.5)
# ===================================================================


class OrderIntent(BaseModel):
    """A proposed order. Carries the decision back-reference and estimates.

    Quantities and prices are Decimal. Strategies emit intents via the engine;
    the LLM never specifies qty directly (§8.2 / D-008).
    """

    model_config = _FROZEN

    intent_id: IntentId
    decision_id: DecisionId
    symbol: Symbol
    side: Side
    qty: Decimal = Field(gt=0)
    order_type: OrderType
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    estimated_cost: Decimal
    estimated_fees: Decimal
    sizing_explanation: str  # human-readable: "5% NAV x conviction 7/10"


class OrderState(BaseModel):
    """Current broker-side state of a submitted order."""

    model_config = _FROZEN

    broker_order_id: BrokerOrderId
    intent_id: IntentId
    status: OrderStatus
    filled_qty: Decimal = Decimal("0")
    avg_fill_price: Decimal | None = None
    last_event_ts: datetime
    raw_broker_state: dict[str, Any] = Field(default_factory=dict)


class Fill(BaseModel):
    """One execution event from the broker."""

    model_config = _FROZEN

    broker_order_id: BrokerOrderId
    ts: datetime
    qty: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    fees: Decimal = Decimal("0")
    liquidity: Literal["MAKER", "TAKER", "UNKNOWN"] = "UNKNOWN"


class Position(BaseModel):
    """Net holding in a symbol."""

    model_config = _FROZEN

    symbol: Symbol
    qty: Decimal  # signed: positive = long, negative = short
    avg_entry_price: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal


# ===================================================================
# Approval (§4.6)
# ===================================================================


class ApprovalRequest(BaseModel):
    """A pending user verdict bound to one decision and one intent."""

    model_config = _FROZEN

    approval_id: ApprovalId
    decision_id: DecisionId
    order_intent_hash: str = Field(min_length=64, max_length=64)
    summary_for_user: str
    one_time_code: str = Field(min_length=4, max_length=12)
    issued_at: datetime
    expires_at: datetime
    status: ApprovalStatus = ApprovalStatus.PENDING


class ApprovalGrant(BaseModel):
    """A signed authorization to submit one specific OrderIntent.

    Single-use. TTL ≤ 5 min. Ed25519-signed. The opaque `grant_token` is what
    `mcp-algo.submit_order` validates — never expose internal fields upward.
    """

    model_config = _FROZEN

    grant_token: str  # opaque base64 payload + signature
    approval_id: ApprovalId
    expires_at: datetime
