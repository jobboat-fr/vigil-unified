"""Minimal .env loader + config accessors for secrets.

Reads from environment variables first, falls back to a `.env` file in the
project root. API keys are NEVER hardcoded — this is the single point of
access for all secret material that isn't the Ed25519 approval key.
"""

from __future__ import annotations

import os
from pathlib import Path


def _find_dotenv() -> Path | None:
    """Walk up from CWD looking for a .env file."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate
    return None


def _load_dotenv() -> None:
    """Parse .env file into os.environ (does NOT override existing vars)."""
    path = _find_dotenv()
    if path is None:
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


# Load on import
_load_dotenv()


def get_cmc_api_key() -> str:
    """Return the CoinMarketCap Pro API key or raise."""
    key = os.environ.get("WINNY_CMC_API_KEY", "")
    if not key:
        raise RuntimeError("WINNY_CMC_API_KEY not set. Add it to your .env file or export it.")
    return key


def get_cryptocompare_api_key() -> str:
    """Return the CryptoCompare API key or raise."""
    key = os.environ.get("WINNY_CRYPTOCOMPARE_API_KEY", "")
    if not key:
        raise RuntimeError(
            "WINNY_CRYPTOCOMPARE_API_KEY not set. Add it to your .env file or export it."
        )
    return key


def get_hf_token() -> str:
    """Return the Hugging Face API token or raise.

    Used by:
      - mcp-timesfm: downloading google/timesfm-2.5-200m-pytorch from HF Hub
      - mcp-tradingagents: authenticating to HF Inference Router for LLM calls (D-004)
    """
    key = os.environ.get("HF_TOKEN", "")
    if not key:
        raise RuntimeError(
            "HF_TOKEN not set. Add it to your .env file or export it. "
            "Get a token at https://huggingface.co/settings/tokens"
        )
    return key
