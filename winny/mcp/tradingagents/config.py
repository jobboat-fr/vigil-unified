"""Configuration for mcp-tradingagents per §3.2.4.

Loaded from ~/.winny/tradingagents.yaml with env-var overrides.
Falls back to sensible defaults for local development.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
import yaml

logger = structlog.get_logger()

_DEFAULT_CONFIG_PATH = Path.home() / ".winny" / "tradingagents.yaml"


@dataclass(frozen=True, slots=True)
class AnalystTeam:
    """Which analyst agents to enable."""

    fundamentals: bool = True
    sentiment: bool = True
    news: bool = True
    technical: bool = True


@dataclass(frozen=True, slots=True)
class TradingAgentsConfig:
    """§3.2.4 configuration surface for the reasoning service."""

    llm_provider: str = "openai"
    deep_think_llm: str = "gpt-4o"
    quick_think_llm: str = "gpt-4o-mini"
    temperature: float = 0.0
    max_debate_rounds: int = 2
    checkpoint_enabled: bool = True
    # D-004: OpenAI-compatible base_url for HF Inference Router or local vLLM.
    # When set, TradingAgents uses this instead of the default provider endpoint.
    base_url: str = ""
    # API key for the LLM endpoint (falls back to HF_TOKEN for the HF Router).
    api_key: str = ""
    analyst_team: AnalystTeam = field(default_factory=AnalystTeam)
    data_sources: dict[str, Any] = field(
        default_factory=lambda: {
            "prices": "yahoo",
            "news": "yahoo_news",
            "social": ["stocktwits", "reddit"],
        }
    )


def load_config(path: Path | None = None) -> TradingAgentsConfig:
    """Load config from YAML, with env-var overrides.

    Priority: env vars > YAML file > defaults.
    """
    config_path = path or Path(
        os.environ.get("WINNY_TRADINGAGENTS_CONFIG", str(_DEFAULT_CONFIG_PATH))
    )

    raw: dict[str, Any] = {}
    if config_path.exists():
        try:
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            logger.info("tradingagents_config_loaded", path=str(config_path))
        except Exception as e:
            logger.warning("tradingagents_config_parse_error", path=str(config_path), error=str(e))
    else:
        logger.info("tradingagents_config_not_found", path=str(config_path), using="defaults")

    # Env overrides (WINNY_TA_ prefix)
    llm_provider = os.environ.get("WINNY_TA_LLM_PROVIDER", raw.get("llm_provider", "openai"))
    deep_think = os.environ.get("WINNY_TA_DEEP_THINK_LLM", raw.get("deep_think_llm", "gpt-4o"))
    quick_think = os.environ.get(
        "WINNY_TA_QUICK_THINK_LLM", raw.get("quick_think_llm", "gpt-4o-mini")
    )
    temperature = float(os.environ.get("WINNY_TA_TEMPERATURE", raw.get("temperature", 0.0)))
    max_rounds = int(os.environ.get("WINNY_TA_MAX_DEBATE_ROUNDS", raw.get("max_debate_rounds", 2)))
    checkpoint = os.environ.get("WINNY_TA_CHECKPOINT", str(raw.get("checkpoint_enabled", True)))

    # D-004: LLM endpoint routing — HF Inference Router or local vLLM
    base_url = os.environ.get(
        "WINNY_TA_BASE_URL",
        raw.get("base_url", "https://router.huggingface.co/v1"),
    )
    # API key: explicit env > yaml > HF_TOKEN fallback
    api_key = os.environ.get(
        "WINNY_TA_API_KEY",
        raw.get("api_key", os.environ.get("HF_TOKEN", "")),
    )

    # Analyst team
    team_raw = raw.get("analyst_team", {})
    analyst_team = AnalystTeam(
        fundamentals=team_raw.get("fundamentals", True),
        sentiment=team_raw.get("sentiment", True),
        news=team_raw.get("news", True),
        technical=team_raw.get("technical", True),
    )

    # Data sources
    data_sources = raw.get(
        "data_sources",
        {
            "prices": "yahoo",
            "news": "yahoo_news",
            "social": ["stocktwits", "reddit"],
        },
    )

    return TradingAgentsConfig(
        llm_provider=llm_provider,
        deep_think_llm=deep_think,
        quick_think_llm=quick_think,
        temperature=temperature,
        max_debate_rounds=max_rounds,
        checkpoint_enabled=checkpoint.lower() in ("true", "1", "yes"),
        base_url=base_url,
        api_key=api_key,
        analyst_team=analyst_team,
        data_sources=data_sources,
    )
