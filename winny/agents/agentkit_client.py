"""CDP AgentKit client — self-custodial wallets for AI agents.

AgentKit gives each WinnyWoo Hermes-orchestrated agent (Executor, and
optionally Forecaster/Analyst for on-chain context) its own onchain
wallet on Base. Wallets are MPC-custodied by CDP (recoverable via the
CDP project) by default; pure self-custody mode persists a seed at
~/.winny/agentkit/<agent-id>.seed.

ENABLED by WW_FEATURE_AGENTKIT (default ON).

Reads config:
  CDP_AGENTKIT_API_KEY_NAME      — "organizations/<org>/apiKeys/<id>"
  CDP_AGENTKIT_PRIVATE_KEY       — PEM EC private key for AgentKit auth
  CDP_AGENTKIT_NETWORK           — "base-mainnet" | "base-sepolia"
                                   (default "base-sepolia" until manually flipped)
  CDP_AGENTKIT_CUSTODY           — "mpc" (default) | "self"

This is a SCAFFOLD: interface contract is real; the actual CDP wallet
calls land alongside the cluster-router PR.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from winny.common.features import features


@dataclass(frozen=True)
class AgentWallet:
    """A single AgentKit wallet bound to one agent or one cluster."""

    wallet_id: str
    agent_id: str
    address: str
    network: str
    custody: str            # "mpc" or "self"
    created_at: str         # ISO 8601


class AgentKitClient:
    """Thin CDP AgentKit wrapper. All methods are flag-gated."""

    def __init__(self) -> None:
        self._api_key_name = os.getenv("CDP_AGENTKIT_API_KEY_NAME", "")
        self._private_key = os.getenv("CDP_AGENTKIT_PRIVATE_KEY", "")
        self._network = os.getenv("CDP_AGENTKIT_NETWORK", "base-sepolia")
        self._custody = os.getenv("CDP_AGENTKIT_CUSTODY", "mpc")

    @property
    def is_authenticated(self) -> bool:
        return bool(self._api_key_name and self._private_key)

    @property
    def network(self) -> str:
        return self._network

    async def create_wallet(self, agent_id: str) -> AgentWallet:
        """Create a new AgentKit wallet for an agent/cluster."""
        features().require("agentkit", "set WW_FEATURE_AGENTKIT=true to enable")
        # TODO: cdp-sdk: client.create_wallet(network=..., custody=...)
        raise NotImplementedError("AgentKit wallet creation lands in P2")

    async def get_balance(self, wallet_id: str) -> dict[str, Any]:
        """Return native + ERC20 balances for the wallet."""
        features().require("agentkit")
        raise NotImplementedError

    async def submit_transaction(
        self, wallet_id: str, *, to: str, value: str, data: str = "0x"
    ) -> str:
        """Sign + broadcast a transaction from the wallet. Returns tx hash."""
        features().require("agentkit")
        raise NotImplementedError

    async def swap(
        self,
        wallet_id: str,
        *,
        from_token: str,
        to_token: str,
        amount: str,
        slippage_bps: int = 50,
    ) -> str:
        """Execute a token swap via CDP Trade API. Returns tx hash."""
        features().require("agentkit")
        features().require("trade_api", "swap needs trade_api too")
        raise NotImplementedError
