"""Feature flags — one switchboard for every external integration.

Every Coinbase CDP product, every broker adapter, every cluster behavior
is gated through this module. Flags resolve from env vars at process
startup; missing flags default to OFF for safety. To flip a flag in
production, set the env var on Railway and redeploy.

Naming convention:
    WW_FEATURE_<DOMAIN>_<NAME>       boolean flag (true/false/1/0/yes/no)
    WW_<DOMAIN>_<NAME>               associated config value (URL, key, etc.)

Anything that reads from the network or signs transactions MUST check its
flag here before doing so. Disabled features raise `FeatureDisabledError`
so callers either guard at call sites or let it bubble as an API 503.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


class FeatureDisabledError(RuntimeError):
    """Raised when code attempts to use a feature whose flag is off.

    The HTTP gateway maps this to 503 Service Unavailable with the flag
    name so the frontend can render a 'feature disabled' state.
    """

    def __init__(self, flag: str, hint: str = "") -> None:
        msg = f"feature '{flag}' is disabled"
        if hint:
            msg += f" — {hint}"
        super().__init__(msg)
        self.flag = flag


def _flag(name: str, default: bool = False) -> bool:
    """Read a boolean env var. Accepts true/false/1/0/yes/no/on/off."""
    raw = os.getenv(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off", ""):
        return default if raw == "" else False
    # Unknown value → treat as disabled and log nothing here (no logger import).
    return False


@dataclass(frozen=True)
class FeatureSet:
    """Resolved view of all feature flags. Built once per process at start."""

    # ─── ENABLED NOW — active components ───────────────────────────────────
    charts_live: bool          # Advanced Trade WS for candlesticks
    data_api: bool             # CDP Data API for wallet balances + tx history
    trade_api: bool            # Coinbase Advanced Trade broker adapter (live)
    webhooks_coinbase: bool    # POST /api/v1/webhooks/coinbase receiver
    agentkit: bool             # CDP AgentKit for agent on-chain capabilities
    clusters: bool             # Cluster router + per-cluster wallets

    # ─── KRAKEN WS v2 — public channels on, trading off ────────────────────
    kraken_charts: bool        # Public market data channels (ticker, book, candles, trades)
    kraken_trade: bool         # Authenticated order placement via WS add_order/batch_add
    kraken_streams: bool       # Authenticated user data (executions + balances) over WS

    # ─── DISABLED FOR LATER — scaffolded, dormant ──────────────────────────
    staking: bool              # CDP Staking API
    deposit_destination: bool  # CDP dedicated inbound address
    transfers: bool            # CDP Transfers API
    paymaster: bool            # CDP Paymaster (gasless txs)
    x402: bool                 # x402 HTTP-native stablecoin payments
    custom_stablecoin: bool    # Custom Base stablecoin issuance

    @classmethod
    def from_env(cls) -> FeatureSet:
        return cls(
            charts_live=_flag("WW_FEATURE_CHARTS_LIVE", default=True),
            data_api=_flag("WW_FEATURE_DATA_API", default=True),
            trade_api=_flag("WW_FEATURE_TRADE_API", default=False),
            # ↑ Trade API defaults OFF — must be explicitly turned on once
            # broker adapter is verified end-to-end.
            webhooks_coinbase=_flag("WW_FEATURE_WEBHOOKS_COINBASE", default=True),
            agentkit=_flag("WW_FEATURE_AGENTKIT", default=True),
            clusters=_flag("WW_FEATURE_CLUSTERS", default=True),
            # ─── Kraken WS v2 ───────────────────────────────────────────
            kraken_charts=_flag("WW_FEATURE_KRAKEN_CHARTS", default=True),
            kraken_trade=_flag("WW_FEATURE_KRAKEN_TRADE", default=False),
            kraken_streams=_flag("WW_FEATURE_KRAKEN_STREAMS", default=False),
            # ─── disabled set ───────────────────────────────────────────
            staking=_flag("WW_FEATURE_STAKING", default=False),
            deposit_destination=_flag("WW_FEATURE_DEPOSIT_DESTINATION", default=False),
            transfers=_flag("WW_FEATURE_TRANSFERS", default=False),
            paymaster=_flag("WW_FEATURE_PAYMASTER", default=False),
            x402=_flag("WW_FEATURE_X402", default=False),
            custom_stablecoin=_flag("WW_FEATURE_CUSTOM_STABLECOIN", default=False),
        )

    def require(self, flag_name: str, hint: str = "") -> None:
        """Raise FeatureDisabledError if the named flag is off.

        Use at the entry point of any feature-gated code path:
            features().require("trade_api", "set WW_FEATURE_TRADE_API=true")
        """
        if not getattr(self, flag_name, False):
            raise FeatureDisabledError(flag_name, hint)

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe view, used by /api/v1/features."""
        return {
            "enabled": {
                "charts_live": self.charts_live,
                "data_api": self.data_api,
                "trade_api": self.trade_api,
                "webhooks_coinbase": self.webhooks_coinbase,
                "agentkit": self.agentkit,
                "clusters": self.clusters,
                "kraken_charts": self.kraken_charts,
                "kraken_trade": self.kraken_trade,
                "kraken_streams": self.kraken_streams,
            },
            "disabled": {
                "staking": self.staking,
                "deposit_destination": self.deposit_destination,
                "transfers": self.transfers,
                "paymaster": self.paymaster,
                "x402": self.x402,
                "custom_stablecoin": self.custom_stablecoin,
            },
        }


# ─── module-level singleton ─────────────────────────────────────────────────

_features: FeatureSet | None = None


def features() -> FeatureSet:
    """Return the process-wide FeatureSet, resolving from env on first call."""
    global _features
    if _features is None:
        _features = FeatureSet.from_env()
    return _features


def reset_for_tests() -> None:
    """Test-only: clear the cached FeatureSet so the next call re-reads env."""
    global _features
    _features = None
