"""CDP Staking API — yield on idle balances.

DISABLED. Flip WW_FEATURE_STAKING=true once a cluster's risk policy
includes an "idle-cash yield" rule.

Will provide:
  • list_stakeable_assets() — which tokens our wallets can stake
  • stake(wallet_id, asset, amount) — initiate staking
  • unstake(wallet_id, staking_id) — initiate unbonding
  • get_rewards(wallet_id) — accrued rewards
"""

from __future__ import annotations

from winny.common.features import features


def list_stakeable_assets() -> list[dict[str, object]]:
    features().require("staking", "set WW_FEATURE_STAKING=true to enable")
    raise NotImplementedError
