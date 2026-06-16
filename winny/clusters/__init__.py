"""Cluster router — one signal fans out into N coordinated positions across N wallets.

A Cluster = capital allocation + risk policy + AgentKit wallet. The
Hermes agent receives a verdict from mcp-tradingagents, hands it to the
cluster allocator, which decides which clusters take this signal and at
what size; each cluster's wallet then receives its own OrderIntent via
the approval gate.

Architecture: see VIGIL_INTEGRATION_SPEC §11 / Cluster Architecture.
ENABLED by WW_FEATURE_CLUSTERS (default ON).
"""

from .policy import ClusterPolicy, RiskProfile
from .store import ClusterStore

__all__ = ["ClusterPolicy", "ClusterStore", "RiskProfile"]
