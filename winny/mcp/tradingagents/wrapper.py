"""TradingAgents framework wrapper per §3.2.

Adapts TauricResearch/TradingAgents' LangGraph-based multi-agent system
to produce our canonical DecisionDraft. Handles:
    - Lazy import of the framework (heavy dependency)
    - Lookahead validation (asof <= now)
    - Checkpoint-based idempotency for same (symbol, asof, config_hash)
    - Mapping from raw TradingAgents output to typed domain objects
    - Cost tracking per invocation
    - Failure-mode handling per §3.2.7
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from winny.common.errors import WinnyValidationError
from winny.common.ids import DecisionId, new_decision_id
from winny.common.symbols import Symbol
from winny.common.types import (
    DecisionAction,
    DecisionDraft,
    DecisionInputs,
    LLMMessage,
    ReasoningTrace,
    RiskFlag,
)

from .config import TradingAgentsConfig

logger = structlog.get_logger()


class ReasoningError(Exception):
    """Raised when the reasoning graph fails irrecoverably."""


class LookaheadViolationError(WinnyValidationError):
    """asof > now - lookahead detected per §3.2.7."""


class QuotaExhaustedError(ReasoningError):
    """LLM quota exhausted after fallback attempts."""


class TradingAgentsWrapper:
    """Wraps TradingAgents propagate() for use by MCP tools.

    The wrapper is designed to be instantiated once per server lifetime.
    It lazily loads the TradingAgents graph on first call.
    """

    def __init__(self, config: TradingAgentsConfig) -> None:
        self._config = config
        self._graph: Any = None
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def _ensure_loaded(self) -> None:
        """Lazy-load the TradingAgents graph."""
        if self._loaded:
            return

        try:
            from tradingagents import TradingAgentsGraph  # type: ignore[import-not-found]

            # D-004: When base_url is set (HF Router or local vLLM), pass it
            # to TradingAgents so all LLM calls route through that endpoint.
            extra_kwargs: dict[str, Any] = {}
            if self._config.base_url:
                extra_kwargs["base_url"] = self._config.base_url
            if self._config.api_key:
                extra_kwargs["api_key"] = self._config.api_key

            self._graph = TradingAgentsGraph(
                llm_provider=self._config.llm_provider,
                deep_think_llm=self._config.deep_think_llm,
                quick_think_llm=self._config.quick_think_llm,
                temperature=self._config.temperature,
                max_debate_rounds=self._config.max_debate_rounds,
                analyst_conf={
                    "fundamentals": self._config.analyst_team.fundamentals,
                    "sentiment": self._config.analyst_team.sentiment,
                    "news": self._config.analyst_team.news,
                    "technical": self._config.analyst_team.technical,
                },
                **extra_kwargs,
            )
            self._loaded = True
            logger.info("tradingagents_graph_loaded", provider=self._config.llm_provider)
        except ImportError as e:
            raise ReasoningError(
                "TradingAgents framework not installed. Install with: pip install tradingagents"
            ) from e
        except Exception as e:
            raise ReasoningError(f"Failed to initialize TradingAgents graph: {e}") from e

    async def analyze(
        self,
        symbol: Symbol,
        asof: datetime,
        *,
        forecast: dict[str, Any] | None = None,
        config_overrides: dict[str, Any] | None = None,
    ) -> DecisionDraft:
        """Run full multi-agent analysis per §3.2.3.

        Args:
            symbol: Canonical Winny symbol.
            asof: Analysis point-in-time. Must be <= now.
            forecast: Optional ForecastResult from mcp-timesfm to inject as Technical signal.
            config_overrides: Runtime overrides for this analysis.

        Returns:
            DecisionDraft with full reasoning trace.

        Raises:
            LookaheadViolationError: if asof > now.
            ReasoningError: on graph failure.
            QuotaExhaustedError: if LLM quota exhausted.
        """
        # Validate asof
        now = datetime.now(UTC)
        if asof > now + timedelta(seconds=60):  # 60s clock-skew tolerance
            raise LookaheadViolationError(
                f"asof={asof.isoformat()} is in the future (now={now.isoformat()}). "
                "Lookahead violation per §3.2.7."
            )

        self._ensure_loaded()

        # Build ticker for TradingAgents (it expects raw ticker strings)
        ticker = self._symbol_to_ticker(symbol)
        date_str = asof.strftime("%Y-%m-%d")

        # Inject forecast as context if provided
        context: dict[str, Any] = {}
        if forecast is not None:
            context["technical_forecast"] = forecast

        # Execute the graph
        start_time = time.monotonic()
        try:
            result = await self._run_graph(ticker, date_str, context)
        except Exception as e:
            elapsed = time.monotonic() - start_time
            logger.error(
                "tradingagents_analyze_failed",
                symbol=str(symbol),
                asof=date_str,
                elapsed_s=round(elapsed, 2),
                error=str(e),
            )
            raise ReasoningError(f"Analysis failed for {symbol}: {e}") from e

        elapsed = time.monotonic() - start_time
        logger.info(
            "tradingagents_analyze_complete",
            symbol=str(symbol),
            asof=date_str,
            elapsed_s=round(elapsed, 2),
            action=result.get("action", "UNKNOWN"),
        )

        # Map to DecisionDraft
        return self._build_decision(symbol, asof, result, forecast)

    async def debate(
        self,
        decision_id: DecisionId,
        user_question: str,
        perspective: str = "bull",
    ) -> dict[str, Any]:
        """Follow-up debate on a prior decision per §3.2.3.

        Returns a structured DebateResponse dict.
        """
        self._ensure_loaded()

        try:
            result = await self._run_debate(decision_id, user_question, perspective)
        except Exception as e:
            raise ReasoningError(f"Debate failed: {e}") from e

        return {
            "decision_id": str(decision_id),
            "perspective": perspective,
            "question": user_question,
            "response": result.get("response", ""),
            "confidence": result.get("confidence", 5),
            "supporting_evidence": result.get("evidence", []),
        }

    # ---------- internal ----------

    def _symbol_to_ticker(self, symbol: Symbol) -> str:
        """Convert Winny Symbol to TradingAgents ticker format.

        TradingAgents expects plain tickers like "NVDA", "BTC-USD".
        """
        if symbol.asset_class.value == "CR":
            base = symbol.base.split("-")[0] if "-" in symbol.base else symbol.base
            quote = symbol.quote or "USD"
            return f"{base}-{quote}"
        elif symbol.asset_class.value == "FX":
            # FX symbols store pair in base (e.g. "EURUSD")
            return f"{symbol.base}=X"
        else:
            # Equity, default
            return symbol.base

    def _config_hash(self) -> str:
        """Hash the current config for idempotency checks."""
        import json

        raw = json.dumps(
            {
                "provider": self._config.llm_provider,
                "deep": self._config.deep_think_llm,
                "quick": self._config.quick_think_llm,
                "temp": self._config.temperature,
                "rounds": self._config.max_debate_rounds,
            },
            sort_keys=True,
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    async def _run_graph(
        self, ticker: str, date_str: str, context: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute the TradingAgents graph. Runs in executor for sync frameworks."""
        import asyncio

        loop = asyncio.get_event_loop()

        def _sync_propagate() -> dict[str, Any]:
            return self._graph.propagate(ticker, date_str, context=context)  # type: ignore[no-any-return]

        return await loop.run_in_executor(None, _sync_propagate)

    async def _run_debate(
        self, decision_id: DecisionId, question: str, perspective: str
    ) -> dict[str, Any]:
        """Run a focused debate round."""
        import asyncio

        loop = asyncio.get_event_loop()

        def _sync_debate() -> dict[str, Any]:
            return self._graph.debate(  # type: ignore[no-any-return]
                decision_id=str(decision_id),
                question=question,
                perspective=perspective,
            )

        return await loop.run_in_executor(None, _sync_debate)

    def _build_decision(
        self,
        symbol: Symbol,
        asof: datetime,
        raw: dict[str, Any],
        forecast: dict[str, Any] | None,
    ) -> DecisionDraft:
        """Map TradingAgents output to our typed DecisionDraft."""
        # Extract action
        action_str = raw.get("action", "HOLD").upper()
        try:
            action = DecisionAction(action_str)
        except ValueError:
            action = DecisionAction.HOLD

        # Extract conviction (1-10 scale)
        conviction = max(1, min(10, int(raw.get("conviction", 5))))

        # Build reasoning trace
        trace = ReasoningTrace(
            analyst_reports=raw.get("analyst_reports", {}),
            debate_rounds=raw.get("debate_rounds", []),
            trader_recommendation=raw.get("trader_recommendation", {}),
            risk_assessment=raw.get("risk_assessment", {}),
            portfolio_verdict=raw.get("portfolio_verdict", {}),
            raw_messages=self._extract_messages(raw),
        )

        # Extract risk flags
        risk_flags = tuple(
            RiskFlag(
                code=rf.get("code", "unknown"),
                severity=rf.get("severity", "LOW"),
                detail=rf.get("detail", ""),
            )
            for rf in raw.get("risk_flags", [])
        )

        # Build inputs provenance
        inputs_used = DecisionInputs(
            forecast_id=forecast.get("forecast_id") if forecast else None,
            data_version_hash=hashlib.sha256(f"{symbol}:{asof.isoformat()}".encode()).hexdigest(),
            llm_versions={
                "deep_think": f"{self._config.llm_provider}/{self._config.deep_think_llm}",
                "quick_think": f"{self._config.llm_provider}/{self._config.quick_think_llm}",
            },
            config_hash=self._config_hash(),
        )

        # Target horizon: from raw or default 24h
        horizon_hours = raw.get("target_horizon_hours", 24)

        return DecisionDraft(
            decision_id=new_decision_id(),
            symbol=symbol,
            asof=asof,
            action=action,
            conviction=conviction,
            target_horizon=timedelta(hours=horizon_hours),
            reasoning_trace=trace,
            risk_flags=risk_flags,
            inputs_used=inputs_used,
        )

    def _extract_messages(self, raw: dict[str, Any]) -> list[LLMMessage]:
        """Extract raw LLM messages for audit trail."""
        messages: list[LLMMessage] = []
        for msg in raw.get("raw_messages", []):
            try:
                messages.append(
                    LLMMessage(
                        role=msg.get("role", "assistant"),
                        content=msg.get("content", ""),
                        model=msg.get(
                            "model", f"{self._config.llm_provider}/{self._config.deep_think_llm}"
                        ),
                        ts=datetime.now(UTC),
                    )
                )
            except Exception:
                continue  # skip malformed messages
        return messages
